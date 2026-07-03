import json
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.delivery import Delivery
from app.routers.auth import get_current_user
from app.models.user import User

router = APIRouter(prefix="/delivery", tags=["delivery"])

# Canonical status constants
STATUS_PENDING      = "Pending"
STATUS_COPYING      = "Copying"
STATUS_READY_TO_QC  = "Ready to QC"
STATUS_CONFIRMED    = "Confirmed"

def _normalize_status(raw) -> str:
    """Normalize status to canonical form regardless of case or source."""
    if raw is None:
        return STATUS_PENDING
    s = str(raw.value if hasattr(raw, 'value') else raw).strip()
    mapping = {
        "pending":     STATUS_PENDING,
        "copying":     STATUS_COPYING,
        "readytoqc":   STATUS_READY_TO_QC,
        "ready to qc": STATUS_READY_TO_QC,
        "ready_to_qc": STATUS_READY_TO_QC,
        "confirmed":   STATUS_CONFIRMED,
    }
    return mapping.get(s.lower().replace(" ", "").replace("_", ""), s)

def _normalize_method(raw) -> str:
    if raw is None:
        return ""
    return str(raw.value if hasattr(raw, 'value') else raw).strip()

# ── Schemas ────────────────────────────────────────────────────────────────

class DeliverySubmit(BaseModel):
    sender_name:     str
    source_category: str
    source_name:     str
    delivery_method: str
    link_video:      Optional[str] = None
    link_trailer:    Optional[str] = None
    link_poster:     Optional[str] = None
    link_metadata:   Optional[str] = None
    link_other:      Optional[str] = None
    content_titles:  List[str]
    delivery_date:   str
    notes:           Optional[str] = None


# ── Helpers ────────────────────────────────────────────────────────────────

def _to_out(d: Delivery) -> dict:
    return {
        "id":              d.id,
        "token":           d.token,
        "sender_name":     d.sender_name,
        "source_category": d.source_category,
        "source_name":     d.source_name,
        "delivery_method": _normalize_method(d.delivery_method),
        "link_video":      d.link_video,
        "link_trailer":    d.link_trailer,
        "link_poster":     d.link_poster,
        "link_metadata":   d.link_metadata,
        "link_other":      d.link_other,
        "content_titles":  json.loads(d.content_titles) if d.content_titles else [],
        "delivery_date":   str(d.delivery_date),
        "notes":           d.notes,
        "status":          _normalize_status(d.status),
        "confirmed_by":    d.confirmed_by,
        "confirmed_at":    d.confirmed_at.isoformat() if d.confirmed_at else None,
        "created_at":      d.created_at.isoformat() if d.created_at else None,
    }


# ── Public endpoints (no auth) ─────────────────────────────────────────────

@router.post("/submit", status_code=201)
def submit_delivery(payload: DeliverySubmit, db: Session = Depends(get_db)):
    from datetime import date
    token = uuid.uuid4().hex
    delivery = Delivery(
        token           = token,
        sender_name     = payload.sender_name,
        source_category = payload.source_category,
        source_name     = payload.source_name,
        delivery_method = payload.delivery_method,
        link_video      = payload.link_video,
        link_trailer    = payload.link_trailer,
        link_poster     = payload.link_poster,
        link_metadata   = payload.link_metadata,
        link_other      = payload.link_other,
        content_titles  = json.dumps(payload.content_titles, ensure_ascii=False),
        delivery_date   = date.fromisoformat(payload.delivery_date),
        notes           = payload.notes,
        status          = STATUS_PENDING,
    )
    db.add(delivery)
    db.commit()
    db.refresh(delivery)
    return {"token": delivery.token, "id": delivery.id}


@router.get("/receipt/{token}")
def get_receipt(token: str, db: Session = Depends(get_db)):
    """Public — full delivery detail for receipt/tracking page."""
    d = db.query(Delivery).filter(Delivery.token == token).first()
    if not d:
        raise HTTPException(404, "Receipt tidak ditemukan")
    return _to_out(d)


# ── Authenticated endpoints ────────────────────────────────────────────────

@router.get("/list")
def list_deliveries(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in ("material_handling", "admin"):
        raise HTTPException(403, "Akses ditolak")
    deliveries = db.query(Delivery).order_by(Delivery.created_at.desc()).all()
    return [_to_out(d) for d in deliveries]


@router.patch("/{delivery_id}/start-copy")
def start_copy(
    delivery_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """MH mulai proses copy materi — Pending → Copying."""
    if current_user.role not in ("material_handling", "admin"):
        raise HTTPException(403, "Akses ditolak")
    d = db.query(Delivery).filter(Delivery.id == delivery_id).first()
    if not d:
        raise HTTPException(404, "Delivery tidak ditemukan")
    current = _normalize_status(d.status)
    if current not in (STATUS_PENDING, STATUS_CONFIRMED):
        raise HTTPException(400, f"Status saat ini: {current}. Harus Pending untuk mulai copy.")
    d.status       = STATUS_COPYING
    d.confirmed_by = current_user.name
    d.confirmed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(d)
    return _to_out(d)


@router.patch("/{delivery_id}/complete-copy")
def complete_copy(
    delivery_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """MH selesai copy materi — Copying → Ready to QC."""
    if current_user.role not in ("material_handling", "admin"):
        raise HTTPException(403, "Akses ditolak")
    d = db.query(Delivery).filter(Delivery.id == delivery_id).first()
    if not d:
        raise HTTPException(404, "Delivery tidak ditemukan")
    current = _normalize_status(d.status)
    if current != STATUS_COPYING:
        raise HTTPException(400, f"Status saat ini: {current}. Harus Copying untuk complete.")
    d.status = STATUS_READY_TO_QC
    db.commit()
    db.refresh(d)
    return _to_out(d)


@router.patch("/{delivery_id}/confirm")
def confirm_delivery(
    delivery_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Legacy confirm endpoint."""
    if current_user.role not in ("material_handling", "admin"):
        raise HTTPException(403, "Akses ditolak")
    d = db.query(Delivery).filter(Delivery.id == delivery_id).first()
    if not d:
        raise HTTPException(404, "Delivery tidak ditemukan")
    d.status       = STATUS_COPYING
    d.confirmed_by = current_user.name
    d.confirmed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(d)
    return _to_out(d)
