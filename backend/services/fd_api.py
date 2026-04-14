"""FanDuel API client (stub).

FanDuel's contest/lobby endpoints require authentication (session cookies or
OAuth).  This module defines the interface so the rest of the codebase can
reference it, but actual implementation is deferred until auth is handled.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def get_mlb_contests() -> list[dict[str, Any]]:
    """Fetch MLB contests from FanDuel.

    TODO: Implement once FD auth flow is in place.  Likely needs a session
    cookie obtained via browser automation (Playwright) or manual export.
    """
    logger.warning("FanDuel contest fetch is not yet implemented")
    return []


async def get_player_list(fixture_list_id: str) -> list[dict[str, Any]]:
    """Fetch the player pool for a FanDuel fixture list.

    TODO: Implement with auth.
    """
    logger.warning("FanDuel player list fetch is not yet implemented")
    return []


def parse_contest(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalise a raw FD contest dict into our Contest model fields.

    Placeholder -- structure TBD once we can hit the real API.
    """
    return {
        "site": "fd",
        "external_id": str(raw.get("id", "")),
        "name": raw.get("name", ""),
        "entry_fee": raw.get("entry_fee", 0),
        "max_entries": raw.get("max_entries", 1),
        "field_size": raw.get("size", 0),
        "prize_pool": raw.get("total_prizes", 0),
        "payout_structure": raw.get("prizes", []),
        "game_type": "classic",
        "draft_group_id": None,
    }
