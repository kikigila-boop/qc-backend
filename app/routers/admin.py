"""
Admin endpoints — Google Sheets management, etc.
Only accessible to users with role='admin'.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.user import User
from ..utils.security import get_current_user
from ..config import settings
from ..services.sheets_service import init_sheet

router = APIRouter(prefix="/admin", tags=["Admin"])


def _require_admin(current_user: User = Depends(get_current_user)):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


@router.get("/sheets/info")
def sheets_info(_: User = Depends(_require_admin)):
    """
    Return current Google Sheets configuration status.
    """
    has_creds = bool(settings.GOOGLE_SHEETS_CREDENTIALS_JSON)
    sheet_id = settings.GOOGLE_SPREADSHEET_ID

    return {
        "credentials_configured": has_creds,
        "spreadsheet_id": sheet_id,
        "spreadsheet_url": (
            f"https://docs.google.com/spreadsheets/d/{sheet_id}"
            if sheet_id else None
        ),
        "sync_active": has_creds and bool(sheet_id),
    }


@router.post("/sheets/init")
def sheets_init(_: User = Depends(_require_admin)):
    """
    Create a new Google Spreadsheet with QC_Data tab + headers.
    Call this once after setting GOOGLE_SHEETS_CREDENTIALS_JSON.
    Then copy the returned spreadsheet_id to GOOGLE_SPREADSHEET_ID env var in Railway.
    """
    if not settings.GOOGLE_SHEETS_CREDENTIALS_JSON:
        raise HTTPException(
            status_code=400,
            detail="GOOGLE_SHEETS_CREDENTIALS_JSON is not set. Add it to Railway environment variables first.",
        )

    sheet_id, sheet_url = init_sheet()

    if not sheet_id:
        raise HTTPException(
            status_code=500,
            detail="Failed to create Google Sheet. Check Railway logs for details.",
        )

    return {
        "spreadsheet_id": sheet_id,
        "spreadsheet_url": sheet_url,
        "next_step": f"Set GOOGLE_SPREADSHEET_ID={sheet_id} in Railway environment variables, then redeploy.",
    }
