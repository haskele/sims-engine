"""Simulation endpoints."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import async_session, get_db
from models.contest import Contest
from models.lineup import Lineup
from models.player import Player
from models.projection import Projection
from models.simulation import SimulationResult
from services.simulator import SimulationConfig, run_simulation

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/simulations", tags=["simulations"])


# ── Pydantic schemas ────────────────────────────────────────────────────────


class SimulationRequest(BaseModel):
    contest_id: int
    sim_count: int = 10000
    site: str = "dk"
    # Optional: provide user lineup IDs; if empty, uses all is_user lineups for the contest
    user_lineup_ids: List[int] = []


class SimulationStatusOut(BaseModel):
    id: int
    status: str
    sim_count: int
    lineup_pool_size: int
    config: Any = None
    results: Any = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None

    model_config = {"from_attributes": True}


# ── Background task ─────────────────────────────────────────────────────────


async def _run_sim_background(sim_id: int, config: SimulationConfig) -> None:
    """Execute simulation in the background and update the DB record."""
    async with async_session() as db:
        try:
            # Mark running
            result = await db.execute(
                select(SimulationResult).where(SimulationResult.id == sim_id)
            )
            sim_rec = result.scalar_one()
            sim_rec.status = "running"
            sim_rec.started_at = datetime.now(timezone.utc)
            await db.commit()

            # Run
            sim_results = await run_simulation(config)

            # Mark complete
            result = await db.execute(
                select(SimulationResult).where(SimulationResult.id == sim_id)
            )
            sim_rec = result.scalar_one()
            sim_rec.status = "complete"
            sim_rec.results = json.dumps(sim_results)
            sim_rec.completed_at = datetime.now(timezone.utc)
            await db.commit()

        except Exception as exc:
            logger.exception("Simulation %d failed", sim_id)
            try:
                result = await db.execute(
                    select(SimulationResult).where(SimulationResult.id == sim_id)
                )
                sim_rec = result.scalar_one()
                sim_rec.status = "error"
                sim_rec.results = json.dumps({"error": str(exc)})
                sim_rec.completed_at = datetime.now(timezone.utc)
                await db.commit()
            except Exception:
                pass


# ── Endpoints ───────────────────────────────────────────────────────────────


@router.post("/", response_model=SimulationStatusOut, status_code=202)
async def start_simulation(
    body: SimulationRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Kick off a Monte Carlo contest simulation (runs async in background)."""
    # Validate contest
    result = await db.execute(select(Contest).where(Contest.id == body.contest_id))
    contest = result.scalar_one_or_none()
    if not contest:
        raise HTTPException(404, "Contest not found")

    # Fetch user lineups
    if body.user_lineup_ids:
        result = await db.execute(
            select(Lineup).where(Lineup.id.in_(body.user_lineup_ids))
        )
    else:
        result = await db.execute(
            select(Lineup).where(
                Lineup.contest_id == body.contest_id, Lineup.is_user == True
            )
        )
    user_lineups_db = result.scalars().all()
    if not user_lineups_db:
        raise HTTPException(400, "No user lineups found for this contest")

    # Parse lineup player data
    user_lineups_parsed = []
    for lu in user_lineups_db:
        try:
            players = json.loads(lu.players) if isinstance(lu.players, str) else lu.players
        except (json.JSONDecodeError, TypeError):
            players = []
        user_lineups_parsed.append(players)

    # Fetch projections for all players on the slate
    # For now, get all projections for the site
    result = await db.execute(
        select(Projection).where(Projection.site == body.site)
    )
    projections = result.scalars().all()

    # Build player pool with projections
    player_ids = list({p.player_id for p in projections})
    result = await db.execute(select(Player).where(Player.id.in_(player_ids)))
    players_db = {p.id: p for p in result.scalars().all()}

    player_pool = []
    for proj in projections:
        player = players_db.get(proj.player_id)
        if not player:
            continue
        salary = player.dk_salary if body.site == "dk" else player.fd_salary
        player_pool.append(
            {
                "id": player.id,
                "name": player.name,
                "team": player.team,
                "position": player.position,
                "salary": salary or 3000,
                "floor_pts": proj.floor_pts,
                "median_pts": proj.median_pts,
                "ceiling_pts": proj.ceiling_pts,
                "projected_ownership": proj.projected_ownership or 5.0,
            }
        )

    # Build contest config
    payout = []
    if contest.payout_structure:
        try:
            payout = json.loads(contest.payout_structure)
        except (json.JSONDecodeError, TypeError):
            payout = []

    contest_config = {
        "entry_fee": contest.entry_fee,
        "field_size": contest.field_size,
        "game_type": contest.game_type,
        "max_entries": contest.max_entries,
        "payout_structure": payout,
    }

    sim_config = SimulationConfig(
        sim_count=body.sim_count,
        contest_config=contest_config,
        game_slate=[],  # TODO: populate from contest's slate games
        player_pool=player_pool,
        user_lineups=user_lineups_parsed,
        site=body.site,
    )

    # Create DB record
    sim_record = SimulationResult(
        contest_id=body.contest_id,
        sim_count=body.sim_count,
        lineup_pool_size=len(user_lineups_parsed),
        config=json.dumps(sim_config.to_dict()),
        status="pending",
    )
    db.add(sim_record)
    await db.flush()
    await db.refresh(sim_record)

    # Launch background task
    background_tasks.add_task(_run_sim_background, sim_record.id, sim_config)

    return SimulationStatusOut(
        id=sim_record.id,
        status="pending",
        sim_count=body.sim_count,
        lineup_pool_size=len(user_lineups_parsed),
        config=sim_config.to_dict(),
    )


@router.get("/{sim_id}", response_model=SimulationStatusOut)
async def get_simulation(sim_id: int, db: AsyncSession = Depends(get_db)):
    """Check status / get results of a simulation."""
    result = await db.execute(
        select(SimulationResult).where(SimulationResult.id == sim_id)
    )
    sim = result.scalar_one_or_none()
    if not sim:
        raise HTTPException(404, "Simulation not found")

    config_data = None
    if sim.config:
        try:
            config_data = json.loads(sim.config)
        except (json.JSONDecodeError, TypeError):
            config_data = sim.config

    results_data = None
    if sim.results:
        try:
            results_data = json.loads(sim.results)
        except (json.JSONDecodeError, TypeError):
            results_data = sim.results

    return SimulationStatusOut(
        id=sim.id,
        status=sim.status,
        sim_count=sim.sim_count,
        lineup_pool_size=sim.lineup_pool_size,
        config=config_data,
        results=results_data,
        started_at=sim.started_at.isoformat() if sim.started_at else None,
        completed_at=sim.completed_at.isoformat() if sim.completed_at else None,
    )


@router.get("/", response_model=List[SimulationStatusOut])
async def list_simulations(
    contest_id: Optional[int] = None,
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """List simulation runs."""
    stmt = select(SimulationResult).order_by(SimulationResult.created_at.desc()).limit(50)
    if contest_id is not None:
        stmt = stmt.where(SimulationResult.contest_id == contest_id)
    if status:
        stmt = stmt.where(SimulationResult.status == status)
    result = await db.execute(stmt)
    rows = result.scalars().all()

    out = []
    for sim in rows:
        config_data = None
        if sim.config:
            try:
                config_data = json.loads(sim.config)
            except (json.JSONDecodeError, TypeError):
                pass
        results_data = None
        if sim.results:
            try:
                results_data = json.loads(sim.results)
            except (json.JSONDecodeError, TypeError):
                pass
        out.append(
            SimulationStatusOut(
                id=sim.id,
                status=sim.status,
                sim_count=sim.sim_count,
                lineup_pool_size=sim.lineup_pool_size,
                config=config_data,
                results=results_data,
                started_at=sim.started_at.isoformat() if sim.started_at else None,
                completed_at=sim.completed_at.isoformat() if sim.completed_at else None,
            )
        )
    return out
