from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
import json

from ..database import get_db
from ..models.qc_content import QCContent, SubtitleTask, SubtitleStatus
from ..schemas.qc_content import SubtitleTaskOut, SubtitleTaskUpdate, SubsContentOut
from .auth import get_current_user
from ..models.user import User

router = APIRouter(prefix="/subs", tags=["subs"])

# Language definitions per platform
VSHORT_LANGS = [
    ("ID", "Indonesia"), ("EN", "English"), ("AR", "Arabic"),
    ("ES", "Spanish"),   ("PT", "Portugis (Brazil)"),
    ("HI", "Hindi"),     ("ZH", "Chinese"),
]
VPLUS_LANGS = [
    ("ID", "Indonesia"), ("EN", "English"), ("MY", "Malay"),
    ("JV", "Javanese"),  ("TH", "Thailand"),
    ("SU", "Sundanese"), ("ZH", "Chinese"),
]

ALL_LANG_MAP = {code: name for code, name in VSHORT_LANGS + VPLUS_LANGS}


def generate_subtitle_tasks(db: Session, content: QCContent, selected_languages: list[str] | None = None):
    """Create SubtitleTask rows for a content. selected_languages overrides platform default."""
    # Delete existing tasks first
    db.query(SubtitleTask).filter(SubtitleTask.qc_content_id == content.id).delete()

    if not content.with_subs:
        db.commit()
        return

    # Determine languages
    if selected_languages:
        langs = [(c, ALL_LANG_MAP.get(c, c)) for c in selected_languages]
    else:
        platforms = []
        try:
            platforms = json.loads(content.platform or "[]")
        except Exception:
            platforms = []

        seen = set()
        langs = []
        if "vshort" in platforms:
            for pair in VSHORT_LANGS:
                if pair[0] not in seen:
                    langs.append(pair); seen.add(pair[0])
        if "vplus" in platforms:
            for pair in VPLUS_LANGS:
                if pair[0] not in seen:
                    langs.append(pair); seen.add(pair[0])

    for code, name in langs:
        task = SubtitleTask(
            qc_content_id=content.id,
            language_code=code,
            language_name=name,
            status=SubtitleStatus.PENDING,
        )
        db.add(task)
    db.commit()


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("", response_model=List[SubsContentOut])
def list_subs_content(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all content that has with_subs=True, with subtitle task progress."""
    items = (
        db.query(QCContent)
        .filter(QCContent.with_subs == True, QCContent.in_logbook == False)
        .order_by(QCContent.updated_at.desc())
        .all()
    )
    return items


@router.get("/{content_id}/tasks", response_model=List[SubtitleTaskOut])
def get_subtitle_tasks(
    content_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tasks = db.query(SubtitleTask).filter(SubtitleTask.qc_content_id == content_id).all()
    return tasks


@router.patch("/{content_id}/tasks/{task_id}", response_model=SubtitleTaskOut)
def update_subtitle_task(
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
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Regenerate subtitle tasks (e.g. after platform or with_subs change)."""
    content = db.query(QCContent).filter(QCContent.id == content_id).first()
    if not content:
        raise HTTPException(404, "Content not found")
    generate_subtitle_tasks(db, content)
    return {"message": "Tasks regenerated"}
