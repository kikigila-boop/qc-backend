from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str

    # JWT
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480

    # App
    APP_NAME: str = "OTT QC Management System"
    DEBUG: bool = False

    # Google Sheets (optional)
    GOOGLE_SHEETS_CREDENTIALS_JSON: Optional[str] = None
    GOOGLE_SPREADSHEET_ID: Optional[str] = None

    class Config:
        env_file = ".env"


settings = Settings()
