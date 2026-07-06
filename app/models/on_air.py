from sqlalchemy import Column, Integer, String, DateTime, JSON
from sqlalchemy.sql import func
from ..database import Base


class OnAirEntry(Base):
    __tablename__ = "on_air_entries"

    id = Column(Integer, primary_key=True, index=True)
    platform = Column(String(20), nullable=False, index=True)   # "vplus" | "vshort"
    row_index = Column(Integer, nullable=False)                  # row number in sheet (0-based)
    row_data = Column(JSON, nullable=False)                      # all column values as dict
    synced_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
