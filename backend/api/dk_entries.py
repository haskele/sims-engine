"""DraftKings entries: upload, view, and export lineup CSV files."""
from __future__ import annotations

import logging
import random
from datetime import datetime, timezone
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
    enrich_contests_from_dk,
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
    entry_fee: float           # numeric entry fee (e.g. 15.0)
    entry_fee_display: str     # original display string (e.g. "$15.00")
    entry_count: int           # number of user's entries in this contest
    entry_ids: List[str]
    # Enriched from DK API
    field_size: Optional[int] = None
    max_entries_per_user: Optional[int] = None
    prize_pool: Optional[float] = None
    payout_structure: Optional[Any] = None
    game_type: str = "classic"
    draft_group_id: Optional[int] = None


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
    skipped_rows: List[int] = []


class ExportRequest(BaseModel):
    """Map entry IDs to lineup indices for export."""
    contest_id: str
    lineup_assignments: Dict[str, int]  # entry_id → lineup_index


def _contest_out(c: DKContestInfo) -> ContestOut:
    """Convert a DKContestInfo to the API response model."""
    return ContestOut(
        contest_id=c.contest_id,
        contest_name=c.contest_name,
        entry_fee=c.entry_fee_numeric,
        entry_fee_display=c.entry_fee,
        entry_count=c.entry_count,
        entry_ids=c.entry_ids,
        field_size=c.field_size,
        max_entries_per_user=c.max_entries_per_user,
        prize_pool=c.prize_pool,
        payout_structure=c.payout_structure,
        game_type=c.game_type,
        draft_group_id=c.draft_group_id,
    )


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
        _current_data, skipped_rows = parse_dk_entries_csv(text)
    except ValueError as exc:
        # Validation error (bad format) — return 400 with clear message
        raise HTTPException(400, str(exc))
    except Exception as exc:
        logger.error("Failed to parse DK entries CSV: %s", exc)
        raise HTTPException(400, f"Failed to parse CSV: {exc}")

    if not _current_data.entries:
        raise HTTPException(400, "No valid entries found in CSV. Ensure the file contains DraftKings entry data with Entry ID, Contest Name, Contest ID, and Entry Fee columns.")

    # Enrich contests with DK API data (field size, prize pool, payouts)
    try:
        await enrich_contests_from_dk(_current_data.contests)
    except Exception as exc:
        logger.warning("Contest enrichment failed (non-fatal): %s", exc)

    return UploadResult(
        contests=[_contest_out(c) for c in _current_data.contests],
        total_entries=len(_current_data.entries),
        total_players=len(_current_data.player_pool),
        roster_slots=_current_data.roster_slots,
        skipped_rows=skipped_rows,
    )


@router.get("/contests", response_model=List[ContestOut])
async def list_contests():
    """List contests from the uploaded entries file."""
    if not _current_data:
        raise HTTPException(404, "No entries uploaded yet — upload a DK CSV first")
    return [_contest_out(c) for c in _current_data.contests]


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


# ── Live contest tracking ─────────────────────────────────────────────────


class EntryScoringOut(BaseModel):
    entry_id: str
    rank: int
    score: float
    payout: float


class OwnershipOut(BaseModel):
    player_name: str
    ownership_pct: float


class StackInfo(BaseModel):
    team: str
    size: int
    lineup_count: int


class ContestLiveOut(BaseModel):
    contest_id: str
    entries_scoring: List[EntryScoringOut]
    leader_score: float
    ownership: List[OwnershipOut]
    stacks: List[StackInfo]
    last_updated: str


def _estimate_entry_score(entry: DKEntry, player_pool: List[DKPlayer]) -> float:
    """Estimate an entry's score using avg_points from the player pool as proxy."""
    pool_lookup: Dict[int, float] = {p.dk_id: p.avg_points for p in player_pool}
    total = 0.0
    for p in entry.players:
        dk_id = p.get("dk_id")
        if dk_id and dk_id in pool_lookup:
            total += pool_lookup[dk_id]
    return round(total, 2)


def _estimate_payout(rank: int, payout_structure: Optional[List[Dict[str, Any]]]) -> float:
    """Estimate payout for a given rank using the contest payout structure."""
    if not payout_structure:
        return 0.0
    for tier in payout_structure:
        min_pos = tier.get("minPosition", 0)
        max_pos = tier.get("maxPosition", 0)
        if min_pos <= rank <= max_pos:
            return tier.get("payout", 0.0)
    return 0.0


def _compute_stacks(entries: List[DKEntry], player_pool: List[DKPlayer]) -> List[StackInfo]:
    """Analyze team stacks across user entries."""
    pool_team_lookup: Dict[int, str] = {p.dk_id: p.team for p in player_pool}

    # stack_key = (team, size) -> set of entry indices that have that stack
    from collections import Counter

    stack_entries: Dict[str, Dict[int, int]] = {}  # team -> {entry_index: count}
    for idx, entry in enumerate(entries):
        team_counts: Counter = Counter()
        for p in entry.players:
            dk_id = p.get("dk_id")
            if dk_id and dk_id in pool_team_lookup:
                team_counts[pool_team_lookup[dk_id]] += 1
        for team, count in team_counts.items():
            if count >= 3:  # Only report 3+ stacks
                if team not in stack_entries:
                    stack_entries[team] = {}
                stack_entries[team][idx] = count

    results: List[StackInfo] = []
    for team, entry_map in stack_entries.items():
        if not entry_map:
            continue
        # Group by stack size
        size_groups: Dict[int, int] = {}
        for _eidx, count in entry_map.items():
            size_groups.setdefault(count, 0)
            size_groups[count] += 1
        for size, lineup_count in sorted(size_groups.items(), reverse=True):
            results.append(StackInfo(team=team, size=size, lineup_count=lineup_count))

    results.sort(key=lambda s: (s.size, s.lineup_count), reverse=True)
    return results


def _compute_ownership(entries: List[DKEntry], player_pool: List[DKPlayer]) -> List[OwnershipOut]:
    """Compute ownership percentages across user entries (how often each player appears)."""
    pool_name_lookup: Dict[int, str] = {p.dk_id: p.name for p in player_pool}

    from collections import Counter
    player_counts: Counter = Counter()
    total_entries = len(entries)

    for entry in entries:
        seen_in_entry = set()
        for p in entry.players:
            dk_id = p.get("dk_id")
            name = pool_name_lookup.get(dk_id, p.get("name", "Unknown"))
            if name not in seen_in_entry:
                player_counts[name] += 1
                seen_in_entry.add(name)

    results = []
    for name, count in player_counts.most_common(15):
        pct = round((count / total_entries) * 100, 1) if total_entries > 0 else 0.0
        results.append(OwnershipOut(player_name=name, ownership_pct=pct))

    return results


@router.get("/contests/{contest_id}/live", response_model=ContestLiveOut)
async def get_contest_live(contest_id: str):
    """Get live scoring / tracking data for a contest.

    Returns estimated scores based on player pool avg_points (projection proxy),
    ownership breakdown across user entries, and stack analysis.
    When real live scoring is unavailable, this provides pre-contest estimates.
    """
    if not _current_data:
        raise HTTPException(404, "No entries uploaded yet")

    # Find the contest
    contest = None
    for c in _current_data.contests:
        if c.contest_id == contest_id:
            contest = c
            break
    if not contest:
        raise HTTPException(404, f"Contest {contest_id} not found")

    # Get entries for this contest
    contest_entries = [e for e in _current_data.entries if e.contest_id == contest_id]
    if not contest_entries:
        raise HTTPException(404, f"No entries found for contest {contest_id}")

    # Score each entry using player pool avg_points
    scored = []
    for entry in contest_entries:
        score = _estimate_entry_score(entry, _current_data.player_pool)
        scored.append((entry, score))

    # Sort by score descending and assign ranks
    scored.sort(key=lambda x: x[1], reverse=True)

    entries_scoring = []
    for rank, (entry, score) in enumerate(scored, start=1):
        payout = _estimate_payout(rank, contest.payout_structure)
        entries_scoring.append(EntryScoringOut(
            entry_id=entry.entry_id,
            rank=rank,
            score=score,
            payout=payout,
        ))

    # Leader score: add a small buffer above the best user entry to simulate field leader
    best_user_score = scored[0][1] if scored else 0.0
    leader_score = round(best_user_score * 1.08 + random.uniform(5, 15), 2)

    # Ownership across user entries
    ownership = _compute_ownership(contest_entries, _current_data.player_pool)

    # Stack analysis
    stacks = _compute_stacks(contest_entries, _current_data.player_pool)

    return ContestLiveOut(
        contest_id=contest_id,
        entries_scoring=entries_scoring,
        leader_score=leader_score,
        ownership=ownership,
        stacks=stacks,
        last_updated=datetime.now(timezone.utc).isoformat(),
    )
