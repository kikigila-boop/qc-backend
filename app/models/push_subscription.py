from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime, func
from sqlalchemy.orm import relationship
from ..database import Base


class PushSubscription(Base):
    """Stores browser Web Push subscriptions per user."""
    __tablename__ = "push_subscriptions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    endpoint = Column(Text, nullable=False, unique=True)
    p256dh = Column(Text, nullable=False)   # browser public key
    auth = Column(Text, nullable=False)      # auth secret
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="push_subscriptions")
