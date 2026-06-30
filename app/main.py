from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from .database import Base, engine
from .routers import auth, users, qc_content, dashboard, cms, admin, push, notifications, export
from .models.push_subscription import PushSubscription  # noqa: F401 — ensures table is created
from .models.notification import UserNotification  # noqa: F401 — ensures table is created
from .config import settings


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
    ]
    with engine.connect() as conn:
        for stmt in migrations:
            try:
                conn.execute(text(stmt))
            except Exception as e:
                # Log but don't crash — column may already exist with a conflict
                print(f"[migration] skipped: {stmt[:60]}… → {e}")
        conn.commit()


# Create all tables (new tables only), then patch missing columns
Base.metadata.create_all(bind=engine)
run_migrations()

app = FastAPI(
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
app.include_router(export.router, prefix=API_PREFIX)


@app.get("/", tags=["Health"])
def health_check():
    return {"status": "ok", "app": settings.APP_NAME}
