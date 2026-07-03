import json
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.content_request import ContentRequest, RequestStatus
from app.models.user import User
from app.routers.auth import get_current_user

router = APIRouter(prefix="/request", tags=["request"])


# ── Schemas ────────────────────────────────────────────────────────────────

class RequestSubmit(BaseModel):
    requestor_name:   str
    requestor_need:   str
    source_requestor: str
    content_titles:   List[str]
    total_eps:        int


class ApproveRequest(BaseModel):
    pass


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
        "status":           r.status.value if hasattr(r.status, "value") else r.status,
        "rejection_notes":  r.rejection_notes,
        "approved_by":      r.approved_by,
        "approved_at":      r.approved_at.isoformat() if r.approved_at else None,
        "created_at":       r.created_at.isoformat() if r.created_at else None,
    }


def _notify_mh(db: Session, message: str, requestor_name: str):
    """Send in-app notification to all MH users."""
    from app.models.notification import UserNotification
    from app.models.user import User as UserModel
    mh_users = db.query(UserModel).filter(
        UserModel.role == "material_handling",
        UserModel.is_active == True
    ).all()
    for u in mh_users:
        notif = UserNotification(
            user_id=u.id,
            title="Request Konten Disetujui",
            message=message,
            url="/material",
        )
        db.add(notif)
    db.commit()


# ── Public endpoints (no auth) ─────────────────────────────────────────────

@router.post("/submit", status_code=201)
def submit_request(payload: RequestSubmit, db: Session = Depends(get_db)):
    if not payload.content_titles:
        raise HTTPException(400, "Minimal satu judul konten wajib diisi")
    token = uuid.uuid4().hex
    req = ContentRequest(
        token            = token,
        requestor_name   = payload.requestor_name,
        requestor_need   = payload.requestor_need,
        source_requestor = payload.source_requestor,
        content_titles   = json.dumps(payload.content_titles, ensure_ascii=False),
        total_eps        = payload.total_eps,
        status           = RequestStatus.PENDING,
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


# ── Authenticated endpoints ────────────────────────────────────────────────

@router.get("/list")
def list_requests(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in ("admin", "material_handling"):
        raise HTTPException(403, "Akses ditolak")
    requests = db.query(ContentRequest).order_by(ContentRequest.created_at.desc()).all()
    return [_to_out(r) for r in requests]


@router.patch("/{request_id}/approve")
def approve_request(
    request_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != "admin":
        raise HTTPException(403, "Hanya admin yang bisa approve")
    r = db.query(ContentRequest).filter(ContentRequest.id == request_id).first()
    if not r:
        raise HTTPException(404, "Request tidak ditemukan")
    if r.status != RequestStatus.PENDING:
        raise HTTPException(400, f"Status sudah {r.status.value}")
    r.status      = RequestStatus.APPROVED
    r.approved_by = current_user.name
    r.approved_at = datetime.now(timezone.utc)
    titles = json.loads(r.content_titles) if r.content_titles else []
    title_str = ", ".join(titles[:2]) + (f" +{len(titles)-2} lainnya" if len(titles) > 2 else "")
    _notify_mh(db, f"Request dari {r.requestor_name} ({r.source_requestor}) telah disetujui: {title_str}", r.requestor_name)
    db.refresh(r)
    return _to_out(r)


@router.patch("/{request_id}/reject")
def reject_request(
    request_id: int,
    payload: RejectRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != "admin":
        raise HTTPException(403, "Hanya admin yang bisa reject")
    r = db.query(ContentRequest).filter(ContentRequest.id == request_id).first()
    if not r:
        raise HTTPException(404, "Request tidak ditemukan")
    if r.status != RequestStatus.PENDING:
        raise HTTPException(400, f"Status sudah {r.status.value}")
    r.status          = RequestStatus.REJECTED
    r.rejection_notes = payload.rejection_notes
    db.commit()
    db.refresh(r)
    return _to_out(r)
