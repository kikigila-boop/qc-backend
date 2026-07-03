import enum
import uuid
from sqlalchemy import Column, Integer, String, Date, Text, DateTime
from sqlalchemy.sql import func
from app.database import Base


class DeliveryMethod(str, enum.Enum):
    HDD      = "HDD"
    GDRIVE   = "GDrive"
    ASPERA   = "Aspera"
    FILEZILLA = "Filezilla"


class DeliveryStatus(str, enum.Enum):
    PENDING   = "Pending"
    CONFIRMED = "Confirmed"


class Delivery(Base):
    __tablename__ = "deliveries"

    id               = Column(Integer, primary_key=True, index=True)
    token            = Column(String(64), unique=True, index=True, nullable=False)

    # Sender info
    sender_name      = Column(String(200), nullable=False)
    source_category  = Column(String(50), nullable=False)   # PH / MNC Group / Others
    source_name      = Column(String(200), nullable=False)  # sub-option or free text

    # Delivery method
    delivery_method  = Column(String(50), nullable=False)

    # Links (GDrive/Aspera: 4 specific; others: 1 generic)
    link_video       = Column(Text, nullable=True)
    link_trailer     = Column(Text, nullable=True)
    link_poster      = Column(Text, nullable=True)
    link_metadata    = Column(Text, nullable=True)
    link_other       = Column(Text, nullable=True)

    # Content titles stored as newline-separated text
    content_titles   = Column(Text, nullable=False)  # JSON array stored as text

    delivery_date    = Column(Date, nullable=False)
    notes            = Column(Text, nullable=True)

    status           = Column(String(50), nullable=False, default="Pending")
    confirmed_by     = Column(String(100), nullable=True)
    confirmed_at     = Column(DateTime(timezone=True), nullable=True)
    created_at       = Column(DateTime(timezone=True), server_default=func.now())
