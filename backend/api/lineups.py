"""Lineup build, list, and export endpoints."""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.lineup import Lineup
from models.player import Player
from models.projection import Projection
from services.optimizer import PlayerPool, generate_lineup_pool, optimize_lineup

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/lineups", tags=["lineups"])


# ── Pydantic schemas ────────────────────────────────────────────────────────


class LineupPlayerSlot(BaseModel):
    player_id: int
    position: str
    salary: int


class LineupOut(BaseModel):
    id: int
    contest_id: int
    entry_id: Optional[str] = None
    user_name: Optional[str] = None
    players: List[LineupPlayerSlot]
    total_salary: int
    total_points: Optional[float] = None
    finish_position: Optional[int] = None
    is_user: bool = False

    model_config = {"from_attributes": True}


class LineupCreate(BaseModel):
    contest_id: int
    entry_id: Optional[str] = None
    user_name: Optional[str] = None
    players: List[LineupPlayerSlot]
    is_user: bool = False


class OptimizeRequest(BaseModel):
    """Request to build optimised lineups from the player pool."""
    game_id: int
    site: str = "dk"
    n_lineups: int = 20
    min_unique: int = 3
    locked_player_ids: List[int] = []
    excluded_player_ids: List[int] = []
    exposure_limits: Dict[int, List[float]] = {}  # player_id -> [min_pct, max_pct]
    objective: str = "median_pts"


class OptimizeResult(BaseModel):
    lineups: List[List[Dict[str, Any]]]
    count: int


# ── Endpoints ───────────────────────────────────────────────────────────────


@router.get("/", response_model=List[LineupOut])
async def list_lineups(
    contest_id: Optional[int] = None,
    is_user: Optional[bool] = None,
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
):
    """List lineups, optionally filtered by contest and user flag."""
    stmt = select(Lineup).order_by(Lineup.created_at.desc()).limit(limit)
    if contest_id is not None:
        stmt = stmt.where(Lineup.contest_id == contest_id)
    if is_user is not None:
        stmt = stmt.where(Lineup.is_user == is_user)
    result = await db.execute(stmt)
    rows = result.scalars().all()

    out = []
    for r in rows:
        try:
            players = json.loads(r.players) if isinstance(r.players, str) else r.players
        except (json.JSONDecodeError, TypeError):
            players = []
        out.append(
            LineupOut(
                id=r.id,
                contest_id=r.contest_id,
                entry_id=r.entry_id,
                user_name=r.user_name,
                players=[LineupPlayerSlot(**p) for p in players],
                total_salary=r.total_salary,
                total_points=r.total_points,
                finish_position=r.finish_position,
                is_user=r.is_user,
            )
        )
    return out


@router.post("/", response_model=LineupOut, status_code=201)
async def create_lineup(body: LineupCreate, db: AsyncSession = Depends(get_db)):
    """Store a lineup."""
    players_json = json.dumps([p.model_dump() for p in body.players])
    total_salary = sum(p.salary for p in body.players)

    lineup = Lineup(
        contest_id=body.contest_id,
        entry_id=body.entry_id,
        user_name=body.user_name,
        players=players_json,
        total_salary=total_salary,
        is_user=body.is_user,
    )
    db.add(lineup)
    await db.flush()
    await db.refresh(lineup)

    return LineupOut(
        id=lineup.id,
        contest_id=lineup.contest_id,
        entry_id=lineup.entry_id,
        user_name=lineup.user_name,
        players=body.players,
        total_salary=total_salary,
        total_points=None,
        finish_position=None,
        is_user=lineup.is_user,
    )


@router.post("/optimize", response_model=OptimizeResult)
async def optimize_lineups(
    body: OptimizeRequest, db: AsyncSession = Depends(get_db)
):
    """Generate optimised lineups from the player pool + projections.

    Pulls all projections for the given game/site, merges with player salary
    data, and runs the optimizer to produce N diverse lineups.
    """
    # Fetch projections
    result = await db.execute(
        select(Projection)
        .where(Projection.game_id == body.game_id, Projection.site == body.site)
    )
    projections = result.scalars().all()
    if not projections:
        raise HTTPException(400, "No projections found for this game/site")

    # Fetch players
    player_ids = [p.player_id for p in projections]
    result = await db.execute(select(Player).where(Player.id.in_(player_ids)))
    players_db = {p.id: p for p in result.scalars().all()}

    # Build pool
    pool_data: list[dict[str, Any]] = []
    for proj in projections:
        player = players_db.get(proj.player_id)
        if not player:
            continue
        salary = player.dk_salary if body.site == "dk" else player.fd_salary
        if not salary:
            continue
        pool_data.append(
            {
                "id": player.id,
                "name": player.name,
                "team": player.team,
                "position": player.position,
                "salary": salary,
                "floor_pts": proj.floor_pts,
                "median_pts": proj.median_pts,
                "ceiling_pts": proj.ceiling_pts,
                "ownership": proj.projected_ownership or 0,
            }
        )

    if not pool_data:
        raise HTTPException(400, "No players with salary data in projection set")

    pool = PlayerPool(pool_data)

    # Convert exposure limits
    exposure = None
    if body.exposure_limits:
        exposure = {
            pid: (bounds[0], bounds[1])
            for pid, bounds in body.exposure_limits.items()
            if len(bounds) == 2
        }

    lineups = generate_lineup_pool(
        pool=pool,
        n_lineups=body.n_lineups,
        site=body.site,
        objective=body.objective,
        min_unique=body.min_unique,
        exposure_limits=exposure,
    )

    return OptimizeResult(lineups=lineups, count=len(lineups))


@router.get("/export/dk")
async def export_dk_csv(
    contest_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Export user lineups for a contest as DK-uploadable CSV text.

    Returns plain text in DraftKings CSV format.
    """
    from fastapi.responses import PlainTextResponse

    result = await db.execute(
        select(Lineup).where(
            Lineup.contest_id == contest_id, Lineup.is_user == True
        )
    )
    lineups = result.scalars().all()
    if not lineups:
        raise HTTPException(404, "No user lineups for this contest")

    from config import DK_ROSTER_SLOTS

    header = ",".join(DK_ROSTER_SLOTS)
    rows = [header]

    for lu in lineups:
        try:
            players = json.loads(lu.players) if isinstance(lu.players, str) else lu.players
        except (json.JSONDecodeError, TypeError):
            continue

        # Build slot -> dk_id mapping
        slot_map: dict[str, int] = {}
        for p in players:
            # Look up dk_id from database
            pr = await db.execute(select(Player).where(Player.id == p["player_id"]))
            player = pr.scalar_one_or_none()
            if player and player.dk_id:
                slot_map[p["position"]] = player.dk_id

        # Build row in slot order
        row_parts = []
        for slot in DK_ROSTER_SLOTS:
            dk_id = slot_map.get(slot, "")
            row_parts.append(str(dk_id))
        rows.append(",".join(row_parts))

    return PlainTextResponse("\n".join(rows), media_type="text/csv")
