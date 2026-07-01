from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from ..models.qc_content import QCResult, StatusEnum


class QCContentCreate(BaseModel):
    title: str
    season: str
    episode: str
    qc_result: QCResult
    editor_name: str                          # free-text, no account required
    editor_id: Optional[int] = None           # optional FK when editor has account
    status: StatusEnum = StatusEnum.QC_PROCESS
    # Optional
    duration: Optional[str] = None
    cast: Optional[str] = None
    storage_location: Optional[str] = None
    notes: Optional[str] = None
    qc_date: Optional[datetime] = None      # tanggal QC; default = hari ini


class QCContentUpdate(BaseModel):
    title: Optional[str] = None
    season: Optional[str] = None
    episode: Optional[str] = None
    qc_result: Optional[QCResult] = None
    editor_name: Optional[str] = None
    duration: Optional[str] = None
    cast: Optional[str] = None
    storage_location: Optional[str] = None
    notes: Optional[str] = None


class StatusTransition(BaseModel):
    new_status: StatusEnum


class QCHistoryOut(BaseModel):
    id: int
    field_name: str
    old_value: Optional[str]
    new_value: Optional[str]
    changed_at: datetime
    changed_by_name: Optional[str] = None

    model_config = {"from_attributes": True}


class QCContentOut(BaseModel):
    id: int
    qcid: Optional[str]
    title: str
    season: str
    episode: str
    duration: Optional[str]
    cast: Optional[str]
    storage_location: Optional[str]
    notes: Optional[str]
    qc_result: QCResult
    status: StatusEnum
    editor_name: str                          # always present
    editor_id: Optional[int] = None
    ingest_by: Optional[str] = None          # CMS operator name
    ingest_at: Optional[datetime] = None
    qc_date: datetime
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class QCContentDetail(QCContentOut):
    histories: List[QCHistoryOut] = []


class CMSIngestRequest(BaseModel):
    """Payload sent by CMS operator to mark a content as Done Ingest."""
    operator_name: str   # name of the CMS person doing the ingest



class CMSRevisedRequest(BaseModel):
    """Payload sent by CMS operator to mark content as Revised."""
    operator_name: str
    revised_notes: str


class ReviseRequest(BaseModel):
    """Payload for marking content as Revised (from editor or CMS)."""
    revised_notes: str

class QCContentFilter(BaseModel):
    search: Optional[str] = None          # global search across QCID, title, episode, cast
    status: Optional[StatusEnum] = None
    qc_result: Optional[QCResult] = None
    editor_id: Optional[int] = None
    season: Optional[str] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    page: int = 1
    page_size: int = 20


class WeeklyProgress(BaseModel):
    week_label: str
    count: int


class MonthlyProgress(BaseModel):
    month_label: str
    count: int


class StatusCount(BaseModel):
    status: str
    count: int


class DashboardStats(BaseModel):
    total: int
    qc_process: int
    qc_done: int
    uploading: int
    ready_to_ingest: int
    done_ingest: int
    weekly_progress: List[WeeklyProgress]
    monthly_progress: List[MonthlyProgress]
    by_status: List[StatusCount]
