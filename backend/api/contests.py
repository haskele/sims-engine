"""Contest CRUD and import endpoints."""
from __future__ import annotations

import json
import logging
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.contest import Contest
from services import dk_api, fd_api

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/contests", tags=["contests"])


# ── Pydantic schemas ────────────────────────────────────────────────────────


class ContestOut(BaseModel):
    id: int
    site: str
    external_id: Optional[str] = None
    name: str
    entry_fee: float
    max_entries: int
    field_size: int
    prize_pool: float
    payout_structure: Any = None
    game_type: str
    slate_id: Optional[str] = None
    draft_group_id: Optional[int] = None

    model_config = {"from_attributes": True}


class ContestCreate(BaseModel):
    site: str = Field(..., pattern="^(dk|fd)$")
    external_id: Optional[str] = None
    name: str
    entry_fee: float = 0
    max_entries: int = 1
    field_size: int
    prize_pool: float = 0
    payout_structure: Any = None
    game_type: str = "classic"
    slate_id: Optional[str] = None
    slate_games: Any = None
    draft_group_id: Optional[int] = None


class ImportResult(BaseModel):
    imported: int
    skipped: int
    errors: List[str] = []


# ── Endpoints ───────────────────────────────────────────────────────────────


@router.get("/", response_model=List[ContestOut])
async def list_contests(
    site: Optional[str] = Query(None, pattern="^(dk|fd)$"),
    db: AsyncSession = Depends(get_db),
):
    """List all stored contests, optionally filtered by site."""
    stmt = select(Contest).order_by(Contest.created_at.desc())
    if site:
        stmt = stmt.where(Contest.site == site)
    result = await db.execute(stmt)
    rows = result.scalars().all()
    out = []
    for r in rows:
        d = ContestOut.model_validate(r)
        if r.payout_structure:
            try:
                d.payout_structure = json.loads(r.payout_structure)
            except (json.JSONDecodeError, TypeError):
                d.payout_structure = r.payout_structure
        out.append(d)
    return out


@router.get("/{contest_id}", response_model=ContestOut)
async def get_contest(contest_id: int, db: AsyncSession = Depends(get_db)):
    """Get a single contest by ID."""
    result = await db.execute(select(Contest).where(Contest.id == contest_id))
    contest = result.scalar_one_or_none()
    if not contest:
        raise HTTPException(404, "Contest not found")
    out = ContestOut.model_validate(contest)
    if contest.payout_structure:
        try:
            out.payout_structure = json.loads(contest.payout_structure)
        except (json.JSONDecodeError, TypeError):
            pass
    return out


@router.post("/", response_model=ContestOut, status_code=201)
async def create_contest(body: ContestCreate, db: AsyncSession = Depends(get_db)):
    """Manually create a contest."""
    payout_json = (
        json.dumps(body.payout_structure) if body.payout_structure else None
    )
    slate_json = json.dumps(body.slate_games) if body.slate_games else None
    contest = Contest(
        site=body.site,
        external_id=body.external_id,
        name=body.name,
        entry_fee=body.entry_fee,
        max_entries=body.max_entries,
        field_size=body.field_size,
        prize_pool=body.prize_pool,
        payout_structure=payout_json,
        game_type=body.game_type,
        slate_id=body.slate_id,
        slate_games=slate_json,
        draft_group_id=body.draft_group_id,
    )
    db.add(contest)
    await db.flush()
    await db.refresh(contest)
    return ContestOut.model_validate(contest)


@router.post("/import/dk", response_model=ImportResult)
async def import_dk_contests(db: AsyncSession = Depends(get_db)):
    """Fetch current DK MLB contests and import them into the database."""
    try:
        raw_contests = await dk_api.get_mlb_contests()
    except Exception as exc:
        raise HTTPException(502, f"Failed to fetch DK contests: {exc}")

    imported = 0
    skipped = 0
    errors: List[str] = []

    for raw in raw_contests:
        parsed = dk_api.parse_contest(raw)
        ext_id = parsed["external_id"]

        # Check for duplicates
        existing = await db.execute(
            select(Contest).where(Contest.external_id == ext_id)
        )
        if existing.scalar_one_or_none():
            skipped += 1
            continue

        try:
            contest = Contest(
                site=parsed["site"],
                external_id=ext_id,
                name=parsed["name"],
                entry_fee=parsed["entry_fee"],
                max_entries=parsed["max_entries"],
                field_size=parsed["field_size"],
                prize_pool=parsed["prize_pool"],
                payout_structure=json.dumps(parsed["payout_structure"]),
                game_type=parsed["game_type"],
                draft_group_id=parsed.get("draft_group_id"),
            )
            db.add(contest)
            imported += 1
        except Exception as exc:
            errors.append(f"Contest {ext_id}: {exc}")

    await db.flush()
    logger.info("DK contest import: %d imported, %d skipped", imported, skipped)
    return ImportResult(imported=imported, skipped=skipped, errors=errors)


@router.delete("/{contest_id}", status_code=204)
async def delete_contest(contest_id: int, db: AsyncSession = Depends(get_db)):
    """Delete a contest."""
    result = await db.execute(select(Contest).where(Contest.id == contest_id))
    contest = result.scalar_one_or_none()
    if not contest:
        raise HTTPException(404, "Contest not found")
    await db.delete(contest)
