"""
Scoring module for MLB DFS projection engine.

Loads site-specific scoring configs (DraftKings, FanDuel) and scores
hitter/pitcher statlines against them.
"""

import json
from pathlib import Path

# Path to scoring config directory — use config_data/ (not data/, which is a
# mounted volume on Fly.io and doesn't include files from the Docker build)
_SCORING_DIR = Path(__file__).resolve().parent.parent / "config_data" / "scoring"
if not _SCORING_DIR.exists():
    _SCORING_DIR = Path(__file__).resolve().parent.parent / "data" / "scoring"

# Module-level config cache
_configs: dict[str, dict] = {}


def _load_config(site: str) -> dict:
    """Load and cache a scoring config from JSON."""
    if site in _configs:
        return _configs[site]

    config_path = _SCORING_DIR / f"{site}.json"
    if not config_path.exists():
        raise FileNotFoundError(
            f"No scoring config for site '{site}'. "
            f"Available: {list_sites()}"
        )

    with open(config_path, "r") as f:
        config = json.load(f)

    _configs[site] = config
    return config


def get_scoring_config(site: str = "dk") -> dict:
    """Return the full scoring config dict for a site."""
    return _load_config(site)


def list_sites() -> list[str]:
    """Return list of available site keys (e.g. ['dk', 'fd'])."""
    return sorted(
        p.stem for p in _SCORING_DIR.glob("*.json")
    )


# -- Statline key -> scoring config key mappings --

_HITTER_KEY_MAP = {
    "singles":          "single",
    "doubles":          "double",
    "triples":          "triple",
    "home_runs":        "homeRun",
    "rbis":             "rbi",
    "runs":             "run",
    "walks":            "baseOnBalls",
    "hbps":             "hitByPitch",
    "stolen_bases":     "stolenBase",
    "caught_stealing":  "caughtStealing",
}

_PITCHER_KEY_MAP = {
    "innings_pitched":  "inningsPitched",
    "strikeouts":       "strikeOut",
    "earned_runs":      "earnedRun",
    "hits_allowed":     "hitAllowed",
    "walks_allowed":    "baseOnBallsAllowed",
    "hbps_allowed":     "hitByPitchAllowed",
    "wins":             "win",
    "complete_game":    "completeGame",
    "shutout":          "completeGameShutout",
    "no_hitter":        "noHitter",
    # FanDuel-only keys (ignored if not in config)
    "quality_start":    "qualityStart",
}


def score_hitter_statline(statline: dict, site: str = "dk") -> float:
    """
    Score a hitter statline dict against a site's scoring config.

    Expected statline keys:
        singles, doubles, triples, home_runs, rbis, runs,
        walks, hbps, stolen_bases, caught_stealing

    Returns total fantasy points as a float.
    """
    config = _load_config(site)
    hitter_scoring = config["hitter"]
    total = 0.0

    for stat_key, config_key in _HITTER_KEY_MAP.items():
        value = statline.get(stat_key, 0)
        multiplier = hitter_scoring.get(config_key, 0)
        total += value * multiplier

    return round(total, 2)


def score_pitcher_statline(statline: dict, site: str = "dk") -> float:
    """
    Score a pitcher statline dict against a site's scoring config.

    Expected statline keys:
        innings_pitched, strikeouts, earned_runs, hits_allowed,
        walks_allowed, hbps_allowed, wins (0 or 1),
        complete_game (bool), shutout (bool), no_hitter (bool)

    Returns total fantasy points as a float.
    """
    config = _load_config(site)
    pitcher_scoring = config["pitcher"]
    total = 0.0

    for stat_key, config_key in _PITCHER_KEY_MAP.items():
        value = statline.get(stat_key, 0)
        # Convert bools to int for scoring
        if isinstance(value, bool):
            value = int(value)
        multiplier = pitcher_scoring.get(config_key, 0)
        total += value * multiplier

    return round(total, 2)
