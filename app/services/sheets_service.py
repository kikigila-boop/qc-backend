"""
Google Sheets sync service — OAuth2 refresh token auth.
Runs as a background task after every write operation.
Falls back gracefully if credentials are not configured.
"""
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
    """Build Sheets API service using OAuth2 refresh token, or None if not configured."""
    if not all([settings.GOOGLE_CLIENT_ID, settings.GOOGLE_CLIENT_SECRET, settings.GOOGLE_REFRESH_TOKEN]):
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
        logger.warning("Google Sheets client init failed: %s", exc)
        return None


def _enum_val(v) -> str:
    """Return the string value of an enum, or str(v) for plain values."""
    if v is None:
        return ""
    if hasattr(v, "value"):
        return str(v.value)
    return str(v)


def init_sheet() -> Tuple[Optional[str], Optional[str]]:
    """
    Create a new Google Spreadsheet with QC_Data tab + header row.
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

        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"{SHEET_TAB}!A1",
            valueInputOption="RAW",
            body={"values": [HEADERS]},
        ).execute()

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
    """Create QC_Data tab + headers if it doesn't exist yet."""
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

    Column A key strategy:
    - If QCID assigned → use real QCID; also look for old PENDING-{id} row to replace.
    - If QCID not yet assigned → use "PENDING-{id}" as temporary key.
    """
    if not settings.GOOGLE_SPREADSHEET_ID:
        return

    service = _get_service()
    if service is None:
        return

    _ensure_tab(service, settings.GOOGLE_SPREADSHEET_ID)

    try:
        sheet = service.spreadsheets()

        qcid = row_data.get("qcid") or None
        db_id = row_data.get("id") or ""
        pending_key = f"PENDING-{db_id}"
        key_in_sheet = qcid if qcid else pending_key

        # Build display row
        status_str = _enum_val(row_data.get("status", ""))
        qc_result_str = _enum_val(row_data.get("qc_result", ""))

        new_row = [
            key_in_sheet,
            row_data.get("title", ""),
            str(row_data.get("season", "")),
            str(row_data.get("episode", "")),
            row_data.get("duration") or "",
            row_data.get("cast") or "",
            row_data.get("storage_location") or "",
            qc_result_str,
            status_str,
            row_data.get("editor_name", ""),
            str(row_data.get("qc_date", "")) if row_data.get("qc_date") else "",
            str(row_data.get("created_at", "")) if row_data.get("created_at") else "",
            str(row_data.get("updated_at", "")) if row_data.get("updated_at") else "",
            row_data.get("notes") or "",
            row_data.get("ingest_by") or "",
            str(row_data.get("ingest_at", "")) if row_data.get("ingest_at") else "",
        ]

        # Fetch existing col A to find row
        result = sheet.values().get(
            spreadsheetId=settings.GOOGLE_SPREADSHEET_ID,
            range=f"{SHEET_TAB}!A:A",
        ).execute()
        existing = result.get("values", [])

        row_num = None
        for i, cell in enumerate(existing):
            if cell and cell[0] in (key_in_sheet, pending_key):
                row_num = i + 1
                break

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

        logger.info("Synced key=%s to Google Sheets (row=%s)", key_in_sheet, row_num or "new")

    except Exception as exc:
        logger.error("Google Sheets sync_row error: %s", exc)


# ─── Library Sync ─────────────────────────────────────────────────────────────
def _parse_duration_minutes(s: str) -> float:
    try:
        parts = str(s or "").strip().split(":")
        if len(parts) == 3:
            return int(parts[0]) * 60 + int(parts[1]) + int(parts[2]) / 60
        elif len(parts) == 2:
            return int(parts[0]) + int(parts[1]) / 60
    except Exception:
        pass
    return 0


def _fmt_minutes(total: float) -> str:
    h = int(total // 60)
    m = int(total % 60)
    return f"{h} jam {m} menit"


def _ensure_library_tab(service, spreadsheet_id: str, tab_name: str) -> int:
    """Create or clear the monthly library tab. Returns sheetId."""
    meta = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    existing = {s["properties"]["title"]: s["properties"]["sheetId"] for s in meta.get("sheets", [])}
    if tab_name in existing:
        # Clear existing content
        service.spreadsheets().values().clear(
            spreadsheetId=spreadsheet_id,
            range=f"'{tab_name}'",
            body={},
        ).execute()
        return existing[tab_name]
    else:
        res = service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [{"addSheet": {"properties": {"title": tab_name}}}]},
        ).execute()
        return res["replies"][0]["addSheet"]["properties"]["sheetId"]


def sync_library_to_sheet(db) -> int:
    """
    Pull all QC + Delivery + Request data, write to monthly Library tab.
    Returns number of data rows written.
    """
    if not settings.GOOGLE_SPREADSHEET_ID:
        raise RuntimeError("GOOGLE_SPREADSHEET_ID not configured")

    service = _get_service()
    if service is None:
        raise RuntimeError("Google Sheets credentials not configured")

    from ..models.qc_content import QCContent, QCHistory
    from ..models.delivery import Delivery
    from ..models.content_request import ContentRequest
    import json
    from datetime import datetime

    tab_name = "Library_" + datetime.now().strftime("%b_%Y")
    _ensure_library_tab(service, settings.GOOGLE_SPREADSHEET_ID, tab_name)

    HEADERS = [
        "Tanggal Input", "Tipe Data", "QCID", "Judul", "Tipe Konten",
        "Season", "Episode", "Durasi", "Durasi (Menit)",
        "Status", "QC Result", "Editor / PIC", "MH", "CMS Operator",
        "Naming Asset", "Sumber / Pengirim", "Metode",
        "Tanggal Update", "Keterangan",
    ]

    rows = [HEADERS]
    total_minutes = 0.0

    def _parse_titles(raw):
        try:
            t = json.loads(raw)
            if isinstance(t, list):
                return ", ".join(str(x) for x in t)
        except Exception:
            pass
        return raw or "-"

    def _fmt_dt(dt):
        if not dt:
            return ""
        if hasattr(dt, "strftime"):
            return dt.strftime("%d/%m/%Y %H:%M")
        return str(dt)

    # — QC Content rows —
    items = db.query(QCContent).order_by(QCContent.created_at.asc()).all()
    for item in items:
        dur_min = _parse_duration_minutes(item.duration or "")
        total_minutes += dur_min
        qc_result = item.qc_result.value if hasattr(item.qc_result, "value") else str(item.qc_result or "")
        rows.append([
            _fmt_dt(item.created_at), "QC",
            item.qcid or "", item.title or "",
            item.content_type or "", item.season or "", item.episode or "",
            item.duration or "", round(dur_min, 2),
            str(item.status or ""), qc_result,
            item.editor_name or "", item.mh_name or "", item.ingest_by or "",
            item.naming_asset or "", "", "",
            _fmt_dt(item.updated_at), item.notes or "",
        ])

    # — Delivery rows —
    deliveries = db.query(Delivery).order_by(Delivery.created_at.asc()).all()
    for d in deliveries:
        rows.append([
            _fmt_dt(d.created_at), "Kiriman",
            "", _parse_titles(d.content_titles),
            "", "", "", "", "",
            d.status or "", "", "", "", "",
            "", d.sender_name or "", d.delivery_method or "",
            _fmt_dt(d.confirmed_at), d.notes or "",
        ])

    # — Request rows —
    requests = db.query(ContentRequest).order_by(ContentRequest.created_at.asc()).all()
    for r in requests:
        rows.append([
            _fmt_dt(r.created_at), "Request",
            "", _parse_titles(r.content_titles),
            "", "", "", "", "",
            r.status or "", "", "", "", "",
            "", r.requestor_name or "", r.source_requestor or "",
            _fmt_dt(r.received_at or r.sent_at), r.requestor_need or "",
        ])

    # — Summary row —
    rows.append([])
    rows.append(["TOTAL DURASI QC", "", "", "", "", "", "", "", _fmt_minutes(total_minutes)] + [""] * 10)

    data_rows = len(rows) - 3  # minus header, blank, summary

    # Write all at once
    service.spreadsheets().values().update(
        spreadsheetId=settings.GOOGLE_SPREADSHEET_ID,
        range=f"'{tab_name}'!A1",
        valueInputOption="USER_ENTERED",
        body={"values": rows},
    ).execute()

    # Bold header row
    sheet_id = _ensure_library_tab(service, settings.GOOGLE_SPREADSHEET_ID, tab_name)
    service.spreadsheets().batchUpdate(
        spreadsheetId=settings.GOOGLE_SPREADSHEET_ID,
        body={"requests": [
            {"repeatCell": {
                "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1},
                "cell": {"userEnteredFormat": {"textFormat": {"bold": True}, "backgroundColor": {"red": 0.2, "green": 0.2, "blue": 0.6}}},
                "fields": "userEnteredFormat.textFormat.bold,userEnteredFormat.backgroundColor",
            }},
            {"updateSheetProperties": {
                "properties": {"sheetId": sheet_id, "gridProperties": {"frozenRowCount": 1}},
                "fields": "gridProperties.frozenRowCount",
            }},
        ]},
    ).execute()

    logger.info("Library synced: %d rows to tab %s", data_rows, tab_name)
    return data_rows
