"""Shared constants for the baseball DFS simulation backend.

This module is the single source of truth for team-abbreviation mappings
and any other constants that were previously duplicated across services.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# DK / MLB team abbreviation map
# ---------------------------------------------------------------------------
# DraftKings (and some data sources like RotoGrinders, MLB Stats API) use
# slightly different abbreviations than our internal standard.  This map
# normalises all known variants to a single canonical MLB abbreviation.

DK_TEAM_ALIAS: dict[str, str] = {
    "ARI": "ARI", "AZ": "ARI",
    "ATL": "ATL",
    "BAL": "BAL",
    "BOS": "BOS",
    "CHC": "CHC", "CHI": "CHC",
    "CWS": "CWS", "CHW": "CWS",
    "CIN": "CIN",
    "CLE": "CLE",
    "COL": "COL",
    "DET": "DET",
    "HOU": "HOU",
    "KC": "KC", "KCR": "KC",
    "LAA": "LAA",
    "LAD": "LAD", "LA": "LAD",
    "MIA": "MIA",
    "MIL": "MIL",
    "MIN": "MIN",
    "NYM": "NYM",
    "NYY": "NYY",
    "OAK": "OAK", "ATH": "OAK", "A'S": "OAK",
    "PHI": "PHI",
    "PIT": "PIT",
    "SD": "SD", "SDP": "SD",
    "SF": "SF", "SFG": "SF",
    "SEA": "SEA",
    "STL": "STL",
    "TB": "TB", "TBR": "TB",
    "TEX": "TEX",
    "TOR": "TOR",
    "WSH": "WSH", "WAS": "WSH",
}


def normalise_dk_team(abbr: str) -> str:
    """Normalise a team abbreviation to our canonical MLB standard.

    Handles DraftKings, RotoGrinders, MLB Stats API, and other common
    abbreviation variants.  Returns the input upper-cased if no mapping
    exists (safe passthrough for already-standard abbreviations).
    """
    return DK_TEAM_ALIAS.get(abbr.upper(), abbr.upper()) if abbr else ""
