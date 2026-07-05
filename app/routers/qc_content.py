from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from pydantic import BaseModel
from ..models.qc_content import SubtitleTask, SubtitleStatus
from ..services.subtitle_service import generate_subtitle_tasks
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
    ClaimRequest, MaterialReturnRequest,
)
from ..utils.security import get_current_user
from ..services.qcid_service import maybe_assign_qcid
from ..services.sheets_service import sync_row
from ..services import push_service, notification_service

router = APIRouter(prefix="/qc", tags=["QC Content"])


# ─── helpers ────────────────────────────────────────────────────────────────

def _enrich(content: QCContent, db: Session) -> dict:
    return {c.name: getattr(content, c.name) for c in content.__table__.columns}


def _log_change(db, content_id, field, old, new, user_id=None, by_name=None):
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


def _validate_workflow(current: StatusEnum, new: StatusEnum):
    """
    Validate status transitions.
    Normal: must move forward in STATUS_ORDER.
    Special cases:
      - MATERIAL_AVAIL → QC_PROCESS  (editor claims — handled via /material/claim)
      - REVISED → QC_PROCESS         (backward compat)
      - NEED_REVISED → READY_TO_INGEST  (editor re-submits after CMS revision)
    """
    if current == StatusEnum.MATERIAL_AVAIL and new == StatusEnum.QC_PROCESS:
        return
    if current == StatusEnum.REVISED and new == StatusEnum.QC_PROCESS:
        return
    if current == StatusEnum.NEED_REVISED and new == StatusEnum.READY_TO_INGEST:
        return
    if current not in STATUS_ORDER or new not in STATUS_ORDER:
        raise HTTPException(status_code=400, detail="Invalid status value.")
    current_idx = STATUS_ORDER.index(current)
    new_idx = STATUS_ORDER.index(new)
    if new_idx <= current_idx:
        raise HTTPException(
            status_code=400,
            detail=f"Tidak bisa mundur. Status saat ini: '{current.value}'.",
        )


def _notify_editor(db, content, background_tasks, title, body, url):
    """Send in-app + push notification to the content's editor."""
    editor_id = content.editor_id
    if not editor_id and content.editor_name:
        user = db.query(User).filter(
            User.name == content.editor_name, User.is_active == True
        ).first()
        if user:
            editor_id = user.id
    if not editor_id:
        return
    try:
        notification_service.create_for_users(db, [editor_id], title, body, url)
    except Exception:
        pass
    background_tasks.add_task(push_service.send_push_to_users, db, [editor_id], title, body, url)


def _notify_cms(db, content, background_tasks, title, body, url):
    """Send in-app + push notification to the entire CMS role."""
    try:
        notification_service.create_for_role(db, "cms", title, body, url)
    except Exception:
        pass
    background_tasks.add_task(push_service.send_push_to_role, db, "cms", title, body, url)


# ─── endpoints ──────────────────────────────────────────────────────────────

@router.post("", response_model=QCContentOut, status_code=201)
def create_qc(
    payload: QCContentCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    data = payload.model_dump()
    if not data.get('qc_date'):
        data['qc_date'] = datetime.utcnow()

    # Role-based initial status
    if current_user.role == "material_handling":
        data['status'] = StatusEnum.MATERIAL_AVAIL
        data['mh_name'] = current_user.name
        # editor_name can be blank when MH creates
        if not data.get('editor_name'):
            data['editor_name'] = None
    else:
        # Editor / Admin: direct QC pipeline
        data['status'] = StatusEnum.QC_PROCESS
        if not data.get('editor_name'):
            data['editor_name'] = current_user.name
        if not data.get('editor_id'):
            data['editor_id'] = current_user.id

    selected_languages = data.pop('selected_languages', None)
    content = QCContent(**data)
    db.add(content)
    db.flush()
    maybe_assign_qcid(content, db)
    _log_change(db, content.id, "created", None, "record created",
                user_id=current_user.id, by_name=current_user.name)
    db.commit()
    db.refresh(content)
    if content.with_subs:
        generate_subtitle_tasks(db, content, selected_languages)
    db.refresh(content)
    row = _enrich(content, db)
    background_tasks.add_task(sync_row, row)

    # Notify CMS to fill in naming asset
    _notify_cms(db, content, background_tasks,
                "Konten Baru — Perlu Naming Asset",
                f"{content.title} (Eps {content.episode}) ditambahkan. Mohon isi Naming Asset.",
                f"/qc/{content.id}")

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
    q = db.query(QCContent).filter(QCContent.in_logbook == False)
    if search:
        like = f"%{search}%"
        q = q.filter(or_(
            QCContent.qcid.ilike(like),
            QCContent.title.ilike(like),
            QCContent.episode.ilike(like),
            QCContent.cast.ilike(like),
            QCContent.editor_name.ilike(like),
        ))
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


# ─── Needs Naming endpoint (CMS worklist) ────────────────────────────────────
@router.get("/needs-naming", response_model=List[QCContentOut])
def list_needs_naming(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return all content items where naming_asset is NULL or empty — for CMS tab."""
    if current_user.role not in ("cms", "admin"):
        raise HTTPException(403, "Akses ditolak")
    items = (
        db.query(QCContent)
        .filter(
            (QCContent.naming_asset == None) | (QCContent.naming_asset == "")
        )
        .order_by(QCContent.updated_at.desc())
        .all()
    )
    return [_enrich(item, db) for item in items]


@router.get("/{content_id}", response_model=QCContentDetail)
def get_qc(content_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    content = db.query(QCContent).filter(QCContent.id == content_id).first()
    if not content:
        raise HTTPException(status_code=404, detail="Content not found")
    row = _enrich(content, db)
    row["histories"] = [
        {"id": h.id, "field_name": h.field_name, "old_value": h.old_value,
         "new_value": h.new_value, "changed_at": h.changed_at, "changed_by_name": h.changed_by_name}
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

    role = current_user.role

    # Role guards for CMS-only transitions
    if payload.new_status in (StatusEnum.INGESTING, StatusEnum.DONE_INGEST):
        if role not in ("cms", "admin"):
            raise HTTPException(
                status_code=403,
                detail="Hanya tim CMS atau Admin yang dapat mengubah status ke Ingesting / Done Ingest.",
            )

    _validate_workflow(content.status, payload.new_status)

    old_status = content.status
    content.status = payload.new_status

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

    notif_body = f"{content.title} - Eps {content.episode}"
    notif_url = f"/qc/{content.id}"

    # Notify CMS when ready to ingest (editor submitted) or re-submitted after Need Revised
    if payload.new_status == StatusEnum.READY_TO_INGEST:
        # Check if naming_asset is empty — warn CMS if so
        if not content.naming_asset:
            _notify_cms(db, content, background_tasks,
                        "⚠️ Naming Asset Belum Diisi!",
                        f"{content.title} (Eps {content.episode}) siap upload tapi Naming Asset belum diisi. Segera isi sebelum ingest.",
                        f"/qc/{content.id}")
        else:
            _notify_cms(db, content, background_tasks,
                        "Konten Siap Diingest", notif_body, notif_url)

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
    CMS marks content as Need Revised during Ingesting.
    Sets status to Need Revised and notifies the editor.
    """
    content = db.query(QCContent).filter(QCContent.id == content_id).first()
    if not content:
        raise HTTPException(status_code=404, detail="Content not found")

    role = current_user.role
    current_status = content.status

    if role == "cms":
        # CMS can only revise when status is Ingesting
        if current_status != StatusEnum.INGESTING:
            raise HTTPException(
                status_code=403,
                detail=f"Tim CMS hanya bisa revisi saat status 'Ingesting'. "
                       f"Status saat ini: '{current_status.value}'.",
            )
    elif role == "editor":
        # Editor cannot initiate a revise — that comes from CMS
        raise HTTPException(
            status_code=403,
            detail="Editor tidak bisa meminta revisi. Gunakan tombol di halaman detail untuk kirim ulang.",
        )
    # admin: no restriction

    old_status = content.status
    content.status = StatusEnum.NEED_REVISED
    content.revised_notes = payload.revised_notes

    _log_change(db, content.id, "status", old_status.value, StatusEnum.NEED_REVISED.value,
                user_id=current_user.id, by_name=current_user.name)
    _log_change(db, content.id, "revised_notes", None, payload.revised_notes,
                user_id=current_user.id, by_name=current_user.name)

    db.commit()
    db.refresh(content)

    row = _enrich(content, db)
    background_tasks.add_task(sync_row, row)

    # Notify editor
    notif_body = f"{content.title} - Eps {content.episode}"
    notif_url = f"/qc/{content.id}"
    _notify_editor(db, content, background_tasks, "Konten Perlu Direvisi", notif_body, notif_url)

    return row


@router.get("/{content_id}/history", response_model=List[QCHistoryOut])
def get_history(content_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    content = db.query(QCContent).filter(QCContent.id == content_id).first()
    if not content:
        raise HTTPException(status_code=404, detail="Content not found")
    return [
        {"id": h.id, "field_name": h.field_name, "old_value": h.old_value,
         "new_value": h.new_value, "changed_at": h.changed_at, "changed_by_name": h.changed_by_name}
        for h in content.histories
    ]

# ─── Naming Asset endpoint ───────────────────────────────────────────────────

class NamingAssetPayload(BaseModel):
    naming_asset: str

@router.patch("/{content_id}/naming-asset", response_model=QCContentOut)
def set_naming_asset(
    content_id: int,
    payload: NamingAssetPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """CMS or Editor can set/update the naming asset for a content."""
    if current_user.role not in ("cms", "editor", "admin"):
        raise HTTPException(403, "Akses ditolak")
    content = db.query(QCContent).filter(QCContent.id == content_id).first()
    if not content:
        raise HTTPException(404, "Content not found")
    old = content.naming_asset
    content.naming_asset = payload.naming_asset.strip()
    _log_change(db, content.id, "naming_asset", old, payload.naming_asset,
                user_id=current_user.id, by_name=current_user.name)
    db.commit()
    db.refresh(content)
    return {**_enrich(content, db)}
