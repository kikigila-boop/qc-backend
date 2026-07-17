# app/routers/qc_results.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
from ..database import get_db
from ..models.qc_result import QCResultRecord, QCResultItem
from ..models.qc_content import QCContent, StatusEnum, QCResult

router = APIRouter(prefix="/qc-results", tags=["QC Results"])


class QCResultItemIn(BaseModel):
    error_type_id: int
    status: str


class QCResultIn(BaseModel):
    qc_content_id: int
    library_id: Optional[str] = None
    intimate_scene: str = "pass"
    gore_scene: str = "pass"
    rating_age: Optional[str] = None
    final_result: str
    condition_note: Optional[str] = None
    auto_pass: bool = False
    items: List[QCResultItemIn] = []


@router.post("")
def submit_qc_result(payload: QCResultIn, db: Session = Depends(get_db)):
    content = db.query(QCContent).filter(QCContent.id == payload.qc_content_id).first()
    if not content:
        raise HTTPException(status_code=404, detail="QC Content tidak ditemukan")

    record = QCResultRecord(
        qc_content_id=payload.qc_content_id,
        library_id=payload.library_id,
        intimate_scene=payload.intimate_scene,
        gore_scene=payload.gore_scene,
        rating_age=payload.rating_age,
        final_result=payload.final_result,
        condition_note=payload.condition_note,
        auto_pass=payload.auto_pass,
    )
    db.add(record)
    db.flush()

    for item in payload.items:
        db.add(QCResultItem(
            qc_result_id=record.id,
            error_type_id=item.error_type_id,
            status=item.status,
        ))

    content.qc_result = QCResult.PASS if payload.final_result == "PASS" else QCResult.NOT_PASS
    if content.status == StatusEnum.QC_PROCESS:
        content.status = StatusEnum.QC_DONE

    db.commit()
    return {"id": record.id, "final_result": record.final_result}


@router.get("/{qc_content_id}")
def get_qc_result(qc_content_id: int, db: Session = Depends(get_db)):
    record = (
        db.query(QCResultRecord)
        .filter(QCResultRecord.qc_content_id == qc_content_id)
        .order_by(QCResultRecord.submitted_at.desc())
        .first()
    )
    if not record:
        return None
    return {
        "id": record.id,
        "final_result": record.final_result,
        "auto_pass": record.auto_pass,
        "intimate_scene": record.intimate_scene,
        "gore_scene": record.gore_scene,
        "rating_age": record.rating_age,
        "condition_note": record.condition_note,
        "submitted_at": record.submitted_at,
        "items": [{"error_type_id": i.error_type_id, "status": i.status} for i in record.items],
    }
