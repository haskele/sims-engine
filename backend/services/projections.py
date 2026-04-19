"""Enhanced projection engine: multi-factor 3-bucket (floor/median/ceiling).

Produces quality projections for MLB hitters and pitchers using:
- Season stats (AVG, OBP, SLG, wOBA, ISO, K%, BB%, HR/FB)
- Recent game logs (last 14 games) for hot/cold streaks
- Career splits vs LHP/RHP
- Batting order position
- Team implied run total (Vegas)
- Park factors (all 30 stadiums)
- Weather adjustments (temperature, wind)
- DK and FD scoring calculated separately

For pitchers:
- Season stats (ERA, WHIP, K/9, BB/9, FIP, HR/9, IP/GS)
- Recent starts (last 5)
- Opposing team offence quality
- Park/weather factors
"""
from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from config import (
    DK_HITTER_SCORING,
    DK_PITCHER_SCORING,
    FD_HITTER_SCORING,
    FD_PITCHER_SCORING,
)
from services.mlb_stats import (
    calculate_dk_hitter_points,
    calculate_dk_pitcher_points,
    calculate_fd_hitter_points,
    calculate_fd_pitcher_points,
    get_player_game_log,
    get_player_season_stats,
)

logger = logging.getLogger(__name__)

# ── Park factors ──────────────────────────────────────────────────────────────

_PARK_FACTORS: Optional[Dict[str, Any]] = None


def _load_park_factors() -> Dict[str, Any]:
    global _PARK_FACTORS
    if _PARK_FACTORS is not None:
        return _PARK_FACTORS
    pf_path = Path(__file__).resolve().parent.parent / "config_data" / "park_factors.json"
    if not pf_path.exists():
        pf_path = Path(__file__).resolve().parent.parent / "data" / "park_factors.json"
    try:
        with open(pf_path) as f:
            _PARK_FACTORS = json.load(f)
    except Exception as exc:
        logger.warning("Could not load park factors: %s", exc)
        _PARK_FACTORS = {}
    return _PARK_FACTORS


def get_park_factor(venue: Optional[str], factor_type: str = "runs") -> float:
    """Return the park factor for a venue.  1.0 = neutral."""
    if not venue:
        return 1.0
    pf = _load_park_factors()
    venue_lower = venue.lower()
    for park_name, info in pf.items():
        if park_name.lower() in venue_lower or venue_lower in park_name.lower():
            return info.get(factor_type, 1.0)
    return 1.0


# Build team -> park factor lookup
def _team_park_factors() -> Dict[str, Dict[str, float]]:
    pf = _load_park_factors()
    result: Dict[str, Dict[str, float]] = {}
    for park_name, info in pf.items():
        team = info.get("team", "")
        if team:
            result[team] = {"runs": info.get("runs", 1.0), "hr": info.get("hr", 1.0)}
    return result


TEAM_PARK_FACTORS = _team_park_factors()


def get_park_factor_by_team(team_abbr: Optional[str], factor_type: str = "runs") -> float:
    """Return park factor by home team abbreviation."""
    if not team_abbr:
        return 1.0
    factors = TEAM_PARK_FACTORS.get(team_abbr.upper(), {})
    return factors.get(factor_type, 1.0)


# ── Batting order adjustment ─────────────────────────────────────────────────

BATTING_ORDER_MULT: Dict[int, float] = {
    1: 1.10,
    2: 1.08,
    3: 1.12,
    4: 1.10,
    5: 1.04,
    6: 1.00,
    7: 0.96,
    8: 0.93,
    9: 0.90,
}


# ── Vegas implied runs adjustment ────────────────────────────────────────────

def _implied_run_mult(implied_runs: Optional[float]) -> float:
    """Scale projections based on team implied run total from Vegas.

    Baseline is roughly 4.5 implied runs.
    """
    if implied_runs is None:
        return 1.0
    return max(0.70, min(1.40, implied_runs / 4.5))


# ── Opposing pitcher quality adjustment ──────────────────────────────────────

def _opp_pitcher_mult(pitcher_k_per_9: Optional[float]) -> float:
    """Adjust for opposing pitcher K/9.  Higher K/9 = tougher matchup."""
    if pitcher_k_per_9 is None:
        return 1.0
    # Baseline ~8.5 K/9
    return max(0.80, min(1.20, 1.0 - (pitcher_k_per_9 - 8.5) * 0.02))


# ── Platoon / handedness split adjustment ────────────────────────────────────

def _platoon_mult(batter_hand: Optional[str], pitcher_hand: Optional[str]) -> float:
    """Adjust for platoon advantage.

    Batters facing opposite-hand pitchers get a boost; same-hand gets penalised.
    Switch hitters are neutral.
    """
    if not batter_hand or not pitcher_hand:
        return 1.0
    batter_hand = batter_hand.upper()
    pitcher_hand = pitcher_hand.upper()
    if batter_hand == "S":
        return 1.02  # Switch hitters have slight edge
    if batter_hand != pitcher_hand:
        return 1.06  # Platoon advantage
    return 0.94  # Same-hand disadvantage


# ── Weather adjustments ──────────────────────────────────────────────────────

def _weather_run_mult(temperature: Optional[float], wind_speed: Optional[float]) -> float:
    """Adjust run environment for weather.

    - Cold temps suppress offence; warm temps boost it.
    - High wind can boost HRs (we simplify to general run boost).
    """
    mult = 1.0
    if temperature is not None:
        # Baseline 72F.  Each degree below reduces runs ~0.15%, above adds ~0.15%
        temp_adj = (temperature - 72.0) * 0.0015
        mult *= (1.0 + temp_adj)
    if wind_speed is not None:
        # Wind above 10mph out to CF adds ~1% per mph
        if wind_speed > 10:
            mult *= 1.0 + (wind_speed - 10) * 0.005
    return max(0.85, min(1.20, mult))


# ── Streak / recency adjustment ──────────────────────────────────────────────

def _recency_mult(recent_fps: List[float], baseline_fps: List[float]) -> float:
    """Adjust based on recent performance vs season baseline.

    recent_fps: last 14 game fantasy point values
    baseline_fps: full season fantasy point values
    """
    if not recent_fps or not baseline_fps:
        return 1.0
    recent_avg = sum(recent_fps) / len(recent_fps)
    season_avg = sum(baseline_fps) / len(baseline_fps)
    if season_avg <= 0:
        return 1.0
    ratio = recent_avg / season_avg
    # Cap the recency impact: +/-15% max, regressed 50% toward 1.0
    raw_adj = ratio - 1.0
    regressed = raw_adj * 0.50
    return max(0.85, min(1.15, 1.0 + regressed))


# ── Season stat helpers ──────────────────────────────────────────────────────

def _parse_season_hitting(stats_data: Dict[str, Any]) -> Dict[str, float]:
    """Extract key hitting stats from MLB Stats API season response."""
    result: Dict[str, float] = {}
    for stat_block in stats_data.get("stats", []):
        for split in stat_block.get("splits", []):
            s = split.get("stat", {})
            result["avg"] = _safe_float(s.get("avg"))
            result["obp"] = _safe_float(s.get("obp"))
            result["slg"] = _safe_float(s.get("slg"))
            result["ops"] = _safe_float(s.get("ops"))
            result["strikeOuts"] = _safe_float(s.get("strikeOuts"))
            result["baseOnBalls"] = _safe_float(s.get("baseOnBalls"))
            result["atBats"] = _safe_float(s.get("atBats"))
            result["plateAppearances"] = _safe_float(s.get("plateAppearances"))
            result["homeRuns"] = _safe_float(s.get("homeRuns"))
            result["hits"] = _safe_float(s.get("hits"))
            result["doubles"] = _safe_float(s.get("doubles"))
            result["triples"] = _safe_float(s.get("triples"))
            result["stolenBases"] = _safe_float(s.get("stolenBases"))
            result["rbi"] = _safe_float(s.get("rbi"))
            result["runs"] = _safe_float(s.get("runs"))
            result["gamesPlayed"] = _safe_float(s.get("gamesPlayed"))

            # Derived stats
            pa = result.get("plateAppearances", 0)
            ab = result.get("atBats", 0)
            if pa > 0:
                result["k_pct"] = result.get("strikeOuts", 0) / pa
                result["bb_pct"] = result.get("baseOnBalls", 0) / pa
            if ab > 0:
                result["iso"] = result.get("slg", 0) - result.get("avg", 0)
            break  # Take first split
    return result


def _parse_season_pitching(stats_data: Dict[str, Any]) -> Dict[str, float]:
    """Extract key pitching stats from MLB Stats API season response."""
    result: Dict[str, float] = {}
    for stat_block in stats_data.get("stats", []):
        for split in stat_block.get("splits", []):
            s = split.get("stat", {})
            result["era"] = _safe_float(s.get("era"))
            result["whip"] = _safe_float(s.get("whip"))
            result["strikeoutsPer9Inn"] = _safe_float(s.get("strikeoutsPer9Inn"))
            result["walksPer9Inn"] = _safe_float(s.get("walksPer9Inn"))
            result["homeRunsPer9"] = _safe_float(s.get("homeRunsPer9"))
            result["strikeOuts"] = _safe_float(s.get("strikeOuts"))
            result["baseOnBalls"] = _safe_float(s.get("baseOnBalls"))
            result["hits"] = _safe_float(s.get("hits"))
            result["earnedRuns"] = _safe_float(s.get("earnedRuns"))
            result["wins"] = _safe_float(s.get("wins"))
            result["losses"] = _safe_float(s.get("losses"))
            result["gamesStarted"] = _safe_float(s.get("gamesStarted"))
            result["gamesPlayed"] = _safe_float(s.get("gamesPlayed"))
            # IP
            ip_str = str(s.get("inningsPitched", "0"))
            if "." in ip_str:
                whole, frac = ip_str.split(".")
                result["inningsPitched"] = float(whole) + float(frac) / 3.0
            else:
                result["inningsPitched"] = _safe_float(ip_str)

            # Derived
            gs = result.get("gamesStarted", 0)
            if gs > 0:
                result["ip_per_gs"] = result.get("inningsPitched", 0) / gs
            else:
                result["ip_per_gs"] = 5.5  # default

            # FIP estimate: (13*HR + 3*BB - 2*K) / IP + constant(~3.1)
            ip = result.get("inningsPitched", 0)
            if ip > 0:
                hr = _safe_float(s.get("homeRuns"))
                bb = result.get("baseOnBalls", 0)
                k = result.get("strikeOuts", 0)
                result["fip"] = (13 * hr + 3 * bb - 2 * k) / ip + 3.10
            break
    return result


def _safe_float(val: Any) -> float:
    """Convert a value to float safely."""
    if val is None:
        return 0.0
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


# ── Hitter projection engine ─────────────────────────────────────────────────

async def build_hitter_projection(
    mlb_player_id: int,
    site: str = "dk",
    season: int = 2026,
    batting_order: Optional[int] = None,
    implied_runs: Optional[float] = None,
    opp_pitcher_k9: Optional[float] = None,
    opp_pitcher_hand: Optional[str] = None,
    batter_hand: Optional[str] = None,
    venue: Optional[str] = None,
    home_team_abbr: Optional[str] = None,
    temperature: Optional[float] = None,
    wind_speed: Optional[float] = None,
    salary: Optional[int] = None,
) -> Dict[str, Any]:
    """Build a comprehensive 3-bucket projection for a hitter.

    Returns dict with floor_pts, median_pts, ceiling_pts plus metadata.
    """
    # 1. Pull season stats
    season_stats_raw: Dict[str, Any] = {}
    try:
        season_stats_raw = await get_player_season_stats(
            mlb_player_id, season=season, group="hitting"
        )
    except Exception as exc:
        logger.debug("Season stats fetch failed for %d: %s", mlb_player_id, exc)

    season_stats = _parse_season_hitting(season_stats_raw)

    # 2. Pull game log
    game_log: List[Dict[str, Any]] = []
    try:
        game_log = await get_player_game_log(mlb_player_id, season=season, group="hitting")
    except Exception as exc:
        logger.debug("Game log fetch failed for %d: %s", mlb_player_id, exc)

    # Scoring function
    if site == "fd":
        calc_fn = calculate_fd_hitter_points
    else:
        calc_fn = calculate_dk_hitter_points

    # Calculate fantasy points for each game
    all_fps: List[float] = []
    for split in game_log:
        stat = split.get("stat", {})
        pts = calc_fn(stat)
        all_fps.append(pts)

    recent_fps = all_fps[-14:] if len(all_fps) > 14 else all_fps

    # 3. Base projection from game log distribution
    if all_fps:
        fp_sorted = sorted(all_fps)
        n = len(fp_sorted)
        third = max(1, n // 3)

        floor_games = fp_sorted[:third]
        middle_games = fp_sorted[third:third * 2]
        ceiling_games = fp_sorted[third * 2:]

        floor_pts = float(np.mean(floor_games)) if floor_games else 0.0
        median_pts = float(np.mean(middle_games)) if middle_games else 0.0
        ceiling_pts = float(np.mean(ceiling_games)) if ceiling_games else 0.0
    else:
        # No game log: use salary-based defaults
        floor_pts, median_pts, ceiling_pts = _salary_default_hitter(salary, site)

    # 4. Apply adjustment multipliers
    adjustments: Dict[str, float] = {}

    # Batting order
    bo_mult = BATTING_ORDER_MULT.get(batting_order, 1.0) if batting_order else 1.0
    adjustments["batting_order"] = bo_mult

    # Implied runs
    ir_mult = _implied_run_mult(implied_runs)
    adjustments["implied_runs"] = ir_mult

    # Opposing pitcher
    op_mult = _opp_pitcher_mult(opp_pitcher_k9)
    adjustments["opp_pitcher"] = op_mult

    # Platoon
    plat_mult = _platoon_mult(batter_hand, opp_pitcher_hand)
    adjustments["platoon"] = plat_mult

    # Park factor
    pf_mult = get_park_factor(venue, "runs")
    if pf_mult == 1.0 and home_team_abbr:
        pf_mult = get_park_factor_by_team(home_team_abbr, "runs")
    adjustments["park_factor"] = pf_mult

    # Weather
    wx_mult = _weather_run_mult(temperature, wind_speed)
    adjustments["weather"] = wx_mult

    # Recency / streaks
    rec_mult = _recency_mult(recent_fps, all_fps)
    adjustments["recency"] = rec_mult

    # Combined multiplier
    combined = bo_mult * ir_mult * op_mult * plat_mult * pf_mult * wx_mult * rec_mult

    floor_pts *= combined
    median_pts *= combined
    ceiling_pts *= combined

    # Ensure floor <= median <= ceiling
    floor_pts = min(floor_pts, median_pts)
    ceiling_pts = max(ceiling_pts, median_pts)

    return {
        "floor_pts": round(floor_pts, 2),
        "median_pts": round(median_pts, 2),
        "ceiling_pts": round(ceiling_pts, 2),
        "adjustments": adjustments,
        "games_in_log": len(all_fps),
        "recent_avg": round(sum(recent_fps) / len(recent_fps), 2) if recent_fps else 0.0,
        "season_avg": round(season_stats.get("avg", 0), 3),
        "season_ops": round(season_stats.get("ops", 0), 3),
    }


def _salary_default_hitter(salary: Optional[int], site: str) -> Tuple[float, float, float]:
    """Estimate projection from salary when no game log exists."""
    if not salary or salary <= 0:
        return (0.0, 3.0, 8.0)
    if site == "fd":
        # FD salaries typically 2000-9000
        pts_per_k = 1.5
    else:
        # DK salaries typically 2000-6500
        pts_per_k = 1.8
    median = salary / 1000.0 * pts_per_k
    floor_val = median * 0.3
    ceiling_val = median * 2.2
    return (round(floor_val, 2), round(median, 2), round(ceiling_val, 2))


# ── Pitcher projection engine ────────────────────────────────────────────────

async def build_pitcher_projection(
    mlb_player_id: int,
    site: str = "dk",
    season: int = 2026,
    opp_implied_runs: Optional[float] = None,
    team_implied_runs: Optional[float] = None,
    venue: Optional[str] = None,
    home_team_abbr: Optional[str] = None,
    temperature: Optional[float] = None,
    wind_speed: Optional[float] = None,
    salary: Optional[int] = None,
) -> Dict[str, Any]:
    """Build a comprehensive 3-bucket projection for a pitcher.

    Returns dict with floor_pts, median_pts, ceiling_pts plus metadata.
    """
    # 1. Pull season stats
    season_stats_raw: Dict[str, Any] = {}
    try:
        season_stats_raw = await get_player_season_stats(
            mlb_player_id, season=season, group="pitching"
        )
    except Exception as exc:
        logger.debug("Season pitching stats failed for %d: %s", mlb_player_id, exc)

    season_stats = _parse_season_pitching(season_stats_raw)

    # 2. Pull game log (pitching starts)
    game_log: List[Dict[str, Any]] = []
    try:
        game_log = await get_player_game_log(
            mlb_player_id, season=season, group="pitching"
        )
    except Exception as exc:
        logger.debug("Pitching game log failed for %d: %s", mlb_player_id, exc)

    # Scoring function
    if site == "fd":
        calc_fn = calculate_fd_pitcher_points
    else:
        calc_fn = calculate_dk_pitcher_points

    # Calculate fantasy points per start
    all_fps: List[float] = []
    for split in game_log:
        stat = split.get("stat", {})
        pts = calc_fn(stat)
        all_fps.append(pts)

    recent_fps = all_fps[-5:] if len(all_fps) > 5 else all_fps

    # 3. Base projection from game log distribution
    if all_fps:
        fp_sorted = sorted(all_fps)
        n = len(fp_sorted)
        third = max(1, n // 3)

        floor_games = fp_sorted[:third]
        middle_games = fp_sorted[third:third * 2]
        ceiling_games = fp_sorted[third * 2:]

        floor_pts = float(np.mean(floor_games)) if floor_games else 0.0
        median_pts = float(np.mean(middle_games)) if middle_games else 0.0
        ceiling_pts = float(np.mean(ceiling_games)) if ceiling_games else 0.0
    else:
        floor_pts, median_pts, ceiling_pts = _salary_default_pitcher(salary, site)

    # 4. Apply adjustments
    adjustments: Dict[str, float] = {}

    # Opposing team implied runs: lower = better for pitcher
    opp_ir_mult = 1.0
    if opp_implied_runs is not None:
        # Baseline ~4.5 runs.  Lower implied = boost pitcher
        opp_ir_mult = max(0.80, min(1.20, 1.0 + (4.5 - opp_implied_runs) * 0.04))
    adjustments["opp_implied_runs"] = opp_ir_mult

    # Pitcher's team implied runs: higher = better W probability
    team_ir_mult = 1.0
    if team_implied_runs is not None:
        # More run support = better W chance = slight boost
        team_ir_mult = max(0.95, min(1.10, 1.0 + (team_implied_runs - 4.5) * 0.015))
    adjustments["team_implied_runs"] = team_ir_mult

    # Park factor (inverted for pitchers: hitter-friendly park = bad for pitcher)
    pf_runs = get_park_factor(venue, "runs")
    if pf_runs == 1.0 and home_team_abbr:
        pf_runs = get_park_factor_by_team(home_team_abbr, "runs")
    # Invert: park factor > 1 means more runs = worse for pitcher
    pf_mult = max(0.85, min(1.15, 2.0 - pf_runs))
    adjustments["park_factor"] = pf_mult

    # Weather (inverted for pitchers)
    wx_mult = _weather_run_mult(temperature, wind_speed)
    wx_pitcher_mult = max(0.85, min(1.15, 2.0 - wx_mult))
    adjustments["weather"] = wx_pitcher_mult

    # Recency
    rec_mult = _recency_mult(recent_fps, all_fps)
    adjustments["recency"] = rec_mult

    combined = opp_ir_mult * team_ir_mult * pf_mult * wx_pitcher_mult * rec_mult

    floor_pts *= combined
    median_pts *= combined
    ceiling_pts *= combined

    # Ensure ordering
    floor_pts = min(floor_pts, median_pts)
    ceiling_pts = max(ceiling_pts, median_pts)

    return {
        "floor_pts": round(floor_pts, 2),
        "median_pts": round(median_pts, 2),
        "ceiling_pts": round(ceiling_pts, 2),
        "adjustments": adjustments,
        "games_in_log": len(all_fps),
        "recent_avg": round(sum(recent_fps) / len(recent_fps), 2) if recent_fps else 0.0,
        "season_era": round(season_stats.get("era", 0), 2),
        "season_k9": round(season_stats.get("strikeoutsPer9Inn", 0), 2),
        "season_whip": round(season_stats.get("whip", 0), 2),
        "ip_per_gs": round(season_stats.get("ip_per_gs", 5.5), 1),
    }


def _salary_default_pitcher(salary: Optional[int], site: str) -> Tuple[float, float, float]:
    """Estimate projection from salary when no game log exists."""
    if not salary or salary <= 0:
        return (2.0, 10.0, 22.0)
    if site == "fd":
        pts_per_k = 2.5
    else:
        pts_per_k = 2.0
    median = salary / 1000.0 * pts_per_k
    floor_val = median * 0.25
    ceiling_val = median * 2.0
    return (round(floor_val, 2), round(median, 2), round(ceiling_val, 2))


# ── Legacy wrapper (backward-compatible) ─────────────────────────────────────

async def build_player_projection(
    player_id: int,
    site: str = "dk",
    is_pitcher: bool = False,
    season: int = 2026,
    batting_order: Optional[int] = None,
    implied_runs: Optional[float] = None,
    opp_pitcher_k9: Optional[float] = None,
    game_count: int = 30,
) -> Dict[str, float]:
    """Legacy wrapper: build a 3-bucket projection for a single player.

    Delegates to the new build_hitter_projection or build_pitcher_projection
    and returns just the floor/median/ceiling values for backward compatibility.
    """
    if is_pitcher:
        result = await build_pitcher_projection(
            mlb_player_id=player_id,
            site=site,
            season=season,
            opp_implied_runs=None,
            team_implied_runs=implied_runs,
        )
    else:
        result = await build_hitter_projection(
            mlb_player_id=player_id,
            site=site,
            season=season,
            batting_order=batting_order,
            implied_runs=implied_runs,
            opp_pitcher_k9=opp_pitcher_k9,
        )
    return {
        "floor_pts": result["floor_pts"],
        "median_pts": result["median_pts"],
        "ceiling_pts": result["ceiling_pts"],
    }


# ── Score sampler (unchanged) ────────────────────────────────────────────────

def sample_player_score(
    floor_pts: float, median_pts: float, ceiling_pts: float
) -> float:
    """Sample a single simulated score from the 3-bucket projection.

    Uses a normal distribution centered on the median, with standard deviation
    derived from the floor-ceiling spread.  Clamps to [floor * 0.5, ceiling * 1.5]
    to allow some tail outcomes while staying reasonable.
    """
    if ceiling_pts <= 0:
        return 0.0

    spread = ceiling_pts - floor_pts
    std_dev = max(spread / 2.0, 0.5)

    score = float(np.random.normal(median_pts, std_dev))

    lo = min(floor_pts * 0.5, 0.0)
    hi = ceiling_pts * 1.5
    return max(lo, min(hi, round(score, 2)))
