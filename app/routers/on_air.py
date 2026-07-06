from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.on_air import OnAirEntry
from ..services.on_air_service import sync_all, sync_platform, get_last_synced
from ..routers.auth import get_current_user
from ..models.user import User

router = APIRouter(prefix="/on-air", tags=["On Air"])


def _format_entries(entries: list[OnAirEntry]) -> dict[str, Any]:
    rows = [e.row_data for e in entries]
    synced_at = entries[0].synced_at.isoformat() if entries else None
    return {"rows": rows, "synced_at": synced_at, "count": len(rows)}


@router.get("/vplus")
def get_vplus(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    entries = (
        db.query(OnAirEntry)
        .filter(OnAirEntry.platform == "vplus")
        .order_by(OnAirEntry.row_index)
        .all()
    )
    return _format_entries(entries)


@router.get("/vshort")
def get_vshort(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    entries = (
        db.query(OnAirEntry)
        .filter(OnAirEntry.platform == "vshort")
        .order_by(OnAirEntry.row_index)
        .all()
    )
    return _format_entries(entries)


@router.post("/sync")
def manual_sync(
    platform: str = "all",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Manual sync trigger. Admin only. platform = 'all' | 'vplus' | 'vshort'"""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")

    if platform == "all":
        results = sync_all(db)
    elif platform in ("vplus", "vshort"):
        results = [sync_platform(db, platform)]
    else:
        raise HTTPException(status_code=400, detail="Invalid platform")

    return {"results": results, "synced_at": datetime.utcnow().isoformat()}
