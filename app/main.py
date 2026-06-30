from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .database import Base, engine
from .routers import auth, users, qc_content, dashboard, cms, admin, push
from .models.push_subscription import PushSubscription  # noqa: F401 — ensures table is created
from .config import settings

# Create all tables
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title=settings.APP_NAME,
    description="REST API for OTT Quality Control Management System",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS — explicit origins required when allow_credentials=True
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://qc-frontend-xi.vercel.app",
        "https://qc-frontend-e6ikyliav-content-operation.vercel.app",
        "http://localhost:3000",
        "http://localhost:3001",
    ],
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


@app.get("/", tags=["Health"])
def health_check():
    return {"status": "ok", "app": settings.APP_NAME}
