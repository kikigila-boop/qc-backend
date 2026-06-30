from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel

from ..database import get_db
from ..models.user import User
from ..models.notification import UserNotification
from ..utils.security import get_current_user

router = APIRouter(prefix="/notifications", tags=["Notifications"])


# ─── schemas ────────────────────────────────────────────────────────────────

class NotificationOut(BaseModel):
    id: int
    title: str
    body: Optional[str] = None
    url: Optional[str] = None
    is_read: bool
    created_at: datetime

    class Config:
        from_attributes = True


class UnreadCountOut(BaseModel):
    count: int


# ─── endpoints ──────────────────────────────────────────────────────────────

@router.get("/unread-count", response_model=UnreadCountOut)
def get_unread_count(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    count = (
        db.query(UserNotification)
        .filter(
            UserNotification.user_id == current_user.id,
            UserNotification.is_read == False,
        )
        .count()
    )
    return {"count": count}


@router.get("", response_model=List[NotificationOut])
def list_notifications(
    limit: int = 30,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return (
        db.query(UserNotification)
        .filter(UserNotification.user_id == current_user.id)
        .order_by(UserNotification.created_at.desc())
        .limit(limit)
        .all()
    )


@router.patch("/{notification_id}/read", response_model=NotificationOut)
def mark_read(
    notification_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    notif = (
        db.query(UserNotification)
        .filter(
            UserNotification.id == notification_id,
            UserNotification.user_id == current_user.id,
        )
        .first()
    )
    if not notif:
        raise HTTPException(status_code=404, detail="Notification not found")
    notif.is_read = True
    db.commit()
    db.refresh(notif)
    return notif


@router.patch("/read-all", response_model=UnreadCountOut)
def mark_all_read(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    db.query(UserNotification).filter(
        UserNotification.user_id == current_user.id,
        UserNotification.is_read == False,
    ).update({"is_read": True})
    db.commit()
    return {"count": 0}
