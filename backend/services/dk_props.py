"""DraftKings player props: strikeouts, home runs, total bases, hits+runs+RBIs."""
from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

# DK Sportsbook base + MLB league ID
_BASE = "https://sportsbook-nash.draftkings.com/api/sportscontent/dkusnj/v1"
_LEAGUE_URL = f"{_BASE}/leagues/84240"
_CATEGORY_URL = _BASE + "/events/{event_id}/categories/{cat_id}"

# Category IDs
_CAT_BATTER = 743
_CAT_PITCHER = 1031

# In-memory cache: key -> (timestamp, data)
_cache: Dict[str, Tuple[float, Dict[str, Dict[str, Any]]]] = {}
_CACHE_TTL = 300  # 5 minutes


def _normalize_odds(odds_str: str) -> str:
    """Normalize Unicode minus sign (U+2212) and en-dash to ASCII minus."""
    if not odds_str:
        return odds_str
    return odds_str.replace("\u2212", "-").replace("\u2013", "-")


def _clean_player_name(name: str) -> str:
    """Strip team suffix like ' (WAS)' from DK player names."""
    return re.sub(r"\s*\([A-Z]{2,3}\)\s*$", "", name).strip()


def _format_line(points: Optional[float], odds_str: str, default_line: float = 1.5) -> str:
    """Format a prop line as a compact string.

    If the line equals the default (e.g. 1.5), just show odds.
    Otherwise show 'line (odds)'.
    """
    odds = _normalize_odds(odds_str)
    if points is not None and float(points) != default_line:
        return f"{points} ({odds})"
    return odds


async def _fetch_json(client: httpx.AsyncClient, url: str) -> Optional[Dict[str, Any]]:
    """GET a URL and return parsed JSON, or None on failure."""
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.warning("DK props fetch failed for %s: %s", url, exc)
        return None


def _parse_pitcher_props(data: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Extract pitcher strikeout lines from category-1031 response."""
    results: Dict[str, Dict[str, Any]] = {}
    markets = data.get("markets", [])
    selections = data.get("selections", [])

    # Index selections by marketId
    sels_by_market: Dict[str, List[Dict[str, Any]]] = {}
    for s in selections:
        mid = s.get("marketId", "")
        sels_by_market.setdefault(mid, []).append(s)

    for market in markets:
        mt = market.get("marketType", {})
        mt_name = mt.get("name", "") if isinstance(mt, dict) else ""
        if mt_name != "Strikeouts Thrown O/U":
            continue

        market_id = market.get("id", "")
        for sel in sels_by_market.get(market_id, []):
            outcome = (sel.get("outcomeType") or "").lower()
            if outcome != "over":
                continue

            # Player name from participants or market name
            player_name = None
            participants = sel.get("participants", [])
            if participants:
                player_name = participants[0].get("name", "")
            if not player_name:
                # Fallback: parse from market name "Player Name - Strikeouts..."
                mname = market.get("name", "")
                if " - " in mname:
                    player_name = mname.split(" - ")[0].strip()
            if not player_name:
                continue

            clean_name = _clean_player_name(player_name)
            points = sel.get("points")
            odds = (sel.get("displayOdds") or {}).get("american", "")
            odds = _normalize_odds(odds)

            if points is not None and odds:
                results[clean_name] = {
                    "k_line": f"{points} ({odds})",
                    "hr_line": None,
                    "tb_line": None,
                    "hrr_line": None,
                }

    return results


def _parse_batter_props(data: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Extract batter HR, TB, and H+R+RBI lines from category-743 response."""
    results: Dict[str, Dict[str, Any]] = {}
    markets = data.get("markets", [])
    selections = data.get("selections", [])

    # Index selections by marketId
    sels_by_market: Dict[str, List[Dict[str, Any]]] = {}
    for s in selections:
        mid = s.get("marketId", "")
        sels_by_market.setdefault(mid, []).append(s)

    for market in markets:
        mt = market.get("marketType", {})
        mt_name = mt.get("name", "") if isinstance(mt, dict) else ""
        market_id = market.get("id", "")
        market_sels = sels_by_market.get(market_id, [])

        if mt_name == "Home Runs Milestones":
            for sel in market_sels:
                if sel.get("label") != "1+":
                    continue
                player_name = _extract_player_name(sel, market)
                if not player_name:
                    continue
                clean_name = _clean_player_name(player_name)
                odds = _normalize_odds(
                    (sel.get("displayOdds") or {}).get("american", "")
                )
                if odds:
                    results.setdefault(clean_name, _empty_batter())
                    results[clean_name]["hr_line"] = odds

        elif mt_name == "Total Bases O/U":
            for sel in market_sels:
                if (sel.get("outcomeType") or "").lower() != "over":
                    continue
                player_name = _extract_player_name(sel, market)
                if not player_name:
                    continue
                clean_name = _clean_player_name(player_name)
                points = sel.get("points")
                odds = (sel.get("displayOdds") or {}).get("american", "")
                if odds:
                    results.setdefault(clean_name, _empty_batter())
                    results[clean_name]["tb_line"] = _format_line(
                        points, odds, default_line=1.5
                    )

        elif mt_name == "Hits + Runs + RBIs O/U":
            for sel in market_sels:
                if (sel.get("outcomeType") or "").lower() != "over":
                    continue
                player_name = _extract_player_name(sel, market)
                if not player_name:
                    continue
                clean_name = _clean_player_name(player_name)
                points = sel.get("points")
                odds = (sel.get("displayOdds") or {}).get("american", "")
                if odds:
                    results.setdefault(clean_name, _empty_batter())
                    results[clean_name]["hrr_line"] = _format_line(
                        points, odds, default_line=1.5
                    )

    return results


def _extract_player_name(
    sel: Dict[str, Any], market: Dict[str, Any]
) -> Optional[str]:
    """Get the player name from a selection's participants or the market name."""
    participants = sel.get("participants", [])
    if participants:
        name = participants[0].get("name", "")
        if name:
            return name
    # Fallback: market name before the first " - "
    mname = market.get("name", "")
    if " - " in mname:
        return mname.split(" - ")[0].strip()
    return None


def _empty_batter() -> Dict[str, Any]:
    return {"k_line": None, "hr_line": None, "tb_line": None, "hrr_line": None}


async def fetch_player_props(
    target_date: str = None,
) -> Dict[str, Dict[str, Any]]:
    """Fetch DK player props for all MLB games.

    Args:
        target_date: Unused for now (DK only serves today's props). Reserved
                     for future cache-key scoping.

    Returns:
        Dict keyed by player name (str) with value dict containing:
          - k_line:   str or None (pitcher only, e.g. "4.5 (-154)")
          - hr_line:  str or None (batter only, e.g. "+407")
          - tb_line:  str or None (batter only, e.g. "-110")
          - hrr_line: str or None (batter only, e.g. "-156")
    """
    cache_key = "dk-props"

    # Return cached data if fresh
    if cache_key in _cache:
        ts, cached = _cache[cache_key]
        if time.time() - ts < _CACHE_TTL:
            logger.debug("Returning cached DK props (%d players)", len(cached))
            return cached

    async with httpx.AsyncClient(headers=_HEADERS, timeout=15) as client:
        # Step 1: Get all event IDs from the league endpoint
        league_data = await _fetch_json(client, _LEAGUE_URL)
        if league_data is None:
            logger.warning("DK league endpoint returned no data")
            return _cache.get(cache_key, (0, {}))[1]

        events = league_data.get("events", [])
        if not events:
            logger.info("DK props: no MLB events found (offseason or no games today)")
            return {}

        event_ids = [str(e["id"]) for e in events if "id" in e]
        logger.info("DK props: found %d MLB events", len(event_ids))

        # Step 2: Fetch batter + pitcher categories for all events concurrently
        tasks = []
        task_meta: List[Tuple[str, int]] = []  # (event_id, category_id)
        for eid in event_ids:
            for cat_id in (_CAT_BATTER, _CAT_PITCHER):
                url = _CATEGORY_URL.format(event_id=eid, cat_id=cat_id)
                tasks.append(_fetch_json(client, url))
                task_meta.append((eid, cat_id))

        responses = await asyncio.gather(*tasks)

    # Step 3: Parse all responses and merge into a single player dict
    all_props: Dict[str, Dict[str, Any]] = {}

    for (eid, cat_id), resp_data in zip(task_meta, responses):
        if resp_data is None:
            continue

        if cat_id == _CAT_PITCHER:
            pitcher_props = _parse_pitcher_props(resp_data)
            for name, props in pitcher_props.items():
                all_props.setdefault(name, _empty_batter())
                all_props[name]["k_line"] = props["k_line"]
        else:
            batter_props = _parse_batter_props(resp_data)
            for name, props in batter_props.items():
                existing = all_props.setdefault(name, _empty_batter())
                if props["hr_line"]:
                    existing["hr_line"] = props["hr_line"]
                if props["tb_line"]:
                    existing["tb_line"] = props["tb_line"]
                if props["hrr_line"]:
                    existing["hrr_line"] = props["hrr_line"]

    # Cache and return
    _cache[cache_key] = (time.time(), all_props)
    pitcher_count = sum(1 for p in all_props.values() if p["k_line"])
    batter_count = sum(1 for p in all_props.values() if p["hr_line"] or p["tb_line"])
    logger.info(
        "DK props: fetched %d pitcher props, %d batter props (%d total players)",
        pitcher_count,
        batter_count,
        len(all_props),
    )
    return all_props
