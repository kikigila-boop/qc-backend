from sqlalchemy import (
    Column, Integer, String, Text, DateTime, ForeignKey,
    Enum as SAEnum, func, Index
)
from sqlalchemy.orm import relationship
from ..database import Base
import enum


class QCResult(str, enum.Enum):
    PASS = "PASS"
    NOT_PASS = "NOT PASS"


class StatusEnum(str, enum.Enum):
    QC_PROCESS = "QC Process"
    QC_DONE = "QC Done"
    UPLOADING = "Uploading"
    READY_TO_INGEST = "Ready To Ingest"
    DONE_INGEST = "Done Ingest"
    REVISED = "Revised"


# Workflow order - used to validate transitions
STATUS_ORDER = [
    StatusEnum.QC_PROCESS,
    StatusEnum.QC_DONE,
    StatusEnum.UPLOADING,
    StatusEnum.READY_TO_INGEST,
    StatusEnum.DONE_INGEST,
]


class StatusMaster(Base):
    __tablename__ = "status_master"

    id = Column(Integer, primary_key=True)
    name = Column(String(50), unique=True, nullable=False)
    order = Column(Integer, nullable=False)
    description = Column(String(200))


class QCContent(Base):
    __tablename__ = "qc_content"

    id = Column(Integer, primary_key=True, index=True)
    qcid = Column(String(20), unique=True, index=True, nullable=True)

    # Mandatory fields
    title = Column(String(300), nullable=False, index=True)
    season = Column(String(20), nullable=False)
    episode = Column(String(20), nullable=False)
    qc_result = Column(SAEnum(QCResult), nullable=False)

    # editor_name: free-text, no user account required
    editor_name = Column(String(100), nullable=False, index=True)
    # editor_id: optional FK when editor has a registered account
    editor_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    status = Column(SAEnum(StatusEnum), nullable=False, default=StatusEnum.QC_PROCESS)
    qc_date = Column(DateTime(timezone=True), server_default=func.now())

    # Optional fields
    duration = Column(String(20))
    cast = Column(Text)
    storage_location = Column(String(200))
    notes = Column(Text)

    # CMS tracking - populated when CMS team marks Done Ingest
    ingest_by = Column(String(100))
    ingest_at = Column(DateTime(timezone=True))

    # Revision tracking (set by CMS when content needs rework)
    revised_notes = Column(Text)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    editor_user = relationship("User", back_populates="qc_contents", foreign_keys=[editor_id])
    histories = relationship("QCHistory", back_populates="qc_content", order_by="QCHistory.changed_at.desc()")

    # Composite indexes for search performance
    __table_args__ = (
        Index("ix_qc_content_title_season_ep", "title", "season", "episode"),
        Index("ix_qc_content_status_result", "status", "qc_result"),
    )


class QCHistory(Base):
    """Immutable activity log - never delete rows from this table."""
    __tablename__ = "qc_history"

    id = Column(Integer, primary_key=True, index=True)
    qc_content_id = Column(Integer, ForeignKey("qc_content.id"), nullable=False, index=True)

    # changed_by_id is null when change comes from CMS operator (non-registered user)
    changed_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    # changed_by_name always populated: user.name or CMS operator name
    changed_by_name = Column(String(100))

    field_name = Column(String(100), nullable=False)
    old_value = Column(Text)
    new_value = Column(Text)
    changed_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    qc_content = relationship("QCContent", back_populates="histories")
    changed_by_user = relationship("User", back_populates="histories", foreign_keys=[changed_by_id])
