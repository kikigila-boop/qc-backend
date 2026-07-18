from sqlalchemy import Column, Integer, String, Text, DateTime
from sqlalchemy.sql import func
from ..database import Base


class LibraryEntry(Base):
    __tablename__ = "library_entries"

        id                 = Column(Integer, primary_key=True, index=True)
            library_id         = Column(String(60), unique=True, index=True, nullable=False)
                platform           = Column(String(20))
                    creation_date      = Column(String(20))
                        provider           = Column(String(100))
                            type               = Column(String(20))
                                show_type          = Column(String(50))
                                    content_type       = Column(String(50))
                                        qc_status          = Column(String(20))
                                            title_en           = Column(String(300))
                                                title_id           = Column(String(300))
                                                    summary_long_en    = Column(Text)
                                                        summary_long_id    = Column(Text)
                                                            summary_short_en   = Column(Text)
                                                                summary_short_id   = Column(Text)
                                                                    rating             = Column(String(20))
                                                                        run_time           = Column(String(20))
                                                                            display_run_time   = Column(String(20))
                                                                                country_of_origin  = Column(String(10))
                                                                                    genre              = Column(String(100))
                                                                                        actors             = Column(Text)
                                                                                            directors          = Column(String(300))
                                                                                                producers          = Column(String(300))
                                                                                                    studio_name        = Column(String(200))
                                                                                                        languages          = Column(String(200))
                                                                                                            subtitle_languages = Column(String(200))
                                                                                                                season_number      = Column(Integer)
                                                                                                                    year               = Column(Integer)
                                                                                                                        ingestion_date     = Column(String(20))
                                                                                                                            qc_date            = Column(String(20))
                                                                                                                                material_date      = Column(String(20))
                                                                                                                                    airing_date        = Column(String(20))
                                                                                                                                        created_at         = Column(DateTime(timezone=True), server_default=func.now())
                                                                                                                                            updated_at         = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

                                                                                                                                                @property
                                                                                                                                                    def is_complete(self):
                                                                                                                                                            required = [self.title_en, self.title_id, self.show_type, self.type,
                                                                                                                                                                                self.summary_short_en, self.summary_short_id, self.genre]
                                                                                                                                                                                        return all(bool(f) for f in required)


                                                                                                                                                                                        class LibraryIdCounter(Base):
                                                                                                                                                                                            __tablename__ = "library_id_counters"

                                                                                                                                                                                                id       = Column(Integer, primary_key=True)
                                                                                                                                                                                                    platform = Column(String(20), unique=True, nullable=False)
                                                                                                                                                                                                        counter  = Column(Integer, default=0, nullable=False)