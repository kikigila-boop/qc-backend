"""
Push notification endpoints:
- GET  /push/vapid-public-key  → return public key for browser subscription
- POST /push/subscribe         → save browser push subscription
- DELETE /push/unsubscribe     → remove subscription
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.user import User
from ..models.push_subscription import PushSubscription
from ..utils.security import get_current_user
from ..config import settings

router = APIRouter(prefix="/push", tags=["Push Notifications"])


class SubscriptionKeys(BaseModel):
    p256dh: str
    auth: str


class SubscriptionPayload(BaseModel):
    endpoint: str
    keys: SubscriptionKeys


@router.get("/vapid-public-key")
def get_vapid_public_key():
    """Return the VAPID public key for the browser to use when subscribing."""
    if not settings.VAPID_PUBLIC_KEY:
        raise HTTPException(status_code=503, detail="Push notifications not configured")
    return {"publicKey": settings.VAPID_PUBLIC_KEY}


@router.post("/subscribe", status_code=201)
def subscribe(
    payload: SubscriptionPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Save a browser push subscription for the current user."""
    existing = db.query(PushSubscription).filter(
        PushSubscription.endpoint == payload.endpoint
    ).first()

    if existing:
        # Update keys in case they changed
        existing.p256dh = payload.keys.p256dh
        existing.auth = payload.keys.auth
        existing.user_id = current_user.id
        db.commit()
        return {"status": "updated"}

    sub = PushSubscription(
        user_id=current_user.id,
        endpoint=payload.endpoint,
        p256dh=payload.keys.p256dh,
        auth=payload.keys.auth,
    )
    db.add(sub)
    db.commit()
    return {"status": "subscribed"}


@router.delete("/unsubscribe")
def unsubscribe(
    payload: SubscriptionPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Remove a push subscription."""
    db.query(PushSubscription).filter(
        PushSubscription.endpoint == payload.endpoint,
        PushSubscription.user_id == current_user.id,
    ).delete()
    db.commit()
    return {"status": "unsubscribed"}
