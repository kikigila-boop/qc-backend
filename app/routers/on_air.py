from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.on_air import OnAirEntry
from ..models.user import User
from ..models.notification import UserNotification
from ..services.on_air_service import sync_all, sync_platform
from ..services.push_service import send_push_to_users
from .auth import get_current_user

from zoneinfo import ZoneInfo

_WIB = ZoneInfo("Asia/Jakarta")
_MONTH_MAP = {
    "jan":1,"feb":2,"mar":3,"apr":4,"may":5,"mei":5,"jun":6,
    "jul":7,"aug":8,"agu":8,"sep":9,"oct":10,"okt":10,"nov":11,"dec":12,"des":12,
}

def _parse_date(date_str: str):
    if not date_str:
        return None
    parts = date_str.strip().split()
    if len(parts) == 3:
        try:
            day = int(parts[0])
            mon = _MONTH_MAP.get(parts[1].lower())
            year = int(parts[2])
            if mon:
                from datetime import date
                return date(year, mon, day)
        except Exception:
            pass
    return None

def _is_upcoming(date_str: str) -> bool:
    from datetime import date
    parsed = _parse_date(date_str)
    if parsed is None:
        return True
    today = datetime.now(_WIB).date()
    return parsed >= today

router = APIRouter(prefix="/on-air", tags=["On Air"])


def _row_with_meta(e: OnAirEntry) -> dict:
    return {
        **e.row_data,
        "_id":              e.id,
        "_is_aired":        e.is_aired,
        "_aired_at":        e.aired_at.isoformat() if e.aired_at else None,
        "_aired_by":        e.aired_by,
        "_pic_user_id":     e.pic_user_id,
        "_pic_name":        e.pic_name,
        "_pic_assigned_at": e.pic_assigned_at.isoformat() if e.pic_assigned_at else None,
        "_job_status":      e.job_status,
        "_platform":        e.platform,
    }


def _format_entries_with_meta(entries: list) -> dict:
    rows = [_row_with_meta(e) for e in entries]
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
    entries = [e for e in entries if _is_upcoming(e.row_data.get("Release Schedule", ""))]
    return _format_entries_with_meta(entries)


@router.get("/vshort")
def get_vshort(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    entries = (
        db.query(OnAirEntry)
        .filter(OnAirEntry.platform == "vshort", OnAirEntry.is_aired == False)
        .order_by(OnAirEntry.row_index)
        .all()
    )
    entries = [e for e in entries if _is_upcoming(e.row_data.get("Release Date", ""))]
    return _format_entries_with_meta(entries)


@router.get("/log-airing")
def get_log_airing(
    platform: str = "all",
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    q = db.query(OnAirEntry).filter(OnAirEntry.is_aired == True)
    if platform != "all":
        q = q.filter(OnAirEntry.platform == platform)
    entries = q.order_by(OnAirEntry.aired_at.desc()).all()
    rows = [_row_with_meta(e) for e in entries]
    return {"rows": rows, "count": len(rows)}


@router.patch("/{entry_id}/aired")
def mark_aired(
    entry_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    entry = db.query(OnAirEntry).filter(OnAirEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")

    entry.is_aired = not entry.is_aired
    entry.aired_at = datetime.now(timezone.utc) if entry.is_aired else None
    entry.aired_by = current_user.name if entry.is_aired else None
    db.commit()
    db.refresh(entry)
    return _row_with_meta(entry)


# ─── PIC Assignment ───────────────────────────────────────────────────────

class AssignPicBody(BaseModel):
    user_id: Optional[int] = None  # None = unassign


@router.patch("/{entry_id}/assign-pic")
def assign_pic(
    entry_id: int,
    body: AssignPicBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in ("admin", "supervisor", "chef_editor"):
        raise HTTPException(status_code=403, detail="Admin/supervisor only")

    entry = db.query(OnAirEntry).filter(OnAirEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")

    if body.user_id is None:
        # Unassign
        entry.pic_user_id = None
        entry.pic_name = None
        entry.pic_assigned_at = None
        entry.job_status = None
        db.commit()
        db.refresh(entry)
        return _row_with_meta(entry)

    editor = db.query(User).filter(User.id == body.user_id, User.is_active == True).first()
    if not editor:
        raise HTTPException(status_code=404, detail="User not found")

    entry.pic_user_id = editor.id
    entry.pic_name = editor.name
    entry.pic_assigned_at = datetime.now(timezone.utc)

    # Derive title for notification
    title_key = "Title" if entry.platform == "vplus" else "Title EN"
    content_title = entry.row_data.get(title_key) or entry.row_data.get("Title") or "—"

    # Create in-app notification
    notif = UserNotification(
        user_id=editor.id,
        title="📋 Kamu ditugaskan sebagai PIC",
        body=f"Konten: {content_title} ({entry.platform.upper()})",
        url="/on-air",
    )
    db.add(notif)
    db.commit()
    db.refresh(entry)

    # Push notification (best-effort)
    try:
        send_push_to_users(
            db,
            user_ids=[editor.id],
            title="📋 PIC Assignment",
            body=f"Kamu ditugaskan ke: {content_title}",
            url="/on-air",
        )
    except Exception:
        pass

    return _row_with_meta(entry)


# ─── Add Job ─────────────────────────────────────────────────────────────

@router.patch("/{entry_id}/add-job")
def add_job(
    entry_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    entry = db.query(OnAirEntry).filter(OnAirEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")

    if not entry.pic_user_id:
        raise HTTPException(status_code=400, detail="PIC belum diassign")

    entry.job_status = "added"
    db.commit()
    db.refresh(entry)
    return _row_with_meta(entry)


# ─── Sync ────────────────────────────────────────────────────────────────

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
