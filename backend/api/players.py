"""Player pool endpoints."""
from __future__ import annotations

import json
import logging
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.player import Player
from services import dk_api

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/players", tags=["players"])


# ── Pydantic schemas ────────────────────────────────────────────────────────


class PlayerOut(BaseModel):
    id: int
    name: str
    team: str
    position: str
    bats: str
    throws: str
    dk_id: Optional[int] = None
    fd_id: Optional[int] = None
    dk_salary: Optional[int] = None
    fd_salary: Optional[int] = None
    mlb_id: Optional[int] = None

    model_config = {"from_attributes": True}


class PlayerCreate(BaseModel):
    name: str
    team: str
    position: str
    bats: str = Field(..., pattern="^[LRS]$")
    throws: str = Field(..., pattern="^[LR]$")
    dk_id: Optional[int] = None
    fd_id: Optional[int] = None
    dk_salary: Optional[int] = None
    fd_salary: Optional[int] = None
    mlb_id: Optional[int] = None


class PlayerUpdate(BaseModel):
    name: Optional[str] = None
    team: Optional[str] = None
    position: Optional[str] = None
    bats: Optional[str] = None
    throws: Optional[str] = None
    dk_id: Optional[int] = None
    fd_id: Optional[int] = None
    dk_salary: Optional[int] = None
    fd_salary: Optional[int] = None
    mlb_id: Optional[int] = None


class ImportDKResult(BaseModel):
    created: int
    updated: int
    errors: List[str] = []


# ── Endpoints ───────────────────────────────────────────────────────────────


@router.get("/", response_model=List[PlayerOut])
async def list_players(
    team: Optional[str] = None,
    position: Optional[str] = None,
    site: Optional[str] = Query(None, pattern="^(dk|fd)$"),
    db: AsyncSession = Depends(get_db),
):
    """List players with optional filters."""
    stmt = select(Player).order_by(Player.name)
    if team:
        stmt = stmt.where(Player.team == team)
    if position:
        stmt = stmt.where(Player.position.contains(position))
    if site == "dk":
        stmt = stmt.where(Player.dk_salary.isnot(None))
    elif site == "fd":
        stmt = stmt.where(Player.fd_salary.isnot(None))
    result = await db.execute(stmt)
    return [PlayerOut.model_validate(r) for r in result.scalars().all()]


@router.get("/{player_id}", response_model=PlayerOut)
async def get_player(player_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Player).where(Player.id == player_id))
    player = result.scalar_one_or_none()
    if not player:
        raise HTTPException(404, "Player not found")
    return PlayerOut.model_validate(player)


@router.post("/", response_model=PlayerOut, status_code=201)
async def create_player(body: PlayerCreate, db: AsyncSession = Depends(get_db)):
    player = Player(**body.model_dump())
    db.add(player)
    await db.flush()
    await db.refresh(player)
    return PlayerOut.model_validate(player)


@router.patch("/{player_id}", response_model=PlayerOut)
async def update_player(
    player_id: int, body: PlayerUpdate, db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Player).where(Player.id == player_id))
    player = result.scalar_one_or_none()
    if not player:
        raise HTTPException(404, "Player not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(player, field, value)
    await db.flush()
    await db.refresh(player)
    return PlayerOut.model_validate(player)


@router.post("/import/dk/{draft_group_id}", response_model=ImportDKResult)
async def import_dk_players(
    draft_group_id: int, db: AsyncSession = Depends(get_db)
):
    """Import players from a DK draft group's draftables endpoint.

    Creates new players or updates existing ones (matched by dk_id).
    """
    try:
        draftables = await dk_api.get_draftables(draft_group_id)
    except Exception as exc:
        raise HTTPException(502, f"Failed to fetch DK draftables: {exc}")

    created = 0
    updated = 0
    errors: List[str] = []

    for raw in draftables:
        parsed = dk_api.parse_draftable(raw)
        dk_id = parsed.get("dk_id")
        if not dk_id:
            continue

        try:
            result = await db.execute(
                select(Player).where(Player.dk_id == dk_id)
            )
            existing = result.scalar_one_or_none()

            if existing:
                existing.dk_salary = parsed["dk_salary"]
                existing.position = parsed["position"] or existing.position
                existing.team = parsed["team"] or existing.team
                updated += 1
            else:
                player = Player(
                    name=parsed["name"],
                    team=parsed["team"],
                    position=parsed["position"] or "UTIL",
                    bats="R",  # Default; MLB Stats API enrichment updates this
                    throws="R",
                    dk_id=dk_id,
                    dk_salary=parsed["dk_salary"],
                )
                db.add(player)
                created += 1
        except Exception as exc:
            errors.append(f"Player dk_id={dk_id}: {exc}")

    await db.flush()
    logger.info(
        "DK player import (dg=%d): %d created, %d updated",
        draft_group_id,
        created,
        updated,
    )
    return ImportDKResult(created=created, updated=updated, errors=errors)
