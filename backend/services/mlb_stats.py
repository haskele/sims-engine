"""MLB Stats API client.

All endpoints are free and require no API key.
Docs: https://statsapi.mlb.com
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

import httpx

from config import settings

logger = logging.getLogger(__name__)

_TIMEOUT = 30


async def get_schedule(
    game_date: date | None = None,
    hydrate: str = "probablePitcher,lineups,weather,team",
) -> dict[str, Any]:
    """Fetch MLB schedule for a date, with optional hydration.

    Parameters
    ----------
    game_date : date, optional
        Defaults to today.
    hydrate : str
        Comma-separated list of hydration targets.

    Returns
    -------
    dict
        Full JSON response from the MLB schedule endpoint.
    """
    if game_date is None:
        game_date = date.today()
    params: dict[str, Any] = {
        "sportId": 1,
        "date": game_date.strftime("%Y-%m-%d"),
    }
    if hydrate:
        params["hydrate"] = hydrate
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(settings.mlb_schedule_url, params=params)
        resp.raise_for_status()
        data = resp.json()
    total = data.get("totalGames", 0)
    logger.info("MLB schedule for %s: %d games", game_date.isoformat(), total)
    return data


async def get_player_season_stats(
    player_id: int, season: int = 2026, group: str = "hitting"
) -> dict[str, Any]:
    """Get aggregated season stats for a player.

    Parameters
    ----------
    player_id : int
        MLB person ID.
    season : int
        Season year.
    group : str
        'hitting' or 'pitching'.
    """
    url = f"{settings.mlb_people_url}/{player_id}/stats"
    params = {"stats": "season", "season": season, "group": group}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()


async def get_player_game_log(
    player_id: int, season: int = 2026, group: str = "hitting"
) -> list[dict[str, Any]]:
    """Get per-game stats for a player in a season.

    Returns the ``splits`` list from the first stat group found.
    """
    url = f"{settings.mlb_people_url}/{player_id}/stats"
    params = {"stats": "gameLog", "season": season, "group": group}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
    for stat_block in data.get("stats", []):
        splits = stat_block.get("splits", [])
        if splits:
            logger.info(
                "Game log for player %d: %d entries", player_id, len(splits)
            )
            return splits
    return []


async def get_player_info(player_id: int) -> dict[str, Any]:
    """Fetch basic biographical/roster info for a player."""
    url = f"{settings.mlb_people_url}/{player_id}"
    params = {"hydrate": "currentTeam"}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
    people = data.get("people", [])
    return people[0] if people else {}


async def get_team_roster(team_id: int, season: int = 2026) -> list[dict[str, Any]]:
    """Fetch active roster for a team.

    Returns list of player dicts with id, fullName, primaryPosition, batSide,
    pitchHand, etc.
    """
    url = f"https://statsapi.mlb.com/api/v1/teams/{team_id}/roster"
    params = {"rosterType": "active", "season": season}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
    roster = data.get("roster", [])
    result: list[dict[str, Any]] = []
    for entry in roster:
        person = entry.get("person", {})
        pos = entry.get("position", {})
        result.append({
            "mlb_id": person.get("id"),
            "fullName": person.get("fullName", ""),
            "position_code": pos.get("code", ""),
            "position_type": pos.get("type", ""),
            "position_abbrev": pos.get("abbreviation", ""),
        })
    logger.info("Roster for team %d: %d players", team_id, len(result))
    return result


async def get_rosters_for_teams(
    team_ids: list[int], season: int = 2026
) -> dict[str, dict[str, Any]]:
    """Fetch rosters for multiple teams and build a name -> player_info lookup.

    Returns dict keyed by lowercase player full name with values containing
    mlb_id, position, etc.
    """
    name_lookup: dict[str, dict[str, Any]] = {}
    for team_id in team_ids:
        try:
            roster = await get_team_roster(team_id, season=season)
            for p in roster:
                name = p.get("fullName", "").lower().strip()
                if name:
                    name_lookup[name] = p
        except Exception as exc:
            logger.debug("Roster fetch failed for team %d: %s", team_id, exc)
    logger.info("Built name lookup with %d players across %d teams",
                len(name_lookup), len(team_ids))
    return name_lookup


def parse_schedule_games(schedule_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract a flat list of game dicts from an MLB schedule response.

    Each dict includes game_pk, home/away team abbreviations, probable
    pitcher IDs, weather info, and lineup arrays when available.
    """
    games: list[dict[str, Any]] = []
    for date_entry in schedule_data.get("dates", []):
        for g in date_entry.get("games", []):
            home = g.get("teams", {}).get("home", {})
            away = g.get("teams", {}).get("away", {})
            wx = g.get("weather") or {}

            home_pitcher = home.get("probablePitcher", {})
            away_pitcher = away.get("probablePitcher", {})

            # Lineups come from hydration
            home_lineup_raw = g.get("lineups", {}).get("homePlayers", [])
            away_lineup_raw = g.get("lineups", {}).get("awayPlayers", [])

            # Team abbreviation: try abbreviation first, fall back to
            # teamName or name + lookup table
            home_team_obj = home.get("team", {})
            away_team_obj = away.get("team", {})
            home_abbr = (
                home_team_obj.get("abbreviation")
                or _team_name_to_abbr(home_team_obj.get("teamName", "")
                                      or home_team_obj.get("name", ""))
            )
            away_abbr = (
                away_team_obj.get("abbreviation")
                or _team_name_to_abbr(away_team_obj.get("teamName", "")
                                      or away_team_obj.get("name", ""))
            )

            games.append(
                {
                    "game_pk": g.get("gamePk"),
                    "game_date": g.get("officialDate"),
                    "game_time": g.get("gameDate"),  # ISO-8601
                    "venue": g.get("venue", {}).get("name"),
                    "home_team_abbr": home_abbr,
                    "away_team_abbr": away_abbr,
                    "home_team_id": home_team_obj.get("id"),
                    "away_team_id": away_team_obj.get("id"),
                    "home_pitcher_id": home_pitcher.get("id"),
                    "home_pitcher_name": home_pitcher.get("fullName"),
                    "home_pitcher_hand": home_pitcher.get("pitchHand", {}).get("code"),
                    "away_pitcher_id": away_pitcher.get("id"),
                    "away_pitcher_name": away_pitcher.get("fullName"),
                    "away_pitcher_hand": away_pitcher.get("pitchHand", {}).get("code"),
                    "home_lineup": [p.get("id") for p in home_lineup_raw],
                    "away_lineup": [p.get("id") for p in away_lineup_raw],
                    "temperature": wx.get("temp"),
                    "wind_speed": wx.get("wind"),
                    "condition": wx.get("condition"),
                }
            )
    return games


# MLB team name -> abbreviation lookup (used when API doesn't return abbreviation)
_MLB_TEAM_ABBR_MAP: dict[str, str] = {
    "diamondbacks": "ARI", "arizona": "ARI",
    "braves": "ATL", "atlanta": "ATL",
    "orioles": "BAL", "baltimore": "BAL",
    "red sox": "BOS", "boston": "BOS",
    "cubs": "CHC", "chicago cubs": "CHC",
    "white sox": "CWS", "chicago white sox": "CWS",
    "reds": "CIN", "cincinnati": "CIN",
    "guardians": "CLE", "cleveland": "CLE",
    "rockies": "COL", "colorado": "COL",
    "tigers": "DET", "detroit": "DET",
    "astros": "HOU", "houston": "HOU",
    "royals": "KC", "kansas city": "KC",
    "angels": "LAA", "los angeles angels": "LAA", "la angels": "LAA",
    "dodgers": "LAD", "los angeles dodgers": "LAD", "la dodgers": "LAD",
    "marlins": "MIA", "miami": "MIA",
    "brewers": "MIL", "milwaukee": "MIL",
    "twins": "MIN", "minnesota": "MIN",
    "mets": "NYM", "new york mets": "NYM",
    "yankees": "NYY", "new york yankees": "NYY",
    "athletics": "OAK", "oakland": "OAK", "a's": "OAK",
    "phillies": "PHI", "philadelphia": "PHI",
    "pirates": "PIT", "pittsburgh": "PIT",
    "padres": "SD", "san diego": "SD",
    "giants": "SF", "san francisco": "SF",
    "mariners": "SEA", "seattle": "SEA",
    "cardinals": "STL", "st. louis": "STL",
    "rays": "TB", "tampa bay": "TB",
    "rangers": "TEX", "texas": "TEX",
    "blue jays": "TOR", "toronto": "TOR",
    "nationals": "WSH", "washington": "WSH",
}


def _team_name_to_abbr(name: str) -> str:
    """Convert a team name to abbreviation using the lookup table."""
    if not name:
        return ""
    lower = name.lower().strip()
    # Try exact match
    if lower in _MLB_TEAM_ABBR_MAP:
        return _MLB_TEAM_ABBR_MAP[lower]
    # Try partial match
    for key, abbr in _MLB_TEAM_ABBR_MAP.items():
        if key in lower or lower in key:
            return abbr
    return name[:3].upper()  # Last resort: first 3 chars


def calculate_dk_hitter_points(stat: dict[str, Any]) -> float:
    """Calculate DraftKings fantasy points for a hitter game stat line.

    Expects MLB Stats API stat keys (e.g. ``homeRuns``, ``doubles``).
    """
    from config import DK_HITTER_SCORING

    hits = stat.get("hits", 0)
    doubles = stat.get("doubles", 0)
    triples = stat.get("triples", 0)
    home_runs = stat.get("homeRuns", 0)
    singles = hits - doubles - triples - home_runs

    pts = 0.0
    pts += singles * DK_HITTER_SCORING["single"]
    pts += doubles * DK_HITTER_SCORING["double"]
    pts += triples * DK_HITTER_SCORING["triple"]
    pts += home_runs * DK_HITTER_SCORING["homeRun"]
    pts += stat.get("rbi", 0) * DK_HITTER_SCORING["rbi"]
    pts += stat.get("runs", 0) * DK_HITTER_SCORING["run"]
    pts += stat.get("baseOnBalls", 0) * DK_HITTER_SCORING["baseOnBalls"]
    pts += stat.get("hitByPitch", 0) * DK_HITTER_SCORING["hitByPitch"]
    pts += stat.get("stolenBases", 0) * DK_HITTER_SCORING["stolenBase"]
    return pts


def calculate_dk_pitcher_points(stat: dict[str, Any]) -> float:
    """Calculate DraftKings fantasy points for a pitcher game stat line."""
    from config import DK_PITCHER_SCORING

    # Innings pitched comes as "6.1" meaning 6 and 1/3
    ip_str = str(stat.get("inningsPitched", "0"))
    if "." in ip_str:
        whole, frac = ip_str.split(".")
        ip = int(whole) + int(frac) / 3.0
    else:
        ip = float(ip_str)

    pts = 0.0
    pts += stat.get("wins", 0) * DK_PITCHER_SCORING["win"]
    pts += stat.get("earnedRuns", 0) * DK_PITCHER_SCORING["earnedRun"]
    pts += stat.get("strikeOuts", 0) * DK_PITCHER_SCORING["strikeOut"]
    pts += ip * DK_PITCHER_SCORING["inningsPitched"]
    pts += stat.get("hits", 0) * DK_PITCHER_SCORING["hitAllowed"]
    pts += stat.get("baseOnBalls", 0) * DK_PITCHER_SCORING["baseOnBallsAllowed"]
    pts += stat.get("hitByPitch", 0) * DK_PITCHER_SCORING["hitByPitchAllowed"]

    # Complete game / shutout / no-hitter bonuses
    if stat.get("completeGame", False) or stat.get("completeGames", 0) > 0:
        pts += DK_PITCHER_SCORING["completeGame"]
        if stat.get("shutouts", 0) > 0:
            pts += DK_PITCHER_SCORING["completeGameShutout"]
    if stat.get("noHitter", False):
        pts += DK_PITCHER_SCORING["noHitter"]

    return pts


def calculate_fd_hitter_points(stat: dict[str, Any]) -> float:
    """Calculate FanDuel fantasy points for a hitter game stat line."""
    from config import FD_HITTER_SCORING

    hits = stat.get("hits", 0)
    doubles = stat.get("doubles", 0)
    triples = stat.get("triples", 0)
    home_runs = stat.get("homeRuns", 0)
    singles = hits - doubles - triples - home_runs

    pts = 0.0
    pts += singles * FD_HITTER_SCORING["single"]
    pts += doubles * FD_HITTER_SCORING["double"]
    pts += triples * FD_HITTER_SCORING["triple"]
    pts += home_runs * FD_HITTER_SCORING["homeRun"]
    pts += stat.get("rbi", 0) * FD_HITTER_SCORING["rbi"]
    pts += stat.get("runs", 0) * FD_HITTER_SCORING["run"]
    pts += stat.get("baseOnBalls", 0) * FD_HITTER_SCORING["baseOnBalls"]
    pts += stat.get("stolenBases", 0) * FD_HITTER_SCORING["stolenBase"]
    pts += stat.get("hitByPitch", 0) * FD_HITTER_SCORING["hitByPitch"]
    return pts


def calculate_fd_pitcher_points(stat: dict[str, Any]) -> float:
    """Calculate FanDuel fantasy points for a pitcher game stat line."""
    from config import FD_PITCHER_SCORING

    ip_str = str(stat.get("inningsPitched", "0"))
    if "." in ip_str:
        whole, frac = ip_str.split(".")
        ip = int(whole) + int(frac) / 3.0
    else:
        ip = float(ip_str)

    pts = 0.0
    pts += stat.get("wins", 0) * FD_PITCHER_SCORING["win"]
    pts += stat.get("earnedRuns", 0) * FD_PITCHER_SCORING["earnedRun"]
    pts += stat.get("strikeOuts", 0) * FD_PITCHER_SCORING["strikeOut"]
    pts += ip * FD_PITCHER_SCORING["inningsPitched"]

    # Quality start: 6+ IP and 3 or fewer ER
    if ip >= 6.0 and stat.get("earnedRuns", 99) <= 3:
        pts += FD_PITCHER_SCORING["qualityStart"]

    return pts
