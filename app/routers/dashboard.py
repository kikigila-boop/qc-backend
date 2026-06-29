from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func, extract
from datetime import datetime, timedelta
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

    # Weekly progress — last 8 weeks
    weekly = []
    for i in range(7, -1, -1):
        week_start = datetime.now() - timedelta(weeks=i + 1)
        week_end = datetime.now() - timedelta(weeks=i)
        cnt = (
            db.query(func.count(QCContent.id))
            .filter(QCContent.created_at >= week_start, QCContent.created_at < week_end)
            .scalar()
            or 0
        )
        weekly.append({"week_label": week_start.strftime("W%W %b"), "count": cnt})

    # Monthly progress — last 6 months
    monthly = []
    for i in range(5, -1, -1):
        now = datetime.now()
        month = (now.month - i - 1) % 12 + 1
        year = now.year if (now.month - i - 1) >= 0 else now.year - 1
        cnt = (
            db.query(func.count(QCContent.id))
            .filter(
                extract("year", QCContent.created_at) == year,
                extract("month", QCContent.created_at) == month,
            )
            .scalar()
            or 0
        )
        monthly.append({"month_label": datetime(year, month, 1).strftime("%b %Y"), "count": cnt})

    by_status = [{"status": s.value, "count": count_status(s)} for s in StatusEnum]

    return DashboardStats(
        total=total,
        qc_process=count_status(StatusEnum.QC_PROCESS),
        qc_done=count_status(StatusEnum.QC_DONE),
        uploading=count_status(StatusEnum.UPLOADING),
        ready_to_ingest=count_status(StatusEnum.READY_TO_INGEST),
        done_ingest=count_status(StatusEnum.DONE_INGEST),
        weekly_progress=weekly,
        monthly_progress=monthly,
        by_status=by_status,
    )
