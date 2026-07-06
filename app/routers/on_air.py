from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.on_air import OnAirEntry
from ..services.on_air_service import sync_all, sync_platform
from .auth import get_current_user
from ..models.user import User

router = APIRouter(prefix="/on-air", tags=["On Air"])


def _format_entries(entries: list) -> dict:
    rows = [e.row_data for e in entries]
    synced_at = entries[0].synced_at.isoformat() if entries else None
    return {"rows": rows, "synced_at": synced_at, "count": len(rows)}


def _format_entries_with_meta(entries: list) -> dict:
    """Include airing metadata alongside row_data."""
    rows = []
    for e in entries:
        rows.append({
            **e.row_data,
            "_id": e.id,
            "_is_aired": e.is_aired,
            "_aired_at": e.aired_at.isoformat() if e.aired_at else None,
            "_aired_by": e.aired_by,
        })
    synced_at = entries[0].synced_at.isoformat() if entries else None
    return {"rows": rows, "synced_at": synced_at, "count": len(rows)}


@router.get("/vplus")
def get_vplus(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    entries = (
        db.query(OnAirEntry)
        .filter(OnAirEntry.platform == "vplus", OnAirEntry.is_aired == False)
        .order_by(OnAirEntry.row_index)
        .all()
    )
    return _format_entries_with_meta(entries)


@router.get("/vshort")
def get_vshort(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    entries = (
        db.query(OnAirEntry)
        .filter(OnAirEntry.platform == "vshort", OnAirEntry.is_aired == False)
        .order_by(OnAirEntry.row_index)
        .all()
    )
    return _format_entries_with_meta(entries)


@router.get("/log-airing")
def get_log_airing(
    platform: str = "all",
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Semua entri yang sudah ditandai aired."""
    q = db.query(OnAirEntry).filter(OnAirEntry.is_aired == True)
    if platform != "all":
        q = q.filter(OnAirEntry.platform == platform)
    entries = q.order_by(OnAirEntry.aired_at.desc()).all()
    rows = []
    for e in entries:
        rows.append({
            **e.row_data,
            "_id": e.id,
            "_platform": e.platform,
            "_aired_at": e.aired_at.isoformat() if e.aired_at else None,
            "_aired_by": e.aired_by,
        })
    return {"rows": rows, "count": len(rows)}


@router.patch("/{entry_id}/aired")
def mark_aired(
    entry_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Toggle is_aired. Tandai konten sudah tayang."""
    entry = db.query(OnAirEntry).filter(OnAirEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")

    entry.is_aired = not entry.is_aired
    entry.aired_at = datetime.now(timezone.utc) if entry.is_aired else None
    entry.aired_by = current_user.name if entry.is_aired else None
    db.commit()
    db.refresh(entry)
    return {
        "id": entry.id,
        "is_aired": entry.is_aired,
        "aired_at": entry.aired_at.isoformat() if entry.aired_at else None,
        "aired_by": entry.aired_by,
    }


@router.post("/sync")
def manual_sync(
    platform: str = "all",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")

    if platform == "all":
        results = sync_all(db)
    elif platform in ("vplus", "vshort"):
        results = [sync_platform(db, platform)]
    else:
        raise HTTPException(status_code=400, detail="Invalid platform")

    return {"results": results, "synced_at": datetime.utcnow().isoformat()}
