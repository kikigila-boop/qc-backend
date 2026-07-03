import enum
import uuid
from sqlalchemy import Column, Integer, String, Text, DateTime, Enum as SAEnum
from sqlalchemy.sql import func
from app.database import Base


class RequestStatus(str, enum.Enum):
    PENDING  = "Pending"
    APPROVED = "Approved"
    REJECTED = "Rejected"


class ContentRequest(Base):
    __tablename__ = "content_requests"

    id               = Column(Integer, primary_key=True, index=True)
    token            = Column(String(64), unique=True, index=True, nullable=False)

    requestor_name   = Column(String(200), nullable=False)
    requestor_need   = Column(Text, nullable=False)
    source_requestor = Column(String(200), nullable=False)
    content_titles   = Column(Text, nullable=False)   # JSON array as text
    total_eps        = Column(Integer, nullable=False)

    status           = Column(SAEnum(RequestStatus, name="requeststatus", create_type=False),
                               nullable=False, default=RequestStatus.PENDING)
    rejection_notes  = Column(Text, nullable=True)
    approved_by      = Column(String(100), nullable=True)
    approved_at      = Column(DateTime(timezone=True), nullable=True)
    created_at       = Column(DateTime(timezone=True), server_default=func.now())
