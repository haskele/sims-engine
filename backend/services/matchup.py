"""Matchup adjustment model: odds-ratio hitter-pitcher combination with environment factors.

Combines hitter true-talent rates and pitcher true-talent rates using the
odds-ratio method (log5), then layers on platoon splits, park factors, and
weather to produce environment-adjusted per-PA outcome rates.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level caches
# ---------------------------------------------------------------------------

_LEAGUE_AVG: Optional[Dict[str, Any]] = None
_PARK_FACTORS: Optional[Dict[str, Any]] = None
_PARK_BY_TEAM: Optional[Dict[str, Dict[str, float]]] = None

_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config_data"
_DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def _load_league_averages() -> Dict[str, Any]:
    global _LEAGUE_AVG
    if _LEAGUE_AVG is not None:
        return _LEAGUE_AVG
    path = _CONFIG_DIR / "league_averages.json"
    if not path.exists():
        path = _DATA_DIR / "league_averages.json"
    try:
        with open(path) as f:
            _LEAGUE_AVG = json.load(f)
    except Exception as exc:
        logger.warning("Could not load league_averages.json: %s", exc)
        _LEAGUE_AVG = {}
    return _LEAGUE_AVG


def _load_park_factors() -> Dict[str, Any]:
    global _PARK_FACTORS
    if _PARK_FACTORS is not None:
        return _PARK_FACTORS
    path = _CONFIG_DIR / "park_factors.json"
    if not path.exists():
        path = _DATA_DIR / "park_factors.json"
    try:
        with open(path) as f:
            _PARK_FACTORS = json.load(f)
    except Exception as exc:
        logger.warning("Could not load park_factors.json: %s", exc)
        _PARK_FACTORS = {}
    return _PARK_FACTORS


def _build_park_by_team() -> Dict[str, Dict[str, float]]:
    global _PARK_BY_TEAM
    if _PARK_BY_TEAM is not None:
        return _PARK_BY_TEAM
    pf = _load_park_factors()
    _PARK_BY_TEAM = {}
    for _name, info in pf.items():
        team = info.get("team", "")
        if team:
            _PARK_BY_TEAM[team] = {
                "hr": info.get("hr", 1.0),
                "runs": info.get("runs", 1.0),
            }
    return _PARK_BY_TEAM


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class MatchupRates:
    """Combined rates for a specific hitter-pitcher matchup in a specific environment."""

    k_rate: float
    bb_rate: float
    hbp_rate: float
    hr_per_contact: float
    triple_per_contact: float
    double_per_contact: float
    single_per_contact: float
    sb_rate: float
    runs_per_pa: float
    rbi_per_pa: float


# ---------------------------------------------------------------------------
# Clamping helpers
# ---------------------------------------------------------------------------

_RATE_BOUNDS: Dict[str, Tuple[float, float]] = {
    "k_rate": (0.05, 0.50),
    "bb_rate": (0.02, 0.25),
    "hbp_rate": (0.002, 0.04),
    "hr_per_contact": (0.005, 0.15),
    "triple_per_contact": (0.001, 0.03),
    "double_per_contact": (0.01, 0.12),
    "single_per_contact": (0.10, 0.35),
    "sb_rate": (0.0, 0.20),
    "runs_per_pa": (0.04, 0.25),
    "rbi_per_pa": (0.03, 0.25),
}


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


# ---------------------------------------------------------------------------
# Odds-ratio helper
# ---------------------------------------------------------------------------

def _odds_ratio(hitter_rate: float, pitcher_rate: float, league_rate: float) -> float:
    """Combine hitter and pitcher rates using the odds-ratio (log5) method.

    combined = (H * P) / L, where H = hitter rate, P = pitcher rate, L = league avg.
    """
    if league_rate <= 0:
        return hitter_rate
    return (hitter_rate * pitcher_rate) / league_rate


# ---------------------------------------------------------------------------
# Core function
# ---------------------------------------------------------------------------

def compute_matchup_rates(
    hitter: Any,
    pitcher: Any,
    park_hr_factor: float = 1.0,
    park_runs_factor: float = 1.0,
    weather_mult: float = 1.0,
) -> MatchupRates:
    """Compute environment-adjusted per-PA rates for a hitter vs a pitcher.

    Parameters
    ----------
    hitter : HitterProfile
        True-talent hitter rates (from services.true_talent).
    pitcher : PitcherProfile
        True-talent pitcher rates (from services.true_talent).
    park_hr_factor : float
        Park HR factor (1.0 = neutral). From ``get_park_factors()``.
    park_runs_factor : float
        Park runs factor (1.0 = neutral).
    weather_mult : float
        Weather run multiplier (from projections._weather_run_mult).

    Returns
    -------
    MatchupRates
        Combined, adjusted per-PA outcome rates.
    """
    lg = _load_league_averages()
    lg_hit = lg.get("hitting", {})
    lg_pit = lg.get("pitching", {})

    # League baseline rates
    lg_k = lg_hit.get("k_rate", 0.223)
    lg_bb = lg_hit.get("bb_rate", 0.083)
    lg_hbp = lg_hit.get("hbp_rate", 0.012)
    lg_hr_per_contact = lg_hit.get("hr_per_contact", 0.038)

    # Convert pitcher HR/BF to HR/contact for odds-ratio compatibility
    pitcher_contact_rate = 1.0 - pitcher.k_rate - pitcher.bb_rate - pitcher.hbp_rate
    if pitcher_contact_rate > 0.05:
        pitcher_hr_per_contact = pitcher.hr_per_bf / pitcher_contact_rate
    else:
        pitcher_hr_per_contact = lg_hr_per_contact

    # --- Odds-ratio combinations ---
    k_rate = _odds_ratio(hitter.k_rate, pitcher.k_rate, lg_k)
    bb_rate = _odds_ratio(hitter.bb_rate, pitcher.bb_rate, lg_bb)
    hbp_rate = _odds_ratio(hitter.hbp_rate, pitcher.hbp_rate, lg_hbp)
    hr_per_contact = _odds_ratio(hitter.hr_per_contact, pitcher_hr_per_contact, lg_hr_per_contact)

    # For batted-ball distribution (2B, 3B, 1B) we use hitter rates directly
    # since pitcher BABIP-against doesn't break down by hit type cleanly.
    # Adjust toward league average slightly using pitcher BABIP influence.
    lg_babip = lg_hit.get("babip", 0.296)
    pit_babip = pitcher.babip_against if pitcher.babip_against > 0 else lg_babip
    babip_ratio = pit_babip / lg_babip if lg_babip > 0 else 1.0

    double_per_contact = hitter.double_per_contact * babip_ratio
    triple_per_contact = hitter.triple_per_contact * babip_ratio
    single_per_contact = hitter.single_per_contact * babip_ratio

    # Stolen bases stay with hitter (pitcher influence is minimal at this level)
    sb_rate = hitter.sb_rate

    # Run production rates — use hitter base with environment scaling
    runs_per_pa = hitter.runs_per_pa
    rbi_per_pa = hitter.rbi_per_pa

    # --- Platoon adjustment ---
    bat = hitter.bat_side.upper() if hitter.bat_side else ""
    throw = pitcher.pitch_hand.upper() if pitcher.pitch_hand else ""

    if bat and throw:
        if bat == "S":
            # Switch hitter: platoon advantage vs RHP, slight edge vs LHP
            if throw == "R":
                hr_per_contact *= 1.08
                double_per_contact *= 1.08
                k_rate *= 0.95
            else:
                # vs LHP — slight advantage (not full platoon)
                hr_per_contact *= 1.03
                double_per_contact *= 1.03
                k_rate *= 0.98
        elif bat != throw:
            # Opposite hand = platoon advantage
            hr_per_contact *= 1.08
            double_per_contact *= 1.08
            k_rate *= 0.95
        else:
            # Same hand = platoon disadvantage
            hr_per_contact *= 0.92
            double_per_contact *= 0.92
            k_rate *= 1.05

    # --- Park factors ---
    hr_per_contact *= park_hr_factor
    runs_per_pa *= park_runs_factor
    rbi_per_pa *= park_runs_factor

    # --- Weather ---
    hr_per_contact *= weather_mult
    runs_per_pa *= weather_mult
    rbi_per_pa *= weather_mult

    # --- Clamp all rates ---
    return MatchupRates(
        k_rate=_clamp(k_rate, *_RATE_BOUNDS["k_rate"]),
        bb_rate=_clamp(bb_rate, *_RATE_BOUNDS["bb_rate"]),
        hbp_rate=_clamp(hbp_rate, *_RATE_BOUNDS["hbp_rate"]),
        hr_per_contact=_clamp(hr_per_contact, *_RATE_BOUNDS["hr_per_contact"]),
        triple_per_contact=_clamp(triple_per_contact, *_RATE_BOUNDS["triple_per_contact"]),
        double_per_contact=_clamp(double_per_contact, *_RATE_BOUNDS["double_per_contact"]),
        single_per_contact=_clamp(single_per_contact, *_RATE_BOUNDS["single_per_contact"]),
        sb_rate=_clamp(sb_rate, *_RATE_BOUNDS["sb_rate"]),
        runs_per_pa=_clamp(runs_per_pa, *_RATE_BOUNDS["runs_per_pa"]),
        rbi_per_pa=_clamp(rbi_per_pa, *_RATE_BOUNDS["rbi_per_pa"]),
    )


# ---------------------------------------------------------------------------
# Park factor lookup
# ---------------------------------------------------------------------------

def get_park_factors(home_team_abbr: str) -> Tuple[float, float]:
    """Return (hr_factor, runs_factor) for a home team abbreviation.

    Falls back to (1.0, 1.0) if the team is not found.
    """
    by_team = _build_park_by_team()
    entry = by_team.get(home_team_abbr.upper(), {})
    return (
        entry.get("hr", 1.0),
        entry.get("runs", 1.0),
    )
