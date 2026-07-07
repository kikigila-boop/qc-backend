from sqlalchemy import Column, Integer, String, DateTime, JSON, Boolean, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from ..database import Base


class OnAirEntry(Base):
    __tablename__ = "on_air_entries"

    id = Column(Integer, primary_key=True, index=True)
    platform = Column(String(20), nullable=False, index=True)   # "vplus" | "vshort"
    row_index = Column(Integer, nullable=False)
    row_data = Column(JSON, nullable=False)
    synced_at = Column(DateTime(timezone=True), server_default=func.now())

    # Airing log fields
    is_aired = Column(Boolean, default=False, nullable=False)
    aired_at = Column(DateTime(timezone=True), nullable=True)
    aired_by = Column(String(100), nullable=True)

    # PIC (editor yang ditugaskan)
    pic_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    pic_name = Column(String(150), nullable=True)
    pic_assigned_at = Column(DateTime(timezone=True), nullable=True)

    # Job status: None = belum, "added" = sudah add job
    job_status = Column(String(20), nullable=True)

    pic_user = relationship("User", foreign_keys=[pic_user_id])
