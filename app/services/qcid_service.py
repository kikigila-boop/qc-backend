"""
QCID Service
Format: QC-YYYY-000001
- Auto-increments per year
- Once assigned, never changes
- Only assigned when: qc_result=PASS AND status=QC Done
"""
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import func, extract
from ..models.qc_content import QCContent


def generate_qcid(db: Session) -> str:
    """Generate the next QCID for the current year."""
    year = datetime.now().year

    # Count existing QCIDs for this year
    count = (
        db.query(func.count(QCContent.id))
        .filter(
            QCContent.qcid.isnot(None),
            extract("year", QCContent.qc_date) == year,
        )
        .scalar()
        or 0
    )

    next_number = count + 1
    return f"QC-{year}-{next_number:06d}"


def maybe_assign_qcid(content: QCContent, db: Session) -> None:
    """
    Assign a QCID if the content qualifies and doesn't have one yet.
    Called whenever qc_result or status changes.
    """
    from ..models.qc_content import QCResult, StatusEnum

    if (
        content.qcid is None
        and content.qc_result == QCResult.PASS
        and content.status == StatusEnum.QC_DONE
    ):
        content.qcid = generate_qcid(db)
