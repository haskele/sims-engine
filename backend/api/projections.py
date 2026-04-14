"""Projection endpoints: get, edit, bulk update, auto-generate, and slate-scoped projections."""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.player import Player
from models.projection import Projection
from services.projections import build_player_projection
from services.slate_manager import fetch_dk_slates, identify_featured_slate

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/projections", tags=["projections"])


# ── Pydantic schemas ────────────────────────────────────────────────────────


class ProjectionOut(BaseModel):
    id: int
    player_id: int
    game_id: int
    site: str
    floor_pts: float
    median_pts: float
    ceiling_pts: float
    projected_ownership: Optional[float] = None
    batting_order: Optional[int] = None
    is_confirmed: bool = False

    model_config = {"from_attributes": True}


class ProjectionUpdate(BaseModel):
    floor_pts: Optional[float] = None
    median_pts: Optional[float] = None
    ceiling_pts: Optional[float] = None
    projected_ownership: Optional[float] = None
    batting_order: Optional[int] = None
    is_confirmed: Optional[bool] = None


class BulkProjectionItem(BaseModel):
    player_id: int
    game_id: int
    site: str = "dk"
    floor_pts: float
    median_pts: float
    ceiling_pts: float
    projected_ownership: Optional[float] = None
    batting_order: Optional[int] = None
    is_confirmed: bool = False


class BulkProjectionRequest(BaseModel):
    projections: List[BulkProjectionItem]


class BulkProjectionResult(BaseModel):
    created: int
    updated: int
    errors: List[str] = []


class GenerateRequest(BaseModel):
    """Request to auto-generate projections for players in a game."""
    game_id: int
    site: str = "dk"
    player_ids: Optional[List[int]] = None
    implied_runs: Optional[float] = None
    opp_pitcher_k9: Optional[float] = None


class SlateOut(BaseModel):
    slate_id: str
    site: str
    name: str
    game_count: int
    start_time: Optional[str] = None
    game_type: str
    draft_group_id: int


class SlateProjectionOut(BaseModel):
    player_name: str
    mlb_id: Optional[int] = None
    team: str
    position: str
    opp_team: Optional[str] = None
    game_pk: Optional[int] = None
    venue: Optional[str] = None
    salary: Optional[int] = None
    batting_order: Optional[int] = None
    is_pitcher: bool = False
    is_confirmed: bool = False
    floor_pts: float
    median_pts: float
    ceiling_pts: float
    projected_ownership: Optional[float] = None
    season_era: Optional[float] = None
    season_k9: Optional[float] = None
    season_avg: Optional[float] = None
    season_ops: Optional[float] = None
    games_in_log: int = 0
    implied_total: Optional[float] = None
    team_implied: Optional[float] = None
    temperature: Optional[float] = None


# ── Slate-scoped endpoints (MUST be before /{projection_id} to avoid route conflict) ──


@router.get("/slates", response_model=List[SlateOut])
async def list_slates(
    site: str = Query("dk", pattern="^(dk|fd)$"),
    target_date: str = Query(None, description="YYYY-MM-DD, defaults to today"),
):
    """List available DFS slates for a given date and site."""
    try:
        d = date.fromisoformat(target_date) if target_date else date.today()
    except ValueError:
        raise HTTPException(400, "Invalid date, use YYYY-MM-DD")

    if site == "dk":
        slates = await fetch_dk_slates(target_date=d)
    else:
        slates = []

    return [
        SlateOut(
            slate_id=s["slate_id"],
            site=s["site"],
            name=s["name"],
            game_count=s["game_count"],
            start_time=s.get("start_time"),
            game_type=s["game_type"],
            draft_group_id=s["draft_group_id"],
        )
        for s in slates
    ]


@router.get("/slates/featured/projections", response_model=List[SlateProjectionOut])
async def get_featured_slate_projections(
    site: str = Query("dk", pattern="^(dk|fd)$"),
    target_date: str = Query(None, description="YYYY-MM-DD"),
):
    """Get projections for the featured/main slate."""
    from services.daily_pipeline import run_daily_pipeline

    d_str = target_date or date.today().isoformat()
    result = await run_daily_pipeline(d_str, site)

    projections = result.get("projections", [])
    return [
        SlateProjectionOut(**_sanitise_projection(p))
        for p in projections
    ]


@router.get("/slates/{slate_id}/projections", response_model=List[SlateProjectionOut])
async def get_slate_projections(
    slate_id: str,
    site: str = Query("dk", pattern="^(dk|fd)$"),
    target_date: str = Query(None, description="YYYY-MM-DD"),
):
    """Get projections scoped to a specific slate."""
    from services.daily_pipeline import run_daily_pipeline

    d_str = target_date or date.today().isoformat()
    result = await run_daily_pipeline(d_str, site)

    projections = result.get("projections", [])
    return [
        SlateProjectionOut(**_sanitise_projection(p))
        for p in projections
    ]


# ── Core CRUD endpoints ───────────────────────────────────────────────────────


@router.get("/", response_model=List[ProjectionOut])
async def list_projections(
    game_id: Optional[int] = None,
    site: Optional[str] = Query(None, pattern="^(dk|fd)$"),
    db: AsyncSession = Depends(get_db),
):
    """List projections with optional filters."""
    stmt = select(Projection).order_by(Projection.median_pts.desc())
    if game_id:
        stmt = stmt.where(Projection.game_id == game_id)
    if site:
        stmt = stmt.where(Projection.site == site)
    result = await db.execute(stmt)
    return [ProjectionOut.model_validate(r) for r in result.scalars().all()]


@router.get("/{projection_id}", response_model=ProjectionOut)
async def get_projection(projection_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Projection).where(Projection.id == projection_id)
    )
    proj = result.scalar_one_or_none()
    if not proj:
        raise HTTPException(404, "Projection not found")
    return ProjectionOut.model_validate(proj)


@router.patch("/{projection_id}", response_model=ProjectionOut)
async def update_projection(
    projection_id: int,
    body: ProjectionUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Edit a single projection (manual override)."""
    result = await db.execute(
        select(Projection).where(Projection.id == projection_id)
    )
    proj = result.scalar_one_or_none()
    if not proj:
        raise HTTPException(404, "Projection not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(proj, field, value)
    await db.flush()
    await db.refresh(proj)
    return ProjectionOut.model_validate(proj)


@router.post("/bulk", response_model=BulkProjectionResult)
async def bulk_upsert_projections(
    body: BulkProjectionRequest, db: AsyncSession = Depends(get_db)
):
    """Create or update projections in bulk (upsert by player_id + game_id + site)."""
    created = 0
    updated = 0
    errors: List[str] = []

    for item in body.projections:
        try:
            result = await db.execute(
                select(Projection).where(
                    Projection.player_id == item.player_id,
                    Projection.game_id == item.game_id,
                    Projection.site == item.site,
                )
            )
            existing = result.scalar_one_or_none()

            if existing:
                existing.floor_pts = item.floor_pts
                existing.median_pts = item.median_pts
                existing.ceiling_pts = item.ceiling_pts
                if item.projected_ownership is not None:
                    existing.projected_ownership = item.projected_ownership
                if item.batting_order is not None:
                    existing.batting_order = item.batting_order
                existing.is_confirmed = item.is_confirmed
                updated += 1
            else:
                proj = Projection(
                    player_id=item.player_id,
                    game_id=item.game_id,
                    site=item.site,
                    floor_pts=item.floor_pts,
                    median_pts=item.median_pts,
                    ceiling_pts=item.ceiling_pts,
                    projected_ownership=item.projected_ownership,
                    batting_order=item.batting_order,
                    is_confirmed=item.is_confirmed,
                )
                db.add(proj)
                created += 1
        except Exception as exc:
            errors.append(
                f"player_id={item.player_id} game_id={item.game_id}: {exc}"
            )

    await db.flush()
    return BulkProjectionResult(created=created, updated=updated, errors=errors)


@router.post("/generate", response_model=BulkProjectionResult)
async def generate_projections(
    body: GenerateRequest, db: AsyncSession = Depends(get_db)
):
    """Auto-generate 3-bucket projections from MLB game logs."""
    if body.player_ids:
        result = await db.execute(
            select(Player).where(Player.id.in_(body.player_ids))
        )
        players = list(result.scalars().all())
    else:
        result = await db.execute(select(Player).where(Player.mlb_id.isnot(None)))
        players = list(result.scalars().all())

    if not players:
        raise HTTPException(400, "No players found to project")

    created = 0
    updated = 0
    errors: List[str] = []

    for player in players:
        if not player.mlb_id:
            errors.append(f"Player {player.id} ({player.name}): no mlb_id")
            continue

        is_pitcher = "P" in player.position.split("/")
        try:
            proj_data = await build_player_projection(
                player_id=player.mlb_id,
                site=body.site,
                is_pitcher=is_pitcher,
                batting_order=None,
                implied_runs=body.implied_runs,
                opp_pitcher_k9=body.opp_pitcher_k9,
            )
        except Exception as exc:
            errors.append(f"Player {player.id} ({player.name}): {exc}")
            continue

        result = await db.execute(
            select(Projection).where(
                Projection.player_id == player.id,
                Projection.game_id == body.game_id,
                Projection.site == body.site,
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            existing.floor_pts = proj_data["floor_pts"]
            existing.median_pts = proj_data["median_pts"]
            existing.ceiling_pts = proj_data["ceiling_pts"]
            updated += 1
        else:
            proj = Projection(
                player_id=player.id,
                game_id=body.game_id,
                site=body.site,
                floor_pts=proj_data["floor_pts"],
                median_pts=proj_data["median_pts"],
                ceiling_pts=proj_data["ceiling_pts"],
            )
            db.add(proj)
            created += 1

    await db.flush()
    return BulkProjectionResult(created=created, updated=updated, errors=errors)



# ── Helpers ────────────────────────────────────────────────────────────────


def _sanitise_projection(p: Dict[str, Any]) -> Dict[str, Any]:
    """Ensure all fields in a projection dict are compatible with the Pydantic model."""
    return {
        "player_name": p.get("player_name", "Unknown"),
        "mlb_id": p.get("mlb_id"),
        "team": p.get("team", ""),
        "position": p.get("position", "UTIL"),
        "opp_team": p.get("opp_team"),
        "game_pk": p.get("game_pk"),
        "venue": p.get("venue"),
        "salary": p.get("salary"),
        "batting_order": p.get("batting_order"),
        "is_pitcher": p.get("is_pitcher", False),
        "is_confirmed": p.get("is_confirmed", False),
        "floor_pts": p.get("floor_pts", 0.0),
        "median_pts": p.get("median_pts", 0.0),
        "ceiling_pts": p.get("ceiling_pts", 0.0),
        "projected_ownership": p.get("projected_ownership"),
        "season_era": p.get("season_era"),
        "season_k9": p.get("season_k9"),
        "season_avg": p.get("season_avg"),
        "season_ops": p.get("season_ops"),
        "games_in_log": p.get("games_in_log", 0),
        "implied_total": p.get("implied_total"),
        "team_implied": p.get("team_implied"),
        "temperature": p.get("temperature"),
    }
