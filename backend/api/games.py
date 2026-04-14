"""Game and lineup data endpoints."""
from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.game import Game
from models.team import Team

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/games", tags=["games"])


# ── Pydantic schemas ────────────────────────────────────────────────────────


class GameOut(BaseModel):
    id: int
    date: str
    time: Optional[str] = None
    home_team_id: int
    away_team_id: int
    venue: Optional[str] = None
    home_pitcher_id: Optional[int] = None
    away_pitcher_id: Optional[int] = None
    home_lineup: Optional[List[int]] = None
    away_lineup: Optional[List[int]] = None
    lineup_confirmed: bool = False
    vegas_home_ml: Optional[int] = None
    vegas_away_ml: Optional[int] = None
    vegas_total: Optional[float] = None
    vegas_home_implied: Optional[float] = None
    vegas_away_implied: Optional[float] = None
    wind_speed: Optional[float] = None
    wind_dir: Optional[float] = None
    temperature: Optional[float] = None
    precip_pct: Optional[float] = None
    mlb_game_pk: Optional[int] = None

    model_config = {"from_attributes": True}


class GameCreate(BaseModel):
    date: str  # YYYY-MM-DD
    time: Optional[str] = None
    home_team_id: int
    away_team_id: int
    venue: Optional[str] = None
    home_pitcher_id: Optional[int] = None
    away_pitcher_id: Optional[int] = None
    mlb_game_pk: Optional[int] = None


class GameUpdate(BaseModel):
    home_pitcher_id: Optional[int] = None
    away_pitcher_id: Optional[int] = None
    home_lineup: Optional[List[int]] = None
    away_lineup: Optional[List[int]] = None
    lineup_confirmed: Optional[bool] = None
    vegas_home_ml: Optional[int] = None
    vegas_away_ml: Optional[int] = None
    vegas_total: Optional[float] = None
    vegas_home_implied: Optional[float] = None
    vegas_away_implied: Optional[float] = None
    wind_speed: Optional[float] = None
    wind_dir: Optional[float] = None
    temperature: Optional[float] = None
    precip_pct: Optional[float] = None


class TeamOut(BaseModel):
    id: int
    name: str
    abbreviation: str
    league: str
    division: str
    stadium_name: Optional[str] = None
    stadium_lat: Optional[float] = None
    stadium_lon: Optional[float] = None
    stadium_roof: str = "open"

    model_config = {"from_attributes": True}


class TeamCreate(BaseModel):
    name: str
    abbreviation: str
    league: str
    division: str
    stadium_name: Optional[str] = None
    stadium_lat: Optional[float] = None
    stadium_lon: Optional[float] = None
    stadium_roof: str = "open"
    mlb_id: Optional[int] = None


# ── Game endpoints ──────────────────────────────────────────────────────────


@router.get("/", response_model=List[GameOut])
async def list_games(
    game_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    db: AsyncSession = Depends(get_db),
):
    """List games, optionally filtered by date."""
    stmt = select(Game).order_by(Game.date.desc())
    if game_date:
        try:
            d = date.fromisoformat(game_date)
        except ValueError:
            raise HTTPException(400, "Invalid date format, use YYYY-MM-DD")
        stmt = stmt.where(Game.date == d)
    result = await db.execute(stmt)
    rows = result.scalars().all()

    out = []
    for g in rows:
        home_lu = None
        away_lu = None
        if g.home_lineup:
            try:
                home_lu = json.loads(g.home_lineup)
            except (json.JSONDecodeError, TypeError):
                pass
        if g.away_lineup:
            try:
                away_lu = json.loads(g.away_lineup)
            except (json.JSONDecodeError, TypeError):
                pass
        out.append(
            GameOut(
                id=g.id,
                date=g.date.isoformat() if g.date else "",
                time=g.time,
                home_team_id=g.home_team_id,
                away_team_id=g.away_team_id,
                venue=g.venue,
                home_pitcher_id=g.home_pitcher_id,
                away_pitcher_id=g.away_pitcher_id,
                home_lineup=home_lu,
                away_lineup=away_lu,
                lineup_confirmed=g.lineup_confirmed,
                vegas_home_ml=g.vegas_home_ml,
                vegas_away_ml=g.vegas_away_ml,
                vegas_total=g.vegas_total,
                vegas_home_implied=g.vegas_home_implied,
                vegas_away_implied=g.vegas_away_implied,
                wind_speed=g.wind_speed,
                wind_dir=g.wind_dir,
                temperature=g.temperature,
                precip_pct=g.precip_pct,
                mlb_game_pk=g.mlb_game_pk,
            )
        )
    return out


@router.get("/{game_id}", response_model=GameOut)
async def get_game(game_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Game).where(Game.id == game_id))
    g = result.scalar_one_or_none()
    if not g:
        raise HTTPException(404, "Game not found")
    home_lu = json.loads(g.home_lineup) if g.home_lineup else None
    away_lu = json.loads(g.away_lineup) if g.away_lineup else None
    return GameOut(
        id=g.id,
        date=g.date.isoformat() if g.date else "",
        time=g.time,
        home_team_id=g.home_team_id,
        away_team_id=g.away_team_id,
        venue=g.venue,
        home_pitcher_id=g.home_pitcher_id,
        away_pitcher_id=g.away_pitcher_id,
        home_lineup=home_lu,
        away_lineup=away_lu,
        lineup_confirmed=g.lineup_confirmed,
        vegas_home_ml=g.vegas_home_ml,
        vegas_away_ml=g.vegas_away_ml,
        vegas_total=g.vegas_total,
        vegas_home_implied=g.vegas_home_implied,
        vegas_away_implied=g.vegas_away_implied,
        wind_speed=g.wind_speed,
        wind_dir=g.wind_dir,
        temperature=g.temperature,
        precip_pct=g.precip_pct,
        mlb_game_pk=g.mlb_game_pk,
    )


@router.post("/", response_model=GameOut, status_code=201)
async def create_game(body: GameCreate, db: AsyncSession = Depends(get_db)):
    try:
        d = date.fromisoformat(body.date)
    except ValueError:
        raise HTTPException(400, "Invalid date format")
    game = Game(
        date=d,
        time=body.time,
        home_team_id=body.home_team_id,
        away_team_id=body.away_team_id,
        venue=body.venue,
        home_pitcher_id=body.home_pitcher_id,
        away_pitcher_id=body.away_pitcher_id,
        mlb_game_pk=body.mlb_game_pk,
    )
    db.add(game)
    await db.flush()
    await db.refresh(game)
    return GameOut(
        id=game.id,
        date=game.date.isoformat(),
        time=game.time,
        home_team_id=game.home_team_id,
        away_team_id=game.away_team_id,
        venue=game.venue,
        home_pitcher_id=game.home_pitcher_id,
        away_pitcher_id=game.away_pitcher_id,
        lineup_confirmed=False,
        mlb_game_pk=game.mlb_game_pk,
    )


@router.patch("/{game_id}", response_model=GameOut)
async def update_game(
    game_id: int, body: GameUpdate, db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Game).where(Game.id == game_id))
    game = result.scalar_one_or_none()
    if not game:
        raise HTTPException(404, "Game not found")

    updates = body.model_dump(exclude_unset=True)

    # Serialize lineup arrays to JSON
    if "home_lineup" in updates and updates["home_lineup"] is not None:
        updates["home_lineup"] = json.dumps(updates["home_lineup"])
    if "away_lineup" in updates and updates["away_lineup"] is not None:
        updates["away_lineup"] = json.dumps(updates["away_lineup"])

    for field, value in updates.items():
        setattr(game, field, value)

    await db.flush()
    await db.refresh(game)

    home_lu = json.loads(game.home_lineup) if game.home_lineup else None
    away_lu = json.loads(game.away_lineup) if game.away_lineup else None
    return GameOut(
        id=game.id,
        date=game.date.isoformat(),
        time=game.time,
        home_team_id=game.home_team_id,
        away_team_id=game.away_team_id,
        venue=game.venue,
        home_pitcher_id=game.home_pitcher_id,
        away_pitcher_id=game.away_pitcher_id,
        home_lineup=home_lu,
        away_lineup=away_lu,
        lineup_confirmed=game.lineup_confirmed,
        vegas_home_ml=game.vegas_home_ml,
        vegas_away_ml=game.vegas_away_ml,
        vegas_total=game.vegas_total,
        vegas_home_implied=game.vegas_home_implied,
        vegas_away_implied=game.vegas_away_implied,
        wind_speed=game.wind_speed,
        wind_dir=game.wind_dir,
        temperature=game.temperature,
        precip_pct=game.precip_pct,
        mlb_game_pk=game.mlb_game_pk,
    )


# ── Team endpoints ──────────────────────────────────────────────────────────


@router.get("/teams/", response_model=List[TeamOut])
async def list_teams(db: AsyncSession = Depends(get_db)):
    """List all teams."""
    result = await db.execute(select(Team).order_by(Team.name))
    return [TeamOut.model_validate(r) for r in result.scalars().all()]


@router.post("/teams/", response_model=TeamOut, status_code=201)
async def create_team(body: TeamCreate, db: AsyncSession = Depends(get_db)):
    team = Team(**body.model_dump())
    db.add(team)
    await db.flush()
    await db.refresh(team)
    return TeamOut.model_validate(team)
