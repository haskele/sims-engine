"""Lineup status fetcher for MLB daily lineups.

Fetches data from external lineup sources (primary + fallback) to determine
which players are in confirmed/expected starting lineups and who is the
starting pitcher for each team.

For today's games, uses Baseball Monster (primary) + RotOwire (fallback)
which provide confirmed batting orders.

For future dates, uses the MLB Stats API to get probable pitchers (batting
orders come from CSV projection data instead).

Designed to be called repeatedly -- each call fetches fresh data so late
lineup changes, scratches, and pitcher swaps are picked up.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx

from services.name_matching import names_match as _central_names_match
from services.name_matching import canonical_name, find_in_dict as _central_find_in_dict

logger = logging.getLogger(__name__)

# Team abbreviation normalisation (source → our standard)
_TEAM_ALIAS = {
    # Source-specific aliases
    "WAS": "WSH", "CHW": "CWS",
    # Standard aliases (identity mappings for safety)
    "WSH": "WSH", "CWS": "CWS",
    # Athletics rebrand
    "ATH": "OAK", "A'S": "OAK",
    # Giants
    "SFG": "SF",
    # MLB Stats API uses "AZ" for Arizona
    "AZ": "ARI",
}

_FUTURE_CACHE_TTL = 600  # 10 minutes for future dates (less volatile)

# Cache: avoid hammering sources more than once per N seconds
_cache: Dict[str, Tuple[float, Dict]] = {}
_CACHE_TTL = 90  # seconds


@dataclass
class PlayerLineup:
    """A single player's lineup status."""
    name: str
    team: str
    position: str
    batting_order: Optional[int] = None  # 1-9 for hitters, None for pitchers
    is_pitcher: bool = False
    handedness: str = ""  # L / R / S


@dataclass
class TeamLineup:
    """Lineup data for one team in one game."""
    team: str
    status: str = "unknown"  # "confirmed", "expected", "unknown"
    pitcher: Optional[PlayerLineup] = None
    batters: List[PlayerLineup] = field(default_factory=list)
    last_checked: Optional[str] = None


@dataclass
class GameLineup:
    """Lineup data for a single game."""
    away: TeamLineup = field(default_factory=TeamLineup)
    home: TeamLineup = field(default_factory=TeamLineup)
    game_time: str = ""


def _normalise_team(abbr: str) -> str:
    """Normalise a team abbreviation to our standard form."""
    upper = abbr.strip().upper()
    return _TEAM_ALIAS.get(upper, upper)


def _normalise_name(name: str) -> str:
    """Normalise a player name for fuzzy matching.

    Strips suffixes like Jr., Sr., III, and normalises whitespace/punctuation.
    """
    name = name.strip()
    # Remove common suffixes
    name = re.sub(r'\s+(Jr\.?|Sr\.?|II|III|IV)$', '', name, flags=re.IGNORECASE)
    # Normalise periods, hyphens, and extra whitespace
    name = name.replace('.', '').replace('-', ' ').strip()
    name = re.sub(r'\s+', ' ', name)
    return name


# ── Primary lineup source ───────────────────────────────────────────────────


async def _fetch_primary_source() -> str:
    """Fetch the primary lineups page."""
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        resp = await client.get(
            "https://baseballmonster.com/lineups.aspx",
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml",
            },
        )
        resp.raise_for_status()
        return resp.text


def _parse_primary_source(html: str) -> List[GameLineup]:
    """Parse the primary lineup page into structured data.

    Structure:
    - Games split by <div class='lineup-holder'>
    - Each holder has two <td> blocks (away, home)
    - Team: TEAM&#160;&#160; header
    - Batters: <tr class='lineup-starting'> rows with order/name/hand/position
    - Pitcher: <tr> (no class) with SP in position cell
    - Confirmed: "VERIFIED LINEUP" after lineup table
    - Expected: "Lineup Expected" after lineup table
    """
    games: List[GameLineup] = []

    # Split into game blocks by lineup-holder divs
    blocks = re.split(r"<div\s+class=['\"]lineup-holder['\"]>", html)
    if len(blocks) < 2:
        logger.warning("Primary source: no lineup-holder blocks found")
        return games

    # First block is page header/nav — skip it
    now_str = datetime.now(timezone.utc).isoformat()

    for block in blocks[1:]:
        game = _parse_bm_game_block(block, now_str)
        if game:
            games.append(game)

    logger.info("Primary source: parsed %d games", len(games))
    return games


def _parse_bm_game_block(block: str, timestamp: str) -> Optional[GameLineup]:
    """Parse a single game block from the primary source.

    Each block has two <td valign='top'> sections -- away (first) and home (second).
    """
    # Extract team abbreviations from bold headers:
    # Away: font-weight: bold;'>TEAM&#160;  or  font-weight: bold;'>TEAM (8)&#160;
    # Home: font-weight: bold;'>@&#160;TEAM&#160;  or  font-weight: bold;'>@ TEAM&#160;
    team_headers = re.findall(
        r"font-weight:\s*bold;'>\s*@?\s*(?:&#160;)?\s*([A-Z]{2,3})",
        block,
    )
    if len(team_headers) < 2:
        # Fallback: try the old format
        team_headers = re.findall(r"([A-Z]{2,3})(?:\s*\(\d+\))?(?:&#160;)+", block)
    if len(team_headers) < 2:
        return None

    away_abbr = _normalise_team(team_headers[0])
    home_abbr = _normalise_team(team_headers[1])

    # Split the block into away/home halves at the second <td valign='top'>
    td_splits = re.split(
        r"</td>\s*<td\s+valign=['\"]top['\"]",
        block,
        maxsplit=1,
    )
    away_html = td_splits[0] if len(td_splits) >= 1 else ""
    home_html = td_splits[1] if len(td_splits) >= 2 else ""

    game = GameLineup(
        away=_parse_bm_team_section(away_html, away_abbr),
        home=_parse_bm_team_section(home_html, home_abbr),
    )
    game.away.last_checked = timestamp
    game.home.last_checked = timestamp
    return game


def _extract_name_hand(raw: str) -> tuple[str, str]:
    """Extract player name and handedness (L/R/S) from a raw string."""
    raw = re.sub(r"<[^>]+>", "", raw).strip()
    raw = re.sub(r"\s*\([A-Z]\)\s*", " ", raw).strip()
    hand_match = re.search(r"\s+([LRS])\s*$", raw)
    hand = hand_match.group(1) if hand_match else ""
    name = raw[:hand_match.start()].strip() if hand_match else raw.strip()
    return name, hand


def _parse_bm_team_section(html: str, team: str) -> TeamLineup:
    """Parse one team's lineup from a primary source HTML section."""
    lineup = TeamLineup(team=team)

    # Status: VERIFIED LINEUP, Lineup Expected, or Lineup Overdue
    if re.search(r"VERIFIED\s+LINEUP", html, re.IGNORECASE):
        lineup.status = "confirmed"
    elif re.search(r"Lineup\s+Expected", html, re.IGNORECASE):
        lineup.status = "expected"
    elif re.search(r"Lineup\s+Overdue", html, re.IGNORECASE):
        lineup.status = "expected"

    # Batters: rows with a batting order number (1-9) in the first cell.
    # Handles both old format (<tr class='lineup-starting'>) and new format
    # (<tr class=''> or <tr class='lineup-starting'>).
    batter_pattern = re.compile(
        r"<tr[^>]*>\s*"
        r"<td[^>]*>(\d)</td>\s*"                              # batting order
        r"<td[^>]*>(.*?)</td>\s*"                              # name + hand
        r"<td[^>]*>\s*(?:<span[^>]*>)?([\w/]+)(?:</span>)?\s*</td>",  # position
        re.IGNORECASE | re.DOTALL,
    )
    for m in batter_pattern.finditer(html):
        order = int(m.group(1))
        if order < 1 or order > 9:
            continue
        pos = m.group(3).strip().upper()
        if pos == "SP":
            continue  # Skip pitcher row that might match
        name, hand = _extract_name_hand(m.group(2))
        if not name:
            continue

        lineup.batters.append(PlayerLineup(
            name=name,
            team=team,
            position=pos,
            batting_order=order,
            handedness=hand,
        ))

    # Pitcher: row with SP position and non-numeric first cell (&#160; or empty)
    sp_pattern = re.compile(
        r"<tr[^>]*>\s*<td[^>]*>(?:&#160;|\s)*</td>\s*"   # spacer cell (only &#160; or whitespace)
        r"<td[^>]*>(.*?)</td>\s*"                          # name + hand
        r"<td[^>]*>\s*(?:<span[^>]*>)?SP(?:</span>)?\s*</td>",  # SP position
        re.IGNORECASE | re.DOTALL,
    )
    sp_match = sp_pattern.search(html)
    if sp_match:
        name, hand = _extract_name_hand(sp_match.group(1))
        if name:
            lineup.pitcher = PlayerLineup(
                name=name,
                team=team,
                position="P",
                is_pitcher=True,
                handedness=hand,
            )

    return lineup


# ── Fallback lineup source ──────────────────────────────────────────────────


async def _fetch_fallback_source() -> str:
    """Fetch the fallback daily lineups page."""
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        resp = await client.get(
            "https://www.rotowire.com/baseball/daily-lineups.php",
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml",
            },
        )
        resp.raise_for_status()
        return resp.text


def _parse_fallback_source(html: str) -> List[GameLineup]:
    """Parse the fallback lineup page into structured data."""
    games: List[GameLineup] = []

    # Fallback uses "lineup is-" classes or "Confirmed Lineup"/"Expected Lineup" text
    # Game blocks contain team abbreviations and player lists
    # Look for team matchup patterns: 3-letter abbreviations in lineup card headers

    # Find game blocks via "Confirmed Lineup" or "Expected Lineup" markers
    # Each game has two of these markers (one per team)
    status_pattern = re.compile(r'(Confirmed|Expected)\s+Lineup', re.IGNORECASE)
    team_pattern = re.compile(r'\b([A-Z]{2,3})\b')

    # Split by lineup card boundaries
    card_splits = re.split(r'(?=lineup__)', html, flags=re.IGNORECASE)

    # Simpler approach: find all status markers and team names near them
    status_matches = list(status_pattern.finditer(html))

    # Group in pairs (away, home)
    for i in range(0, len(status_matches) - 1, 2):
        away_status = status_matches[i].group(1).lower()
        home_status = status_matches[i + 1].group(1).lower() if i + 1 < len(status_matches) else "unknown"

        # Look for team abbrevs near each status marker
        away_region = html[max(0, status_matches[i].start() - 200):status_matches[i].start() + 200]
        home_region = html[max(0, status_matches[i + 1].start() - 200):status_matches[i + 1].start() + 200] if i + 1 < len(status_matches) else ""

        away_teams = team_pattern.findall(away_region)
        home_teams = team_pattern.findall(home_region)

        # Filter to valid MLB abbreviations
        mlb_teams = {"ARI", "ATL", "BAL", "BOS", "CHC", "CWS", "CIN", "CLE", "COL",
                     "DET", "HOU", "KC", "LAA", "LAD", "MIA", "MIL", "MIN", "NYM",
                     "NYY", "OAK", "ATH", "PHI", "PIT", "SD", "SF", "SFG", "SEA",
                     "STL", "TB", "TEX", "TOR", "WSH", "WAS", "CHW"}
        away_team = next((t for t in away_teams if t in mlb_teams), "")
        home_team = next((t for t in home_teams if t in mlb_teams), "")

        if away_team and home_team:
            game = GameLineup(
                away=TeamLineup(team=_normalise_team(away_team), status=away_status),
                home=TeamLineup(team=_normalise_team(home_team), status=home_status),
            )
            now_str = datetime.now(timezone.utc).isoformat()
            game.away.last_checked = now_str
            game.home.last_checked = now_str
            games.append(game)

    logger.info("Fallback source: parsed %d games", len(games))
    return games


# ── MLB Stats API source (future dates) ───────────────────────────────────


async def _fetch_mlb_api_lineups(target_date: str) -> List[GameLineup]:
    """Fetch probable pitchers for a given date from the MLB Stats API.

    This is used for future dates where confirmed batting orders are not yet
    available.  Returns GameLineup objects with pitcher data but empty
    batter lists (batting orders come from CSV projections for future dates).

    Args:
        target_date: Date string in YYYY-MM-DD format.
    """
    from config import settings

    url = settings.mlb_schedule_url
    params = {
        "sportId": 1,
        "date": target_date,
        "hydrate": "probablePitcher,team",
    }

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()

    games: List[GameLineup] = []
    now_str = datetime.now(timezone.utc).isoformat()

    for date_entry in data.get("dates", []):
        for g in date_entry.get("games", []):
            teams = g.get("teams", {})

            away_info = teams.get("away", {})
            home_info = teams.get("home", {})

            away_abbr = _normalise_team(
                away_info.get("team", {}).get("abbreviation", "")
            )
            home_abbr = _normalise_team(
                home_info.get("team", {}).get("abbreviation", "")
            )

            if not away_abbr or not home_abbr:
                continue

            # Parse game time from ISO datetime
            game_date_str = g.get("gameDate", "")
            game_time = ""
            if game_date_str:
                try:
                    dt = datetime.fromisoformat(game_date_str.replace("Z", "+00:00"))
                    # Convert to ET (UTC-4 during EDT)
                    et = dt - timedelta(hours=4)
                    hour = et.hour % 12 or 12
                    ampm = "PM" if et.hour >= 12 else "AM"
                    game_time = f"{hour}:{et.minute:02d} {ampm} ET"
                except (ValueError, TypeError):
                    pass

            # Extract probable pitchers
            away_pitcher = _parse_probable_pitcher(away_info, away_abbr)
            home_pitcher = _parse_probable_pitcher(home_info, home_abbr)

            game = GameLineup(
                away=TeamLineup(
                    team=away_abbr,
                    status="expected",
                    pitcher=away_pitcher,
                    batters=[],
                    last_checked=now_str,
                ),
                home=TeamLineup(
                    team=home_abbr,
                    status="expected",
                    pitcher=home_pitcher,
                    batters=[],
                    last_checked=now_str,
                ),
                game_time=game_time,
            )
            games.append(game)

    logger.info("MLB API: parsed %d games for %s", len(games), target_date)
    return games


def _parse_probable_pitcher(
    team_info: Dict[str, Any], team_abbr: str
) -> Optional[PlayerLineup]:
    """Extract a probable pitcher from the MLB API team info.

    Returns None if the pitcher is TBD or not yet announced.
    """
    pp = team_info.get("probablePitcher")
    if not pp:
        return None

    full_name = pp.get("fullName", "")
    if not full_name or full_name.upper() == "TBD":
        return None

    return PlayerLineup(
        name=full_name,
        team=team_abbr,
        position="P",
        is_pitcher=True,
        handedness="",  # MLB API doesn't include this in schedule hydrate
    )


# ── Public API ──────────────────────────────────────────────────────────────


async def fetch_lineups(
    force_refresh: bool = False,
    target_date: Optional[str] = None,
) -> List[GameLineup]:
    """Fetch MLB lineup data for a given date.

    Args:
        force_refresh: Bypass the cache and fetch fresh data.
        target_date: Date in YYYY-MM-DD format. None means today.

    Routing logic:
    - Today (or None): use Baseball Monster (primary) + RotOwire (fallback)
      for confirmed batting orders.  Cache TTL: 90 seconds.
    - Future date: use MLB Stats API for probable pitchers (no batting
      orders — those come from CSV projections).  Cache TTL: 10 minutes.
    """
    today_str = date.today().isoformat()
    date_str = target_date or today_str
    is_today = date_str == today_str

    cache_key = f"lineups-{date_str}"
    ttl = _CACHE_TTL if is_today else _FUTURE_CACHE_TTL
    now = time.time()

    if not force_refresh and cache_key in _cache:
        cached_time, cached_data = _cache[cache_key]
        if now - cached_time < ttl:
            logger.debug(
                "Returning cached lineup data for %s (%.0fs old)",
                date_str, now - cached_time,
            )
            return cached_data

    games: List[GameLineup] = []

    if is_today:
        # Today: scrape confirmed lineups from external sources
        try:
            html = await _fetch_primary_source()
            games = _parse_primary_source(html)
        except Exception as exc:
            logger.warning("Primary lineup fetch failed: %s", exc)

        if not games:
            try:
                html = await _fetch_fallback_source()
                games = _parse_fallback_source(html)
            except Exception as exc:
                logger.warning("Fallback lineup fetch failed: %s", exc)
    else:
        # Future date: use MLB Stats API for probable pitchers
        try:
            games = await _fetch_mlb_api_lineups(date_str)
        except Exception as exc:
            logger.warning("MLB API lineup fetch failed for %s: %s", date_str, exc)

    if games:
        _cache[cache_key] = (now, games)

    return games


def get_team_status(games: List[GameLineup], team: str) -> Optional[TeamLineup]:
    """Find a team's lineup status from the fetched games."""
    team_upper = _normalise_team(team)
    for game in games:
        if game.away.team == team_upper:
            return game.away
        if game.home.team == team_upper:
            return game.home
    return None


def build_lineup_lookup(games: List[GameLineup]) -> Dict[str, Dict[str, Any]]:
    """Build a lookup dict of team → lineup info for fast access.

    Returns: {
        "NYY": {
            "status": "confirmed",
            "pitcher": "Gerrit Cole",
            "batters": {"Aaron Judge": 2, "Juan Soto": 3, ...},  # name → order
            "last_checked": "2026-04-15T18:00:00+00:00",
        },
        ...
    }
    """
    lookup: Dict[str, Dict[str, Any]] = {}

    for game in games:
        for team_lineup in (game.away, game.home):
            batters = {}
            for b in team_lineup.batters:
                batters[_normalise_name(b.name)] = b.batting_order

            lookup[team_lineup.team] = {
                "status": team_lineup.status,
                "pitcher": _normalise_name(team_lineup.pitcher.name) if team_lineup.pitcher else None,
                "batters": batters,
                "last_checked": team_lineup.last_checked,
            }

    return lookup


def apply_lineup_status(
    projections: List[Dict[str, Any]],
    lineup_lookup: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Update projection dicts with fresh lineup status.

    For each player:
    - If their team has a confirmed/expected lineup:
      - Pitchers: is_confirmed = True only if they match the starting pitcher
      - Hitters: is_confirmed = True only if their name appears in the batting order
    - If team status is "unknown", fall back to CSV Order field (existing logic)

    Also sets lineup_status: "confirmed", "expected", "out", or "unknown".
    Also updates batting_order from the live lineup data when available.
    """
    for proj in projections:
        team = _normalise_team(proj.get("team", ""))
        team_info = lineup_lookup.get(team)

        if not team_info:
            # No live data for this team -- keep existing is_confirmed
            proj["lineup_status"] = "unknown"
            continue

        team_status = team_info["status"]  # "confirmed", "expected", "unknown"
        player_name = _normalise_name(proj.get("player_name", ""))

        # Ohtani dual-role: determine pitcher vs hitter from lineup data
        if _names_match(player_name, "Shohei Ohtani"):
            sp_name = team_info.get("pitcher")
            batters = team_info.get("batters", {})
            if sp_name and _names_match(player_name, sp_name):
                # Ohtani is starting pitcher today — pitching points only
                proj["is_pitcher"] = True
                proj["position"] = "SP"
                proj["batting_order"] = None
                proj["is_confirmed"] = True
                proj["lineup_status"] = team_status
            else:
                # Ohtani is NOT pitching — treat as hitter
                proj["is_pitcher"] = False
                if proj["position"] in ("P", "SP", "RP"):
                    proj["position"] = "OF"
                matched_order = _find_name_in_dict(player_name, batters)
                if matched_order is not None:
                    proj["is_confirmed"] = True
                    proj["batting_order"] = matched_order
                    proj["lineup_status"] = team_status
                elif team_status in ("confirmed", "expected"):
                    proj["is_confirmed"] = False
                    proj["lineup_status"] = "out"
                else:
                    proj["lineup_status"] = "unknown"
            continue

        if proj.get("is_pitcher"):
            # Pitcher: confirmed only if they're the listed starter
            sp_name = team_info.get("pitcher")
            if sp_name:
                is_starter = _names_match(player_name, sp_name)
                proj["is_confirmed"] = is_starter
                proj["lineup_status"] = team_status if is_starter else "out"
            else:
                proj["lineup_status"] = "unknown"
        else:
            # Hitter: confirmed if in the batting order
            batters = team_info.get("batters", {})
            matched_order = _find_name_in_dict(player_name, batters)
            if matched_order is not None:
                proj["is_confirmed"] = True
                proj["batting_order"] = matched_order
                proj["lineup_status"] = team_status
            elif team_status in ("confirmed", "expected"):
                # Team has a lineup posted but this player isn't in it
                proj["is_confirmed"] = False
                proj["lineup_status"] = "out"
            else:
                proj["lineup_status"] = "unknown"

    return projections


def _names_match(name1: str, name2: str) -> bool:
    """Fuzzy name matching — delegates to centralised name_matching module.

    Handles accent normalisation, known aliases, suffix stripping,
    and first-initial + last-name fuzzy matching.
    """
    return _central_names_match(name1, name2)


def _find_name_in_dict(name: str, name_dict: Dict[str, Any]) -> Optional[Any]:
    """Find a name in a dictionary using canonical + fuzzy matching."""
    result = _central_find_in_dict(name, name_dict)
    if result is not None:
        return result[1]  # return the value, not the (key, value) tuple
    return None
