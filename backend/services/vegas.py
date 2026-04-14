"""DraftKings Sportsbook API client for MLB lines and totals."""
from __future__ import annotations

import logging
from typing import Any

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


async def get_mlb_odds() -> dict[str, Any]:
    """Fetch current MLB odds from DraftKings Sportsbook.

    Returns the raw JSON which contains events with markets (moneyline,
    run total, run line, etc.).
    """
    async with httpx.AsyncClient(headers=_HEADERS, timeout=30) as client:
        resp = await client.get(settings.dk_sportsbook_url)
        resp.raise_for_status()
        data = resp.json()
    logger.info("Fetched DK sportsbook MLB data")
    return data


def parse_odds(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse DK sportsbook response into per-game odds dicts.

    Returns a list of dicts with keys:
      - event_id, event_name
      - home_team, away_team
      - home_ml, away_ml
      - total (over/under run total)
      - home_implied, away_implied  (derived from total + ML)
    """
    games: list[dict[str, Any]] = []
    events = raw.get("events", [])
    for event in events:
        game: dict[str, Any] = {
            "event_id": event.get("eventId"),
            "event_name": event.get("name", ""),
            "home_team": None,
            "away_team": None,
            "home_ml": None,
            "away_ml": None,
            "total": None,
            "home_implied": None,
            "away_implied": None,
        }

        # Parse team names from event name (format: "Away @ Home")
        name = event.get("name", "")
        if " @ " in name:
            parts = name.split(" @ ", 1)
            game["away_team"] = parts[0].strip()
            game["home_team"] = parts[1].strip()

        # Walk through offer categories -> offers -> outcomes
        for cat in event.get("offerCategories", []):
            cat_name = (cat.get("name") or "").lower()
            for sub in cat.get("offerSubcategoryDescriptors", []):
                for offer in sub.get("offerSubcategory", {}).get("offers", []):
                    for market in offer:
                        label = (market.get("label") or "").lower()
                        outcomes = market.get("outcomes", [])

                        if "moneyline" in label:
                            for o in outcomes:
                                odds = o.get("oddsAmerican")
                                participant = (o.get("label") or "").lower()
                                if odds is not None:
                                    try:
                                        odds_int = int(odds.replace("+", ""))
                                    except (ValueError, AttributeError):
                                        continue
                                    # Match to home/away
                                    if game["home_team"] and game["home_team"].lower() in participant:
                                        game["home_ml"] = odds_int
                                    elif game["away_team"] and game["away_team"].lower() in participant:
                                        game["away_ml"] = odds_int

                        elif "total" in label and "run" in label:
                            for o in outcomes:
                                if (o.get("label") or "").lower() == "over":
                                    line = o.get("line")
                                    if line is not None:
                                        try:
                                            game["total"] = float(line)
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


def _ml_to_prob(ml: int) -> float:
    """Convert American moneyline to implied probability (no-vig)."""
    if ml > 0:
        return 100.0 / (ml + 100.0)
    else:
        return abs(ml) / (abs(ml) + 100.0)
