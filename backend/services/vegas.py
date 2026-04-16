"""Vegas odds: DraftKings Sportsbook + Fantasy Labs APIs for MLB lines and totals."""
from __future__ import annotations

import logging
import re
import time
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

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

# DK Sportsbook MLB league ID
MLB_LEAGUE_ID = 84240

# ── Fantasy Labs team name → standard abbreviation ──────────────────────────
_FL_TEAM_ABBR: Dict[str, str] = {
    "Arizona Diamondbacks": "ARI",
    "Atlanta Braves": "ATL",
    "Baltimore Orioles": "BAL",
    "Boston Red Sox": "BOS",
    "Chicago Cubs": "CHC",
    "Chicago White Sox": "CWS",
    "Cincinnati Reds": "CIN",
    "Cleveland Guardians": "CLE",
    "Colorado Rockies": "COL",
    "Detroit Tigers": "DET",
    "Houston Astros": "HOU",
    "Kansas City Royals": "KC",
    "Los Angeles Angels": "LAA",
    "Los Angeles Dodgers": "LAD",
    "Miami Marlins": "MIA",
    "Milwaukee Brewers": "MIL",
    "Minnesota Twins": "MIN",
    "New York Mets": "NYM",
    "New York Yankees": "NYY",
    "Athletics": "OAK",
    "Oakland Athletics": "OAK",
    "Philadelphia Phillies": "PHI",
    "Pittsburgh Pirates": "PIT",
    "San Diego Padres": "SD",
    "San Francisco Giants": "SF",
    "Seattle Mariners": "SEA",
    "St. Louis Cardinals": "STL",
    "Tampa Bay Rays": "TB",
    "Texas Rangers": "TEX",
    "Toronto Blue Jays": "TOR",
    "Washington Nationals": "WSH",
}

# Cache for Fantasy Labs odds: key -> (timestamp, data)
_fl_cache: Dict[str, Tuple[float, List[Dict[str, Any]]]] = {}
_FL_CACHE_TTL = 300  # 5 minutes


async def get_mlb_odds() -> Dict[str, Any]:
    """Fetch current MLB odds from DraftKings Sportsbook.

    Returns the raw JSON which contains events, markets, and selections
    at the top level.
    """
    async with httpx.AsyncClient(headers=_HEADERS, timeout=30) as client:
        resp = await client.get(settings.dk_sportsbook_url)
        resp.raise_for_status()
        data = resp.json()
    logger.info("Fetched DK sportsbook MLB data")
    return data


def parse_odds(raw: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Parse DK sportsbook response into per-game odds dicts.

    The DK sportsbook API returns a flat structure with:
    - events: list of games with participants
    - markets: list of betting markets (Moneyline, Total, Run Line) linked by eventId
    - selections: list of outcomes linked by marketId

    Returns a list of dicts with keys:
      - event_id, event_name
      - home_team, away_team, home_abbr, away_abbr
      - home_ml, away_ml
      - total (over/under run total)
      - home_implied, away_implied (derived from total + ML)
    """
    events = raw.get("events", [])
    markets = raw.get("markets", [])
    selections = raw.get("selections", [])

    # Index markets by eventId
    markets_by_event: Dict[str, List[Dict[str, Any]]] = {}
    for m in markets:
        eid = str(m.get("eventId", ""))
        markets_by_event.setdefault(eid, []).append(m)

    # Index selections by marketId
    selections_by_market: Dict[str, List[Dict[str, Any]]] = {}
    for s in selections:
        mid = s.get("marketId", "")
        selections_by_market.setdefault(mid, []).append(s)

    games: List[Dict[str, Any]] = []

    for event in events:
        event_id = str(event.get("id", ""))
        game: Dict[str, Any] = {
            "event_id": event_id,
            "event_name": event.get("name", ""),
            "home_team": None,
            "away_team": None,
            "home_abbr": None,
            "away_abbr": None,
            "home_ml": None,
            "away_ml": None,
            "total": None,
            "home_implied": None,
            "away_implied": None,
        }

        # Extract team names and abbreviations from participants
        for p in event.get("participants", []):
            role = (p.get("venueRole") or "").lower()
            meta = p.get("metadata", {})
            short = meta.get("shortName", "")
            full_name = p.get("name", "")
            if role == "home":
                game["home_team"] = full_name
                game["home_abbr"] = short
            elif role == "away":
                game["away_team"] = full_name
                game["away_abbr"] = short

        # Parse markets for this event
        event_markets = markets_by_event.get(event_id, [])
        for market in event_markets:
            market_name = (market.get("name") or "").lower()
            market_id = market.get("id", "")
            market_sels = selections_by_market.get(market_id, [])

            if "moneyline" in market_name:
                for sel in market_sels:
                    outcome_type = (sel.get("outcomeType") or "").lower()
                    odds_str = (sel.get("displayOdds") or {}).get("american", "")
                    odds_val = _parse_american_odds(odds_str)
                    if odds_val is not None:
                        if outcome_type == "home":
                            game["home_ml"] = odds_val
                        elif outcome_type == "away":
                            game["away_ml"] = odds_val

            elif market_name == "total":
                for sel in market_sels:
                    outcome_type = (sel.get("outcomeType") or "").lower()
                    if outcome_type == "over":
                        pts = sel.get("points")
                        if pts is not None:
                            try:
                                game["total"] = float(pts)
                            except (ValueError, TypeError):
                                pass

        # Derive implied run totals from total + moneyline
        if game["total"] and game["home_ml"] is not None and game["away_ml"] is not None:
            home_prob = _ml_to_prob(game["home_ml"])
            away_prob = _ml_to_prob(game["away_ml"])
            total_prob = home_prob + away_prob
            if total_prob > 0:
                game["home_implied"] = round(
                    game["total"] * home_prob / total_prob, 2
                )
                game["away_implied"] = round(
                    game["total"] * away_prob / total_prob, 2
                )

        games.append(game)

    logger.info("Parsed %d MLB game odds", len(games))
    return games


def _parse_american_odds(odds_str: str) -> Optional[int]:
    """Parse American odds string that may use Unicode minus sign."""
    if not odds_str:
        return None
    # Normalise Unicode minus (U+2212) and en-dash (U+2013) to ASCII hyphen
    cleaned = odds_str.replace("\u2212", "-").replace("\u2013", "-").replace("+", "")
    try:
        return int(cleaned)
    except (ValueError, TypeError):
        return None


def _ml_to_prob(ml: int) -> float:
    """Convert American moneyline to implied probability (no-vig)."""
    if ml > 0:
        return 100.0 / (ml + 100.0)
    else:
        return abs(ml) / (abs(ml) + 100.0)


# ── Fantasy Labs sportevents API ────────────────────────────────────────────


async def fetch_fantasylabs_odds(
    target_date: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Fetch MLB odds from Fantasy Labs sportevents API.

    Returns a list of per-game dicts with keys:
      away_team, home_team (abbreviations), away_ml, home_ml,
      game_total, spread, away_implied, home_implied
    """
    d = date.fromisoformat(target_date) if target_date else date.today()
    date_key = f"{d.month}_{d.day}_{d.year}"
    cache_key = f"fl-odds-{date_key}"

    # Check cache
    if cache_key in _fl_cache:
        ts, cached = _fl_cache[cache_key]
        if time.time() - ts < _FL_CACHE_TTL:
            return cached

    url = f"https://www.fantasylabs.com/api/sportevents/3/{date_key}"
    try:
        async with httpx.AsyncClient(headers=_HEADERS, timeout=15) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            raw = resp.json()
    except Exception as exc:
        logger.warning("Fantasy Labs odds fetch failed for %s: %s", date_key, exc)
        return _fl_cache.get(cache_key, (0, []))[1]  # return stale cache if any

    games: List[Dict[str, Any]] = []
    for ev in raw if isinstance(raw, list) else []:
        away_full = ev.get("VisitorTeam", "")
        home_full = ev.get("HomeTeam", "")
        away_abbr = _FL_TEAM_ABBR.get(away_full, "")
        home_abbr = _FL_TEAM_ABBR.get(home_full, "")
        if not away_abbr or not home_abbr:
            logger.debug("Unknown FL team: %s vs %s", away_full, home_full)
            continue

        away_ml = _safe_int(ev.get("MLMoney1"))
        home_ml = _safe_int(ev.get("MLMoney2"))
        game_total = _safe_float_val(ev.get("OU"))
        spread = _safe_float_val(ev.get("Spread"))

        # Derive implied team totals from game O/U + moneyline
        away_implied = None
        home_implied = None
        if game_total and away_ml is not None and home_ml is not None:
            away_prob = _ml_to_prob(away_ml)
            home_prob = _ml_to_prob(home_ml)
            total_prob = away_prob + home_prob
            if total_prob > 0:
                away_implied = round(game_total * away_prob / total_prob, 2)
                home_implied = round(game_total * home_prob / total_prob, 2)

        games.append({
            "away_team": away_abbr,
            "home_team": home_abbr,
            "away_ml": away_ml,
            "home_ml": home_ml,
            "game_total": game_total,
            "spread": spread,
            "away_implied": away_implied,
            "home_implied": home_implied,
        })

    _fl_cache[cache_key] = (time.time(), games)
    logger.info("Fetched %d MLB game odds from Fantasy Labs for %s", len(games), date_key)
    return games


def _safe_int(val: Any) -> Optional[int]:
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def _safe_float_val(val: Any) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None
