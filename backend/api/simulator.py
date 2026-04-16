"""Simulation endpoints."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

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
from services.csv_projections import list_available_slates, load_csv_projections

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/simulations", tags=["simulations"])


# ── Pydantic schemas ────────────────────────────────────────────────────────


class SimulationRequest(BaseModel):
    contest_id: int
    sim_count: int = 10000
    site: str = "dk"
    # Optional: provide user lineup IDs; if empty, uses all is_user lineups for the contest
    user_lineup_ids: List[int] = []


class InlineContestConfig(BaseModel):
    entry_fee: float = 20.0
    field_size: int = 1000
    game_type: str = "classic"
    max_entries: int = 150
    payout_structure: List[Dict[str, Any]] = []


class InlineSimulationRequest(BaseModel):
    sim_count: int = 10000
    site: str = "dk"
    slate_id: Optional[str] = None
    contest_config: InlineContestConfig
    user_lineups: List[List[Dict[str, Any]]]


class QuickRunRequest(BaseModel):
    """Simplified simulation request that auto-fills from stored DK entries data."""
    contest_id: str  # DK contest ID string from uploaded entries
    user_lineups: List[List[Dict[str, Any]]]  # lineup arrays with name/position/salary
    sim_count: int = 5000
    site: str = "dk"
    target_date: Optional[str] = None


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
            sim_results = await asyncio.to_thread(run_simulation, config)

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


@router.post("/run-inline")
async def run_inline_simulation(body: InlineSimulationRequest):
    """Run a simulation synchronously with provided lineups and contest config.

    No database records are created. Player pool is loaded from CSV projections.
    """
    if not body.user_lineups:
        raise HTTPException(400, "No user lineups provided")

    body.sim_count = min(body.sim_count, 50000)

    # Load player pool from CSV
    slates = list_available_slates(site=body.site)
    csv_path = None
    if body.slate_id:
        for s in slates:
            if s["slate_id"] == body.slate_id:
                csv_path = s["csv_path"]
                break
    if not csv_path and slates:
        # Fall back to featured
        from services.csv_projections import identify_featured_csv_slate
        featured = identify_featured_csv_slate(slates)
        if featured:
            csv_path = featured["csv_path"]

    if not csv_path:
        raise HTTPException(400, "No projection CSV found for this slate")

    raw_projections = load_csv_projections(csv_path, body.site)
    if not raw_projections:
        raise HTTPException(400, "No projections loaded from CSV")

    # Build player pool for simulator
    player_pool = []
    for i, p in enumerate(raw_projections):
        player_pool.append({
            "id": i + 1,
            "name": p["player_name"],
            "team": p["team"],
            "position": p["position"],
            "salary": p.get("salary", 3000),
            "floor_pts": p.get("floor_pts", 0),
            "median_pts": p.get("median_pts", 0),
            "ceiling_pts": p.get("ceiling_pts", 0),
            "projected_ownership": p.get("projected_ownership", 5.0),
        })

    # Build name→id map so we can resolve user lineup player references
    name_to_id = {p["name"]: p["id"] for p in player_pool}

    # Convert user lineups to the format the simulator expects (with player_id)
    resolved_lineups = []
    for lu in body.user_lineups:
        resolved = []
        for slot in lu:
            pid = name_to_id.get(slot.get("name"), 0)
            resolved.append({
                "player_id": pid,
                "name": slot.get("name", ""),
                "position": slot.get("position", ""),
                "salary": slot.get("salary", 0),
                "team": slot.get("team", ""),
            })
        resolved_lineups.append(resolved)

    contest_cfg = {
        "entry_fee": body.contest_config.entry_fee,
        "field_size": body.contest_config.field_size,
        "game_type": body.contest_config.game_type,
        "max_entries": body.contest_config.max_entries,
        "payout_structure": body.contest_config.payout_structure,
    }

    sim_config = SimulationConfig(
        sim_count=body.sim_count,
        contest_config=contest_cfg,
        game_slate=[],
        player_pool=player_pool,
        user_lineups=resolved_lineups,
        site=body.site,
    )

    results = await asyncio.to_thread(run_simulation, sim_config)
    return results


@router.post("/quick-run")
async def quick_run_simulation(body: QuickRunRequest):
    """Run a simulation using stored DK entries data for contest config.

    Looks up field_size, entry_fee, payout_structure from the uploaded DK
    entries data, builds a player pool from current CSV projections, and
    runs the simulation synchronously.
    """
    from api.dk_entries import _current_data as dk_data
    from services.csv_projections import identify_featured_csv_slate

    if not dk_data:
        raise HTTPException(400, "No DK entries uploaded — upload a CSV first")

    if not body.user_lineups:
        raise HTTPException(400, "No user lineups provided")

    body.sim_count = min(body.sim_count, 50000)

    # Find the contest in stored DK entries data
    contest_info = None
    for c in dk_data.contests:
        if c.contest_id == body.contest_id:
            contest_info = c
            break

    if not contest_info:
        raise HTTPException(404, f"Contest {body.contest_id} not found in uploaded entries")

    # Load player pool from CSV projections
    try:
        d = date.fromisoformat(body.target_date) if body.target_date else date.today()
    except ValueError:
        raise HTTPException(400, "Invalid date format, use YYYY-MM-DD")

    slates = list_available_slates(site=body.site, target_date=d)
    csv_path = None
    if slates:
        featured = identify_featured_csv_slate(slates)
        if featured:
            csv_path = featured["csv_path"]

    if not csv_path:
        raise HTTPException(400, "No projection CSV found for this date/site")

    raw_projections = load_csv_projections(csv_path, body.site)
    if not raw_projections:
        raise HTTPException(400, "No projections loaded from CSV")

    # Build player pool for simulator
    player_pool = []
    for i, p in enumerate(raw_projections):
        player_pool.append({
            "id": i + 1,
            "name": p["player_name"],
            "team": p["team"],
            "position": p["position"],
            "salary": p.get("salary", 3000),
            "floor_pts": p.get("floor_pts", 0),
            "median_pts": p.get("median_pts", 0),
            "ceiling_pts": p.get("ceiling_pts", 0),
            "projected_ownership": p.get("projected_ownership", 5.0),
        })

    name_to_id = {p["name"]: p["id"] for p in player_pool}

    # Convert user lineups to simulator format
    resolved_lineups = []
    for lu in body.user_lineups:
        resolved = []
        for slot in lu:
            pid = name_to_id.get(slot.get("name"), 0)
            resolved.append({
                "player_id": pid,
                "name": slot.get("name", ""),
                "position": slot.get("position", ""),
                "salary": slot.get("salary", 0),
                "team": slot.get("team", ""),
            })
        resolved_lineups.append(resolved)

    # Build contest config from stored DK entries data
    payout_structure = contest_info.payout_structure or []
    contest_cfg = {
        "entry_fee": contest_info.entry_fee_numeric,
        "field_size": contest_info.field_size or 1000,
        "game_type": contest_info.game_type,
        "max_entries": contest_info.max_entries_per_user or 150,
        "payout_structure": payout_structure,
    }

    sim_config = SimulationConfig(
        sim_count=body.sim_count,
        contest_config=contest_cfg,
        game_slate=[],
        player_pool=player_pool,
        user_lineups=resolved_lineups,
        site=body.site,
    )

    results = await asyncio.to_thread(run_simulation, sim_config)
    return results


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
