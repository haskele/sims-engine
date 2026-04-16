"""DraftKings entries CSV parser and export builder.

Handles the CSV format that DK uses for entry download/upload:

Upload section (rows with Entry IDs):
  Entry ID, Contest Name, Contest ID, Entry Fee, SP, SP, C, 1B, 2B, 3B, SS, OF, OF, OF

Player pool section (rows after entries):
  Position, Name + ID, Name, ID, Roster Position, Salary, Game Info, TeamAbbrev, AvgPointsPerGame

Player slot format: "PlayerName (DK_ID)"
"""
from __future__ import annotations

import csv
import io
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

# DK Classic MLB roster slots (in order)
DK_ROSTER_SLOTS = ["SP", "SP", "C", "1B", "2B", "3B", "SS", "OF", "OF", "OF"]


@dataclass
class DKPlayer:
    """A player from the DK player pool."""
    dk_id: int
    name: str
    position: str            # DK position label (SP, RP, C, 1B, etc.)
    roster_position: str     # Eligible roster slot (P, C, 1B, etc.)
    salary: int
    game_info: str           # "AWAY@HOME MM/DD/YYYY HH:MMPM ET"
    team: str
    avg_points: float
    name_with_id: str        # "PlayerName (DK_ID)" format for export


@dataclass
class DKEntry:
    """A single contest entry."""
    entry_id: str
    contest_name: str
    contest_id: str
    entry_fee: str
    players: List[Dict[str, Any]]  # [{slot: "SP", name: str, dk_id: int}, ...]


@dataclass
class DKContestInfo:
    """Aggregated contest info from entries."""
    contest_id: str
    contest_name: str
    entry_fee: str           # raw string from CSV, e.g. "$15.00"
    entry_fee_numeric: float = 0.0  # parsed numeric value
    entry_count: int = 0
    entry_ids: List[str] = field(default_factory=list)
    # Enriched from DK API (populated after CSV parse)
    field_size: Optional[int] = None
    max_entries_per_user: Optional[int] = None
    prize_pool: Optional[float] = None
    payout_structure: Optional[List[Dict[str, Any]]] = None
    game_type: str = "classic"
    draft_group_id: Optional[int] = None


@dataclass
class DKEntriesData:
    """Parsed result from a DK entries CSV."""
    contests: List[DKContestInfo]
    entries: List[DKEntry]
    player_pool: List[DKPlayer]
    roster_slots: List[str]  # ordered slot names from the header


def _parse_entry_fee(raw: str) -> float:
    """Parse an entry fee string like '$15.00' into a float."""
    cleaned = raw.strip().replace("$", "").replace(",", "")
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return 0.0


def parse_player_slot(slot_value: str) -> Tuple[Optional[str], Optional[int]]:
    """Parse a DK lineup slot value like 'PlayerName (12345678)'.

    Returns (name, dk_id) or (None, None) if empty.
    """
    if not slot_value or not slot_value.strip():
        return None, None
    m = re.match(r"(.+?)\s*\((\d+)\)\s*$", slot_value.strip())
    if m:
        return m.group(1).strip(), int(m.group(2))
    return slot_value.strip(), None


_REQUIRED_HEADERS = {"entry id", "contest name", "contest id", "entry fee"}


def validate_dk_csv_header(header: List[str]) -> None:
    """Validate that the CSV header contains required DK entries columns.

    Raises ValueError with a descriptive message if validation fails.
    """
    if not header:
        raise ValueError("Empty CSV file")

    normalised = [h.strip().lower() for h in header]

    missing = _REQUIRED_HEADERS - set(normalised[:4])
    if missing:
        raise ValueError(
            f"Invalid CSV format — missing required columns: {', '.join(sorted(missing))}. "
            "Expected a DraftKings entries CSV with columns: Entry ID, Contest Name, Contest ID, Entry Fee, "
            "followed by roster position columns (SP, C, 1B, etc.)"
        )

    # Check for at least one roster slot column after Entry Fee
    roster_start = 4
    has_roster = False
    for i in range(roster_start, len(header)):
        val = header[i].strip()
        if val == "":
            break
        if val.upper() in ("SP", "RP", "P", "C", "1B", "2B", "3B", "SS", "OF", "UTIL"):
            has_roster = True
            break

    if not has_roster:
        raise ValueError(
            "Invalid CSV format — no roster position columns found after Entry Fee. "
            "Expected columns like SP, C, 1B, 2B, 3B, SS, OF after Entry Fee."
        )


def parse_dk_entries_csv(csv_content: str) -> Tuple[DKEntriesData, List[int]]:
    """Parse a DraftKings entries CSV file.

    The CSV has two sections:
    1. Entry rows: Entry ID, Contest Name, Contest ID, Entry Fee, then roster slots
    2. Player pool: starts after a row with blank Entry ID and Position header

    Returns:
        Tuple of (structured data, list of skipped row numbers).
        Skipped rows are those with incomplete data (missing Entry ID, Contest ID, etc.).
    """
    reader = csv.reader(io.StringIO(csv_content))

    # Read header
    header = next(reader, None)
    if not header:
        raise ValueError("Empty CSV file")

    # Validate header format
    validate_dk_csv_header(header)

    # Identify roster slot columns (after Entry Fee, before the empty column)
    # Header: Entry ID, Contest Name, Contest ID, Entry Fee, SP, SP, C, 1B, 2B, 3B, SS, OF, OF, OF, , Instructions, ...
    roster_start = 4  # slots start at column 4
    roster_end = roster_start
    for i in range(roster_start, len(header)):
        if header[i].strip() == "":
            break
        roster_end = i + 1

    roster_slots = [h.strip() for h in header[roster_start:roster_end]]
    logger.info("DK roster slots: %s", roster_slots)

    # Find the player pool header columns (they appear in the "Instructions" area)
    # The pool data is in columns starting after the empty separator column
    pool_col_start = roster_end + 1  # skip the empty separator column
    # Pool columns: Position, Name + ID, Name, ID, Roster Position, Salary, Game Info, TeamAbbrev, AvgPointsPerGame
    # But they might start at a different offset — we detect by looking for "Instructions" column

    entries: List[DKEntry] = []
    player_pool: List[DKPlayer] = []
    pool_header_found = False
    pool_col_offset = pool_col_start
    skipped_rows: List[int] = []
    row_num = 1  # header was row 1

    for row in reader:
        row_num += 1
        if len(row) < 4:
            continue

        entry_id = row[0].strip()
        # If entry_id is non-empty and numeric-ish, it's an entry row
        if entry_id and entry_id.isdigit():
            contest_name = row[1].strip() if len(row) > 1 else ""
            contest_id = row[2].strip() if len(row) > 2 else ""
            entry_fee = row[3].strip() if len(row) > 3 else ""

            # Validate required fields — skip incomplete rows
            if not contest_id or not contest_name:
                skipped_rows.append(row_num)
                _try_parse_pool_row(row, pool_col_offset, player_pool)
                continue

            players = []
            for i, slot in enumerate(roster_slots):
                col_idx = roster_start + i
                if col_idx < len(row):
                    name, dk_id = parse_player_slot(row[col_idx])
                    if name:
                        players.append({
                            "slot": slot,
                            "slot_index": i,
                            "name": name,
                            "dk_id": dk_id,
                        })
            entries.append(DKEntry(
                entry_id=entry_id,
                contest_name=contest_name,
                contest_id=contest_id,
                entry_fee=entry_fee,
                players=players,
            ))

            # Also check if this row has player pool data in the right-side columns
            _try_parse_pool_row(row, pool_col_offset, player_pool)

        elif not entry_id:
            # Blank entry ID — could be a pool-only row
            _try_parse_pool_row(row, pool_col_offset, player_pool)

    # Aggregate by contest
    contests_map: Dict[str, DKContestInfo] = {}
    for entry in entries:
        cid = entry.contest_id
        if cid not in contests_map:
            contests_map[cid] = DKContestInfo(
                contest_id=cid,
                contest_name=entry.contest_name,
                entry_fee=entry.entry_fee,
                entry_fee_numeric=_parse_entry_fee(entry.entry_fee),
                entry_count=0,
                entry_ids=[],
            )
        contests_map[cid].entry_count += 1
        contests_map[cid].entry_ids.append(entry.entry_id)

    logger.info(
        "Parsed DK entries: %d entries across %d contests, %d players in pool, %d skipped rows",
        len(entries), len(contests_map), len(player_pool), len(skipped_rows),
    )

    return (
        DKEntriesData(
            contests=list(contests_map.values()),
            entries=entries,
            player_pool=player_pool,
            roster_slots=roster_slots,
        ),
        skipped_rows,
    )


def _try_parse_pool_row(
    row: List[str],
    pool_col_offset: int,
    player_pool: List[DKPlayer],
):
    """Try to parse a player pool entry from the right-side columns of a row."""
    if len(row) <= pool_col_offset + 8:
        return

    position = row[pool_col_offset].strip() if pool_col_offset < len(row) else ""
    name_with_id = row[pool_col_offset + 1].strip() if pool_col_offset + 1 < len(row) else ""
    name = row[pool_col_offset + 2].strip() if pool_col_offset + 2 < len(row) else ""
    dk_id_str = row[pool_col_offset + 3].strip() if pool_col_offset + 3 < len(row) else ""
    roster_pos = row[pool_col_offset + 4].strip() if pool_col_offset + 4 < len(row) else ""
    salary_str = row[pool_col_offset + 5].strip() if pool_col_offset + 5 < len(row) else ""
    game_info = row[pool_col_offset + 6].strip() if pool_col_offset + 6 < len(row) else ""
    team = row[pool_col_offset + 7].strip() if pool_col_offset + 7 < len(row) else ""
    avg_str = row[pool_col_offset + 8].strip() if pool_col_offset + 8 < len(row) else ""

    # Validate — need at minimum a position, name, and dk_id
    if not position or not name or not dk_id_str:
        return
    if not dk_id_str.isdigit():
        return

    try:
        salary = int(salary_str) if salary_str else 0
        avg_pts = float(avg_str) if avg_str else 0.0
    except (ValueError, TypeError):
        return

    player_pool.append(DKPlayer(
        dk_id=int(dk_id_str),
        name=name,
        position=position,
        roster_position=roster_pos,
        salary=salary,
        game_info=game_info,
        team=team,
        avg_points=avg_pts,
        name_with_id=name_with_id,
    ))


def build_dk_id_lookup(player_pool: List[DKPlayer]) -> Dict[str, int]:
    """Build a name → dk_id lookup from the player pool.

    Uses lowercase name for matching.
    """
    lookup: Dict[str, int] = {}
    for p in player_pool:
        lookup[p.name.lower()] = p.dk_id
        # Also index by name_with_id format
        lookup[p.name_with_id.lower()] = p.dk_id
    return lookup


def build_export_csv(
    entries: List[DKEntry],
    lineups: List[List[Dict[str, Any]]],
    roster_slots: List[str],
    dk_id_lookup: Dict[str, int],
) -> str:
    """Build a DK-uploadable CSV from optimized lineups mapped to entry IDs.

    Args:
        entries: DK entries (provides entry IDs)
        lineups: Optimized lineups, each is a list of player dicts with
                 'player_name', 'position', 'dk_id' fields
        roster_slots: Ordered roster slot names (e.g. ["SP","SP","C","1B",...])
        dk_id_lookup: name → dk_id mapping from the player pool

    Returns CSV string ready for DK upload.
    """
    output = io.StringIO()
    writer = csv.writer(output)

    # Header: Entry ID, Contest Name, Contest ID, Entry Fee, then roster slots
    writer.writerow(["Entry ID", "Contest Name", "Contest ID", "Entry Fee"] + roster_slots)

    # Map each entry to a lineup
    for i, entry in enumerate(entries):
        lineup_idx = i % len(lineups) if lineups else 0
        lineup = lineups[lineup_idx] if lineups else []

        # Build slot assignments
        slot_values = _assign_players_to_slots(lineup, roster_slots, dk_id_lookup)

        writer.writerow([
            entry.entry_id,
            entry.contest_name,
            entry.contest_id,
            entry.entry_fee,
        ] + slot_values)

    return output.getvalue()


def _assign_players_to_slots(
    lineup: List[Dict[str, Any]],
    roster_slots: List[str],
    dk_id_lookup: Dict[str, int],
) -> List[str]:
    """Assign lineup players to DK roster slots in the correct format.

    Returns list of "PlayerName (DK_ID)" strings, one per slot.
    """
    # Build position groups from lineup
    # DK slots: SP, SP, C, 1B, 2B, 3B, SS, OF, OF, OF
    position_players: Dict[str, List[Dict[str, Any]]] = {}
    for player in lineup:
        pos = player.get("position", "UTIL")
        # Map positions to DK slot categories
        dk_slot = _position_to_dk_slot(pos)
        position_players.setdefault(dk_slot, []).append(player)

    # Fill slots in order
    used_players = set()
    slot_values = []
    for slot in roster_slots:
        assigned = False
        candidates = position_players.get(slot, [])
        for player in candidates:
            pid = id(player)
            if pid not in used_players:
                dk_id = player.get("dk_id") or dk_id_lookup.get(
                    player.get("player_name", "").lower()
                )
                if dk_id:
                    name = player.get("player_name", "Unknown")
                    slot_values.append(f"{name} ({dk_id})")
                    used_players.add(pid)
                    assigned = True
                    break
        if not assigned:
            slot_values.append("")

    return slot_values


def _position_to_dk_slot(position: str) -> str:
    """Map a player's position to the DK roster slot it fills."""
    pos = position.upper().strip()
    if pos in ("P", "SP", "RP"):
        return "SP"
    if pos in ("C", "1B", "2B", "3B", "SS"):
        return pos
    if pos in ("OF", "LF", "CF", "RF"):
        return "OF"
    # Multi-position: take first eligible
    parts = pos.split("/")
    for p in parts:
        p = p.strip()
        if p in ("C", "1B", "2B", "3B", "SS", "OF", "LF", "CF", "RF"):
            return "OF" if p in ("LF", "CF", "RF") else p
    return "UTIL"


_DK_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


async def enrich_contests_from_dk(contests: List[DKContestInfo]) -> None:
    """Fetch contest details from DK API and enrich parsed contests.

    Uses two sources:
    1. Contest detail API per contest (has full payout structure)
    2. Lobby API as fallback (has field size, prize pool, max entries)

    Modifies contests in place. Fails silently if API is unreachable.
    """
    if not contests:
        return

    async with httpx.AsyncClient(headers=_DK_HEADERS, timeout=15) as client:
        # Try the per-contest detail API first (works for started contests)
        for contest in contests:
            try:
                resp = await client.get(
                    f"https://api.draftkings.com/contests/v1/contests/{contest.contest_id}?format=json"
                )
                if resp.status_code == 200:
                    detail = resp.json().get("contestDetail", {})
                    _apply_contest_detail(contest, detail)
            except Exception as exc:
                logger.debug("Contest detail fetch failed for %s: %s", contest.contest_id, exc)

        # Fill gaps from lobby if needed
        missing = [c for c in contests if c.field_size is None]
        if missing:
            try:
                resp = await client.get(
                    "https://www.draftkings.com/lobby/getcontests?sport=MLB"
                )
                resp.raise_for_status()
                data = resp.json()
                lobby_map: Dict[str, dict] = {}
                for lc in data.get("Contests", []):
                    cid = str(lc.get("id", ""))
                    lobby_map[cid] = lc

                for contest in missing:
                    lc = lobby_map.get(contest.contest_id)
                    if lc:
                        _apply_lobby_contest(contest, lc)
            except Exception as exc:
                logger.debug("DK lobby fetch failed: %s", exc)

    enriched = sum(1 for c in contests if c.field_size is not None)
    logger.info("DK enrichment: enriched %d/%d contests", enriched, len(contests))


def _apply_contest_detail(contest: DKContestInfo, detail: dict) -> None:
    """Apply contest detail API data to a DKContestInfo."""
    # Direct fields from detail API
    if detail.get("maximumEntries"):
        contest.field_size = detail["maximumEntries"]
    if detail.get("maximumEntriesPerUser"):
        contest.max_entries_per_user = detail["maximumEntriesPerUser"]
    if detail.get("totalPayouts"):
        contest.prize_pool = detail["totalPayouts"]
    if detail.get("draftGroupId"):
        contest.draft_group_id = detail["draftGroupId"]
    gt = str(detail.get("gameTypeId", "")).lower()
    if gt in ("96",):
        contest.game_type = "showdown"

    # Parse payout summary
    payout_summary = detail.get("payoutSummary", [])
    if payout_summary:
        payouts = []
        for tier in payout_summary:
            # Extract numeric payout from descriptions
            payout_val = 0.0
            for desc in tier.get("payoutDescriptions", []):
                if desc.get("value"):
                    payout_val = desc["value"]
                    break
            payouts.append({
                "minPosition": tier.get("minPosition", 0),
                "maxPosition": tier.get("maxPosition", 0),
                "payout": payout_val,
            })
        contest.payout_structure = payouts


def _apply_lobby_contest(contest: DKContestInfo, lc: dict) -> None:
    """Apply lobby API data (minified keys) to a DKContestInfo."""
    # Lobby uses minified keys: m=field_size, a=entry_fee, po=prize_pool,
    # mec=max_entries, dg=draft_group_id, gameType=game_type
    if contest.field_size is None:
        contest.field_size = lc.get("m")
    if contest.prize_pool is None:
        contest.prize_pool = lc.get("po")
    if contest.max_entries_per_user is None:
        contest.max_entries_per_user = lc.get("mec")
    if contest.draft_group_id is None:
        contest.draft_group_id = lc.get("dg")
    gt = str(lc.get("gameType", "")).lower()
    if "showdown" in gt:
        contest.game_type = "showdown"
