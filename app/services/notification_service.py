"""
Helper to create in-app UserNotification records.
Call this alongside push_service calls so users get both
a browser push AND a persistent bell-icon notification.
"""
from typing import List
from sqlalchemy.orm import Session

from ..models.notification import UserNotification
from ..models.user import User


def create_for_users(
    db: Session,
    user_ids: List[int],
    title: str,
    body: str = None,
    url: str = None,
):
    """Create a notification record for each user in user_ids."""
    for uid in user_ids:
        db.add(UserNotification(user_id=uid, title=title, body=body, url=url))
    db.commit()


def create_for_role(
    db: Session,
    role: str,
    title: str,
    body: str = None,
    url: str = None,
):
    """Create notification records for all active users with the given role."""
    users = db.query(User).filter(User.role == role, User.is_active == True).all()
    for u in users:
        db.add(UserNotification(user_id=u.id, title=title, body=body, url=url))
    db.commit()
