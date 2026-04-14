"""Data pipeline trigger endpoints.

These endpoints orchestrate fetching data from external APIs (MLB Stats,
DraftKings, weather, Vegas lines) and storing it in the database.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.game import Game
from models.player import Player
from models.team import Team
from services import dk_api, mlb_stats, vegas, weather
from services.daily_pipeline import run_daily_pipeline

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/pipeline", tags=["data-pipeline"])


# ── Pydantic schemas ────────────────────────────────────────────────────────


class PipelineResult(BaseModel):
    step: str
    success: bool
    detail: str
    records_affected: int = 0


class FullPipelineResult(BaseModel):
    steps: List[PipelineResult]


# ── Endpoints ───────────────────────────────────────────────────────────────


@router.post("/fetch-schedule", response_model=PipelineResult)
async def fetch_schedule(
    game_date: str = Query(None, description="YYYY-MM-DD, defaults to today"),
    db: AsyncSession = Depends(get_db),
):
    """Fetch MLB schedule for a date and upsert games into the database."""
    try:
        d = date.fromisoformat(game_date) if game_date else date.today()
    except ValueError:
        raise HTTPException(400, "Invalid date, use YYYY-MM-DD")

    try:
        schedule = await mlb_stats.get_schedule(d)
    except Exception as exc:
        return PipelineResult(
            step="fetch-schedule", success=False, detail=str(exc)
        )

    games = mlb_stats.parse_schedule_games(schedule)
    created = 0
    updated = 0

    for g in games:
        game_pk = g.get("game_pk")
        if not game_pk:
            continue

        # Look up team IDs
        home_team = await _get_or_create_team(db, g.get("home_team_abbr", ""))
        away_team = await _get_or_create_team(db, g.get("away_team_abbr", ""))

        # Look up or create pitchers
        home_pitcher = await _get_or_create_player(
            db, g.get("home_pitcher_id"), g.get("home_pitcher_name"), "P"
        )
        away_pitcher = await _get_or_create_player(
            db, g.get("away_pitcher_id"), g.get("away_pitcher_name"), "P"
        )

        # Check existing
        result = await db.execute(
            select(Game).where(Game.mlb_game_pk == game_pk)
        )
        existing = result.scalar_one_or_none()

        home_lu = json.dumps(g["home_lineup"]) if g.get("home_lineup") else None
        away_lu = json.dumps(g["away_lineup"]) if g.get("away_lineup") else None

        if existing:
            existing.home_pitcher_id = home_pitcher.id if home_pitcher else None
            existing.away_pitcher_id = away_pitcher.id if away_pitcher else None
            existing.home_lineup = home_lu
            existing.away_lineup = away_lu
            if g.get("temperature"):
                existing.temperature = _parse_temp(g["temperature"])
            updated += 1
        else:
            game_time = None
            if g.get("game_time"):
                try:
                    dt = datetime.fromisoformat(g["game_time"].replace("Z", "+00:00"))
                    game_time = dt.strftime("%I:%M %p ET")
                except (ValueError, TypeError):
                    pass

            game = Game(
                date=d,
                time=game_time,
                home_team_id=home_team.id if home_team else 0,
                away_team_id=away_team.id if away_team else 0,
                venue=g.get("venue"),
                home_pitcher_id=home_pitcher.id if home_pitcher else None,
                away_pitcher_id=away_pitcher.id if away_pitcher else None,
                home_lineup=home_lu,
                away_lineup=away_lu,
                mlb_game_pk=game_pk,
                temperature=_parse_temp(g.get("temperature")),
            )
            db.add(game)
            created += 1

    await db.flush()
    total = created + updated
    return PipelineResult(
        step="fetch-schedule",
        success=True,
        detail=f"Created {created}, updated {updated} games for {d.isoformat()}",
        records_affected=total,
    )


@router.post("/fetch-vegas", response_model=PipelineResult)
async def fetch_vegas_lines(db: AsyncSession = Depends(get_db)):
    """Fetch DK Sportsbook MLB lines and update game records."""
    try:
        raw = await vegas.get_mlb_odds()
    except Exception as exc:
        return PipelineResult(
            step="fetch-vegas", success=False, detail=str(exc)
        )

    odds = vegas.parse_odds(raw)
    updated = 0

    for od in odds:
        # Try to match to a game by team abbreviations
        # This is imperfect; a more robust approach would match by date + teams
        home = od.get("home_team")
        away = od.get("away_team")
        if not home or not away:
            continue

        # Get today's games
        today = date.today()
        result = await db.execute(select(Game).where(Game.date == today))
        games = result.scalars().all()

        for game in games:
            # Load team abbreviations
            ht_result = await db.execute(
                select(Team).where(Team.id == game.home_team_id)
            )
            at_result = await db.execute(
                select(Team).where(Team.id == game.away_team_id)
            )
            ht = ht_result.scalar_one_or_none()
            at = at_result.scalar_one_or_none()

            if not ht or not at:
                continue

            # Fuzzy match team names
            if (
                ht.name.lower() in home.lower()
                or home.lower() in ht.name.lower()
            ) and (
                at.name.lower() in away.lower()
                or away.lower() in at.name.lower()
            ):
                game.vegas_home_ml = od.get("home_ml")
                game.vegas_away_ml = od.get("away_ml")
                game.vegas_total = od.get("total")
                game.vegas_home_implied = od.get("home_implied")
                game.vegas_away_implied = od.get("away_implied")
                updated += 1
                break

    await db.flush()
    return PipelineResult(
        step="fetch-vegas",
        success=True,
        detail=f"Updated {updated} games with Vegas lines",
        records_affected=updated,
    )


@router.post("/fetch-weather", response_model=PipelineResult)
async def fetch_weather(db: AsyncSession = Depends(get_db)):
    """Fetch weather for today's games using stadium coordinates."""
    today = date.today()
    result = await db.execute(select(Game).where(Game.date == today))
    games = result.scalars().all()

    updated = 0
    for game in games:
        # Get home team stadium coords
        result = await db.execute(
            select(Team).where(Team.id == game.home_team_id)
        )
        team = result.scalar_one_or_none()
        if not team or not team.stadium_lat or not team.stadium_lon:
            continue

        # Skip domes
        if team.stadium_roof == "dome":
            continue

        try:
            forecast = await weather.get_weather_forecast(
                team.stadium_lat, team.stadium_lon, today
            )
            wx = weather.extract_game_time_weather(forecast, game_hour=19)
            game.temperature = wx.get("temperature")
            game.wind_speed = wx.get("wind_speed")
            game.wind_dir = wx.get("wind_dir")
            game.precip_pct = wx.get("precip_pct")
            updated += 1
        except Exception as exc:
            logger.warning(
                "Weather fetch failed for game %d: %s", game.id, exc
            )

    await db.flush()
    return PipelineResult(
        step="fetch-weather",
        success=True,
        detail=f"Updated weather for {updated} games",
        records_affected=updated,
    )


@router.post("/fetch-dk-salaries/{draft_group_id}", response_model=PipelineResult)
async def fetch_dk_salaries(
    draft_group_id: int, db: AsyncSession = Depends(get_db)
):
    """Import DK player salaries from a draft group."""
    try:
        draftables = await dk_api.get_draftables(draft_group_id)
    except Exception as exc:
        return PipelineResult(
            step="fetch-dk-salaries", success=False, detail=str(exc)
        )

    updated = 0
    created = 0

    for raw in draftables:
        parsed = dk_api.parse_draftable(raw)
        dk_id = parsed.get("dk_id")
        if not dk_id:
            continue

        result = await db.execute(select(Player).where(Player.dk_id == dk_id))
        existing = result.scalar_one_or_none()

        if existing:
            existing.dk_salary = parsed["dk_salary"]
            existing.team = parsed["team"] or existing.team
            if parsed["position"]:
                existing.position = parsed["position"]
            updated += 1
        else:
            player = Player(
                name=parsed["name"],
                team=parsed["team"],
                position=parsed["position"] or "UTIL",
                bats="R",
                throws="R",
                dk_id=dk_id,
                dk_salary=parsed["dk_salary"],
            )
            db.add(player)
            created += 1

    await db.flush()
    return PipelineResult(
        step="fetch-dk-salaries",
        success=True,
        detail=f"Created {created}, updated {updated} players from DG {draft_group_id}",
        records_affected=created + updated,
    )


@router.post("/fetch-all", response_model=FullPipelineResult)
async def fetch_all_data(
    game_date: str = Query(None, description="YYYY-MM-DD"),
    draft_group_id: int = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Run the full daily data pipeline: schedule -> vegas -> weather."""
    steps: List[PipelineResult] = []

    # 1. Schedule
    r1 = await fetch_schedule(game_date=game_date, db=db)
    steps.append(r1)

    # 2. Vegas
    r2 = await fetch_vegas_lines(db=db)
    steps.append(r2)

    # 3. Weather
    r3 = await fetch_weather(db=db)
    steps.append(r3)

    # 4. DK salaries (if draft group provided)
    if draft_group_id:
        r4 = await fetch_dk_salaries(draft_group_id, db=db)
        steps.append(r4)

    return FullPipelineResult(steps=steps)


# ── Daily pipeline (full orchestrated run) ─────────────────────────────────


class DailyPipelineResult(BaseModel):
    steps: List[PipelineResult]
    total_games: int = 0
    total_projections: int = 0
    total_pitchers: int = 0
    total_hitters: int = 0
    slates_found: int = 0
    featured_slate: Optional[Dict[str, Any]] = None
    top_5_pitchers: List[Dict[str, Any]] = []
    top_10_hitters: List[Dict[str, Any]] = []
    errors: int = 0


@router.post("/run-daily", response_model=DailyPipelineResult)
async def run_daily(
    target_date: str = Query("2026-04-14", description="YYYY-MM-DD"),
    site: str = Query("dk", pattern="^(dk|fd)$"),
    db: AsyncSession = Depends(get_db),
):
    """Run the full daily projection pipeline.

    Fetches schedule, slates, salaries, Vegas lines, weather, lineups,
    generates projections for all players, and returns a comprehensive
    result summary.

    This does NOT require the database to be pre-populated -- it fetches
    everything from external APIs and generates projections in memory.
    """
    result = await run_daily_pipeline(target_date, site)

    # Convert pipeline steps to PipelineResult models
    pipeline_steps: List[PipelineResult] = []
    for step in result.get("steps", []):
        pipeline_steps.append(
            PipelineResult(
                step=step["step"],
                success=step["success"],
                detail=step["detail"],
                records_affected=step.get("records_affected", 0),
            )
        )

    summary = result.get("summary", {})
    return DailyPipelineResult(
        steps=pipeline_steps,
        total_games=summary.get("total_games", 0),
        total_projections=summary.get("total_projections", 0),
        total_pitchers=summary.get("total_pitchers", 0),
        total_hitters=summary.get("total_hitters", 0),
        slates_found=summary.get("slates_found", 0),
        featured_slate=summary.get("featured_slate"),
        top_5_pitchers=summary.get("top_5_pitchers", []),
        top_10_hitters=summary.get("top_10_hitters", []),
        errors=summary.get("errors", 0),
    )


# ── Helpers ─────────────────────────────────────────────────────────────────


async def _get_or_create_team(
    db: AsyncSession, abbr: str
) -> Optional[Team]:
    """Look up a team by abbreviation, or create a stub."""
    if not abbr:
        return None
    result = await db.execute(select(Team).where(Team.abbreviation == abbr))
    team = result.scalar_one_or_none()
    if team:
        return team
    # Create stub
    team = Team(
        name=abbr,
        abbreviation=abbr,
        league="AL",  # Will be corrected on enrichment
        division="East",
        stadium_roof="open",
    )
    db.add(team)
    await db.flush()
    await db.refresh(team)
    return team


async def _get_or_create_player(
    db: AsyncSession,
    mlb_id: Optional[int],
    name: Optional[str],
    position: str = "UTIL",
) -> Optional[Player]:
    """Look up a player by MLB ID, or create a stub."""
    if not mlb_id:
        return None
    result = await db.execute(select(Player).where(Player.mlb_id == mlb_id))
    player = result.scalar_one_or_none()
    if player:
        return player
    player = Player(
        name=name or f"Player {mlb_id}",
        team="",
        position=position,
        bats="R",
        throws="R",
        mlb_id=mlb_id,
    )
    db.add(player)
    await db.flush()
    await db.refresh(player)
    return player


def _parse_temp(temp_str: Any) -> Optional[float]:
    """Parse temperature from MLB weather string like '72 degrees'."""
    if temp_str is None:
        return None
    if isinstance(temp_str, (int, float)):
        return float(temp_str)
    try:
        return float(str(temp_str).split()[0])
    except (ValueError, IndexError):
        return None
