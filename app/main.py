from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from .database import Base, engine
from .routers import auth, users, qc_content, dashboard, cms, admin, push, notifications, export, material, delivery, request, logbook, subs, on_air
from .models.push_subscription import PushSubscription  # noqa: F401
from .models.notification import UserNotification  # noqa: F401
from .models.delivery import Delivery  # noqa: F401
from .models.content_request import ContentRequest  # noqa: F401
from .models.on_air import OnAirEntry  # noqa: F401
from .config import settings


def run_enum_types():
    do_stmts = [
        "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'deliverymethod') THEN CREATE TYPE deliverymethod AS ENUM ('HDD', 'GDrive', 'Aspera', 'Filezilla'); END IF; END $$",
        "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'deliverystatus') THEN CREATE TYPE deliverystatus AS ENUM ('Pending', 'Copying', 'Ready to QC', 'Confirmed'); END IF; END $$",
        "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'requeststatus') THEN CREATE TYPE requeststatus AS ENUM ('Pending', 'Approved', 'Rejected'); END IF; END $$",
    ]
    for stmt in do_stmts:
        try:
            with engine.connect() as conn:
                conn.execute(text(stmt))
                conn.commit()
        except Exception as e:
            print(f"[enum migration] skipped: {e}")

    alter_stmts = [
        "ALTER TYPE deliverystatus ADD VALUE IF NOT EXISTS 'Copying'",
        "ALTER TYPE deliverystatus ADD VALUE IF NOT EXISTS 'Ready to QC'",
    ]
    for stmt in alter_stmts:
        try:
            with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
                conn.execute(text(stmt))
        except Exception as e:
            print(f"[enum alter] skipped: {e}")


def run_migrations():
    migrations = [
        "ALTER TABLE qc_content ADD COLUMN IF NOT EXISTS qcid VARCHAR(20) UNIQUE",
        "ALTER TABLE qc_content ADD COLUMN IF NOT EXISTS editor_name VARCHAR(100)",
        "ALTER TABLE qc_content ADD COLUMN IF NOT EXISTS editor_id INTEGER REFERENCES users(id)",
        "ALTER TABLE qc_content ADD COLUMN IF NOT EXISTS ingest_by VARCHAR(100)",
        "ALTER TABLE qc_content ADD COLUMN IF NOT EXISTS ingest_at TIMESTAMP WITH TIME ZONE",
        "ALTER TABLE qc_content ADD COLUMN IF NOT EXISTS revised_notes TEXT",
        "ALTER TABLE qc_history ADD COLUMN IF NOT EXISTS changed_by_name VARCHAR(100)",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE",
        "ALTER TABLE user_notifications ADD COLUMN IF NOT EXISTS url VARCHAR(500)",
        "ALTER TYPE statusenum ADD VALUE IF NOT EXISTS 'INGESTING'",
        "ALTER TYPE statusenum ADD VALUE IF NOT EXISTS 'NEED_REVISED'",
        "ALTER TYPE statusenum ADD VALUE IF NOT EXISTS 'MATERIAL_AVAIL'",
        "ALTER TYPE statusenum ADD VALUE IF NOT EXISTS 'MATERIAL_REVISED'",
        "ALTER TABLE qc_content ADD COLUMN IF NOT EXISTS mh_name VARCHAR(100)",
        "ALTER TABLE qc_content ADD COLUMN IF NOT EXISTS naming_asset TEXT",
        "ALTER TABLE qc_content ADD COLUMN IF NOT EXISTS content_type VARCHAR(50)",
        "ALTER TABLE qc_content ADD COLUMN IF NOT EXISTS in_logbook BOOLEAN DEFAULT FALSE",
        "ALTER TABLE qc_content ADD COLUMN IF NOT EXISTS platform VARCHAR(100)",
        "ALTER TABLE qc_content ADD COLUMN IF NOT EXISTS with_subs BOOLEAN DEFAULT FALSE",
        """CREATE TABLE IF NOT EXISTS subtitle_tasks (
            id SERIAL PRIMARY KEY,
            qc_content_id INTEGER NOT NULL REFERENCES qc_content(id) ON DELETE CASCADE,
            language_code VARCHAR(5) NOT NULL,
            language_name VARCHAR(50) NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            pic VARCHAR(100),
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            updated_by_id INTEGER REFERENCES users(id)
        )""",
        "CREATE INDEX IF NOT EXISTS ix_subtitle_tasks_qc_content_id ON subtitle_tasks(qc_content_id)",
        "ALTER TABLE qc_content ALTER COLUMN editor_name DROP NOT NULL",
        "ALTER TABLE deliveries ALTER COLUMN status TYPE VARCHAR(50) USING status::text",
        "ALTER TABLE deliveries ALTER COLUMN delivery_method TYPE VARCHAR(50) USING delivery_method::text",
        "ALTER TABLE content_requests ALTER COLUMN status TYPE VARCHAR(50) USING status::text",
        "UPDATE deliveries SET status = 'Pending' WHERE LOWER(status) = 'pending'",
        "UPDATE deliveries SET status = 'Copying' WHERE LOWER(status) = 'copying'",
        "UPDATE deliveries SET status = 'Ready to QC' WHERE LOWER(status) IN ('ready to qc', 'ready_to_qc', 'readytoqc')",
        "UPDATE deliveries SET status = 'Confirmed' WHERE LOWER(status) = 'confirmed'",
        "UPDATE content_requests SET status = 'Pending' WHERE LOWER(status) = 'pending'",
        "UPDATE content_requests SET status = 'Approved' WHERE LOWER(status) = 'approved'",
        "UPDATE content_requests SET status = 'Rejected' WHERE LOWER(status) = 'rejected'",
        "ALTER TABLE content_requests ADD COLUMN IF NOT EXISTS sent_by VARCHAR(100)",
        "ALTER TABLE content_requests ADD COLUMN IF NOT EXISTS sent_at TIMESTAMP WITH TIME ZONE",
        "ALTER TABLE content_requests ADD COLUMN IF NOT EXISTS received_at TIMESTAMP WITH TIME ZONE",
        "ALTER TABLE qc_content ADD COLUMN IF NOT EXISTS with_dubb BOOLEAN DEFAULT FALSE",
        "ALTER TABLE subtitle_tasks ADD COLUMN IF NOT EXISTS task_type VARCHAR(10) NOT NULL DEFAULT 'subs'",
        # on_air_entries airing columns
        "ALTER TABLE on_air_entries ADD COLUMN IF NOT EXISTS is_aired BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE on_air_entries ADD COLUMN IF NOT EXISTS aired_at TIMESTAMP WITH TIME ZONE",
        "ALTER TABLE on_air_entries ADD COLUMN IF NOT EXISTS aired_by VARCHAR(100)",
    ]
    for stmt in migrations:
        try:
            with engine.connect() as conn:
                conn.execute(text(stmt))
                conn.commit()
        except Exception as e:
            print(f"[migration] skipped: {stmt[:60]}… → {e}")


# ─── Startup: enums → tables → patches ──────────────────────────────────────────
try:
    run_enum_types()
    Base.metadata.create_all(bind=engine)
    run_migrations()
except Exception as _startup_err:
    import traceback
    print(f"[startup] WARNING: DB init error: {_startup_err}")
    traceback.print_exc()

# ─── Scheduled sync ─────────────────────────────────────────────────────────────
try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    from .database import SessionLocal
    from .services.on_air_service import sync_all

    def _scheduled_on_air_sync():
        db = SessionLocal()
        try:
            results = sync_all(db)
            print(f"[scheduler] On Air sync done: {results}")
        except Exception as exc:
            print(f"[scheduler] On Air sync error: {exc}")
        finally:
            db.close()

    _scheduler = BackgroundScheduler(timezone="Asia/Jakarta")
    # Every day at 07:00 WIB
    _scheduler.add_job(_scheduled_on_air_sync, CronTrigger(hour=7, minute=0))
    _scheduler.start()
    print("[scheduler] On Air daily sync scheduled at 07:00 WIB")
except Exception as _sched_err:
    print(f"[scheduler] Could not start scheduler: {_sched_err}")

# ─── App ─────────────────────────────────────────────────────────────────────────
app = FastAPI(
    title=settings.APP_NAME,
    description="REST API for OTT Quality Control Management System",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    redirect_slashes=False,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://qc-frontend-xi.vercel.app",
        "http://localhost:3000",
        "http://localhost:3001",
    ],
    allow_origin_regex=r"https://qc-frontend-.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API_PREFIX = "/api/v1"
app.include_router(auth.router, prefix=API_PREFIX)
app.include_router(users.router, prefix=API_PREFIX)
app.include_router(qc_content.router, prefix=API_PREFIX)
app.include_router(dashboard.router, prefix=API_PREFIX)
app.include_router(cms.router, prefix=API_PREFIX)
app.include_router(admin.router, prefix=API_PREFIX)
app.include_router(push.router, prefix=API_PREFIX)
app.include_router(notifications.router, prefix=API_PREFIX)
app.include_router(material.router, prefix=API_PREFIX)
app.include_router(export.router, prefix=API_PREFIX)
app.include_router(delivery.router, prefix=API_PREFIX)
app.include_router(request.router, prefix=API_PREFIX)
app.include_router(logbook.router, prefix=API_PREFIX)
app.include_router(subs.router, prefix=API_PREFIX)
app.include_router(on_air.router, prefix=API_PREFIX)


@app.get("/", tags=["Health"])
def health_check():
    return {"status": "ok", "app": settings.APP_NAME}
