from fastapi import FastAPI
from datetime import datetime, timedelta
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from .database import Base, engine
from .routers import auth, users, qc_content, dashboard, cms, admin, push, notifications, export, material, delivery, request
from .models.push_subscription import PushSubscription  # noqa: F401 — ensures table is created
from .models.notification import UserNotification  # noqa: F401 — ensures table is created
from .models.delivery import Delivery  # noqa: F401 — ensures table is created
from .models.content_request import ContentRequest  # noqa: F401 — ensures table is created
from .config import settings


def run_enum_types():
    """Create custom PostgreSQL enum types before tables are created."""
    # DO $$ ... $$ blocks — safe in normal transaction
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

    # ALTER TYPE ADD VALUE requires AUTOCOMMIT — cannot run inside a transaction
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
    """
    Safely add any columns that may have been introduced after the initial
    Railway deployment.  Uses IF NOT EXISTS so it is idempotent.
    """
    migrations = [
        # qc_content table
        "ALTER TABLE qc_content ADD COLUMN IF NOT EXISTS qcid VARCHAR(20) UNIQUE",
        "ALTER TABLE qc_content ADD COLUMN IF NOT EXISTS editor_name VARCHAR(100)",
        "ALTER TABLE qc_content ADD COLUMN IF NOT EXISTS editor_id INTEGER REFERENCES users(id)",
        "ALTER TABLE qc_content ADD COLUMN IF NOT EXISTS ingest_by VARCHAR(100)",
        "ALTER TABLE qc_content ADD COLUMN IF NOT EXISTS ingest_at TIMESTAMP WITH TIME ZONE",
        "ALTER TABLE qc_content ADD COLUMN IF NOT EXISTS revised_notes TEXT",
        # qc_history table
        "ALTER TABLE qc_history ADD COLUMN IF NOT EXISTS changed_by_name VARCHAR(100)",
        # users table
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE",
        # user_notifications table — created via create_all but guard just in case
        "ALTER TABLE user_notifications ADD COLUMN IF NOT EXISTS url VARCHAR(500)",
        # New status enum values (PostgreSQL ALTER TYPE, idempotent via IF NOT EXISTS)
        "ALTER TYPE statusenum ADD VALUE IF NOT EXISTS 'INGESTING'",
        "ALTER TYPE statusenum ADD VALUE IF NOT EXISTS 'NEED_REVISED'",
        "ALTER TYPE statusenum ADD VALUE IF NOT EXISTS 'MATERIAL_AVAIL'",
        "ALTER TYPE statusenum ADD VALUE IF NOT EXISTS 'MATERIAL_REVISED'",
        "ALTER TABLE qc_content ADD COLUMN IF NOT EXISTS mh_name VARCHAR(100)",
        "ALTER TABLE qc_content ADD COLUMN IF NOT EXISTS naming_asset TEXT",
        "ALTER TABLE qc_content ADD COLUMN IF NOT EXISTS content_type VARCHAR(50)",
        "ALTER TABLE qc_content ADD COLUMN IF NOT EXISTS in_logbook BOOLEAN DEFAULT FALSE",
        "ALTER TABLE qc_content ALTER COLUMN editor_name DROP NOT NULL",
        # Enum types are created in run_enum_types() before create_all()
        # Convert enum columns to VARCHAR if they are still PostgreSQL enum types
        "ALTER TABLE deliveries ALTER COLUMN status TYPE VARCHAR(50) USING status::text",
        "ALTER TABLE deliveries ALTER COLUMN delivery_method TYPE VARCHAR(50) USING delivery_method::text",
        "ALTER TABLE content_requests ALTER COLUMN status TYPE VARCHAR(50) USING status::text",
        # Normalize status to canonical case (fix PENDING → Pending, etc.)
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
    ]
    # Each statement runs in its own connection/transaction.
    # This prevents a single failure from aborting subsequent migrations.
    for stmt in migrations:
        try:
            with engine.connect() as conn:
                conn.execute(text(stmt))
                conn.commit()
        except Exception as e:
            print(f"[migration] skipped: {stmt[:60]}… → {e}")


# Startup sequence: enums first → tables → column patches
try:
    run_enum_types()
    Base.metadata.create_all(bind=engine)
    run_migrations()
except Exception as _startup_err:
    import traceback
    print(f"[startup] WARNING: DB init error (app will still start): {_startup_err}")
    traceback.print_exc()

def _auto_move_done_ingest():
    """Every 24h: flag Done Ingest items older than 3 days as in_logbook=True."""
    from .database import SessionLocal
    from .models.qc_content import QCContent, QCHistory
    db = SessionLocal()
    try:
        cutoff = datetime.utcnow() - timedelta(days=3)
        items = db.query(QCContent).filter(
            QCContent.status == "Done Ingest",
            QCContent.in_logbook == False,
            QCContent.updated_at <= cutoff,
        ).all()
        for item in items:
            item.in_logbook = True
            db.add(QCHistory(
                qc_content_id=item.id,
                field_name="in_logbook",
                old_value="False",
                new_value="True (auto 3d)",
            ))
        if items:
            db.commit()
    except Exception as e:
        import logging; logging.getLogger(__name__).error("auto_move error: %s", e)
    finally:
        db.close()

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app):
    # Start background scheduler safely
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        _scheduler = BackgroundScheduler()
        _scheduler.add_job(_auto_move_done_ingest, "interval", hours=24, id="auto_logbook")
        _scheduler.start()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("APScheduler not started: %s", e)
    yield

app = FastAPI(
    lifespan=lifespan,
    title=settings.APP_NAME,
    description="REST API for OTT Quality Control Management System",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    redirect_slashes=False,
)

# CORS — explicit origins required when allow_credentials=True
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://qc-frontend-xi.vercel.app",
        "http://localhost:3000",
        "http://localhost:3001",
    ],
    # Cover all Vercel preview deploy URLs (*.vercel.app)
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


@app.get("/", tags=["Health"])
def health_check():
    return {"status": "ok", "app": settings.APP_NAME}
