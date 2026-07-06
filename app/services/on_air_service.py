"""
On Air sync service — reads schedule from two Google Spreadsheets (V+ and Vshort)
and stores rows into the on_air_entries table.
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from ..models.on_air import OnAirEntry
from ..config import settings

logger = logging.getLogger(__name__)

# ─── Sheet config ───────────────────────────────────────────────────────────────
VSHORT_SPREADSHEET_ID = "12c0SyPoUyHwO6A0gEA0oefvTZeDPS_nEGtftu5xbal8"
VSHORT_TAB = "Release Schedule"
VSHORT_COLUMNS = [
    "Release Date", "Time", "Naik di Coming Soon", "Turun dari Recently Added",
    "Title EN", "Exclusivity", "License", "Country of Origin", "Production House",
]

VPLUS_SPREADSHEET_ID = "18PTYONpD0HSrOFUlT5NyWQImpgiptdtFCYQBRLmH8jQ"
VPLUS_TAB = "VOD"
VPLUS_COLUMNS = [
    "Release Schedule", "Title", "Type", "Season", "Eps",
    "PH / Licensor", "License Start", "License End", "Cluster",
]


def _get_service():
    """Build Google Sheets API service using OAuth2 refresh token."""
    if not all([settings.GOOGLE_CLIENT_ID, settings.GOOGLE_CLIENT_SECRET, settings.GOOGLE_REFRESH_TOKEN]):
        logger.warning("Google credentials not configured — skipping On Air sync")
        return None
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build

        creds = Credentials(
            token=None,
            refresh_token=settings.GOOGLE_REFRESH_TOKEN,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=settings.GOOGLE_CLIENT_ID,
            client_secret=settings.GOOGLE_CLIENT_SECRET,
            scopes=["https://www.googleapis.com/auth/spreadsheets"],
        )
        creds.refresh(Request())
        return build("sheets", "v4", credentials=creds, cache_discovery=False)
    except Exception as exc:
        logger.error("Sheets service init failed: %s", exc)
        return None


def _read_sheet(service, spreadsheet_id: str, tab: str, columns: list[str]) -> list[dict]:
    """
    Read all rows from a sheet tab and return list of dicts keyed by column name.
    Skips header row. Empty rows are skipped.
    """
    try:
        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=f"'{tab}'",
            valueRenderOption="FORMATTED_VALUE",
        ).execute()
    except Exception as exc:
        logger.error("Failed to read sheet %s / %s: %s", spreadsheet_id, tab, exc)
        return []

    raw_rows = result.get("values", [])
    if not raw_rows:
        return []

    # Find header row — look for first row that contains at least one known column
    header_idx = None
    header_map = {}
    for i, row in enumerate(raw_rows):
        matched = {col: j for j, cell in enumerate(row) for col in columns if cell.strip() == col}
        if matched:
            header_idx = i
            header_map = matched
            break

    if header_idx is None:
        # fallback: assume row 0 is header, map by position
        header_row = raw_rows[0] if raw_rows else []
        header_map = {col: j for j, cell in enumerate(header_row) for col in columns if cell.strip() == col}
        header_idx = 0

    data_rows = raw_rows[header_idx + 1:]
    entries = []
    for row in data_rows:
        row_dict = {}
        for col, idx in header_map.items():
            row_dict[col] = row[idx].strip() if idx < len(row) else ""
        # Skip completely empty rows
        if all(v == "" for v in row_dict.values()):
            continue
        entries.append(row_dict)

    return entries


def sync_platform(db: Session, platform: str) -> dict:
    """
    Sync one platform's schedule from Google Sheets into DB.
    Returns {"platform": ..., "synced": N, "error": None | str}
    """
    service = _get_service()
    if service is None:
        return {"platform": platform, "synced": 0, "error": "Google Sheets not configured"}

    if platform == "vshort":
        rows = _read_sheet(service, VSHORT_SPREADSHEET_ID, VSHORT_TAB, VSHORT_COLUMNS)
    elif platform == "vplus":
        rows = _read_sheet(service, VPLUS_SPREADSHEET_ID, VPLUS_TAB, VPLUS_COLUMNS)
    else:
        return {"platform": platform, "synced": 0, "error": f"Unknown platform: {platform}"}

    try:
        # Delete existing entries for this platform
        db.query(OnAirEntry).filter(OnAirEntry.platform == platform).delete()
        db.flush()

        # Insert fresh rows
        now = datetime.now(timezone.utc)
        for idx, row_data in enumerate(rows):
            entry = OnAirEntry(
                platform=platform,
                row_index=idx,
                row_data=row_data,
                synced_at=now,
            )
            db.add(entry)

        db.commit()
        logger.info("On Air sync [%s]: %d rows", platform, len(rows))
        return {"platform": platform, "synced": len(rows), "error": None}
    except Exception as exc:
        db.rollback()
        logger.error("On Air sync [%s] DB error: %s", platform, exc)
        return {"platform": platform, "synced": 0, "error": str(exc)}


def sync_all(db: Session) -> list[dict]:
    """Sync both V+ and Vshort."""
    return [
        sync_platform(db, "vplus"),
        sync_platform(db, "vshort"),
    ]


def get_last_synced(db: Session, platform: str) -> Optional[datetime]:
    """Return synced_at of the most recently synced entry for a platform."""
    entry = (
        db.query(OnAirEntry)
        .filter(OnAirEntry.platform == platform)
        .order_by(OnAirEntry.synced_at.desc())
        .first()
    )
    return entry.synced_at if entry else None
