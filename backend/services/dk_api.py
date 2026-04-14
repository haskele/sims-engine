"""DraftKings API client.

All endpoints are public/read-only and require no authentication.
"""
from __future__ import annotations

import csv
import io
import logging
from typing import Any

import httpx

from config import settings

logger = logging.getLogger(__name__)

# DraftKings uses browser-like headers; without them some endpoints return 403.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


async def get_mlb_contests() -> list[dict[str, Any]]:
    """Fetch the current MLB contest lobby from DraftKings.

    Returns a list of contest dicts with keys like ContestId, ContestName,
    EntryFee, MaximumEntries, MaxNumberPlayers, TotalPayouts,
    DraftGroupId, GameType, etc.
    """
    async with httpx.AsyncClient(headers=_HEADERS, timeout=30) as client:
        resp = await client.get(settings.dk_contests_url)
        resp.raise_for_status()
        data = resp.json()
    contests = data.get("Contests", [])
    draft_groups = {dg["DraftGroupId"]: dg for dg in data.get("DraftGroups", [])}
    # Attach draft-group metadata to each contest for convenience
    for c in contests:
        dg = draft_groups.get(c.get("DraftGroupId"))
        if dg:
            c["_draftGroup"] = dg
    logger.info("Fetched %d DK MLB contests", len(contests))
    return contests


async def get_draft_group(draft_group_id: int) -> dict[str, Any]:
    """Fetch metadata for a specific draft group."""
    url = f"{settings.dk_draftgroups_url}{draft_group_id}"
    async with httpx.AsyncClient(headers=_HEADERS, timeout=30) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()


async def get_draftables(draft_group_id: int) -> list[dict[str, Any]]:
    """Fetch the draftable players JSON for a draft group.

    Each item contains playerId, salary, position, names, team info, etc.
    """
    url = settings.dk_draftables_url.format(draft_group_id=draft_group_id)
    async with httpx.AsyncClient(headers=_HEADERS, timeout=30) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()
    draftables = data.get("draftables", [])
    logger.info(
        "Fetched %d draftables for draft group %d", len(draftables), draft_group_id
    )
    return draftables


async def get_salaries_csv(draft_group_id: int) -> list[dict[str, str]]:
    """Download the player salary CSV and return rows as dicts.

    Columns typically: Position, Name+ID, Name, ID, Roster Position,
    Salary, Game Info, TeamAbbrev, AvgPointsPerGame.
    """
    url = settings.dk_salaries_csv_url.format(draft_group_id=draft_group_id)
    async with httpx.AsyncClient(headers=_HEADERS, timeout=30) as client:
        resp = await client.get(url)
        resp.raise_for_status()
    reader = csv.DictReader(io.StringIO(resp.text))
    rows = list(reader)
    logger.info(
        "Fetched %d salary rows for draft group %d", len(rows), draft_group_id
    )
    return rows


def parse_contest(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalise a raw DK contest dict into our Contest model fields."""
    payout_raw = raw.get("PayoutSummaries") or raw.get("PayoutStructure") or []
    return {
        "site": "dk",
        "external_id": str(raw.get("ContestId", "")),
        "name": raw.get("ContestName", raw.get("n", "")),
        "entry_fee": raw.get("EntryFee", 0),
        "max_entries": raw.get("MaximumEntries", 1),
        "field_size": raw.get("MaxNumberPlayers", 0),
        "prize_pool": raw.get("TotalPayouts", 0),
        "payout_structure": payout_raw,
        "game_type": _game_type(raw.get("GameType", "")),
        "draft_group_id": raw.get("DraftGroupId"),
    }


def parse_draftable(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalise a raw draftable dict into Player-ish fields."""
    return {
        "dk_id": raw.get("playerId"),
        "name": raw.get("displayName", ""),
        "team": raw.get("teamAbbreviation", ""),
        "position": raw.get("position", ""),
        "dk_salary": raw.get("salary", 0),
    }


def _game_type(gt: str | int) -> str:
    gt_str = str(gt).lower()
    if "showdown" in gt_str or gt_str == "96":
        return "showdown"
    return "classic"
