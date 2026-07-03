import enum
import uuid
from sqlalchemy import Column, Integer, String, Text, DateTime
from sqlalchemy.sql import func
from app.database import Base


class RequestStatus(str, enum.Enum):
    PENDING   = "Pending"
    APPROVED  = "Approved"
    REJECTED  = "Rejected"
    COPYING   = "Copying"
    TERKIRIM  = "Terkirim"
    DITERIMA  = "Diterima"


class ContentRequest(Base):
    __tablename__ = "content_requests"

    id               = Column(Integer, primary_key=True, index=True)
    token            = Column(String(64), unique=True, index=True, nullable=False)

    requestor_name   = Column(String(200), nullable=False)
    requestor_need   = Column(Text, nullable=False)
    source_requestor = Column(String(200), nullable=False)
    content_titles   = Column(Text, nullable=False)
    total_eps        = Column(Integer, nullable=False)

    status           = Column(String(50), nullable=False, default="Pending")
    rejection_notes  = Column(Text, nullable=True)
    approved_by      = Column(String(100), nullable=True)
    approved_at      = Column(DateTime(timezone=True), nullable=True)
    sent_by          = Column(String(100), nullable=True)
    sent_at          = Column(DateTime(timezone=True), nullable=True)
    received_at      = Column(DateTime(timezone=True), nullable=True)
    created_at       = Column(DateTime(timezone=True), server_default=func.now())
