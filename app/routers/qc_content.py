from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_
from typing import List, Optional
from datetime import datetime

from ..database import get_db
from ..models.user import User
from ..models.qc_content import QCContent, QCHistory, StatusEnum, STATUS_ORDER
from ..schemas.qc_content import (
    QCContentCreate, QCContentUpdate, QCContentOut,
    QCContentDetail, QCHistoryOut, StatusTransition, ReviseRequest,
)
from ..utils.security import get_current_user
from ..services.qcid_service import maybe_assign_qcid
from ..services.sheets_service import sync_row
from ..services import push_service, notification_service

router = APIRouter(prefix="/qc", tags=["QC Content"])


# ─── helpers ────────────────────────────────────────────────────────────────

def _enrich(content: QCContent, db: Session) -> dict:
    """Return a dict from model columns."""
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
    """Allow any forward movement in STATUS_ORDER; block backwards moves."""
    if current not in STATUS_ORDER or new not in STATUS_ORDER:
        raise HTTPException(status_code=400, detail="Invalid status value.")
    current_idx = STATUS_ORDER.index(current)
    new_idx = STATUS_ORDER.index(new)
    if new_idx <= current_idx:
        raise HTTPException(
            status_code=400,
            detail=f"Tidak bisa mundur. Status saat ini: '{current.value}'.",
        )


# ─── endpoints ──────────────────────────────────────────────────────────────
# NOTE: routes use "" (empty string), NOT "/" — required by redirect_slashes=False

@router.post("", response_model=QCContentOut, status_code=201)
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

    _log_change(db, content.id, "created", None, "record created",
                user_id=current_user.id, by_name=current_user.name)

    db.commit()
    db.refresh(content)

    row = _enrich(content, db)
    background_tasks.add_task(sync_row, row)
    return {**row}


@router.get("", response_model=List[QCContentOut])
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
    items = q.offset((page - 1) * page_size).limit(page_size).all()

    return [_enrich(item, db) for item in items]


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
    row["histories"] = [
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

    if content.status == StatusEnum.DONE_INGEST:
        raise HTTPException(status_code=400, detail="Content dengan status 'Done Ingest' tidak bisa diedit.")

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

    # Only cms/admin can set Done Ingest
    if payload.new_status == StatusEnum.DONE_INGEST and current_user.role not in ("cms", "admin"):
        raise HTTPException(
            status_code=403,
            detail="Hanya tim CMS atau Admin yang dapat mengubah status ke Done Ingest.",
        )

    _validate_workflow(content.status, payload.new_status)

    old_status = content.status
    content.status = payload.new_status

    # Track who did the ingest
    if payload.new_status == StatusEnum.DONE_INGEST:
        content.ingest_by = current_user.name
        content.ingest_at = datetime.utcnow()

    _log_change(db, content.id, "status", old_status.value, payload.new_status.value,
                user_id=current_user.id, by_name=current_user.name)

    maybe_assign_qcid(content, db)
    db.commit()
    db.refresh(content)

    row = _enrich(content, db)
    background_tasks.add_task(sync_row, row)

    # Notify CMS when status becomes Ready To Ingest
    if payload.new_status == StatusEnum.READY_TO_INGEST:
        title_short = content.title[:40] + ("..." if len(content.title) > 40 else "")
        notif_title = "Konten Siap Diingest"
        notif_body = f"{title_short} sudah Ready To Ingest."
        notif_url = f"/qc/{content.id}"
        background_tasks.add_task(
            push_service.send_push_to_role, db, "cms",
            notif_title, notif_body, notif_url,
        )
        background_tasks.add_task(
            notification_service.create_for_role, db, "cms",
            notif_title, notif_body, notif_url,
        )

    return row


@router.patch("/{content_id}/revise", response_model=QCContentOut)
def revise_content(
    content_id: int,
    payload: ReviseRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Mark content as Revised.
    - Editor: allowed when status is NOT Done Ingest or already Revised
    - CMS: allowed only when status is Ready To Ingest or Done Ingest
    - Admin: no restriction
    """
    content = db.query(QCContent).filter(QCContent.id == content_id).first()
    if not content:
        raise HTTPException(status_code=404, detail="Content not found")

    role = current_user.role
    current_status = content.status

    if role == "editor":
        if current_status in (StatusEnum.DONE_INGEST, StatusEnum.REVISED):
            raise HTTPException(
                status_code=403,
                detail=f"Editor tidak bisa revise konten dengan status '{current_status.value}'.",
            )
    elif role == "cms":
        if current_status not in (StatusEnum.READY_TO_INGEST, StatusEnum.DONE_INGEST):
            raise HTTPException(
                status_code=403,
                detail=f"Tim CMS hanya bisa revise saat status 'Ready To Ingest' atau 'Done Ingest'. Status saat ini: '{current_status.value}'.",
            )
    # admin: no restriction

    old_status = content.status
    content.status = StatusEnum.REVISED
    content.revised_notes = payload.revised_notes

    _log_change(db, content.id, "status", old_status.value, StatusEnum.REVISED.value,
                user_id=current_user.id, by_name=current_user.name)
    _log_change(db, content.id, "revised_notes", None, payload.revised_notes,
                user_id=current_user.id, by_name=current_user.name)

    db.commit()
    db.refresh(content)

    row = _enrich(content, db)
    background_tasks.add_task(sync_row, row)

    # Notify the editor
    if content.editor_id:
        title_short = content.title[:40] + ("..." if len(content.title) > 40 else "")
        notif_title = "Konten Perlu Direvisi"
        notif_body = f"{title_short} dikembalikan untuk revisi. Catatan: {payload.revised_notes[:60]}"
        notif_url = f"/qc/{content.id}"
        background_tasks.add_task(
            push_service.send_push_to_users, db, [content.editor_id],
            notif_title, notif_body, notif_url,
        )
        background_tasks.add_task(
            notification_service.create_for_users, db, [content.editor_id],
            notif_title, notif_body, notif_url,
        )

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
