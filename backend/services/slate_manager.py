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

        # Parse start time — prefer StartDateEst (Eastern) over StartDate (UTC)
        start_time_raw = dg.get("StartDateEst") or dg.get("StartDate")
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

        # Filter to target date using StartDateEst
        draft_group_date = None
        if start_time:
            try:
                clean = start_time.split(".")[0]  # strip .0000000 suffix
                dt = datetime.fromisoformat(clean.replace("Z", "+00:00"))
                draft_group_date = dt.date()
            except (ValueError, TypeError):
                pass

        if target_date and draft_group_date and draft_group_date != target_date:
            continue

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

        # Build a readable name with ET start time
        tag = dg.get("DraftGroupTag", "")
        suffix = dg.get("ContestStartTimeSuffix", "") or ""
        if suffix == "None":
            suffix = ""

        # Format start time as "H:MM PM ET"
        time_label = ""
        if start_time:
            try:
                clean = start_time.split(".")[0]
                dt_parsed = datetime.fromisoformat(clean)
                hour = dt_parsed.hour
                minute = dt_parsed.minute
                ampm = "AM" if hour < 12 else "PM"
                display_hour = hour % 12 or 12
                time_label = f"{display_hour}:{minute:02d} {ampm} ET"
            except (ValueError, TypeError):
                pass

        name_parts = []
        if game_count > 0:
            name_parts.append(f"{game_count}-Game")
        if suffix.strip():
            name_parts.append(suffix.strip())
        elif tag:
            name_parts.append(tag)
        if time_label:
            name_parts.append(f"({time_label})")
        slate_name = " ".join(name_parts) if name_parts else f"DG-{dg_id}"

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

# Canonical map and normalizer live in services.constants; re-exported here
# for backward compatibility with existing importers (e.g. daily_pipeline).
from services.constants import DK_TEAM_ALIAS as DK_TO_MLB_TEAM  # noqa: E402
from services.constants import normalise_dk_team  # noqa: E402, F401
