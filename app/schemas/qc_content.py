from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from ..models.qc_content import QCResult, StatusEnum


class QCContentCreate(BaseModel):
    title: str
    season: str
    episode: str
    qc_result: QCResult
    editor_name: Optional[str] = None         # nullable; MH creates before editor assigned
    editor_id: Optional[int] = None           # optional FK when editor has account
    status: StatusEnum = StatusEnum.QC_PROCESS
    # Optional
    duration: Optional[str] = None
    cast: Optional[str] = None
    naming_asset: Optional[str] = None
    content_type: Optional[str] = None
    platform: Optional[str] = None      # JSON: '["vshort"]' or '["vshort","vplus"]'
    with_subs: bool = False
    with_dubb: bool = False
    selected_languages: Optional[List[str]] = None
    with_dubb: bool = False
    selected_dubb_languages: Optional[List[str]] = None
    storage_location: Optional[str] = None
    notes: Optional[str] = None
    qc_date: Optional[datetime] = None        # tanggal QC; default = hari ini


class ClaimRequest(BaseModel):
    content_ids: List[int]


class MaterialReturnRequest(BaseModel):
    notes: str


class QCContentUpdate(BaseModel):
    title: Optional[str] = None
    season: Optional[str] = None
    episode: Optional[str] = None
    qc_result: Optional[QCResult] = None
    editor_name: Optional[str] = None
    duration: Optional[str] = None
    cast: Optional[str] = None
    naming_asset: Optional[str] = None
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
    mh_name: Optional[str] = None            # Material Handling person who input this
    editor_name: Optional[str] = None         # set when editor claims or creates directly
    editor_id: Optional[int] = None
    ingest_by: Optional[str] = None          # CMS operator name
    ingest_at: Optional[datetime] = None
    revised_notes: Optional[str] = None
    naming_asset: Optional[str] = None
    content_type: Optional[str] = None
    in_logbook: bool = False
    platform: Optional[str] = None
    with_subs: bool = False
    with_dubb: bool = False
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


class EditorStats(BaseModel):
    editor_name: str
    total: int
    pass_count: int
    not_pass_count: int
    done_ingest: int


class DashboardStats(BaseModel):
    total: int
    qc_process: int
    qc_done: int
    uploading: int
    ready_to_ingest: int
    done_ingest: int
    revised: int = 0
    pass_rate: float = 0.0
    avg_turnaround_days: Optional[float] = None
    by_editor: List[EditorStats] = []
    weekly_progress: List[WeeklyProgress]
    monthly_progress: List[MonthlyProgress]
    by_status: List[StatusCount]


# ── Subtitle Schemas ─────────────────────────────────────────────────────────

class SubtitleTaskOut(BaseModel):
    id: int
    qc_content_id: int
    language_code: str
    language_name: str
    status: str
    task_type: str = "subs"
    pic: Optional[str] = None
    updated_at: Optional[datetime] = None
    model_config = {"from_attributes": True}


class SubtitleTaskUpdate(BaseModel):
    status: Optional[str] = None   # pending | in_progress | done
    pic: Optional[str] = None


class SubsContentOut(BaseModel):
    """QC content with subtitle task progress for /subs page."""
    id: int
    qcid: Optional[str]
    title: str
    season: str
    episode: str
    content_type: Optional[str]
    platform: Optional[str]
    with_subs: bool
    status: StatusEnum
    subtitle_tasks: List[SubtitleTaskOut] = []
    model_config = {"from_attributes": True}
