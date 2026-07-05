import json
from sqlalchemy.orm import Session
from ..models.qc_content import QCContent, SubtitleTask, SubtitleStatus

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


def generate_subtitle_tasks(db: Session, content: QCContent, selected_languages: list | None = None):
    db.query(SubtitleTask).filter(SubtitleTask.qc_content_id == content.id).delete()
    if not content.with_subs:
        db.commit()
        return
    if selected_languages:
        langs = [(c, ALL_LANG_MAP.get(c, c)) for c in selected_languages]
    else:
        platforms = []
        try:
            platforms = json.loads(content.platform or "[]")
        except Exception:
            platforms = []
        seen: set = set()
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
        db.add(SubtitleTask(
            qc_content_id=content.id,
            language_code=code,
            language_name=name,
            status=SubtitleStatus.PENDING,
        ))
    db.commit()
