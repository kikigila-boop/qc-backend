from sqlalchemy import (
    Column, Integer, String, Text, DateTime, ForeignKey,
    Enum as SAEnum, Boolean, func, Index
)
from sqlalchemy.orm import relationship
from ..database import Base
import enum


class QCResult(str, enum.Enum):
    PASS = "PASS"
    NOT_PASS = "NOT PASS"


class StatusEnum(str, enum.Enum):
    MATERIAL_AVAIL   = "Material Avail"    # NEW: MH input, waiting for editor
    QC_PROCESS       = "QC Process"
    QC_DONE          = "QC Done"
    UPLOADING        = "Uploading"
    READY_TO_INGEST  = "Ready To Ingest"
    INGESTING        = "Ingesting"
    DONE_INGEST      = "Done Ingest"
    REVISED          = "Revised"           # backward compat
    NEED_REVISED     = "Need Revised"      # CMS → editor revisi
    MATERIAL_REVISED = "Material Revised"  # NEW: editor → MH (materi bermasalah)


# Main linear workflow order
STATUS_ORDER = [
    StatusEnum.QC_PROCESS,
    StatusEnum.QC_DONE,
    StatusEnum.UPLOADING,
    StatusEnum.READY_TO_INGEST,
    StatusEnum.INGESTING,
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

    title = Column(String(300), nullable=False, index=True)
    season = Column(String(20), nullable=False)
    episode = Column(String(20), nullable=False)
    qc_result = Column(SAEnum(QCResult), nullable=False)

    # MH tracking — who from Material Handling input this content
    mh_name = Column(String(100), nullable=True)

    # Editor — nullable now (MH creates before editor is assigned)
    editor_name = Column(String(100), nullable=True, index=True)
    editor_id   = Column(Integer, ForeignKey("users.id"), nullable=True)

    status  = Column(SAEnum(StatusEnum), nullable=False, default=StatusEnum.QC_PROCESS)
    qc_date = Column(DateTime(timezone=True), server_default=func.now())

    duration         = Column(String(20))
    cast             = Column(Text)
    naming_asset     = Column(Text, nullable=True)   # Naming asset untuk ADI metadata
    content_type     = Column(String(50), nullable=True)  # Microdrama / Series / Movies / Trailer
    in_logbook       = Column(Boolean, nullable=False, default=False)  # Moved to Log QC
    storage_location = Column(String(200))
    notes            = Column(Text)

    ingest_by = Column(String(100))
    ingest_at = Column(DateTime(timezone=True))

    revised_notes = Column(Text)

    platform   = Column(String(100), nullable=True)   # JSON array e.g. '["vshort","vplus"]'
    with_subs  = Column(Boolean, nullable=False, default=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    editor_user = relationship("User", back_populates="qc_contents", foreign_keys=[editor_id])
    histories       = relationship("QCHistory", back_populates="qc_content", order_by="QCHistory.changed_at.desc()")
    subtitle_tasks  = relationship("SubtitleTask", back_populates="qc_content", order_by="SubtitleTask.language_code")

    __table_args__ = (
        Index("ix_qc_content_title_season_ep", "title", "season", "episode"),
        Index("ix_qc_content_status_result",   "status", "qc_result"),
    )


class QCHistory(Base):
    __tablename__ = "qc_history"

    id             = Column(Integer, primary_key=True, index=True)
    qc_content_id  = Column(Integer, ForeignKey("qc_content.id"), nullable=False, index=True)
    changed_by_id  = Column(Integer, ForeignKey("users.id"), nullable=True)
    changed_by_name= Column(String(100))
    field_name     = Column(String(100), nullable=False)
    old_value      = Column(Text)
    new_value      = Column(Text)
    changed_at     = Column(DateTime(timezone=True), server_default=func.now())

    qc_content      = relationship("QCContent", back_populates="histories")
    changed_by_user = relationship("User", back_populates="histories", foreign_keys=[changed_by_id])


# ── Subtitle Tasks ──────────────────────────────────────────────────────────

class SubtitleStatus(str, enum.Enum):
    PENDING     = "pending"
    IN_PROGRESS = "in_progress"
    DONE        = "done"


class SubtitleTask(Base):
    __tablename__ = "subtitle_tasks"

    id             = Column(Integer, primary_key=True, index=True)
    qc_content_id  = Column(Integer, ForeignKey("qc_content.id"), nullable=False, index=True)
    language_code  = Column(String(5), nullable=False)   # ID, EN, AR, …
    language_name  = Column(String(50), nullable=False)  # Indonesia, English, …
    status         = Column(SAEnum(SubtitleStatus), nullable=False, default=SubtitleStatus.PENDING)
    pic            = Column(String(100), nullable=True)
    updated_at     = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    updated_by_id  = Column(Integer, ForeignKey("users.id"), nullable=True)

    qc_content     = relationship("QCContent", back_populates="subtitle_tasks")
    updated_by     = relationship("User", foreign_keys=[updated_by_id])
