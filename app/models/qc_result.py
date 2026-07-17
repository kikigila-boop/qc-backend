# app/models/qc_result.py
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship
from ..database import Base


class QCErrorType(Base):
    __tablename__ = "qc_error_types"

    id = Column(Integer, primary_key=True, index=True)
    category = Column(String(100), nullable=False, index=True)
    error_name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)

    result_items = relationship("QCResultItem", back_populates="error_type")


class QCResultRecord(Base):
    __tablename__ = "qc_result_records"

    id = Column(Integer, primary_key=True, index=True)
    qc_content_id = Column(Integer, ForeignKey("qc_content.id"), nullable=False, index=True)
    library_id = Column(String(50), nullable=True)
    intimate_scene = Column(String(10), nullable=False, default="pass")
    gore_scene = Column(String(10), nullable=False, default="pass")
    rating_age = Column(String(10), nullable=True)
    final_result = Column(String(20), nullable=False)
    condition_note = Column(Text, nullable=True)
    auto_pass = Column(Boolean, nullable=False, default=False)
    submitted_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    submitted_by_name = Column(String(100), nullable=True)
    submitted_at = Column(DateTime(timezone=True), server_default=func.now())

    qc_content = relationship("QCContent")
    submitted_by = relationship("User", foreign_keys=[submitted_by_id])
    items = relationship("QCResultItem", back_populates="qc_result", cascade="all, delete-orphan")


class QCResultItem(Base):
    __tablename__ = "qc_result_items"

    id = Column(Integer, primary_key=True, index=True)
    qc_result_id = Column(Integer, ForeignKey("qc_result_records.id"), nullable=False, index=True)
    error_type_id = Column(Integer, ForeignKey("qc_error_types.id"), nullable=False)
    status = Column(String(10), nullable=False, default="pass")

    qc_result = relationship("QCResultRecord", back_populates="items")
    error_type = relationship("QCErrorType", back_populates="result_items")
