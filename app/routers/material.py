"""
Material Handling Router
Flow:
  MH input konten â Material Avail (editor belum assign)
  Editor claim â QC Process (editor assigned, pipeline normal)
  Editor return to MH (materi bermasalah) â Material Revised
  MH fix + re-avail â Material Avail (editor bisa claim lagi)
"""
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.user import User
from ..models.qc_content import QCContent, QCHistory, StatusEnum
from ..models.library import LibraryEntry, LibraryIdCounter
from ..schemas.qc_content import ClaimRequest, MaterialReturnRequest, QCContentOut
from ..utils.security import get_current_user
from ..services import push_service, notification_service

router = APIRouter(prefix="/material", tags=["Material Handling"])


def _log(db, content_id, field, old, new, user_id=None, by_name=None):
    db.add(QCHistory(
        content_id=content_id, field=field,
        old_value=str(old) if old is not None else None,
        new_value=str(new) if new is not None else None,
        changed_by_id=user_id, changed_by_name=by_name,
    ))


def _enrich(c: QCContent) -> dict:
    return c


def _notify_mh(db, content, background_tasks, title, body, url):
    notification_service.create_for_role(db, "material_handling", title, body, url)


# âââ MH endpoints ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ

@router.get("/queue", response_model=List[QCContentOut])
def mh_queue(
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    MH sees their own submitted items.
    - Material Avail items they created (waiting for editor to claim)
    - Material Revised items (returned by editor, needs fixing)
    Admin/supervisor sees everything.
    """
    if current_user.role not in ("material_handling", "admin", "supervisor", "chef_editor"):
        raise HTTPException(status_code=403, detail="Tidak memiliki akses.")

    q = db.query(QCContent).filter(
        QCContent.status.in_([StatusEnum.MATERIAL_AVAIL, StatusEnum.MATERIAL_REVISED])
    )

    if current_user.role == "material_handling":
        q = q.filter(QCContent.mh_id == current_user.id)

    if status:
        try:
            q = q.filter(QCContent.status == StatusEnum(status))
        except ValueError:
            pass

    if search:
        like = f"%{search}%"
        q = q.filter(or_(
            QCContent.title.ilike(like),
            QCContent.episode.ilike(like),
            QCContent.season.ilike(like),
        ))

    items = q.order_by(QCContent.created_at.desc()).all()
    return items


@router.get("/queue/count")
def mh_queue_count(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in ("material_handling", "admin", "supervisor", "chef_editor"):
        raise HTTPException(status_code=403, detail="Tidak memiliki akses.")

    q = db.query(QCContent).filter(
        QCContent.status.in_([StatusEnum.MATERIAL_AVAIL, StatusEnum.MATERIAL_REVISED])
    )
    if current_user.role == "material_handling":
        q = q.filter(QCContent.mh_id == current_user.id)

    total = q.count()
    avail = q.filter(QCContent.status == StatusEnum.MATERIAL_AVAIL).count()
    revised = q.filter(QCContent.status == StatusEnum.MATERIAL_REVISED).count()
    return {"total": total, "avail": avail, "revised": revised}


@router.patch("/{content_id}/re-avail", response_model=QCContentOut)
def re_avail(
    content_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """MH marks revised content as available again."""
    if current_user.role not in ("material_handling", "admin"):
        raise HTTPException(status_code=403, detail="Hanya MH / Admin.")

    content = db.query(QCContent).filter(QCContent.id == content_id).first()
    if not content:
        raise HTTPException(status_code=404, detail="Content not found")
    if content.status != StatusEnum.MATERIAL_REVISED:
        raise HTTPException(
            status_code=400,
            detail=f"Status harus Material Revised, bukan '{content.status.value}'.",
        )

    old_status = content.status
    content.status = StatusEnum.MATERIAL_AVAIL
    _log(db, content.id, "status", old_status.value, StatusEnum.MATERIAL_AVAIL.value,
         user_id=current_user.id, by_name=current_user.name)
    db.commit()
    db.refresh(content)
    return content


# âââ Readiness endpoint (alias for available â used by Readiness tab) âââââââââââââââââââââ

@router.get("/readiness", response_model=List[QCContentOut])
def readiness_list(
    search: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """All Material Avail items â visible to MH for readiness overview."""
    q = db.query(QCContent).filter(QCContent.status == StatusEnum.MATERIAL_AVAIL)
    if search:
        like = f"%{search}%"
        q = q.filter(or_(
            QCContent.title.ilike(like),
            QCContent.episode.ilike(like),
            QCContent.season.ilike(like),
        ))
    return q.order_by(QCContent.title.asc(), QCContent.season.asc(), QCContent.episode.asc()).all()


# âââ Editor endpoints ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ

@router.get("/available", response_model=List[QCContentOut])
def available_for_editors(
    search: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """All Material Avail items â editors browse and claim from here."""
    q = db.query(QCContent).filter(QCContent.status == StatusEnum.MATERIAL_AVAIL)
    if search:
        like = f"%{search}%"
        q = q.filter(or_(
            QCContent.title.ilike(like),
            QCContent.episode.ilike(like),
            QCContent.season.ilike(like),
        ))
    items = q.order_by(QCContent.title.asc(), QCContent.season.asc(), QCContent.episode.asc()).all()
    return items


@router.post("/claim")
def claim_content(
    payload: ClaimRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Editor claims one or more Material Avail items."""
    if current_user.role not in ("editor", "chef_editor", "admin"):
        raise HTTPException(status_code=403, detail="Hanya Editor / Admin.")

    contents = (
        db.query(QCContent)
        .filter(
            QCContent.id.in_(payload.content_ids),
            QCContent.status == StatusEnum.MATERIAL_AVAIL,
        )
        .all()
    )
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
    Editor returns content to MH â material has issues.
    Status â Material Revised, MH gets notified.
    """
    if current_user.role not in ("editor", "chef_editor", "admin"):
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
    db.commit()
    db.refresh(content)

    _notify_mh(
        db, content, background_tasks,
        title=f"Material perlu diperbaiki: {content.title}",
        body=payload.notes or "Editor mengembalikan konten ke MH.",
        url=f"/material",
    )
    db.commit()
    return content


# âââ Library ID endpoint ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ

@router.post("/{content_id}/create-job", response_model=QCContentOut)
def create_library_id_for_content(
    content_id: int,
    library_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Auto-generate or link a Library ID for this content item.
    - If library_id query param given â link to existing LibraryEntry.
    - If not given â auto-create a new LibraryEntry with counter-based ID.
    """
    if current_user.role not in ("material_handling", "admin", "supervisor"):
        raise HTTPException(status_code=403, detail="Tidak memiliki akses.")

    content = db.query(QCContent).filter(QCContent.id == content_id).first()
    if not content:
        raise HTTPException(status_code=404, detail="Content not found")

    if library_id:
        entry = db.query(LibraryEntry).filter(LibraryEntry.library_id == library_id).first()
        if not entry:
            raise HTTPException(status_code=404, detail=f"Library entry '{library_id}' tidak ditemukan")
        content.library_id = library_id
        db.commit()
        db.refresh(content)
        return content

    if content.library_id:
        return content

    _platform_label = "vshort" if (content.platform or "").lower() == "vshort" else "vplus"
    _lib_label      = "VShort" if _platform_label == "vshort" else "VPlus"

    existing = db.query(LibraryEntry).filter(
        LibraryEntry.title_id == content.title,
        LibraryEntry.platform == _platform_label,
    ).first()

    if existing:
        content.library_id = existing.library_id
        db.commit()
        db.refresh(content)
        return content

    counter = (
        db.query(LibraryIdCounter)
        .filter(LibraryIdCounter.platform == _lib_label)
        .with_for_update()
        .first()
    )
    if counter is None:
        counter = LibraryIdCounter(platform=_lib_label, counter=1)
        db.add(counter)
    else:
        counter.counter += 1
    db.flush()

    new_lib_id = f"{datetime.utcnow().strftime('%Y%m%d')}-{_lib_label}-{counter.counter:04d}"
    entry = LibraryEntry(
        library_id=new_lib_id,
        platform=_platform_label,
        title_id=content.title,
        creation_date=datetime.utcnow().strftime("%Y-%m-%d"),
        provider=getattr(content, "mh_name", None),
    )
    db.add(entry)
    content.library_id = new_lib_id
    db.commit()
    db.refresh(content)
    return content


# âââ Delete endpoint ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ

@router.delete("/{content_id}", status_code=204)
def delete_content(
    content_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a content entry (admin / MH only)."""
    if current_user.role not in ("material_handling", "admin"):
        raise HTTPException(status_code=403, detail="Tidak memiliki akses.")
    content = db.query(QCContent).filter(QCContent.id == content_id).first()
    if not content:
        raise HTTPException(status_code=404, detail="Content not found")
    db.delete(content)
    db.commit()
