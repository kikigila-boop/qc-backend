"""
Google Sheets sync service.
Runs as a background task after every write operation.
Falls back gracefully if credentials are not configured.
"""
import json
import logging
from typing import Optional, Tuple
from ..config import settings

logger = logging.getLogger(__name__)

SHEET_TAB = "QC_Data"
HEADERS = [
    "QCID", "Title", "Season", "Episode", "Duration", "Cast",
    "Storage Location", "QC Result", "Status", "Editor",
    "QC Date", "Created At", "Updated At", "Notes",
    "Ingest By", "Ingest At",
]


def _get_service():
    """Build and return the Sheets API service, or None if not configured."""
    if not settings.GOOGLE_SHEETS_CREDENTIALS_JSON:
        return None
    try:
        from google.oauth2.service_account import Credentials
        from googleapiclient.discovery import build

        creds_dict = json.loads(settings.GOOGLE_SHEETS_CREDENTIALS_JSON)
        creds = Credentials.from_service_account_info(
            creds_dict,
            scopes=["https://www.googleapis.com/auth/spreadsheets"],
        )
        return build("sheets", "v4", credentials=creds, cache_discovery=False)
    except Exception as exc:
        logger.warning("Google Sheets client init failed: %s", exc)
        return None


def init_sheet() -> Tuple[Optional[str], Optional[str]]:
    """
    Create a new Google Spreadsheet with a QC_Data tab + header row.
    Returns (spreadsheet_id, spreadsheet_url) or (None, None) on failure.
    """
    service = _get_service()
    if service is None:
        return None, None

    try:
        spreadsheet = service.spreadsheets().create(body={
            "properties": {"title": "OTT QC Management — Data"},
            "sheets": [{"properties": {"title": SHEET_TAB}}],
        }).execute()

        spreadsheet_id = spreadsheet["spreadsheetId"]
        spreadsheet_url = spreadsheet["spreadsheetUrl"]

        # Write header row
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"{SHEET_TAB}!A1",
            valueInputOption="RAW",
            body={"values": [HEADERS]},
        ).execute()

        # Bold + freeze header row
        sheet_id = spreadsheet["sheets"][0]["properties"]["sheetId"]
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [
                {
                    "repeatCell": {
                        "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1},
                        "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                        "fields": "userEnteredFormat.textFormat.bold",
                    }
                },
                {
                    "updateSheetProperties": {
                        "properties": {"sheetId": sheet_id, "gridProperties": {"frozenRowCount": 1}},
                        "fields": "gridProperties.frozenRowCount",
                    }
                },
            ]},
        ).execute()

        logger.info("Google Sheet created: %s", spreadsheet_url)
        return spreadsheet_id, spreadsheet_url

    except Exception as exc:
        logger.error("init_sheet error: %s", exc)
        return None, None


def _ensure_tab(service, spreadsheet_id: str):
    """Create QC_Data tab if it doesn't exist yet."""
    try:
        meta = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        tabs = [s["properties"]["title"] for s in meta.get("sheets", [])]
        if SHEET_TAB not in tabs:
            service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={"requests": [{"addSheet": {"properties": {"title": SHEET_TAB}}}]},
            ).execute()
            service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range=f"{SHEET_TAB}!A1",
                valueInputOption="RAW",
                body={"values": [HEADERS]},
            ).execute()
    except Exception as exc:
        logger.warning("_ensure_tab error: %s", exc)


def sync_row(row_data: dict) -> None:
    """
    Upsert a single QC record to Google Sheets.
    Matches on QCID (column A). Appends if not found.
    """
    if not settings.GOOGLE_SPREADSHEET_ID:
        return

    service = _get_service()
    if service is None:
        return

    _ensure_tab(service, settings.GOOGLE_SPREADSHEET_ID)

    try:
        sheet = service.spreadsheets()
        result = sheet.values().get(
            spreadsheetId=settings.GOOGLE_SPREADSHEET_ID,
            range=f"{SHEET_TAB}!A:A",
        ).execute()
        existing = result.get("values", [])

        qcid = row_data.get("qcid") or ""
        row_num = None
        for i, cell in enumerate(existing):
            if cell and cell[0] == qcid:
                row_num = i + 1
                break

        new_row = [
            qcid,
            row_data.get("title", ""),
            str(row_data.get("season", "")),
            str(row_data.get("episode", "")),
            row_data.get("duration") or "",
            row_data.get("cast") or "",
            row_data.get("storage_location") or "",
            row_data.get("qc_result", ""),
            str(row_data.get("status", "")),
            row_data.get("editor_name", ""),
            str(row_data.get("qc_date", "")),
            str(row_data.get("created_at", "")),
            str(row_data.get("updated_at", "")),
            row_data.get("notes") or "",
            row_data.get("ingest_by") or "",
            str(row_data.get("ingest_at", "")) if row_data.get("ingest_at") else "",
        ]

        if row_num:
            sheet.values().update(
                spreadsheetId=settings.GOOGLE_SPREADSHEET_ID,
                range=f"{SHEET_TAB}!A{row_num}",
                valueInputOption="USER_ENTERED",
                body={"values": [new_row]},
            ).execute()
        else:
            sheet.values().append(
                spreadsheetId=settings.GOOGLE_SPREADSHEET_ID,
                range=f"{SHEET_TAB}!A1",
                valueInputOption="USER_ENTERED",
                body={"values": [new_row]},
            ).execute()

        logger.info("Synced QCID=%s to Google Sheets (row=%s)", qcid, row_num or "new")

    except Exception as exc:
        logger.error("Google Sheets sync_row error: %s", exc)
