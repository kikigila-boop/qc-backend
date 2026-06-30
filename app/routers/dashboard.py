from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func, extract, case
from datetime import datetime, timedelta
from typing import Optional

from ..database import get_db
from ..models.user import User
from ..models.qc_content import QCContent, StatusEnum
from ..schemas.qc_content import DashboardStats
from ..utils.security import get_current_user

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/stats", response_model=DashboardStats)
def get_stats(db: Session = Depends(get_db), _: User = Depends(get_current_user)):

    def count_status(s: StatusEnum) -> int:
        return db.query(func.count(QCContent.id)).filter(QCContent.status == s).scalar() or 0

    total = db.query(func.count(QCContent.id)).scalar() or 0

    # ── Pass rate ────────────────────────────────────────────────────────────
    pass_count = (
        db.query(func.count(QCContent.id))
        .filter(QCContent.qc_result == "PASS")
        .scalar() or 0
    )
    pass_rate = round((pass_count / total * 100), 1) if total > 0 else 0.0

    # ── Revised count ────────────────────────────────────────────────────────
    revised = count_status(StatusEnum.REVISED)

    # ── Avg turnaround (qc_date → ingest_at) in days ─────────────────────────
    # Only items that have been ingested
    avg_turnaround_days: Optional[float] = None
    try:
        from sqlalchemy import cast, Float
        from sqlalchemy.dialects.postgresql import INTERVAL

        rows = (
            db.query(QCContent.qc_date, QCContent.ingest_at)
            .filter(QCContent.ingest_at.isnot(None), QCContent.qc_date.isnot(None))
            .all()
        )
        if rows:
            deltas = [(r.ingest_at - r.qc_date).total_seconds() / 86400 for r in rows if r.ingest_at > r.qc_date]
            avg_turnaround_days = round(sum(deltas) / len(deltas), 1) if deltas else None
    except Exception:
        avg_turnaround_days = None

    # ── Per-editor breakdown ─────────────────────────────────────────────────
    editor_rows = (
        db.query(
            QCContent.editor_name,
            func.count(QCContent.id).label("total"),
            func.sum(case((QCContent.qc_result == "PASS", 1), else_=0)).label("pass_count"),
            func.sum(case((QCContent.qc_result == "NOT PASS", 1), else_=0)).label("not_pass_count"),
            func.sum(case((QCContent.status == StatusEnum.DONE_INGEST, 1), else_=0)).label("done_ingest"),
        )
        .filter(QCContent.editor_name.isnot(None), QCContent.editor_name != "")
        .group_by(QCContent.editor_name)
        .order_by(func.count(QCContent.id).desc())
        .limit(20)
        .all()
    )

    by_editor = [
        {
            "editor_name": r.editor_name,
            "total": r.total,
            "pass_count": r.pass_count or 0,
            "not_pass_count": r.not_pass_count or 0,
            "done_ingest": r.done_ingest or 0,
        }
        for r in editor_rows
    ]

    # ── Weekly progress — last 8 weeks ───────────────────────────────────────
    weekly = []
    for i in range(7, -1, -1):
        week_start = datetime.now() - timedelta(weeks=i + 1)
        week_end   = datetime.now() - timedelta(weeks=i)
        cnt = (
            db.query(func.count(QCContent.id))
            .filter(QCContent.created_at >= week_start, QCContent.created_at < week_end)
            .scalar() or 0
        )
        weekly.append({"week_label": week_start.strftime("W%W"), "count": cnt})

    # ── Monthly progress — last 6 months ─────────────────────────────────────
    monthly = []
    for i in range(5, -1, -1):
        now   = datetime.now()
        month = (now.month - i - 1) % 12 + 1
        year  = now.year if (now.month - i - 1) >= 0 else now.year - 1
        cnt = (
            db.query(func.count(QCContent.id))
            .filter(
                extract("year",  QCContent.created_at) == year,
                extract("month", QCContent.created_at) == month,
            )
            .scalar() or 0
        )
        monthly.append({
            "month_label": datetime(year, month, 1).strftime("%b %Y"),
            "count": cnt,
        })

    by_status = [{"status": s.value, "count": count_status(s)} for s in StatusEnum]

    return DashboardStats(
        total=total,
        qc_process=count_status(StatusEnum.QC_PROCESS),
        qc_done=count_status(StatusEnum.QC_DONE),
        uploading=count_status(StatusEnum.UPLOADING),
        ready_to_ingest=count_status(StatusEnum.READY_TO_INGEST),
        done_ingest=count_status(StatusEnum.DONE_INGEST),
        revised=revised,
        pass_rate=pass_rate,
        avg_turnaround_days=avg_turnaround_days,
        by_editor=by_editor,
        weekly_progress=weekly,
        monthly_progress=monthly,
        by_status=by_status,
    )
