"""Opportunity model: expected plate appearances, innings pitched, and win probability.

Translates batting order position, game environment (Vegas totals), and
pitcher workload into the volume inputs the simulation engine needs.
"""
from __future__ import annotations

import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Expected PA by batting order position (9-inning MLB game averages)
EXPECTED_PA_BY_ORDER: Dict[int, float] = {
    1: 4.85,
    2: 4.75,
    3: 4.65,
    4: 4.55,
    5: 4.45,
    6: 4.35,
    7: 4.25,
    8: 4.15,
    9: 4.05,
}

_DEFAULT_PA = 4.3
_BASELINE_GAME_TOTAL = 9.0
_PA_PER_EXCESS_RUN = 0.04
_PA_FLOOR = 3.0
_PA_CEILING = 6.0

_IP_FLOOR = 3.5
_IP_CEILING = 8.0
_IP_OPP_ADJ_PER_RUN = 0.15
_BASELINE_OPP_IMPLIED = 4.5

_BF_PER_IP = 3.5  # ~3.5 batters faced per inning (accounts for baserunners)
_BF_FLOOR = 10
_BF_CEILING = 35

_WIN_PROB_DEFAULT = 0.40
_WIN_PROB_PER_RUN_DIFF = 0.05
_WIN_PROB_FLOOR = 0.15
_WIN_PROB_CEILING = 0.75


# ---------------------------------------------------------------------------
# Hitter opportunity
# ---------------------------------------------------------------------------

def expected_hitter_pa(
    batting_order: int | None,
    team_implied: float | None = None,
    game_total: float | None = None,
) -> float:
    """Estimate plate appearances for a hitter in a specific game.

    Parameters
    ----------
    batting_order : int or None
        1-9 batting order slot. None defaults to league-average PA.
    team_implied : float or None
        Team implied run total (from Vegas). Currently unused directly but
        reserved for future per-team PA modeling.
    game_total : float or None
        Over/under game total. Higher totals mean more PA for everyone.

    Returns
    -------
    float
        Expected plate appearances, clamped to [3.0, 6.0].
    """
    if batting_order is not None and batting_order in EXPECTED_PA_BY_ORDER:
        base_pa = EXPECTED_PA_BY_ORDER[batting_order]
    else:
        base_pa = _DEFAULT_PA

    # Higher game total = more PA (longer innings, more baserunners)
    excess_runs = (game_total or _BASELINE_GAME_TOTAL) - _BASELINE_GAME_TOTAL
    pa_adj = excess_runs * _PA_PER_EXCESS_RUN

    return max(_PA_FLOOR, min(_PA_CEILING, base_pa + pa_adj))


# ---------------------------------------------------------------------------
# Pitcher opportunity
# ---------------------------------------------------------------------------

def expected_pitcher_ip(
    ip_per_start: float,
    opp_implied: float | None = None,
) -> float:
    """Estimate innings pitched for a starter in a specific game.

    Parameters
    ----------
    ip_per_start : float
        Pitcher's season average IP per start.
    opp_implied : float or None
        Opposing team's implied run total. Higher = tougher matchup = fewer IP.

    Returns
    -------
    float
        Expected innings pitched, clamped to [3.5, 8.0].
    """
    ip = ip_per_start

    # Tough lineup (high opp implied) shortens outings
    opp = opp_implied if opp_implied is not None else _BASELINE_OPP_IMPLIED
    adj = (_BASELINE_OPP_IMPLIED - opp) * _IP_OPP_ADJ_PER_RUN
    ip += adj

    return max(_IP_FLOOR, min(_IP_CEILING, ip))


def expected_pitcher_bf(
    ip: float,
    k_rate: float,
    bb_rate: float,
) -> int:
    """Approximate batters faced from expected IP and rate profile.

    Uses a simple model: ~3.5 batters per IP as baseline. Pitchers with
    higher walk rates face more batters per inning.

    Parameters
    ----------
    ip : float
        Expected innings pitched.
    k_rate : float
        Pitcher strikeout rate (0-1).
    bb_rate : float
        Pitcher walk rate (0-1).

    Returns
    -------
    int
        Estimated batters faced, clamped to [10, 35].
    """
    # Base: 3 outs per inning requires ~3.3 batters at league avg
    # Add extra batters for walks (each walk adds a batter without an out)
    bf = round(ip * 3.0 + ip * (0.33 + bb_rate * 3.0))
    return max(_BF_FLOOR, min(_BF_CEILING, bf))


# ---------------------------------------------------------------------------
# Win probability
# ---------------------------------------------------------------------------

def pitcher_win_probability(
    team_implied: float | None,
    opp_implied: float | None,
) -> float:
    """Approximate pitcher win probability from Vegas implied run totals.

    Each run of implied advantage is worth roughly 5 percentage points of
    win probability. Clamped to [0.15, 0.75] — starters don't pitch the
    full game so even dominant matchups cap out.

    Parameters
    ----------
    team_implied : float or None
        Pitcher's team implied run total.
    opp_implied : float or None
        Opposing team implied run total.

    Returns
    -------
    float
        Estimated probability the pitcher earns a win.
    """
    if team_implied is None or opp_implied is None:
        return _WIN_PROB_DEFAULT

    diff = team_implied - opp_implied
    prob = 0.5 + diff * _WIN_PROB_PER_RUN_DIFF

    return max(_WIN_PROB_FLOOR, min(_WIN_PROB_CEILING, prob))
