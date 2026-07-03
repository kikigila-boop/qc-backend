import json
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.content_request import ContentRequest
from app.models.user import User
from app.routers.auth import get_current_user

router = APIRouter(prefix="/request", tags=["request"])

# Canonical status constants
S_PENDING  = "Pending"
S_APPROVED = "Approved"
S_REJECTED = "Rejected"
S_COPYING  = "Copying"
S_TERKIRIM = "Terkirim"
S_DITERIMA = "Diterima"

def _norm(raw) -> str:
    if raw is None: return S_PENDING
    s = str(raw.value if hasattr(raw, 'value') else raw).strip().lower()
    return {
        "pending":  S_PENDING, "approved": S_APPROVED, "rejected": S_REJECTED,
        "copying":  S_COPYING, "terkirim": S_TERKIRIM, "diterima": S_DITERIMA,
    }.get(s, str(raw).strip())


# ── Schemas ────────────────────────────────────────────────────────────────

class RequestSubmit(BaseModel):
    requestor_name:   str
    requestor_need:   str
    source_requestor: str
    content_titles:   List[str]
    total_eps:        int = 0

class RejectRequest(BaseModel):
    rejection_notes: str


# ── Helpers ────────────────────────────────────────────────────────────────

def _to_out(r: ContentRequest) -> dict:
    return {
        "id":               r.id,
        "token":            r.token,
        "requestor_name":   r.requestor_name,
        "requestor_need":   r.requestor_need,
        "source_requestor": r.source_requestor,
        "content_titles":   json.loads(r.content_titles) if r.content_titles else [],
        "total_eps":        r.total_eps,
        "status":           _norm(r.status),
        "rejection_notes":  r.rejection_notes,
        "approved_by":      r.approved_by,
        "approved_at":      r.approved_at.isoformat() if r.approved_at else None,
        "sent_by":          getattr(r, "sent_by", None),
        "sent_at":          r.sent_at.isoformat() if getattr(r, "sent_at", None) else None,
        "received_at":      r.received_at.isoformat() if getattr(r, "received_at", None) else None,
        "created_at":       r.created_at.isoformat() if r.created_at else None,
    }


def _notify_mh(db: Session, title: str, message: str, url: str = "/material"):
    from app.models.notification import UserNotification
    mh_users = db.query(User).filter(
        User.role == "material_handling", User.is_active == True
    ).all()
    for u in mh_users:
        db.add(UserNotification(user_id=u.id, title=title, message=message, url=url))
    db.commit()


# ── Public endpoints ────────────────────────────────────────────────────────

@router.post("/submit", status_code=201)
def submit_request(payload: RequestSubmit, db: Session = Depends(get_db)):
    if not payload.content_titles or not any(t.strip() for t in payload.content_titles):
        raise HTTPException(400, "Minimal satu judul konten wajib diisi")
    token = uuid.uuid4().hex
    req = ContentRequest(
        token            = token,
        requestor_name   = payload.requestor_name.strip(),
        requestor_need   = payload.requestor_need.strip(),
        source_requestor = payload.source_requestor.strip(),
        content_titles   = json.dumps([t.strip() for t in payload.content_titles if t.strip()], ensure_ascii=False),
        total_eps        = payload.total_eps or 0,
        status           = S_PENDING,
    )
    db.add(req)
    db.commit()
    db.refresh(req)
    return {"token": req.token, "id": req.id}


@router.get("/receipt/{token}")
def get_receipt(token: str, db: Session = Depends(get_db)):
    r = db.query(ContentRequest).filter(ContentRequest.token == token).first()
    if not r:
        raise HTTPException(404, "Receipt tidak ditemukan")
    return _to_out(r)


@router.patch("/confirm-receipt/{token}")
def confirm_receipt(token: str, db: Session = Depends(get_db)):
    """Public — requestor mengklik 'Materi Diterima'."""
    r = db.query(ContentRequest).filter(ContentRequest.token == token).first()
    if not r:
        raise HTTPException(404, "Request tidak ditemukan")
    if _norm(r.status) != S_TERKIRIM:
        raise HTTPException(400, f"Status saat ini: {_norm(r.status)}. Harus Terkirim.")
    r.status      = S_DITERIMA
    r.received_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(r)
    return _to_out(r)


# ── Authenticated endpoints ────────────────────────────────────────────────

@router.get("/list")
def list_requests(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role not in ("admin", "material_handling"):
        raise HTTPException(403, "Akses ditolak")
    reqs = db.query(ContentRequest).order_by(ContentRequest.created_at.desc()).all()
    return [_to_out(r) for r in reqs]


@router.patch("/{request_id}/approve")
def approve_request(request_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role != "admin":
        raise HTTPException(403, "Hanya admin yang bisa approve")
    r = db.query(ContentRequest).filter(ContentRequest.id == request_id).first()
    if not r:
        raise HTTPException(404, "Request tidak ditemukan")
    if _norm(r.status) != S_PENDING:
        raise HTTPException(400, f"Status sudah {_norm(r.status)}")
    r.status      = S_APPROVED
    r.approved_by = current_user.name
    r.approved_at = datetime.now(timezone.utc)
    db.commit()
    titles = json.loads(r.content_titles) if r.content_titles else []
    title_str = ", ".join(titles[:2]) + (f" +{len(titles)-2} lainnya" if len(titles) > 2 else "")
    _notify_mh(db, "Request Konten Disetujui",
               f"Request dari {r.requestor_name} ({r.source_requestor}) disetujui: {title_str}",
               "/material")
    db.refresh(r)
    return _to_out(r)


@router.patch("/{request_id}/reject")
def reject_request(request_id: int, payload: RejectRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role != "admin":
        raise HTTPException(403, "Hanya admin yang bisa reject")
    r = db.query(ContentRequest).filter(ContentRequest.id == request_id).first()
    if not r:
        raise HTTPException(404, "Request tidak ditemukan")
    if _norm(r.status) != S_PENDING:
        raise HTTPException(400, f"Status sudah {_norm(r.status)}")
    r.status          = S_REJECTED
    r.rejection_notes = payload.rejection_notes
    db.commit()
    db.refresh(r)
    return _to_out(r)


@router.patch("/{request_id}/start-copy")
def start_copy(request_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role not in ("material_handling", "admin"):
        raise HTTPException(403, "Akses ditolak")
    r = db.query(ContentRequest).filter(ContentRequest.id == request_id).first()
    if not r:
        raise HTTPException(404, "Request tidak ditemukan")
    if _norm(r.status) != S_APPROVED:
        raise HTTPException(400, f"Status saat ini: {_norm(r.status)}. Harus Approved.")
    r.status  = S_COPYING
    r.sent_by = current_user.name
    db.commit()
    db.refresh(r)
    return _to_out(r)


@router.patch("/{request_id}/complete-copy")
def complete_copy(request_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role not in ("material_handling", "admin"):
        raise HTTPException(403, "Akses ditolak")
    r = db.query(ContentRequest).filter(ContentRequest.id == request_id).first()
    if not r:
        raise HTTPException(404, "Request tidak ditemukan")
    if _norm(r.status) != S_COPYING:
        raise HTTPException(400, f"Status saat ini: {_norm(r.status)}. Harus Copying.")
    r.status  = S_TERKIRIM
    r.sent_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(r)
    return _to_out(r)
