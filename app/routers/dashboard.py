from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func, extract, text
from datetime import datetime, timedelta, timezone
from typing import Optional

from ..database import get_db
from ..models.user import User
from ..models.qc_content import QCContent, StatusEnum, QCResult
from ..schemas.qc_content import DashboardStats
from ..utils.security import get_current_user

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/stats", response_model=DashboardStats)
def get_stats(db: Session = Depends(get_db), _: User = Depends(get_current_user)):

    # ── Status counts via single raw SQL query (avoids PostgreSQL enum cast issues) ─
    status_counts: dict = {}
    total = 0
    try:
        from sqlalchemy import text as sql_text
        rows = db.execute(sql_text(
            "SELECT status, COUNT(*) as cnt FROM qc_content GROUP BY status"
        )).fetchall()
        for row in rows:
            status_counts[row[0]] = int(row[1])
        total = sum(status_counts.values())
    except Exception as e:
        print(f"[dashboard] status count error: {e}")

    def count_status(s: StatusEnum) -> int:
        # Match by enum value string (what's actually stored in DB)
        return status_counts.get(s.name, 0)  # DB stores enum names: QC_DONE, DONE_INGEST, etc.

    # ── Pass rate ─────────────────────────────────────────────────────────────
    try:
        from sqlalchemy import text as sql_text
        pc_rows = db.execute(sql_text(
            "SELECT qc_result, COUNT(*) as cnt FROM qc_content GROUP BY qc_result"
        )).fetchall()
        qr_counts = {row[0]: int(row[1]) for row in pc_rows}
        pass_count = qr_counts.get("PASS", 0) + qr_counts.get("QCResult.PASS", 0)
        pass_rate = round((pass_count / total * 100), 1) if total > 0 else 0.0
    except Exception as e:
        print(f"[dashboard] pass_rate error: {e}")
        pass_count = 0
        pass_rate = 0.0

    # ── Revised count ─────────────────────────────────────────────────────────
    revised = count_status(StatusEnum.REVISED)

    # ── Avg turnaround (qc_date → ingest_at) in days ──────────────────────────
    avg_turnaround_days: Optional[float] = None
    try:
        rows = (
            db.query(QCContent.qc_date, QCContent.ingest_at)
            .filter(QCContent.ingest_at.isnot(None), QCContent.qc_date.isnot(None))
            .all()
        )
        if rows:
            deltas = []
            for r in rows:
                try:
                    diff = (r.ingest_at - r.qc_date).total_seconds() / 86400
                    if diff > 0:
                        deltas.append(diff)
                except Exception:
                    pass
            if deltas:
                avg_turnaround_days = round(sum(deltas) / len(deltas), 1)
    except Exception:
        avg_turnaround_days = None

    # ── Per-editor breakdown — Python-side aggregation (no case() SQL) ────────
    by_editor = []
    try:
        all_items = (
            db.query(
                QCContent.editor_name,
                QCContent.qc_result,
                QCContent.status,
            )
            .filter(QCContent.editor_name.isnot(None), QCContent.editor_name != "")
            .all()
        )
        editor_map: dict = {}
        for row in all_items:
            name = row.editor_name
            if name not in editor_map:
                editor_map[name] = {"editor_name": name, "total": 0, "pass_count": 0,
                                     "not_pass_count": 0, "done_ingest": 0}
            e = editor_map[name]
            e["total"] += 1
            qr = str(row.qc_result)
            if qr in ("PASS", "QCResult.PASS") or row.qc_result == QCResult.PASS:
                e["pass_count"] += 1
            elif qr in ("NOT_PASS", "NOT PASS", "QCResult.NOT_PASS") or row.qc_result == QCResult.NOT_PASS:
                e["not_pass_count"] += 1
            if row.status == StatusEnum.DONE_INGEST:
                e["done_ingest"] += 1

        by_editor = sorted(editor_map.values(), key=lambda x: x["total"], reverse=True)[:20]
    except Exception as e:
        print(f"[dashboard] by_editor error: {e}")
        by_editor = []

    # ── Weekly progress — last 8 weeks ────────────────────────────────────────
    weekly = []
    try:
        now = datetime.now(timezone.utc)
        for i in range(7, -1, -1):
            week_start = now - timedelta(weeks=i + 1)
            week_end   = now - timedelta(weeks=i)
            cnt = (
                db.query(func.count(QCContent.id))
                .filter(QCContent.created_at >= week_start, QCContent.created_at < week_end)
                .scalar() or 0
            )
            weekly.append({"week_label": week_start.strftime("W%W"), "count": cnt})
    except Exception as e:
        print(f"[dashboard] weekly error: {e}")
        weekly = [{"week_label": f"W{i}", "count": 0} for i in range(8)]

    # ── Monthly progress — last 6 months ─────────────────────────────────────
    monthly = []
    try:
        now = datetime.now(timezone.utc)
        for i in range(5, -1, -1):
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
    except Exception as e:
        print(f"[dashboard] monthly error: {e}")
        monthly = []

    by_status = [{"status": s.value, "count": count_status(s)} for s in StatusEnum]
    print(f"[dashboard] status_counts keys: {list(status_counts.keys())}")

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


@router.get("/debug-status")
def debug_status(db: Session = Depends(get_db)):
    """Temporary debug: show raw status values stored in DB."""
    from sqlalchemy import text as sql_text
    rows = db.execute(sql_text(
        "SELECT status, COUNT(*) as cnt FROM qc_content GROUP BY status ORDER BY cnt DESC"
    )).fetchall()
    return {
        "raw_status_distribution": [{"status": row[0], "count": int(row[1])} for row in rows],
        "total_rows": sum(int(r[1]) for r in rows),
    }
