"""Shared pytest fixtures for the Baseball DFS Simulator integration tests."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import httpx

# Ensure the backend package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def app():
    """Create the FastAPI application instance (no lifespan — avoids background tasks)."""
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware

    # Build a lightweight app that mounts the same routers as main.py
    # but without the lifespan (nightly task, DB table creation).
    test_app = FastAPI(title="Test App")
    test_app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from api.contests import router as contests_router
    from api.players import router as players_router
    from api.projections import router as projections_router
    from api.lineups import router as lineups_router
    from api.simulator import router as simulator_router
    from api.games import router as games_router
    from api.data_pipeline import router as pipeline_router
    from api.dk_entries import router as dk_entries_router
    from api.contest_history import router as contest_history_router
    from api.staging_projections import router as staging_router

    test_app.include_router(contests_router)
    test_app.include_router(players_router)
    test_app.include_router(projections_router)
    test_app.include_router(lineups_router)
    test_app.include_router(simulator_router)
    test_app.include_router(games_router)
    test_app.include_router(pipeline_router)
    test_app.include_router(dk_entries_router)
    test_app.include_router(contest_history_router)
    test_app.include_router(staging_router)

    @test_app.get("/health")
    async def health_check():
        return {"status": "ok"}

    return test_app


@pytest.fixture
async def client(app):
    """Async httpx test client bound to the FastAPI app (no network calls)."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as c:
        yield c


# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

SAMPLE_PROJECTION = {
    "player_name": "Aaron Judge",
    "mlb_id": 592450,
    "dk_id": 10000001,
    "team": "NYY",
    "position": "OF",
    "opp_team": "BOS",
    "is_home": True,
    "game_pk": 745123,
    "venue": "Yankee Stadium",
    "salary": 6200,
    "batting_order": 2,
    "is_pitcher": False,
    "is_bench": False,
    "is_confirmed": True,
    "floor_pts": 4.5,
    "median_pts": 9.8,
    "ceiling_pts": 22.0,
    "projected_ownership": 18.5,
    "season_era": None,
    "season_k9": None,
    "season_avg": 0.310,
    "season_ops": 1.012,
    "games_in_log": 15,
    "implied_total": 5.2,
    "team_implied": 5.2,
    "temperature": 72.0,
    "lineup_status": "confirmed",
    "opener_status": None,
    "is_projected_starter": None,
    "rp_role": None,
    "appearance_rate": None,
    "expected_ip": None,
    "recent_usage_penalty": None,
    "k_line": None,
    "hr_line": "+407",
    "tb_line": "-110",
    "hrr_line": "-156",
    "game_total": 9.5,
    "min_exposure": None,
    "max_exposure": None,
}

SAMPLE_PITCHER_PROJECTION = {
    "player_name": "Gerrit Cole",
    "mlb_id": 543037,
    "dk_id": 10000002,
    "team": "NYY",
    "position": "SP",
    "opp_team": "BOS",
    "is_home": True,
    "game_pk": 745123,
    "venue": "Yankee Stadium",
    "salary": 10400,
    "batting_order": None,
    "is_pitcher": True,
    "is_bench": False,
    "is_confirmed": True,
    "floor_pts": 8.0,
    "median_pts": 16.5,
    "ceiling_pts": 35.0,
    "projected_ownership": 22.0,
    "season_era": 3.15,
    "season_k9": 10.2,
    "season_avg": None,
    "season_ops": None,
    "games_in_log": 5,
    "implied_total": 5.2,
    "team_implied": 5.2,
    "temperature": 72.0,
    "lineup_status": "confirmed",
    "opener_status": None,
    "is_projected_starter": True,
    "rp_role": None,
    "appearance_rate": None,
    "expected_ip": None,
    "recent_usage_penalty": None,
    "k_line": "6.5 (-154)",
    "hr_line": None,
    "tb_line": None,
    "hrr_line": None,
    "game_total": 9.5,
    "min_exposure": None,
    "max_exposure": None,
}
