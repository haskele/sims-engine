"""Slate-aware data pipeline: fetches DK/FD slates and maps games.

DraftKings exposes draft groups (slates) via a public JSON API.
FanDuel requires auth, so we provide a stub interface.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional

import httpx

from config import settings

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


# ── Pydantic-free data classes (plain dicts) ─────────────────────────────────


def _make_slate(
    *,
    slate_id: str,
    site: str,
    draft_group_id: int,
    name: str,
    game_count: int,
    start_time: Optional[str],
    game_type: str,
    games: List[Dict[str, Any]],
    sport: str = "MLB",
) -> Dict[str, Any]:
    """Build a normalised slate dict."""
    return {
        "slate_id": slate_id,
        "site": site,
        "draft_group_id": draft_group_id,
        "name": name,
        "game_count": game_count,
        "start_time": start_time,
        "game_type": game_type,
        "games": games,
        "sport": sport,
    }


# ── DraftKings slate fetcher ─────────────────────────────────────────────────


async def fetch_dk_slates(target_date: Optional[date] = None) -> List[Dict[str, Any]]:
    """Fetch all MLB draft groups (slates) from DraftKings for a given date.

    Uses the public contests lobby endpoint which returns DraftGroups alongside
    contests.  Each DraftGroup is a slate.

    Returns a list of normalised slate dicts.
    """
    if target_date is None:
        target_date = date.today()

    slates: List[Dict[str, Any]] = []

    try:
        async with httpx.AsyncClient(headers=_HEADERS, timeout=30) as client:
            # Fetch the MLB lobby which includes DraftGroups
            resp = await client.get(settings.dk_contests_url)
            resp.raise_for_status()
            lobby = resp.json()
    except Exception as exc:
        logger.error("Failed to fetch DK contests lobby: %s", exc)
        return slates

    draft_groups = lobby.get("DraftGroups", [])
    logger.info("Found %d DK draft groups in lobby", len(draft_groups))

    for dg in draft_groups:
        dg_id = dg.get("DraftGroupId")
        if not dg_id:
            continue

        # Filter to MLB (sport ID 2 for MLB on DK)
        sport_id = dg.get("SportId")
        # Also accept by sport sort order or contest type label
        sport = dg.get("Sport", "")
        if sport_id not in (None, 2) and "MLB" not in str(sport).upper():
            # Try to infer from contest type
            ct = str(dg.get("ContestTypeId", ""))
            game_type_str = str(dg.get("GameTypeId", ""))
            if sport_id not in (2,):
                continue

        # Parse start time
        start_time_raw = dg.get("StartDate") or dg.get("StartDateEst")
        start_time = None
        if start_time_raw:
            try:
                # DK returns .NET-style dates or ISO strings
                if "/Date(" in str(start_time_raw):
                    ms = int(re.search(r"\d+", str(start_time_raw)).group())
                    dt = datetime.utcfromtimestamp(ms / 1000)
                    start_time = dt.isoformat()
                else:
                    start_time = str(start_time_raw)
            except Exception:
                start_time = str(start_time_raw)

        # Check if this slate is for the target date
        # DK draft groups have StartDateEst or we can check games
        draft_group_date = None
        if start_time:
            try:
                dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
                draft_group_date = dt.date()
            except (ValueError, TypeError):
                pass

        # Get detailed info about this draft group (games list)
        games_in_slate: List[Dict[str, Any]] = []
        game_count = dg.get("GameCount", 0)

        # Determine game type and skip non-classic/non-showdown slates
        game_type_id = dg.get("GameTypeId", 1)
        game_type = "classic"
        dg_name = dg.get("ContestStartTimeSuffix", "") or dg.get("DraftGroupTag", "") or ""
        dg_name_lower = dg_name.lower()
        # Showdown / Captain mode (GameTypeId 114 for single-game)
        if game_type_id == 114 or "showdown" in dg_name_lower or "captain" in dg_name_lower:
            game_type = "showdown"
        # Skip non-classic/non-showdown types:
        #   45 = Tiers, 178/179 = Snake, 346 = Home Runs, etc.
        # Also filter by name patterns
        non_classic_patterns = ("pick", "snake", "tier", "best ball", "bestball", "arcade", "flash", "home run")
        if any(p in dg_name_lower for p in non_classic_patterns):
            logger.debug("Skipping non-classic slate: %s (name=%s)", dg_id, dg_name)
            continue
        # GameTypeId 2 = Classic, 114 = Showdown; skip all others
        if game_type_id not in (2, 114):
            logger.debug("Skipping slate with GameTypeId=%s: %s", game_type_id, dg_name)
            continue

        # Build a readable name
        name_parts = []
        tag = dg.get("DraftGroupTag", "")
        suffix = dg.get("ContestStartTimeSuffix", "")
        if tag:
            name_parts.append(tag)
        if suffix:
            name_parts.append(suffix)
        if not name_parts:
            name_parts.append(f"DG-{dg_id}")
        slate_name = " ".join(name_parts)

        slates.append(
            _make_slate(
                slate_id=str(dg_id),
                site="dk",
                draft_group_id=dg_id,
                name=slate_name,
                game_count=game_count,
                start_time=start_time,
                game_type=game_type,
                games=games_in_slate,
            )
        )

    logger.info("Parsed %d DK MLB slates", len(slates))
    return slates


async def fetch_dk_slate_details(draft_group_id: int) -> Dict[str, Any]:
    """Fetch full details for a single DK draft group including games list.

    Calls the draftgroups v1 API and the draftables API to get both the
    games on the slate and all player salaries.
    """
    result: Dict[str, Any] = {
        "draft_group_id": draft_group_id,
        "games": [],
        "draftables": [],
    }

    try:
        async with httpx.AsyncClient(headers=_HEADERS, timeout=30) as client:
            # Draft group metadata (includes games)
            url = f"{settings.dk_draftgroups_url}{draft_group_id}"
            resp = await client.get(url)
            resp.raise_for_status()
            dg_data = resp.json()

            # Extract games
            dg_info = dg_data.get("draftGroup", dg_data)
            games_raw = dg_info.get("games", [])
            for g in games_raw:
                game_info: Dict[str, Any] = {
                    "game_pk": g.get("gameId"),
                    "home_team": g.get("homeTeamAbbreviation", g.get("homeTeam", "")),
                    "away_team": g.get("awayTeamAbbreviation", g.get("awayTeam", "")),
                    "start_time": g.get("startDate") or g.get("gameStartTime"),
                    "description": g.get("description", ""),
                }
                result["games"].append(game_info)

            # Draftables (player salaries)
            draftables_url = settings.dk_draftables_url.format(
                draft_group_id=draft_group_id
            )
            resp2 = await client.get(draftables_url)
            resp2.raise_for_status()
            draftables_data = resp2.json()
            result["draftables"] = draftables_data.get("draftables", [])

    except Exception as exc:
        logger.error(
            "Failed to fetch DK slate details for DG %d: %s",
            draft_group_id,
            exc,
        )

    logger.info(
        "DK slate DG-%d: %d games, %d draftables",
        draft_group_id,
        len(result["games"]),
        len(result["draftables"]),
    )
    return result


def identify_featured_slate(slates: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Pick the "main" / "featured" slate from a list.

    Heuristic priority:
    1. Slate whose name contains "Main" (case-insensitive)
    2. Slate whose name contains "All Day"
    3. Classic game type with the most games
    """
    if not slates:
        return None

    # Filter to classic only
    classic = [s for s in slates if s["game_type"] == "classic"]
    if not classic:
        classic = slates

    for s in classic:
        name_lower = s["name"].lower()
        if "main" in name_lower:
            return s

    for s in classic:
        name_lower = s["name"].lower()
        if "all day" in name_lower or "all-day" in name_lower:
            return s

    # Fallback: most games
    return max(classic, key=lambda s: s["game_count"])


# ── FanDuel slate fetcher (stub) ─────────────────────────────────────────────


async def fetch_fd_slates(target_date: Optional[date] = None) -> List[Dict[str, Any]]:
    """Fetch FanDuel MLB slates.

    FanDuel requires authentication.  This is a stub that returns an empty
    list.  To implement:
    1. Obtain session cookies via Playwright or manual export.
    2. Hit ``https://api.fanduel.com/fixture-lists?sport=MLB`` with auth.
    3. Parse fixture lists into normalised slate dicts.
    """
    logger.warning("FanDuel slate fetch is not yet implemented (needs auth)")
    return []


# ── Team abbreviation mapping ────────────────────────────────────────────────

# DK sometimes uses slightly different abbreviations than MLB Stats API.
# This map converts DK team abbrevs to standard MLB ones.
DK_TO_MLB_TEAM: Dict[str, str] = {
    "ARI": "ARI", "AZ": "ARI",
    "ATL": "ATL",
    "BAL": "BAL",
    "BOS": "BOS",
    "CHC": "CHC", "CHI": "CHC",
    "CWS": "CWS",
    "CIN": "CIN",
    "CLE": "CLE",
    "COL": "COL",
    "DET": "DET",
    "HOU": "HOU",
    "KC": "KC",
    "LAA": "LAA",
    "LAD": "LAD", "LA": "LAD",
    "MIA": "MIA",
    "MIL": "MIL",
    "MIN": "MIN",
    "NYM": "NYM",
    "NYY": "NYY",
    "OAK": "OAK", "A'S": "OAK",
    "PHI": "PHI",
    "PIT": "PIT",
    "SD": "SD",
    "SF": "SF", "SFG": "SF",
    "SEA": "SEA",
    "STL": "STL",
    "TB": "TB",
    "TEX": "TEX",
    "TOR": "TOR",
    "WSH": "WSH", "WAS": "WSH",
}


def normalise_dk_team(abbr: str) -> str:
    """Convert a DK team abbreviation to the standard MLB abbreviation."""
    return DK_TO_MLB_TEAM.get(abbr.upper(), abbr.upper())
