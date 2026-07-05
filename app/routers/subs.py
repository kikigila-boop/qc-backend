from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List

from ..database import get_db
from ..models.qc_content import QCContent, SubtitleTask, SubtitleStatus
from ..schemas.qc_content import SubtitleTaskOut, SubtitleTaskUpdate, SubsContentOut
from .auth import get_current_user
from ..models.user import User
from ..services.subtitle_service import generate_tasks

router = APIRouter(prefix="/subs", tags=["subs"])


# ── Subs endpoints ───────────────────────────────────────────────────────────

@router.get("", response_model=List[SubsContentOut])
def list_subs_content(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    items = db.query(QCContent).filter(QCContent.with_subs == True, QCContent.in_logbook == False).order_by(QCContent.updated_at.desc()).all()
    return items


@router.get("/dubb", response_model=List[SubsContentOut])
def list_dubb_content(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    items = db.query(QCContent).filter(QCContent.with_dubb == True, QCContent.in_logbook == False).order_by(QCContent.updated_at.desc()).all()
    return items


@router.get("/{content_id}/tasks", response_model=List[SubtitleTaskOut])
def get_tasks(
    content_id: int,
    task_type: str = Query("subs", regex="^(subs|dubb)$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return db.query(SubtitleTask).filter(
        SubtitleTask.qc_content_id == content_id,
        SubtitleTask.task_type == task_type,
    ).all()


@router.patch("/{content_id}/tasks/{task_id}", response_model=SubtitleTaskOut)
def update_task(
    content_id: int,
    task_id: int,
    payload: SubtitleTaskUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    task = db.query(SubtitleTask).filter(
        SubtitleTask.id == task_id,
        SubtitleTask.qc_content_id == content_id,
    ).first()
    if not task:
        raise HTTPException(404, "Task not found")
    if payload.status is not None:
        try:
            task.status = SubtitleStatus(payload.status)
        except ValueError:
            raise HTTPException(400, f"Invalid status: {payload.status}")
    if payload.pic is not None:
        task.pic = payload.pic
    task.updated_by_id = current_user.id
    db.commit()
    db.refresh(task)
    return task


@router.post("/{content_id}/regenerate")
def regenerate_tasks(
    content_id: int,
    task_type: str = Query("subs", regex="^(subs|dubb)$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    content = db.query(QCContent).filter(QCContent.id == content_id).first()
    if not content:
        raise HTTPException(404, "Content not found")
    generate_tasks(db, content, task_type)
    return {"message": f"{task_type} tasks regenerated"}
