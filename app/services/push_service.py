"""
Web Push notification service (VAPID).
Sends browser push notifications to subscribed users.
Falls back gracefully if VAPID keys not configured.
"""
import json
import logging
from typing import List, Optional

from sqlalchemy.orm import Session
from ..config import settings

logger = logging.getLogger(__name__)


def _can_push() -> bool:
    return bool(settings.VAPID_PUBLIC_KEY and settings.VAPID_PRIVATE_KEY)


def send_push_to_users(
    db: Session,
    user_ids: List[int],
    title: str,
    body: str,
    url: str = "/",
) -> None:
    """
    Send a Web Push notification to all subscriptions for the given user IDs.
    Dead subscriptions (410 Gone) are auto-removed from the DB.
    """
    if not _can_push():
        logger.warning("VAPID keys not configured — push skipped")
        return

    from pywebpush import webpush, WebPushException
    from ..models.push_subscription import PushSubscription

    subs = (
        db.query(PushSubscription)
        .filter(PushSubscription.user_id.in_(user_ids))
        .all()
    )

    if not subs:
        logger.info("No push subscriptions found for user_ids=%s", user_ids)
        return

    payload = json.dumps({"title": title, "body": body, "url": url})
    dead_ids = []

    for sub in subs:
        try:
            webpush(
                subscription_info={
                    "endpoint": sub.endpoint,
                    "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
                },
                data=payload,
                vapid_private_key=settings.VAPID_PRIVATE_KEY,
                vapid_claims={"sub": settings.VAPID_SUBJECT},
            )
            logger.info("Push sent to user_id=%s endpoint=...%s", sub.user_id, sub.endpoint[-20:])
        except WebPushException as exc:
            status = exc.response.status_code if exc.response else 0
            logger.warning("Push failed for sub %s: %s (status=%s)", sub.id, exc, status)
            if status in (404, 410):
                dead_ids.append(sub.id)
        except Exception as exc:
            logger.error("Unexpected push error for sub %s: %s", sub.id, exc)

    if dead_ids:
        db.query(PushSubscription).filter(PushSubscription.id.in_(dead_ids)).delete()
        db.commit()
        logger.info("Removed %d stale subscriptions", len(dead_ids))


def send_push_to_role(
    db: Session,
    role: str,
    title: str,
    body: str,
    url: str = "/",
) -> None:
    """Send push to all users with a given role."""
    from ..models.user import User
    user_ids = [u.id for u in db.query(User.id).filter(User.role == role, User.is_active == True).all()]
    if user_ids:
        send_push_to_users(db, user_ids, title, body, url)
