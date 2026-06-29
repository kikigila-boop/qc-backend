"""
Google Sheets sync service.
Runs as a background task after every write operation.
Falls back gracefully if credentials are not configured.
"""
import json
import logging
from typing import Optional
from ..config import settings

logger = logging.getLogger(__name__)


def _get_sheets_client():
    if not settings.GOOGLE_SHEETS_CREDENTIALS_JSON or not settings.GOOGLE_SPREADSHEET_ID:
        return None, None
    try:
        from google.oauth2.service_account import Credentials
        from googleapiclient.discovery import build

        creds_dict = json.loads(settings.GOOGLE_SHEETS_CREDENTIALS_JSON)
        creds = Credentials.from_service_account_info(
            creds_dict,
            scopes=["https://www.googleapis.com/auth/spreadsheets"],
        )
        service = build("sheets", "v4", credentials=creds)
        return service, settings.GOOGLE_SPREADSHEET_ID
    except Exception as exc:
        logger.warning("Google Sheets client init failed: %s", exc)
        return None, None


def sync_row(row_data: dict) -> None:
    """
    Upsert a single QC record to Google Sheets.
    Sheet columns (row 1 as header):
    QCID | Title | Season | Episode | Duration | Cast | Storage | QC Result | Status | Editor | QC Date | Created | Updated | Notes
    """
    service, spreadsheet_id = _get_sheets_client()
    if service is None:
        return

    try:
        sheet = service.spreadsheets()
        # Read existing rows to find or append
        result = sheet.values().get(
            spreadsheetId=spreadsheet_id,
            range="QC_Data!A:A",
        ).execute()
        values = result.get("values", [])

        row_num = None
        for i, row in enumerate(values):
            if row and row[0] == row_data.get("qcid", ""):
                row_num = i + 1
                break

        new_row = [
            row_data.get("qcid", ""),
            row_data.get("title", ""),
            row_data.get("season", ""),
            row_data.get("episode", ""),
            row_data.get("duration", ""),
            row_data.get("cast", ""),
            row_data.get("storage_location", ""),
            row_data.get("qc_result", ""),
            row_data.get("status", ""),
            row_data.get("editor_name", ""),
            str(row_data.get("qc_date", "")),
            str(row_data.get("created_at", "")),
            str(row_data.get("updated_at", "")),
            row_data.get("notes", ""),
        ]

        if row_num:
            sheet.values().update(
                spreadsheetId=spreadsheet_id,
                range=f"QC_Data!A{row_num}",
                valueInputOption="USER_ENTERED",
                body={"values": [new_row]},
            ).execute()
        else:
            sheet.values().append(
                spreadsheetId=spreadsheet_id,
                range="QC_Data!A1",
                valueInputOption="USER_ENTERED",
                body={"values": [new_row]},
            ).execute()
    except Exception as exc:
        logger.error("Google Sheets sync error: %s", exc)
