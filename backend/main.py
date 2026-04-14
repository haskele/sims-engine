"""FastAPI application entry point for the Baseball DFS Simulator."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from database import create_tables

# ── Logging ─────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO if settings.debug else logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ── Lifespan ────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    # Create data directory
    data_dir = Path(__file__).resolve().parent.parent / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Data directory: %s", data_dir)

    # Create database tables
    await create_tables()
    logger.info("Database tables created")

    yield

    logger.info("Shutting down")


# ── App ─────────────────────────────────────────────────────────────────────

app = FastAPI(
    title=settings.app_name,
    description=(
        "Backend for baseball DFS simulation: projections, lineup optimization, "
        "and Monte Carlo contest simulation."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

# CORS (allow all for local dev)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ─────────────────────────────────────────────────────────────────

from api.contests import router as contests_router
from api.players import router as players_router
from api.projections import router as projections_router
from api.lineups import router as lineups_router
from api.simulator import router as simulator_router
from api.games import router as games_router
from api.data_pipeline import router as pipeline_router

app.include_router(contests_router)
app.include_router(players_router)
app.include_router(projections_router)
app.include_router(lineups_router)
app.include_router(simulator_router)
app.include_router(games_router)
app.include_router(pipeline_router)


# ── Health check ────────────────────────────────────────────────────────────


@app.get("/health", tags=["system"])
async def health_check():
    return {"status": "ok", "app": settings.app_name, "version": "0.1.0"}


@app.get("/", tags=["system"])
async def root():
    return {
        "app": settings.app_name,
        "docs": "/docs",
        "health": "/health",
    }
