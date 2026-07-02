"""
CMS Router — Workflow:
  Ready To Ingest → [CMS klik Ingesting] → Ingesting
  Ingesting → [CMS klik Done Ingest] → Done Ingest
  Ingesting → [CMS klik Revisi] → Need Revised (→ editor dinotif)
  Need Revised → [Editor fix + klik Ready To Ingest] → Ready To Ingest (→ CMS dinotif)
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
from ..services import push_service, notification_service

router = APIRouter(prefix="/cms", tags=["CMS"])


def _log(db, content_id, field, old, new, user_id=None, by_name=None):
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


# ─── Queue endpoints ─────────────────────────────────────────────────────────

@router.get("/queue", response_model=List[QCContentOut])
def get_ingest_queue(
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Return Ready To Ingest AND Ingesting items — the full CMS work queue."""
    q = db.query(QCContent).filter(
        QCContent.status.in_([StatusEnum.READY_TO_INGEST, StatusEnum.INGESTING])
    )
    if search:
        like = f"%{search}%"
        q = q.filter(or_(
            QCContent.qcid.ilike(like),
            QCContent.title.ilike(like),
            QCContent.episode.ilike(like),
            QCContent.season.ilike(like),
        ))
    items = q.order_by(QCContent.updated_at.asc()).offset((page - 1) * page_size).limit(page_size).all()
    return [_enrich(i) for i in items]


@router.get("/queue/count")
def get_queue_count(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    ready = db.query(QCContent).filter(QCContent.status == StatusEnum.READY_TO_INGEST).count()
    ingesting = db.query(QCContent).filter(QCContent.status == StatusEnum.INGESTING).count()
    return {"ready_to_ingest": ready, "ingesting": ingesting, "total": ready + ingesting}


@router.get("/item/{qcid}", response_model=QCContentOut)
def get_by_qcid(qcid: str, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    content = db.query(QCContent).filter(QCContent.qcid == qcid.upper()).first()
    if not content:
        raise HTTPException(status_code=404, detail=f"No content found with QCID '{qcid}'")
    return _enrich(content)


# ─── Action endpoints ────────────────────────────────────────────────────────

@router.patch("/item/{qcid}/start-ingesting", response_model=QCContentOut)
def start_ingesting(
    qcid: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """CMS memulai proses ingest — Ready To Ingest → Ingesting."""
    if current_user.role not in ("cms", "admin"):
        raise HTTPException(status_code=403, detail="Hanya CMS / Admin.")

    content = db.query(QCContent).filter(QCContent.qcid == qcid.upper()).first()
    if not content:
        raise HTTPException(status_code=404, detail=f"No content found with QCID '{qcid}'")

    if content.status != StatusEnum.READY_TO_INGEST:
        raise HTTPException(
            status_code=400,
            detail=f"Hanya 'Ready To Ingest' yang bisa diubah ke Ingesting. Status saat ini: '{content.status.value}'.",
        )

    old_status = content.status
    content.status = StatusEnum.INGESTING

    _log(db, content.id, "status", old_status.value, StatusEnum.INGESTING.value,
         user_id=current_user.id, by_name=current_user.name)

    db.commit()
    db.refresh(content)

    row = _enrich(content)
    background_tasks.add_task(sync_row, row)
    return row


@router.patch("/item/{qcid}/done-ingest", response_model=QCContentOut)
def mark_done_ingest(
    qcid: str,
    payload: CMSIngestRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """CMS selesai ingest — Ingesting → Done Ingest."""
    if current_user.role not in ("cms", "admin"):
        raise HTTPException(status_code=403, detail="Hanya CMS / Admin.")

    content = db.query(QCContent).filter(QCContent.qcid == qcid.upper()).first()
    if not content:
        raise HTTPException(status_code=404, detail=f"No content found with QCID '{qcid}'")

    if content.status != StatusEnum.INGESTING:
        raise HTTPException(
            status_code=400,
            detail=f"Hanya status 'Ingesting' yang bisa diubah ke Done Ingest. Status saat ini: '{content.status.value}'.",
        )

    old_status = content.status
    content.status = StatusEnum.DONE_INGEST
    content.ingest_by = payload.operator_name
    content.ingest_at = datetime.utcnow()

    _log(db, content.id, "status", old_status.value, StatusEnum.DONE_INGEST.value,
         user_id=current_user.id, by_name=payload.operator_name)
    _log(db, content.id, "ingest_by", None, payload.operator_name,
         user_id=current_user.id, by_name=payload.operator_name)

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
    CMS request revisi ke editor — hanya saat status Ingesting.
    Status berubah ke Need Revised, editor dapat notifikasi.
    """
    if current_user.role not in ("cms", "admin"):
        raise HTTPException(status_code=403, detail="Hanya CMS / Admin.")

    content = db.query(QCContent).filter(QCContent.qcid == qcid.upper()).first()
    if not content:
        raise HTTPException(status_code=404, detail=f"No content found with QCID '{qcid}'")

    if content.status != StatusEnum.INGESTING:
        raise HTTPException(
            status_code=400,
            detail=f"Hanya status 'Ingesting' yang bisa direquest revisi. Status saat ini: '{content.status.value}'.",
        )

    old_status = content.status
    content.status = StatusEnum.NEED_REVISED
    content.revised_notes = payload.revised_notes

    _log(db, content.id, "status", old_status.value, StatusEnum.NEED_REVISED.value,
         user_id=current_user.id, by_name=payload.operator_name)
    _log(db, content.id, "revised_notes", None, payload.revised_notes,
         user_id=current_user.id, by_name=payload.operator_name)

    db.commit()
    db.refresh(content)

    row = _enrich(content)
    background_tasks.add_task(sync_row, row)

    # Notify editor
    notif_title = "Konten Perlu Direvisi"
    notif_body = f"{content.title} - Eps {content.episode}"
    notif_url = f"/qc/{content.id}"

    editor_id = content.editor_id
    if not editor_id and content.editor_name:
        editor_user = db.query(User).filter(
            User.name == content.editor_name, User.is_active == True
        ).first()
        if editor_user:
            editor_id = editor_user.id

    if editor_id:
        try:
            notification_service.create_for_users(db, [editor_id], notif_title, notif_body, notif_url)
        except Exception:
            pass
        background_tasks.add_task(push_service.send_push_to_users, db, [editor_id], notif_title, notif_body, notif_url)

    return row


@router.get("/item/{qcid}/history", response_model=List[QCHistoryOut])
def get_item_history(qcid: str, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    content = db.query(QCContent).filter(QCContent.qcid == qcid.upper()).first()
    if not content:
        raise HTTPException(status_code=404, detail=f"No content found with QCID '{qcid}'")
    return [
        {"id": h.id, "field_name": h.field_name, "old_value": h.old_value,
         "new_value": h.new_value, "changed_at": h.changed_at, "changed_by_name": h.changed_by_name}
        for h in content.histories
    ]
