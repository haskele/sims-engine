"""Recent starting lineup history from the MLB Stats API.

When today's lineup isn't posted yet, we use boxscore data from the past
N days to project likely starters.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT = 30
_BASE_URL = "https://statsapi.mlb.com"

# Semaphore to limit concurrent boxscore fetches.
_sem = asyncio.Semaphore(10)


@dataclass
class RecentStarter:
    mlb_id: int
    name: str
    team: str
    position: str
    games_started: int
    dates_started: list[str] = field(default_factory=list)


# Module-level cache keyed by (team_abbr, date_range_str) to avoid
# redundant fetches within the same pipeline run.
_cache: dict[tuple[str, str], list[RecentStarter]] = {}


async def _fetch_boxscore(client: httpx.AsyncClient, game_pk: int) -> dict[str, Any]:
    """Fetch live feed for a single game, respecting the semaphore."""
    async with _sem:
        url = f"{_BASE_URL}/api/v1.1/game/{game_pk}/feed/live"
        try:
            resp = await client.get(url, timeout=_TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.debug("Failed to fetch boxscore for game %d: %s", game_pk, exc)
            return {}


def _extract_starters(
    feed: dict[str, Any], team_abbr: str, game_date: str
) -> list[dict[str, Any]]:
    """Pull batting order starters from a live feed response for a given team."""
    boxscore = feed.get("liveData", {}).get("boxscore", {})
    game_data = feed.get("gameData", {})

    # Determine which side (home/away) matches our team
    home_abbr = game_data.get("teams", {}).get("home", {}).get("abbreviation", "")
    away_abbr = game_data.get("teams", {}).get("away", {}).get("abbreviation", "")

    if team_abbr.upper() == home_abbr.upper():
        side = "home"
    elif team_abbr.upper() == away_abbr.upper():
        side = "away"
    else:
        return []

    team_box = boxscore.get("teams", {}).get(side, {})
    batting_order = team_box.get("battingOrder", [])
    players_map = team_box.get("players", {})

    starters: list[dict[str, Any]] = []
    for mlb_id in batting_order:
        player_key = f"ID{mlb_id}"
        player_info = players_map.get(player_key, {})
        person = player_info.get("person", {})
        position = player_info.get("position", {})
        starters.append({
            "mlb_id": mlb_id,
            "name": person.get("fullName", "Unknown"),
            "position": position.get("abbreviation", ""),
            "date": game_date,
        })

    return starters


async def get_recent_starters(
    team_abbr: str,
    lookback_days: int = 3,
    as_of_date: str | None = None,
) -> list[RecentStarter]:
    """Get players who started for a team in the last N days.

    Parameters
    ----------
    team_abbr : str
        MLB team abbreviation (e.g. "NYY", "LAD").
    lookback_days : int
        Number of past days to check (default 3).
    as_of_date : str, optional
        Reference date in YYYY-MM-DD format. Defaults to today.

    Returns
    -------
    list[RecentStarter]
        Players sorted by games_started descending, then batting order.
    """
    if as_of_date:
        ref_date = date.fromisoformat(as_of_date)
    else:
        ref_date = date.today()

    # Build date range for cache key
    start_date = ref_date - timedelta(days=lookback_days)
    cache_key = (team_abbr.upper(), f"{start_date.isoformat()}_{ref_date.isoformat()}")
    if cache_key in _cache:
        logger.debug("Cache hit for %s", cache_key)
        return _cache[cache_key]

    # Fetch schedule for each lookback day and collect game_pks
    dates_to_check = [
        ref_date - timedelta(days=i) for i in range(1, lookback_days + 1)
    ]

    game_info: list[tuple[int, str]] = []  # (game_pk, date_str)

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        for check_date in dates_to_check:
            date_str = check_date.strftime("%Y-%m-%d")
            url = f"{_BASE_URL}/api/v1/schedule"
            params = {"sportId": 1, "date": date_str, "hydrate": "team"}
            try:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                schedule = resp.json()
            except Exception as exc:
                logger.warning("Schedule fetch failed for %s: %s", date_str, exc)
                continue

            for date_entry in schedule.get("dates", []):
                for game in date_entry.get("games", []):
                    home_abbr = (
                        game.get("teams", {})
                        .get("home", {})
                        .get("team", {})
                        .get("abbreviation", "")
                    )
                    away_abbr = (
                        game.get("teams", {})
                        .get("away", {})
                        .get("team", {})
                        .get("abbreviation", "")
                    )
                    if team_abbr.upper() in (home_abbr.upper(), away_abbr.upper()):
                        game_pk = game.get("gamePk")
                        if game_pk:
                            game_info.append((game_pk, date_str))

        # Fetch boxscores concurrently
        tasks = [_fetch_boxscore(client, gp) for gp, _ in game_info]
        feeds = await asyncio.gather(*tasks)

    # Aggregate starters across games
    player_starts: dict[int, dict[str, Any]] = {}  # mlb_id -> info

    for (_, game_date), feed in zip(game_info, feeds):
        if not feed:
            continue
        starters = _extract_starters(feed, team_abbr, game_date)
        for s in starters:
            mid = s["mlb_id"]
            if mid not in player_starts:
                player_starts[mid] = {
                    "mlb_id": mid,
                    "name": s["name"],
                    "position": s["position"],
                    "dates": [],
                }
            player_starts[mid]["dates"].append(game_date)

    # Build result
    result = [
        RecentStarter(
            mlb_id=info["mlb_id"],
            name=info["name"],
            team=team_abbr.upper(),
            position=info["position"],
            games_started=len(info["dates"]),
            dates_started=sorted(info["dates"]),
        )
        for info in player_starts.values()
    ]
    result.sort(key=lambda x: x.games_started, reverse=True)

    _cache[cache_key] = result
    logger.info(
        "Recent starters for %s (%d days back): %d players",
        team_abbr.upper(),
        lookback_days,
        len(result),
    )
    return result


async def get_recent_starters_bulk(
    team_abbrs: list[str],
    lookback_days: int = 3,
    as_of_date: str | None = None,
) -> dict[str, list[RecentStarter]]:
    """Batch version — returns {team_abbr: [RecentStarter, ...]}.

    Fetches all teams concurrently.
    """
    tasks = [
        get_recent_starters(abbr, lookback_days=lookback_days, as_of_date=as_of_date)
        for abbr in team_abbrs
    ]
    results = await asyncio.gather(*tasks)
    return {abbr.upper(): starters for abbr, starters in zip(team_abbrs, results)}
