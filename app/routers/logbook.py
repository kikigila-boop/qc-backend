from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import json

from ..database import get_db
from ..models.user import User
from ..models.qc_content import QCContent, QCHistory
from ..models.delivery import Delivery
from ..models.content_request import ContentRequest
from ..utils.security import get_current_user
from ..config import settings

router = APIRouter(prefix="/logbook", tags=["Logbook"])


# ─── Helpers ─────────────────────────────────────────────────────────────────
def _parse_titles(raw: str) -> str:
    try:
        titles = json.loads(raw)
        if isinstance(titles, list):
            return ", ".join(str(t) for t in titles)
    except Exception:
        pass
    return raw or "-"


# ─── Tab 1: Traffic Log ───────────────────────────────────────────────────────
@router.get("/traffic")
def get_traffic(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    deliveries = db.query(Delivery).order_by(Delivery.created_at.desc()).all()
    requests   = db.query(ContentRequest).order_by(ContentRequest.created_at.desc()).all()

    rows = []
    for d in deliveries:
        rows.append({
            "id": d.id, "type": "Kiriman",
            "title": _parse_titles(d.content_titles),
            "from": d.sender_name,
            "method": d.delivery_method,
            "status": d.status,
            "created_at": d.created_at.isoformat() if d.created_at else None,
            "updated_at": d.confirmed_at.isoformat() if d.confirmed_at else None,
            "notes": d.notes or "",
        })
    for r in requests:
        rows.append({
            "id": r.id, "type": "Request",
            "title": _parse_titles(r.content_titles),
            "from": r.requestor_name,
            "method": r.source_requestor,
            "status": r.status,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "updated_at": (r.received_at or r.sent_at or r.approved_at),
            "notes": r.requestor_need or "",
        })

    rows.sort(key=lambda x: x["created_at"] or "", reverse=True)
    return rows


# ─── Tab 2: QC Log ────────────────────────────────────────────────────────────
@router.get("/qc")
def get_qc_log(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    items = db.query(QCContent).filter(QCContent.in_logbook == True).order_by(QCContent.created_at.desc()).all()
    result = []
    for item in items:
        histories = (
            db.query(QCHistory)
            .filter(QCHistory.qc_content_id == item.id)
            .order_by(QCHistory.changed_at.asc())
            .all()
        )
        result.append({
            "id": item.id,
            "qcid": item.qcid,
            "title": item.title,
            "season": item.season,
            "episode": item.episode,
            "content_type": item.content_type,
            "duration": item.duration,
            "status": item.status,
            "qc_result": item.qc_result.value if hasattr(item.qc_result, 'value') else str(item.qc_result),
            "editor_name": item.editor_name,
            "mh_name": item.mh_name,
            "ingest_by": item.ingest_by,
            "naming_asset": item.naming_asset,
            "notes": item.notes,
            "created_at": item.created_at.isoformat() if item.created_at else None,
            "updated_at": item.updated_at.isoformat() if item.updated_at else None,
            "histories": [
                {
                    "field": h.field_name,
                    "old": h.old_value,
                    "new": h.new_value,
                    "at": h.changed_at.isoformat() if h.changed_at else None,
                    "by": h.changed_by_name,
                }
                for h in histories
            ],
        })
    return result


# ─── Re-QC ───────────────────────────────────────────────────────────────────
class ReQCPayload(BaseModel):
    notes: Optional[str] = None


@router.post("/{content_id}/reqc")
def reqc(
    content_id: int,
    payload: ReQCPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in ("admin", "material_handling", "editor"):
        raise HTTPException(403, "Akses ditolak")

    item = db.query(QCContent).filter(QCContent.id == content_id).first()
    if not item:
        raise HTTPException(404, "Konten tidak ditemukan")

    old_status = str(item.status)
    item.status = "QC Process"  # type: ignore

    if payload.notes:
        ts = datetime.now().strftime("%d/%m/%Y %H:%M")
        item.notes = (item.notes or "") + f"\n[Re-QC {ts} oleh {current_user.name}] {payload.notes}"

    db.add(QCHistory(
        qc_content_id=item.id,
        changed_by_id=current_user.id,
        changed_by_name=current_user.name,
        field_name="status",
        old_value=old_status,
        new_value="QC Process",
    ))
    db.commit()
    return {"message": "Re-QC berhasil", "id": item.id}




# ─── Move single item to logbook ─────────────────────────────────────────────
@router.post("/{content_id}/move")
def move_to_logbook(
    content_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in ("admin", "material_handling"):
        raise HTTPException(403, "Akses ditolak")
    item = db.query(QCContent).filter(QCContent.id == content_id).first()
    if not item:
        raise HTTPException(404, "Konten tidak ditemukan")
    if str(item.status) != "Done Ingest":
        raise HTTPException(400, "Hanya item Done Ingest yang bisa dipindah ke Log QC")
    item.in_logbook = True
    db.add(QCHistory(
        qc_content_id=item.id,
        changed_by_id=current_user.id,
        changed_by_name=current_user.name,
        field_name="in_logbook",
        old_value="False",
        new_value="True",
    ))
    db.commit()
    return {"message": "Berhasil dipindah ke Log QC", "id": item.id}


# ─── Bulk sync all Done Ingest → logbook ─────────────────────────────────────
@router.post("/sync-to-logbook")
def sync_all_to_logbook(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in ("admin", "material_handling"):
        raise HTTPException(403, "Akses ditolak")
    items = db.query(QCContent).filter(
        QCContent.status == "Done Ingest",
        QCContent.in_logbook == False,
    ).all()
    for item in items:
        item.in_logbook = True
        db.add(QCHistory(
            qc_content_id=item.id,
            changed_by_id=current_user.id,
            changed_by_name=current_user.name,
            field_name="in_logbook",
            old_value="False",
            new_value="True",
        ))
    db.commit()
    return {"message": f"{len(items)} konten dipindah ke Log QC", "count": len(items)}

# ─── Tab 3: Sync Library to Google Sheet ─────────────────────────────────────
@router.post("/sync-library")
def sync_library(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role not in ("admin",):
        raise HTTPException(403, "Hanya admin yang bisa sync library")

    from ..services.sheets_service import sync_library_to_sheet
    try:
        count = sync_library_to_sheet(db)
        return {"message": f"Berhasil sync {count} baris ke Google Sheet", "rows": count}
    except Exception as e:
        raise HTTPException(500, f"Gagal sync: {str(e)}")
