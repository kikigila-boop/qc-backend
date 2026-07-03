"""
Material Handling Router
Flow:
  MH input konten → Material Avail (editor belum assign)
  Editor claim → QC Process (editor assigned, pipeline normal)
  Editor return to MH (materi bermasalah) → Material Revised
  MH fix + re-avail → Material Avail (editor bisa claim lagi)
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.user import User
from ..models.qc_content import QCContent, QCHistory, StatusEnum
from ..schemas.qc_content import ClaimRequest, MaterialReturnRequest, QCContentOut
from ..utils.security import get_current_user
from ..services import push_service, notification_service

router = APIRouter(prefix="/material", tags=["Material Handling"])


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


def _enrich(c: QCContent) -> dict:
    return {col.name: getattr(c, col.name) for col in c.__table__.columns}


def _notify_mh(db, content, background_tasks, title, body, url):
    try:
        notification_service.create_for_role(db, "material_handling", title, body, url)
    except Exception:
        pass
    background_tasks.add_task(
        push_service.send_push_to_role, db, "material_handling", title, body, url
    )


# ─── MH endpoints ─────────────────────────────────────────────────────────────

from fastapi import BackgroundTasks

@router.get("/queue", response_model=List[QCContentOut])
def mh_queue(
    search: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    MH sees:
    - Material Avail items they created (waiting for editor to claim)
    - Material Revised items returned by editors (needs fixing)
    - Items up to QC Done (for tracking)
    """
    if current_user.role not in ("material_handling", "admin"):
        raise HTTPException(status_code=403, detail="Hanya Material Handling / Admin.")

    q = db.query(QCContent).filter(
        QCContent.status.in_([
            StatusEnum.MATERIAL_AVAIL,
            StatusEnum.MATERIAL_REVISED,
            StatusEnum.QC_PROCESS,
            StatusEnum.QC_DONE,
        ])
    )
    if current_user.role == "material_handling":
        # MH only sees their own content
        q = q.filter(QCContent.mh_name == current_user.name)
    if search:
        like = f"%{search}%"
        q = q.filter(or_(
            QCContent.qcid.ilike(like),
            QCContent.title.ilike(like),
            QCContent.episode.ilike(like),
        ))
    items = q.order_by(QCContent.updated_at.desc()).all()
    return [_enrich(i) for i in items]


@router.get("/queue/count")
def mh_queue_count(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in ("material_handling", "admin"):
        raise HTTPException(status_code=403, detail="Hanya Material Handling / Admin.")

    base = db.query(QCContent)
    if current_user.role == "material_handling":
        base = base.filter(QCContent.mh_name == current_user.name)

    avail    = base.filter(QCContent.status == StatusEnum.MATERIAL_AVAIL).count()
    revised  = base.filter(QCContent.status == StatusEnum.MATERIAL_REVISED).count()
    in_qc    = base.filter(QCContent.status.in_([StatusEnum.QC_PROCESS, StatusEnum.QC_DONE])).count()
    return {"material_avail": avail, "material_revised": revised, "in_qc": in_qc}


@router.patch("/{content_id}/re-avail", response_model=QCContentOut)
def re_avail(
    content_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """MH marks a Material Revised item as Material Avail again after fixing."""
    if current_user.role not in ("material_handling", "admin"):
        raise HTTPException(status_code=403, detail="Hanya Material Handling / Admin.")

    content = db.query(QCContent).filter(QCContent.id == content_id).first()
    if not content:
        raise HTTPException(status_code=404, detail="Content not found")
    if content.status != StatusEnum.MATERIAL_REVISED:
        raise HTTPException(
            status_code=400,
            detail=f"Hanya 'Material Revised' yang bisa di-re-avail. Status: '{content.status.value}'.",
        )

    content.status = StatusEnum.MATERIAL_AVAIL
    content.revised_notes = None  # clear notes after fix
    _log(db, content.id, "status", StatusEnum.MATERIAL_REVISED.value, StatusEnum.MATERIAL_AVAIL.value,
         user_id=current_user.id, by_name=current_user.name)
    db.commit()
    db.refresh(content)
    return _enrich(content)


# ─── Editor endpoints ─────────────────────────────────────────────────────────

@router.get("/available", response_model=List[QCContentOut])
def available_for_editors(
    search: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """All Material Avail items — editors browse and claim from here."""
    q = db.query(QCContent).filter(QCContent.status == StatusEnum.MATERIAL_AVAIL)
    if search:
        like = f"%{search}%"
        q = q.filter(or_(
            QCContent.title.ilike(like),
            QCContent.episode.ilike(like),
            QCContent.season.ilike(like),
        ))
    items = q.order_by(QCContent.title.asc(), QCContent.season.asc(), QCContent.episode.asc()).all()
    return [_enrich(i) for i in items]


@router.post("/claim")
def claim_content(
    payload: ClaimRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Editor claims one or more Material Avail items.
    Sets editor_id, editor_name, status → QC Process.
    """
    if current_user.role not in ("editor", "admin"):
        raise HTTPException(status_code=403, detail="Hanya Editor / Admin yang bisa claim konten.")

    contents = db.query(QCContent).filter(
        QCContent.id.in_(payload.content_ids),
        QCContent.status == StatusEnum.MATERIAL_AVAIL,
    ).all()

    if not contents:
        raise HTTPException(status_code=404, detail="Tidak ada konten Material Avail dengan ID tersebut.")

    for c in contents:
        c.editor_id   = current_user.id
        c.editor_name = current_user.name
        c.status      = StatusEnum.QC_PROCESS
        _log(db, c.id, "status", StatusEnum.MATERIAL_AVAIL.value, StatusEnum.QC_PROCESS.value,
             user_id=current_user.id, by_name=current_user.name)
        _log(db, c.id, "editor_name", None, current_user.name,
             user_id=current_user.id, by_name=current_user.name)

    db.commit()
    return {"claimed": len(contents), "editor": current_user.name}


@router.patch("/{content_id}/return-to-mh", response_model=QCContentOut)
def return_to_mh(
    content_id: int,
    payload: MaterialReturnRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Editor returns content to MH — material has issues.
    Status → Material Revised, MH gets notified.
    """
    if current_user.role not in ("editor", "admin"):
        raise HTTPException(status_code=403, detail="Hanya Editor / Admin.")

    content = db.query(QCContent).filter(QCContent.id == content_id).first()
    if not content:
        raise HTTPException(status_code=404, detail="Content not found")
    if content.status not in (StatusEnum.QC_PROCESS, StatusEnum.QC_DONE, StatusEnum.MATERIAL_AVAIL):
        raise HTTPException(
            status_code=400,
            detail=f"Tidak bisa dikembalikan ke MH dari status '{content.status.value}'.",
        )

    old_status = content.status
    content.status        = StatusEnum.MATERIAL_REVISED
    content.revised_notes = payload.notes
    content.editor_id     = None
    content.editor_name   = None

    _log(db, content.id, "status", old_status.value, StatusEnum.MATERIAL_REVISED.value,
         user_id=current_user.id, by_name=current_user.name)
    _log(db, content.id, "revised_notes", None, payload.notes,
         user_id=current_user.id, by_name=current_user.name)

    db.commit()
    db.refresh(content)

    # Notify MH
    notif_body = f"{content.title} - Eps {content.episode}"
    notif_url  = f"/qc/{content.id}"
    _notify_mh(db, content, background_tasks, "Materi Perlu Diperbaiki", notif_body, notif_url)

    return _enrich(content)
