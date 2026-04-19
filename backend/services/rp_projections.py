"""Relief pitcher projection model for the DFS simulation engine.

Projects relief pitchers by:
1. Estimating appearance probability (usage rate from game logs)
2. Applying recent-usage penalties (back-to-back days reduce likelihood)
3. Classifying RP role (closer, setup, middle, long) from salary + stats
4. Running Monte Carlo simulations for each RP
5. Blending appearance-weighted zeros with pitched-game distributions

The final projection AVERAGE includes zero-game outcomes, so an RP who
projects 8 FPTS when pitching but only appears 30% of games nets ~2.4 FPTS.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Optional

import numpy as np

from services import mlb_stats
from services.constants import normalise_dk_team as _normalise_team
from services.pa_simulator import SimulatedDistribution, _distribution_from_scores, _round_ip_to_thirds
from services.scoring import score_pitcher_statline
from services.true_talent import (
    PitcherProfile,
    batch_build_pitcher_profiles,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# RP role classifications
ROLE_CLOSER = "closer"
ROLE_SETUP = "setup"
ROLE_MIDDLE = "middle"
ROLE_LONG = "long"

# Expected IP by role (when they DO pitch)
_EXPECTED_IP_BY_ROLE = {
    ROLE_CLOSER: 1.0,
    ROLE_SETUP: 1.0,
    ROLE_MIDDLE: 0.85,
    ROLE_LONG: 2.5,
}

# IP standard deviation by role (for simulation variance)
_IP_STD_BY_ROLE = {
    ROLE_CLOSER: 0.33,
    ROLE_SETUP: 0.33,
    ROLE_MIDDLE: 0.4,
    ROLE_LONG: 0.8,
}

# Default appearance rate when no game log data available
_DEFAULT_APPEARANCE_RATE = 0.35

# Recent usage penalty multipliers applied to appearance probability
_PENALTY_PITCHED_2_CONSECUTIVE = 0.20  # 80% reduction (3-straight is very rare)
_PENALTY_PITCHED_YESTERDAY = 0.70  # 30% reduction

# Salary thresholds for role estimation (DK)
_SALARY_CLOSER_THRESHOLD = 7500
_SALARY_SETUP_THRESHOLD = 6000
_SALARY_LONG_RELIEF_FLOOR = 4500  # below this, likely low-leverage

# Minimum games for a team's season to calculate appearance rate
_MIN_TEAM_GAMES = 5

# Save opportunity threshold for closer classification
_SAVE_THRESHOLD = 3


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class RPUsageStats:
    """Usage statistics for a relief pitcher."""
    mlb_id: int
    games_appeared: int
    team_games: int
    appearance_rate: float
    saves: int
    holds: int
    avg_ip_per_appearance: float
    days_since_last_pitch: Optional[int]  # None if unknown
    pitched_yesterday: bool
    pitched_2_consecutive: bool


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def build_rp_projections(
    draftables: list[dict[str, Any]],
    salary_lookup: dict[str, dict[str, Any]],
    target_date: str,
    site: str = "dk",
    n_sims: int = 1000,
) -> list[dict[str, Any]]:
    """Generate sim-based projections for relief pitchers on a slate.

    Parameters
    ----------
    draftables : list[dict]
        DK draftable entries for RPs. Each should have keys:
        displayName, salary, teamAbbreviation, position, playerId, competition.
    salary_lookup : dict
        Full salary lookup dict keyed by player name (from pipeline).
    target_date : str
        YYYY-MM-DD date string.
    site : str
        Scoring site ('dk' or 'fd').
    n_sims : int
        Monte Carlo iterations per player.

    Returns
    -------
    list[dict]
        Projection dicts in the same format as projection_pipeline output.
    """
    if not draftables:
        return []

    logger.info("Building RP projections for %d relievers (date=%s)", len(draftables), target_date)

    # Step 1: Resolve MLB IDs and build pitcher info dicts
    rp_infos: list[dict[str, Any]] = []
    for dk in draftables:
        name = dk.get("displayName", "").strip()
        salary = dk.get("salary", 0) or 0
        team = _normalise_team(dk.get("teamAbbreviation", ""))
        dk_id = dk.get("playerId")

        # Extract opponent from competition field
        opp_team = _extract_opponent(dk, team)

        # Resolve MLB ID from salary lookup or DK data
        mlb_id = None
        sal_entry = salary_lookup.get(name)
        if sal_entry:
            mlb_id = sal_entry.get("mlb_id")

        rp_infos.append({
            "name": name,
            "mlb_id": mlb_id,
            "dk_id": dk_id,
            "team": team,
            "opp_team": opp_team,
            "salary": salary,
            "pitch_hand": "R",  # Default; updated from profile if available
        })

    # Step 2: Fetch usage stats for all RPs with MLB IDs
    rps_with_id = [r for r in rp_infos if r.get("mlb_id")]
    usage_stats: dict[int, RPUsageStats] = {}

    if rps_with_id:
        usage_stats = await _batch_get_usage_stats(
            [r["mlb_id"] for r in rps_with_id],
            target_date=target_date,
        )

    # Step 3: Build true-talent pitcher profiles
    pitcher_inputs = [
        {"mlb_id": r["mlb_id"], "name": r["name"], "team": r["team"], "pitch_hand": r["pitch_hand"]}
        for r in rp_infos if r.get("mlb_id")
    ]
    pitcher_profiles: dict[int, PitcherProfile] = {}
    if pitcher_inputs:
        pitcher_profiles = await batch_build_pitcher_profiles(pitcher_inputs)

    # Step 4: Project each RP
    projections: list[dict[str, Any]] = []
    for rp in rp_infos:
        try:
            proj = _project_single_rp(
                rp_info=rp,
                profile=pitcher_profiles.get(rp.get("mlb_id")) if rp.get("mlb_id") else None,
                usage=usage_stats.get(rp.get("mlb_id")) if rp.get("mlb_id") else None,
                site=site,
                n_sims=n_sims,
            )
            if proj:
                projections.append(proj)
        except Exception as exc:
            logger.warning("RP projection failed for %s: %s", rp.get("name"), exc)

    logger.info("Generated %d RP projections", len(projections))
    return projections


# ---------------------------------------------------------------------------
# Usage stats fetcher
# ---------------------------------------------------------------------------


async def _batch_get_usage_stats(
    mlb_ids: list[int],
    target_date: str,
    season: int = 2026,
) -> dict[int, RPUsageStats]:
    """Fetch appearance rate and recent usage for multiple RPs.

    Uses the MLB Stats API game log endpoint to determine:
    - Total games appeared / team games played = appearance rate
    - Whether the RP pitched yesterday or two consecutive days
    """
    sem = asyncio.Semaphore(15)
    results: dict[int, RPUsageStats] = {}

    async def _fetch_one(mlb_id: int) -> None:
        async with sem:
            try:
                stats = await _get_rp_usage_stats(mlb_id, target_date, season)
                if stats:
                    results[mlb_id] = stats
            except Exception as exc:
                logger.debug("Usage stats fetch failed for %d: %s", mlb_id, exc)

    await asyncio.gather(*[_fetch_one(mid) for mid in mlb_ids])
    logger.info("Fetched usage stats for %d / %d RPs", len(results), len(mlb_ids))
    return results


async def _get_rp_usage_stats(
    mlb_id: int,
    target_date: str,
    season: int = 2026,
) -> Optional[RPUsageStats]:
    """Fetch appearance rate and recent usage from MLB Stats API game logs.

    Returns None if no data is available.
    """
    # Fetch pitching game log
    game_log = await mlb_stats.get_player_game_log(mlb_id, season=season, group="pitching")

    if not game_log:
        return None

    # Parse game dates and stats
    games_appeared = len(game_log)
    total_saves = 0
    total_holds = 0
    total_ip = 0.0
    game_dates: list[date] = []

    for entry in game_log:
        stat = entry.get("stat", {})
        total_saves += int(stat.get("saves", 0))
        total_holds += int(stat.get("holds", 0))

        # Parse IP
        ip_str = str(stat.get("inningsPitched", "0"))
        if "." in ip_str:
            whole, frac = ip_str.split(".", 1)
            total_ip += int(whole or 0) + int(frac or 0) / 3.0
        else:
            total_ip += float(ip_str or 0)

        # Parse game date
        game_date_str = entry.get("date")
        if game_date_str:
            try:
                game_dates.append(date.fromisoformat(game_date_str))
            except (ValueError, TypeError):
                pass

    # Calculate average IP per appearance
    avg_ip = total_ip / games_appeared if games_appeared > 0 else 1.0

    # Estimate team games played from season context
    # Use days elapsed from opening day as rough proxy, or use the log span
    ref_date = date.fromisoformat(target_date)

    # Approximate team games: MLB teams play ~162 games over ~183 days
    # ~0.89 games/day. Use the span of the game log to estimate.
    if game_dates:
        earliest = min(game_dates)
        days_elapsed = (ref_date - earliest).days
        # MLB averages about 0.89 games per day
        team_games = max(int(days_elapsed * 0.89), games_appeared, _MIN_TEAM_GAMES)
    else:
        team_games = max(games_appeared * 3, _MIN_TEAM_GAMES)  # Conservative estimate

    appearance_rate = games_appeared / team_games if team_games > 0 else _DEFAULT_APPEARANCE_RATE
    # Clamp to reasonable range
    appearance_rate = max(0.10, min(0.85, appearance_rate))

    # Determine recent usage (pitched yesterday? two consecutive days?)
    pitched_yesterday = False
    pitched_2_consecutive = False
    days_since_last = None

    if game_dates:
        sorted_dates = sorted(game_dates, reverse=True)
        yesterday = ref_date - timedelta(days=1)
        two_days_ago = ref_date - timedelta(days=2)

        if sorted_dates[0] >= yesterday:
            days_since_last = (ref_date - sorted_dates[0]).days
        else:
            days_since_last = (ref_date - sorted_dates[0]).days

        # Check if pitched yesterday
        if yesterday in sorted_dates:
            pitched_yesterday = True

        # Check if pitched two consecutive days (yesterday AND day before)
        if yesterday in sorted_dates and two_days_ago in sorted_dates:
            pitched_2_consecutive = True

    return RPUsageStats(
        mlb_id=mlb_id,
        games_appeared=games_appeared,
        team_games=team_games,
        appearance_rate=appearance_rate,
        saves=total_saves,
        holds=total_holds,
        avg_ip_per_appearance=avg_ip,
        days_since_last_pitch=days_since_last,
        pitched_yesterday=pitched_yesterday,
        pitched_2_consecutive=pitched_2_consecutive,
    )


# ---------------------------------------------------------------------------
# Role estimation
# ---------------------------------------------------------------------------


def _estimate_rp_role(
    salary: int,
    usage: Optional[RPUsageStats] = None,
) -> str:
    """Classify RP role from DK salary and usage stats.

    Role hierarchy:
    - Closer: High salary + saves history
    - Setup: Mid-high salary + holds or high appearance rate
    - Long relief: Lower salary + higher avg IP
    - Middle relief: Default/everything else

    Parameters
    ----------
    salary : int
        DK salary.
    usage : RPUsageStats, optional
        Historical usage data.

    Returns
    -------
    str
        One of ROLE_CLOSER, ROLE_SETUP, ROLE_MIDDLE, ROLE_LONG.
    """
    # If we have usage data, use saves/holds + IP to classify
    if usage:
        # Closer: meaningful save totals
        if usage.saves >= _SAVE_THRESHOLD:
            return ROLE_CLOSER
        # Setup: holds indicate late-inning work
        if usage.holds >= 3:
            return ROLE_SETUP
        # Long relief: consistently pitching 1.5+ IP per appearance
        if usage.avg_ip_per_appearance >= 1.5:
            return ROLE_LONG

    # Fall back to salary-based classification
    if salary >= _SALARY_CLOSER_THRESHOLD:
        return ROLE_CLOSER
    elif salary >= _SALARY_SETUP_THRESHOLD:
        return ROLE_SETUP
    elif salary < _SALARY_LONG_RELIEF_FLOOR:
        # Very cheap RPs could be long-relief or mop-up
        # If we have IP data suggesting longer outings, classify as long
        if usage and usage.avg_ip_per_appearance >= 1.3:
            return ROLE_LONG
        return ROLE_MIDDLE
    else:
        return ROLE_MIDDLE


# ---------------------------------------------------------------------------
# Single RP projection
# ---------------------------------------------------------------------------


def _project_single_rp(
    rp_info: dict[str, Any],
    profile: Optional[PitcherProfile],
    usage: Optional[RPUsageStats],
    site: str,
    n_sims: int,
) -> Optional[dict[str, Any]]:
    """Run simulation for one relief pitcher.

    Incorporates:
    - Appearance probability (games_appeared / team_games)
    - Recent usage penalty (back-to-back days)
    - Role-based expected IP
    - True-talent pitcher rates (or league-average defaults)

    The output distribution includes zero-point sims for non-appearance games.
    """
    name = rp_info["name"]
    team = rp_info["team"]
    opp_team = rp_info.get("opp_team")
    salary = rp_info.get("salary", 0)

    # Determine role
    role = _estimate_rp_role(salary, usage)

    # Determine appearance probability
    if usage:
        appearance_rate = usage.appearance_rate
    else:
        appearance_rate = _DEFAULT_APPEARANCE_RATE

    # Apply recent usage penalties
    if usage and usage.pitched_2_consecutive:
        appearance_rate *= _PENALTY_PITCHED_2_CONSECUTIVE
    elif usage and usage.pitched_yesterday:
        appearance_rate *= _PENALTY_PITCHED_YESTERDAY

    # Clamp after penalties
    appearance_rate = max(0.02, min(0.90, appearance_rate))

    # Determine expected IP for this role
    if usage and usage.avg_ip_per_appearance > 0:
        # Use actual average IP, but weight toward role expectation
        actual_ip = usage.avg_ip_per_appearance
        role_ip = _EXPECTED_IP_BY_ROLE[role]
        expected_ip = 0.6 * actual_ip + 0.4 * role_ip
    else:
        expected_ip = _EXPECTED_IP_BY_ROLE[role]

    # Get pitcher rates (from profile or defaults)
    if profile:
        k_rate = profile.k_rate
        bb_rate = profile.bb_rate
        hbp_rate = profile.hbp_rate
        hr_per_bf = profile.hr_per_bf
        babip = profile.babip_against
    else:
        # League-average relief pitcher defaults (slightly better than starters)
        k_rate = 0.245  # RPs typically K more than SPs
        bb_rate = 0.085
        hbp_rate = 0.010
        hr_per_bf = 0.028
        babip = 0.290

    # Run the simulation
    dist = _simulate_rp_game(
        k_rate=k_rate,
        bb_rate=bb_rate,
        hbp_rate=hbp_rate,
        hr_per_bf=hr_per_bf,
        babip=babip,
        expected_ip=expected_ip,
        ip_std=_IP_STD_BY_ROLE[role],
        appearance_rate=appearance_rate,
        role=role,
        site=site,
        n_sims=n_sims,
    )

    # Build projection dict matching pipeline format
    return {
        "player_name": name,
        "mlb_id": rp_info.get("mlb_id"),
        "dk_id": rp_info.get("dk_id"),
        "team": team,
        "position": "RP",
        "opp_team": opp_team,
        "game_pk": None,
        "venue": None,
        "salary": salary,
        "batting_order": None,
        "is_pitcher": True,
        "is_confirmed": True,
        "floor_pts": round(dist.p10, 2),
        "median_pts": round(dist.mean, 2),
        "ceiling_pts": round(dist.p90, 2),
        "projected_ownership": None,
        "season_era": None,
        "season_k9": None,
        "season_avg": None,
        "season_ops": None,
        "games_in_log": usage.games_appeared if usage else 0,
        "implied_total": None,
        "team_implied": None,
        "game_total": None,
        "temperature": None,
        "dk_std": round(dist.std, 2),
        "p85": round(dist.p90, 2),
        "p95": round(dist.ceiling, 2),
        # RP-specific metadata
        "rp_role": role,
        "appearance_rate": round(appearance_rate, 3),
        "expected_ip": round(expected_ip, 2),
        "recent_usage_penalty": _get_penalty_label(usage),
    }


# ---------------------------------------------------------------------------
# RP-specific simulation
# ---------------------------------------------------------------------------


def _simulate_rp_game(
    k_rate: float,
    bb_rate: float,
    hbp_rate: float,
    hr_per_bf: float,
    babip: float,
    expected_ip: float,
    ip_std: float,
    appearance_rate: float,
    role: str,
    site: str = "dk",
    n_sims: int = 1000,
) -> SimulatedDistribution:
    """Simulate an RP's game outcome distribution including non-appearances.

    In (1 - appearance_rate) fraction of sims, the RP gets 0 FPTS.
    In appearance_rate fraction, we simulate actual pitching outcomes.

    This means the final distribution's mean correctly reflects the
    probability-weighted expectation.
    """
    rng = np.random.default_rng()

    # Determine which sims the RP appears in
    appears = rng.random(n_sims) < appearance_rate

    # BF outcome thresholds
    k_thresh = k_rate
    bb_thresh = k_thresh + bb_rate
    hbp_thresh = bb_thresh + hbp_rate

    # Ball-in-play sub-thresholds
    bip_rate = max(0.01, 1.0 - k_thresh - bb_rate - hbp_rate)
    hr_per_bip = min(hr_per_bf / bip_rate, 0.99)

    scores = np.zeros(n_sims, dtype=np.float64)

    for i in range(n_sims):
        if not appears[i]:
            # RP doesn't pitch this game — 0 fantasy points
            scores[i] = 0.0
            continue

        # Sample IP for this appearance
        ip_raw = rng.normal(expected_ip, ip_std)
        ip_raw = max(0.0, ip_raw)
        ip = _round_ip_to_thirds(ip_raw)

        # Batters faced (roughly 3.3 per IP for relievers, slightly lower than starters)
        bf = max(1, round(ip * 3.3))

        if bf == 0:
            scores[i] = 0.0
            continue

        # Vectorized BF resolution
        rolls = rng.random(bf)

        strikeouts = int((rolls < k_thresh).sum())
        walks = int(((rolls >= k_thresh) & (rolls < bb_thresh)).sum())
        hbps = int(((rolls >= bb_thresh) & (rolls < hbp_thresh)).sum())
        n_bip = int((rolls >= hbp_thresh).sum())

        # Resolve balls in play
        home_runs = 0
        hits_bip = 0
        if n_bip > 0:
            bip_rolls = rng.random(n_bip)
            home_runs = int((bip_rolls < hr_per_bip).sum())
            remaining = int((bip_rolls >= hr_per_bip).sum())
            if remaining > 0:
                hit_rolls = rng.random(remaining)
                hits_bip = int((hit_rolls < babip).sum())

        total_hits = home_runs + hits_bip

        # Earned runs — relief pitchers typically allow clustered damage
        # Use a slightly tighter noise model than starters (shorter outings)
        er_expected = 0.5 * hits_bip + 1.4 * home_runs + 0.33 * walks
        er_noise_std = max(0.5, er_expected * 0.4)
        er = max(0, round(rng.normal(er_expected, er_noise_std)))

        # Win: RPs rarely get wins (occasional vulture win)
        # ~5% chance for a reliever in a given appearance
        won = 1 if rng.random() < 0.05 else 0

        # Complete game / shutout / no-hitter: impossible for RPs
        statline = {
            "innings_pitched": ip,
            "strikeouts": strikeouts,
            "earned_runs": er,
            "hits_allowed": total_hits,
            "walks_allowed": walks,
            "hbps_allowed": hbps,
            "wins": won,
            "complete_game": False,
            "shutout": False,
            "no_hitter": False,
        }
        scores[i] = score_pitcher_statline(statline, site)

    return _distribution_from_scores(scores)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_opponent(draftable: dict, player_team: str) -> Optional[str]:
    """Extract opponent team abbreviation from DK competition field."""
    comp = draftable.get("competition") or {}
    comp_name = comp.get("name", "")
    if " @ " not in comp_name:
        return None
    parts = [p.strip() for p in comp_name.split(" @ ")]
    if len(parts) != 2:
        return None
    away = _normalise_team(parts[0])
    home = _normalise_team(parts[1])
    pt = player_team.upper()
    if pt == away:
        return home
    if pt == home:
        return away
    return None


def _get_penalty_label(usage: Optional[RPUsageStats]) -> Optional[str]:
    """Return a human-readable label for any recent usage penalty applied."""
    if not usage:
        return None
    if usage.pitched_2_consecutive:
        return "pitched_2_consecutive_days"
    if usage.pitched_yesterday:
        return "pitched_yesterday"
    return None
