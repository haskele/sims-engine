"""DraftKings entries: upload, view, and export lineup CSV files."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, UploadFile, File, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from services.dk_entries import (
    DKContestInfo,
    DKEntry,
    DKEntriesData,
    DKPlayer,
    build_dk_id_lookup,
    build_export_csv,
    parse_dk_entries_csv,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/dk-entries", tags=["dk-entries"])

# In-memory store for the most recently uploaded entries data.
# This is session-scoped (single user tool) — no need for database persistence.
_current_data: Optional[DKEntriesData] = None


# ── Pydantic response schemas ─────────────────────────────────────────────


class ContestOut(BaseModel):
    contest_id: str
    contest_name: str
    entry_fee: str
    entry_count: int
    entry_ids: List[str]


class EntryOut(BaseModel):
    entry_id: str
    contest_name: str
    contest_id: str
    entry_fee: str
    players: List[Dict[str, Any]]


class PlayerPoolOut(BaseModel):
    dk_id: int
    name: str
    position: str
    roster_position: str
    salary: int
    team: str
    game_info: str
    avg_points: float


class UploadResult(BaseModel):
    contests: List[ContestOut]
    total_entries: int
    total_players: int
    roster_slots: List[str]


class ExportRequest(BaseModel):
    """Map entry IDs to lineup indices for export."""
    contest_id: str
    lineup_assignments: Dict[str, int]  # entry_id → lineup_index


# ── Endpoints ──────────────────────────────────────────────────────────────


@router.post("/upload", response_model=UploadResult)
async def upload_dk_entries(file: UploadFile = File(...)):
    """Upload a DraftKings entries CSV file.

    Parses the file and stores it in memory for the session.
    Returns contest info, entry counts, and player pool stats.
    """
    global _current_data

    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(400, "File must be a CSV")

    content = await file.read()
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("latin-1")

    try:
        _current_data = parse_dk_entries_csv(text)
    except Exception as exc:
        logger.error("Failed to parse DK entries CSV: %s", exc)
        raise HTTPException(400, f"Failed to parse CSV: {exc}")

    return UploadResult(
        contests=[
            ContestOut(
                contest_id=c.contest_id,
                contest_name=c.contest_name,
                entry_fee=c.entry_fee,
                entry_count=c.entry_count,
                entry_ids=c.entry_ids,
            )
            for c in _current_data.contests
        ],
        total_entries=len(_current_data.entries),
        total_players=len(_current_data.player_pool),
        roster_slots=_current_data.roster_slots,
    )


@router.get("/contests", response_model=List[ContestOut])
async def list_contests():
    """List contests from the uploaded entries file."""
    if not _current_data:
        raise HTTPException(404, "No entries uploaded yet — upload a DK CSV first")
    return [
        ContestOut(
            contest_id=c.contest_id,
            contest_name=c.contest_name,
            entry_fee=c.entry_fee,
            entry_count=c.entry_count,
            entry_ids=c.entry_ids,
        )
        for c in _current_data.contests
    ]


@router.get("/entries", response_model=List[EntryOut])
async def list_entries(
    contest_id: Optional[str] = Query(None, description="Filter by contest ID"),
):
    """List all entries, optionally filtered by contest."""
    if not _current_data:
        raise HTTPException(404, "No entries uploaded yet")

    entries = _current_data.entries
    if contest_id:
        entries = [e for e in entries if e.contest_id == contest_id]

    return [
        EntryOut(
            entry_id=e.entry_id,
            contest_name=e.contest_name,
            contest_id=e.contest_id,
            entry_fee=e.entry_fee,
            players=e.players,
        )
        for e in entries
    ]


@router.get("/player-pool", response_model=List[PlayerPoolOut])
async def get_player_pool():
    """Get the DK player pool from the uploaded entries file.

    This provides the DK IDs needed for lineup export.
    """
    if not _current_data:
        raise HTTPException(404, "No entries uploaded yet")

    return [
        PlayerPoolOut(
            dk_id=p.dk_id,
            name=p.name,
            position=p.position,
            roster_position=p.roster_position,
            salary=p.salary,
            team=p.team,
            game_info=p.game_info,
            avg_points=p.avg_points,
        )
        for p in _current_data.player_pool
    ]


@router.post("/export")
async def export_lineups(
    lineups: List[List[Dict[str, Any]]],
    contest_id: Optional[str] = Query(None),
):
    """Export optimized lineups as a DK-uploadable CSV.

    Accepts an array of lineups (each lineup is an array of player dicts
    with player_name, position, and optionally dk_id). Maps them to the
    uploaded entry IDs.

    Each player dict should have at minimum:
      - player_name: str
      - position: str (e.g. "P", "SP", "C", "1B", "OF")

    If dk_id is not provided, it will be looked up from the player pool.
    """
    if not _current_data:
        raise HTTPException(404, "No entries uploaded yet — upload a DK CSV first")

    if not lineups:
        raise HTTPException(400, "No lineups provided")

    # Filter entries by contest if specified
    entries = _current_data.entries
    if contest_id:
        entries = [e for e in entries if e.contest_id == contest_id]

    if not entries:
        raise HTTPException(404, f"No entries found for contest {contest_id}")

    dk_id_lookup = build_dk_id_lookup(_current_data.player_pool)
    csv_text = build_export_csv(
        entries=entries,
        lineups=lineups,
        roster_slots=_current_data.roster_slots,
        dk_id_lookup=dk_id_lookup,
    )

    return PlainTextResponse(
        csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=DKLineups.csv"},
    )


@router.get("/status")
async def entries_status():
    """Check if entries have been uploaded and return summary."""
    if not _current_data:
        return {
            "uploaded": False,
            "contests": 0,
            "entries": 0,
            "players": 0,
        }
    return {
        "uploaded": True,
        "contests": len(_current_data.contests),
        "entries": len(_current_data.entries),
        "players": len(_current_data.player_pool),
        "roster_slots": _current_data.roster_slots,
    }
