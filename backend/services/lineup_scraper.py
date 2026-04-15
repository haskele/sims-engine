"""Lineup status scraper for MLB daily lineups.

Scrapes Baseball Monster (primary) and RotOwire (fallback) to determine
which players are in confirmed/expected starting lineups and who is the
starting pitcher for each team.

Designed to be called repeatedly — each call fetches fresh data so late
lineup changes, scratches, and pitcher swaps are picked up.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

# Team abbreviation normalisation (source → our standard)
_TEAM_ALIAS = {
    # Baseball Monster uses these
    "WAS": "WSH", "CHW": "CWS",
    # RotOwire uses these already-standard names, but just in case
    "WSH": "WSH", "CWS": "CWS",
    # Athletics rebrand
    "ATH": "OAK", "A'S": "OAK",
    # Giants
    "SFG": "SF",
}

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


# ── Baseball Monster scraper ────────────────────────────────────────────────


async def _fetch_baseball_monster() -> str:
    """Fetch the Baseball Monster lineups page."""
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


def _parse_baseball_monster(html: str) -> List[GameLineup]:
    """Parse Baseball Monster lineup page into structured data.

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
        logger.warning("Baseball Monster: no lineup-holder blocks found")
        return games

    # First block is page header/nav — skip it
    now_str = datetime.now(timezone.utc).isoformat()

    for block in blocks[1:]:
        game = _parse_bm_game_block(block, now_str)
        if game:
            games.append(game)

    logger.info("Baseball Monster: parsed %d games", len(games))
    return games


def _parse_bm_game_block(block: str, timestamp: str) -> Optional[GameLineup]:
    """Parse a single game block from Baseball Monster.

    Each block has two <td> sections — away (first) and home (second).
    """
    # Find team abbreviations: TEAM&#160;&#160;
    team_matches = re.findall(r"([A-Z]{2,3})(?:&#160;)+", block)
    if len(team_matches) < 2:
        return None

    away_abbr = _normalise_team(team_matches[0])
    home_abbr = _normalise_team(team_matches[1])

    # Split the block into away/home halves at the second <td valign
    # The first <td> is away, the second is home
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


def _parse_bm_team_section(html: str, team: str) -> TeamLineup:
    """Parse one team's lineup from a Baseball Monster HTML section."""
    lineup = TeamLineup(team=team)

    # Status: VERIFIED LINEUP or Lineup Expected
    if re.search(r"VERIFIED\s+LINEUP", html, re.IGNORECASE):
        lineup.status = "confirmed"
    elif re.search(r"Lineup\s+Expected", html, re.IGNORECASE):
        lineup.status = "expected"

    # Batters: <tr class='lineup-starting'> rows
    # Each row: <td>ORDER</td><td>NAME HAND </td><td>POS</td>
    batter_pattern = re.compile(
        r"<tr\s+class=['\"]lineup-starting['\"]>\s*"
        r"<td[^>]*>(\d)</td>\s*"                              # batting order
        r"<td[^>]*>(.*?)</td>\s*"                              # name + hand
        r"<td[^>]*>\s*(?:<span[^>]*>)?([\w]+)(?:</span>)?\s*</td>",  # position
        re.IGNORECASE | re.DOTALL,
    )
    for m in batter_pattern.finditer(html):
        order = int(m.group(1))
        name_hand = m.group(2).strip()
        pos = m.group(3).strip().upper()

        # Strip HTML tags and inline markers
        name_hand = re.sub(r"<[^>]+>", "", name_hand).strip()
        name_hand = re.sub(r"\s*\([A-Z]\)\s*", " ", name_hand).strip()
        # Extract handedness from end of name string: "Ketel Marte S "
        hand_match = re.search(r"\s+([LRS])\s*$", name_hand)
        hand = hand_match.group(1) if hand_match else ""
        name = name_hand[:hand_match.start()].strip() if hand_match else name_hand.strip()

        lineup.batters.append(PlayerLineup(
            name=name,
            team=team,
            position=pos,
            batting_order=order,
            handedness=hand,
        ))

    # Pitcher: row WITHOUT lineup-starting class, with SP position
    # <tr><td>&nbsp;</td><td>PlayerName HAND </td><td>SP</td></tr>
    sp_pattern = re.compile(
        r"<tr>\s*<td[^>]*>[^<]*</td>\s*"      # spacer cell (&#160; or empty)
        r"<td[^>]*>(.*?)</td>\s*"               # name + hand
        r"<td[^>]*>\s*SP\s*</td>",              # SP position
        re.IGNORECASE | re.DOTALL,
    )
    sp_match = sp_pattern.search(html)
    if sp_match:
        raw = sp_match.group(1).strip()
        # Strip HTML tags (injury icons, etc.)
        raw = re.sub(r"<[^>]+>", "", raw).strip()
        # Strip inline markers like (P) (H) from Ohtani etc.
        raw = re.sub(r"\s*\([A-Z]\)\s*", " ", raw).strip()
        # Extract handedness from end
        hand_match = re.search(r"\s+([LRS])\s*$", raw)
        hand = hand_match.group(1) if hand_match else ""
        name = raw[:hand_match.start()].strip() if hand_match else raw.strip()

        lineup.pitcher = PlayerLineup(
            name=name,
            team=team,
            position="P",
            is_pitcher=True,
            handedness=hand,
        )

    return lineup


# ── RotOwire scraper (fallback) ─────────────────────────────────────────────


async def _fetch_rotowire() -> str:
    """Fetch the RotOwire daily lineups page."""
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


def _parse_rotowire(html: str) -> List[GameLineup]:
    """Parse RotOwire lineup page into structured data."""
    games: List[GameLineup] = []

    # RotOwire uses "lineup is-" classes or "Confirmed Lineup"/"Expected Lineup" text
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

    logger.info("RotOwire: parsed %d games", len(games))
    return games


# ── Public API ──────────────────────────────────────────────────────────────


async def fetch_lineups(force_refresh: bool = False) -> List[GameLineup]:
    """Fetch current MLB lineup data.

    Uses Baseball Monster as primary source, RotOwire as fallback.
    Results are cached for 90 seconds to avoid hammering.
    """
    cache_key = "lineups"
    now = time.time()

    if not force_refresh and cache_key in _cache:
        cached_time, cached_data = _cache[cache_key]
        if now - cached_time < _CACHE_TTL:
            logger.debug("Returning cached lineup data (%.0fs old)", now - cached_time)
            return cached_data

    # Try Baseball Monster first
    games = []
    try:
        html = await _fetch_baseball_monster()
        games = _parse_baseball_monster(html)
    except Exception as exc:
        logger.warning("Baseball Monster scrape failed: %s", exc)

    # Fallback to RotOwire
    if not games:
        try:
            html = await _fetch_rotowire()
            games = _parse_rotowire(html)
        except Exception as exc:
            logger.warning("RotOwire scrape failed: %s", exc)

    if games:
        _cache[cache_key] = (now, games)

    return games


def get_team_status(games: List[GameLineup], team: str) -> Optional[TeamLineup]:
    """Find a team's lineup status from the scraped games."""
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

    Also updates batting_order from the scraped data when available.
    """
    for proj in projections:
        team = _normalise_team(proj.get("team", ""))
        team_info = lineup_lookup.get(team)

        if not team_info:
            # No scraped data for this team — keep existing is_confirmed
            continue

        player_name = _normalise_name(proj.get("player_name", ""))

        if proj.get("is_pitcher"):
            # Pitcher: confirmed only if they're the listed starter
            sp_name = team_info.get("pitcher")
            if sp_name:
                proj["is_confirmed"] = _names_match(player_name, sp_name)
            # If team is confirmed but no pitcher name parsed, keep existing
        else:
            # Hitter: confirmed if in the batting order
            batters = team_info.get("batters", {})
            matched_order = _find_name_in_dict(player_name, batters)
            if matched_order is not None:
                proj["is_confirmed"] = True
                proj["batting_order"] = matched_order
            elif team_info["status"] in ("confirmed", "expected"):
                # Team has a lineup posted but this player isn't in it
                proj["is_confirmed"] = False

    return projections


def _names_match(name1: str, name2: str) -> bool:
    """Fuzzy name matching — checks if names refer to the same player.

    Handles:
    - Exact match
    - Last name match (when one source uses full name and other uses shortened)
    - First initial + last name match
    - Suffix differences (Jr., Sr., III, etc.)
    """
    n1 = _normalise_name(name1).lower()
    n2 = _normalise_name(name2).lower()

    if n1 == n2:
        return True

    parts1 = n1.split()
    parts2 = n2.split()
    if parts1 and parts2:
        if parts1[-1] == parts2[-1]:
            # Same last name — check first initial if available
            if len(parts1) > 1 and len(parts2) > 1:
                if parts1[0][0] == parts2[0][0]:
                    return True
            # Single-name match (just last name)
            return True

    return False


def _find_name_in_dict(name: str, name_dict: Dict[str, Any]) -> Optional[Any]:
    """Find a name in a dictionary using fuzzy matching."""
    for dict_name, value in name_dict.items():
        if _names_match(name, dict_name):
            return value
    return None
