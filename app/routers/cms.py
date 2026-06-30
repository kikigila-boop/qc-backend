"""
CMS Router
Endpoints used by the CMS (Content Management System) team.

Key workflow: QC team sets content to "Ready To Ingest",
then CMS team queries this queue and marks each item as "Done Ingest".

Authentication: same JWT token — CMS operators must be registered users.
The operator's name is recorded in `ingest_by` and in the activity log.
"""
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.user import User
from ..models.qc_content import QCContent, QCHistory, StatusEnum
from ..schemas.qc_content import CMSIngestRequest, CMSRevisedRequest, QCContentOut, QCHistoryOut
from ..utils.security import get_current_user
from ..services.sheets_service import sync_row
from ..services import push_service

router = APIRouter(prefix="/cms", tags=["CMS"])


# ─── helpers ────────────────────────────────────────────────────────────────

def _log(
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
    db.add(QCHistory(
        qc_content_id=content_id,
        changed_by_id=user_id,
        changed_by_name=by_name,
        field_name=field,
        old_value=str(old) if old is not None else None,
        new_value=str(new) if new is not None else None,
    ))


def _enrich(content: QCContent) -> dict:
    return {c.name: getattr(content, c.name) for c in content.__table__.columns}


# ─── endpoints ──────────────────────────────────────────────────────────────

@router.get("/queue", response_model=List[QCContentOut])
def get_ingest_queue(
    search: Optional[str] = Query(None, description="Search by QCID, title, or episode"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """
    Return all content with status 'Ready To Ingest'.
    This is the CMS team's main work queue.
    """
    q = db.query(QCContent).filter(QCContent.status == StatusEnum.READY_TO_INGEST)

    if search:
        like = f"%{search}%"
        q = q.filter(
            or_(
                QCContent.qcid.ilike(like),
                QCContent.title.ilike(like),
                QCContent.episode.ilike(like),
                QCContent.season.ilike(like),
            )
        )

    items = (
        q.order_by(QCContent.updated_at.asc())   # oldest first — FIFO queue
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return [_enrich(i) for i in items]


@router.get("/queue/count")
def get_queue_count(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """Quick count of items waiting to be ingested."""
    count = db.query(QCContent).filter(QCContent.status == StatusEnum.READY_TO_INGEST).count()
    return {"ready_to_ingest": count}


@router.get("/item/{qcid}", response_model=QCContentOut)
def get_by_qcid(
    qcid: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """
    Fetch a single QC item by its QCID.
    CMS team can use this to look up a specific title before ingesting.
    """
    content = db.query(QCContent).filter(QCContent.qcid == qcid.upper()).first()
    if not content:
        raise HTTPException(status_code=404, detail=f"No content found with QCID '{qcid}'")
    return _enrich(content)


@router.patch("/item/{qcid}/done-ingest", response_model=QCContentOut)
def mark_done_ingest(
    qcid: str,
    payload: CMSIngestRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Mark a content item as 'Done Ingest'.
    Only valid when current status is 'Ready To Ingest'.
    Records the CMS operator name + timestamp.
    """
    content = db.query(QCContent).filter(QCContent.qcid == qcid.upper()).first()
    if not content:
        raise HTTPException(status_code=404, detail=f"No content found with QCID '{qcid}'")

    if content.status != StatusEnum.READY_TO_INGEST:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Cannot set Done Ingest. Current status is '{content.status.value}'. "
                f"Only 'Ready To Ingest' content can be ingested."
            ),
        )

    old_status = content.status
    content.status = StatusEnum.DONE_INGEST
    content.ingest_by = payload.operator_name
    content.ingest_at = datetime.utcnow()

    _log(db, content.id, "status",
         old_status.value, StatusEnum.DONE_INGEST.value,
         user_id=current_user.id,
         by_name=payload.operator_name)

    _log(db, content.id, "ingest_by",
         None, payload.operator_name,
         user_id=current_user.id,
         by_name=payload.operator_name)

    db.commit()
    db.refresh(content)

    row = _enrich(content)
    background_tasks.add_task(sync_row, row)
    return row




@router.patch("/item/{qcid}/revised", response_model=QCContentOut)
def mark_revised(
    qcid: str,
    payload: CMSRevisedRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    CMS marks a content item as 'Revised' — something is missing or incorrect.
    Valid from 'Ready To Ingest' status.
    Triggers a push notification to the editor.
    """
    content = db.query(QCContent).filter(QCContent.qcid == qcid.upper()).first()
    if not content:
        raise HTTPException(status_code=404, detail=f"No content found with QCID '{qcid}'")

    if content.status not in (StatusEnum.READY_TO_INGEST, StatusEnum.DONE_INGEST):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Cannot mark as Revised. Current status is '{content.status.value}'. "
                f"Only 'Ready To Ingest' or 'Done Ingest' items can be revised."
            ),
        )

    old_status = content.status
    content.status = StatusEnum.REVISED
    content.revised_notes = payload.revised_notes

    _log(db, content.id, "status",
         old_status.value, StatusEnum.REVISED.value,
         user_id=current_user.id,
         by_name=payload.operator_name)

    _log(db, content.id, "revised_notes",
         None, payload.revised_notes,
         user_id=current_user.id,
         by_name=payload.operator_name)

    db.commit()
    db.refresh(content)

    row = _enrich(content)
    background_tasks.add_task(sync_row, row)
    return row

@router.get("/item/{qcid}/history", response_model=List[QCHistoryOut])
def get_item_history(
    qcid: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Full activity log for a content item, accessible by QCID."""
    content = db.query(QCContent).filter(QCContent.qcid == qcid.upper()).first()
    if not content:
        raise HTTPException(status_code=404, detail=f"No content found with QCID '{qcid}'")

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
