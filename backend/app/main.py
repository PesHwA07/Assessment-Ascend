"""
FastAPI application entry point.

- Initializes the database on startup
- Mounts CORS middleware for the React frontend
- Registers all API routers
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import FRONTEND_ORIGINS
from app.database import init_db
from app.routers import events, reports, audit


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle hook."""
    # ── Startup ──
    init_db()
    yield
    # ── Shutdown ──  (nothing to clean up for SQLite)


app = FastAPI(
    title="Clinical Report Generator",
    description=(
        "Stateful, reconciliation-driven LLM report generator "
        "with temporal evidence and conflict resolution."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# ── CORS ─────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=FRONTEND_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ──────────────────────────────────────────────────────────────
app.include_router(events.router)
app.include_router(reports.router)
app.include_router(audit.router)


# ── Health Check ─────────────────────────────────────────────────────────
@app.get("/health", tags=["system"])
async def health_check():
    """Simple liveness probe."""
    return {"status": "ok"}
