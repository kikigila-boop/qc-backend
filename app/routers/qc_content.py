from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_
from typing import List, Optional
from datetime import datetime

from ..database import get_db
from ..models.user import User
from ..models.qc_content import QCContent, QCHistory, StatusEnum, STATUS_ORDER
from ..schemas.qc_content import (
    QCContentCreate, QCContentUpdate, QCContentOut,
    QCContentDetail, QCHistoryOut, StatusTransition,
)
from ..utils.security import get_current_user
from ..services.qcid_service import maybe_assign_qcid
from ..services.sheets_service import sync_row

router = APIRouter(prefix="/qc", tags=["QC Content"])


# ─── helpers ────────────────────────────────────────────────────────────────

def _enrich(content: QCContent, db: Session) -> dict:
    """Return a dict; editor_name is taken directly from the model column."""
    data = {c.name: getattr(content, c.name) for c in content.__table__.columns}
    return data


def _log_change(
    db: Session,
    content_id: int,
    field: str,
    old,
    new,
    user_id: int = None,
    by_name: str = None,
):
    if str(old) == str(new):
        return
    history = QCHistory(
        qc_content_id=content_id,
        changed_by_id=user_id,
        changed_by_name=by_name,
        field_name=field,
        old_value=str(old) if old is not None else None,
        new_value=str(new) if new is not None else None,
    )
    db.add(history)


def _validate_workflow(current: StatusEnum, new: StatusEnum):
    current_idx = STATUS_ORDER.index(current)
    new_idx = STATUS_ORDER.index(new)
    if new_idx != current_idx + 1:
        allowed_next = STATUS_ORDER[current_idx + 1].value if current_idx + 1 < len(STATUS_ORDER) else "None"
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status transition. From '{current.value}' the only allowed next step is '{allowed_next}'.",
        )


# ─── endpoints ──────────────────────────────────────────────────────────────

@router.post("/", response_model=QCContentOut, status_code=201)
def create_qc(
    payload: QCContentCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    content = QCContent(**payload.model_dump())
    db.add(content)
    db.flush()  # get ID before commit

    maybe_assign_qcid(content, db)

    # Log creation
    _log_change(db, content.id, "created", None, "record created",
                user_id=current_user.id, by_name=current_user.name)

    db.commit()
    db.refresh(content)

    row = _enrich(content, db)
    background_tasks.add_task(sync_row, row)
    return {**row}


@router.get("/", response_model=List[QCContentOut])
def list_qc(
    search: Optional[str] = Query(None),
    status: Optional[StatusEnum] = Query(None),
    qc_result: Optional[str] = Query(None),
    editor_id: Optional[int] = Query(None),
    editor_name: Optional[str] = Query(None),
    season: Optional[str] = Query(None),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    q = db.query(QCContent)

    if search:
        like = f"%{search}%"
        q = q.filter(
            or_(
                QCContent.qcid.ilike(like),
                QCContent.title.ilike(like),
                QCContent.episode.ilike(like),
                QCContent.cast.ilike(like),
                QCContent.editor_name.ilike(like),
            )
        )
    if status:
        q = q.filter(QCContent.status == status)
    if qc_result:
        q = q.filter(QCContent.qc_result == qc_result)
    if editor_id:
        q = q.filter(QCContent.editor_id == editor_id)
    if editor_name:
        q = q.filter(QCContent.editor_name.ilike(f"%{editor_name}%"))
    if season:
        q = q.filter(QCContent.season.ilike(f"%{season}%"))
    if date_from:
        q = q.filter(QCContent.qc_date >= date_from)
    if date_to:
        q = q.filter(QCContent.qc_date <= date_to)

    q = q.order_by(QCContent.updated_at.desc())
    total = q.count()
    items = q.offset((page - 1) * page_size).limit(page_size).all()

    result = []
    for item in items:
        row = _enrich(item, db)
        result.append(row)
    return result


@router.get("/{content_id}", response_model=QCContentDetail)
def get_qc(
    content_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    content = db.query(QCContent).filter(QCContent.id == content_id).first()
    if not content:
        raise HTTPException(status_code=404, detail="Content not found")

    row = _enrich(content, db)
    histories = [
        {
            "id": h.id,
            "field_name": h.field_name,
            "old_value": h.old_value,
            "new_value": h.new_value,
            "changed_at": h.changed_at,
            "changed_by_name": h.changed_by_name,
        }
        for h in content.histories
    ]
    row["histories"] = histories
    return row


@router.put("/{content_id}", response_model=QCContentOut)
def update_qc(
    content_id: int,
    payload: QCContentUpdate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    content = db.query(QCContent).filter(QCContent.id == content_id).first()
    if not content:
        raise HTTPException(status_code=404, detail="Content not found")

    # Block edits on completed workflows
    if content.status == StatusEnum.DONE_INGEST:
        raise HTTPException(status_code=400, detail="Content with status 'Done Ingest' cannot be edited.")

    update_data = payload.model_dump(exclude_unset=True)
    for field, new_val in update_data.items():
        old_val = getattr(content, field)
        _log_change(db, content.id, field, old_val, new_val,
                    user_id=current_user.id, by_name=current_user.name)
        setattr(content, field, new_val)

    maybe_assign_qcid(content, db)
    db.commit()
    db.refresh(content)

    row = _enrich(content, db)
    background_tasks.add_task(sync_row, row)
    return row


@router.patch("/{content_id}/status", response_model=QCContentOut)
def transition_status(
    content_id: int,
    payload: StatusTransition,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    content = db.query(QCContent).filter(QCContent.id == content_id).first()
    if not content:
        raise HTTPException(status_code=404, detail="Content not found")

    _validate_workflow(content.status, payload.new_status)

    old_status = content.status
    content.status = payload.new_status
    _log_change(db, content.id, "status", old_status.value, payload.new_status.value,
                user_id=current_user.id, by_name=current_user.name)

    maybe_assign_qcid(content, db)
    db.commit()
    db.refresh(content)

    row = _enrich(content, db)
    background_tasks.add_task(sync_row, row)
    return row


@router.get("/{content_id}/history", response_model=List[QCHistoryOut])
def get_history(
    content_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    content = db.query(QCContent).filter(QCContent.id == content_id).first()
    if not content:
        raise HTTPException(status_code=404, detail="Content not found")

    return [
        {
            "id": h.id,
            "field_name": h.field_name,
            "old_value": h.old_value,
            "new_value": h.new_value,
            "changed_at": h.changed_at,
            "changed_by_name": h.changed_by_name,
        }
        for h in content.histories
    ]
