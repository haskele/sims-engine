"""Plate-appearance-level Monte Carlo simulator for MLB DFS projections.

Simulates individual hitter and pitcher games at the PA/BF level using
matchup-derived rates, then scores each simulated statline to produce
a full fantasy-point distribution.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

from services.scoring import score_hitter_statline, score_pitcher_statline

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# MatchupRates stub — used until the real services/matchup.py lands
# ---------------------------------------------------------------------------

try:
    from services.matchup import MatchupRates
except ImportError:
    logger.debug("services.matchup not available; using local MatchupRates stub")

    @dataclass
    class MatchupRates:  # type: ignore[no-redef]
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
# Output dataclass
# ---------------------------------------------------------------------------


@dataclass
class SimulatedDistribution:
    """Summary statistics from a Monte Carlo simulation run."""

    mean: float
    p10: float
    p25: float
    p50: float
    p75: float
    p90: float
    ceiling: float  # p99
    std: float
    floor: float  # p10 (lowest reasonable outcome)

    def to_dict(self) -> dict[str, float]:
        return {
            "mean": round(self.mean, 2),
            "p10": round(self.p10, 2),
            "p25": round(self.p25, 2),
            "p50": round(self.p50, 2),
            "p75": round(self.p75, 2),
            "p90": round(self.p90, 2),
            "ceiling": round(self.ceiling, 2),
            "std": round(self.std, 2),
            "floor": round(self.floor, 2),
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _distribution_from_scores(scores: np.ndarray) -> SimulatedDistribution:
    """Build a SimulatedDistribution from an array of fantasy-point scores."""
    if len(scores) == 0:
        return SimulatedDistribution(
            mean=0.0, p10=0.0, p25=0.0, p50=0.0,
            p75=0.0, p90=0.0, ceiling=0.0, std=0.0, floor=0.0,
        )
    return SimulatedDistribution(
        mean=float(np.mean(scores)),
        p10=float(np.percentile(scores, 10)),
        p25=float(np.percentile(scores, 25)),
        p50=float(np.percentile(scores, 50)),
        p75=float(np.percentile(scores, 75)),
        p90=float(np.percentile(scores, 90)),
        ceiling=float(np.percentile(scores, 99)),
        std=float(np.std(scores)),
        floor=float(np.percentile(scores, 10)),
    )


def _round_ip_to_thirds(ip: float) -> float:
    """Round innings pitched to the nearest third (0, .33, .67)."""
    full = int(ip)
    frac = ip - full
    if frac < 0.165:
        return float(full)
    elif frac < 0.50:
        return full + 1 / 3
    else:
        return full + 2 / 3


# ---------------------------------------------------------------------------
# Hitter simulation
# ---------------------------------------------------------------------------


def simulate_hitter_game(
    matchup_rates: MatchupRates,
    expected_pa: float,
    site: str = "dk",
    n_sims: int = 1000,
    team_implied: float | None = None,
) -> SimulatedDistribution:
    """Simulate a hitter's game *n_sims* times and return the score distribution.

    Each iteration samples PA count, resolves each PA via matchup rates,
    then derives counting stats (runs, RBI, SB) and scores the line.

    Parameters
    ----------
    matchup_rates : MatchupRates
        PA-outcome probabilities for this hitter vs. the opposing pitcher.
    expected_pa : float
        Projected plate appearances (typically 3.5-4.5 for a starter).
    site : str
        Scoring site key (``"dk"`` or ``"fd"``).
    n_sims : int
        Number of Monte Carlo iterations.
    team_implied : float | None
        Team implied run total from Vegas.  Scales run/RBI expectations.

    Returns
    -------
    SimulatedDistribution
    """
    if expected_pa <= 0:
        return _distribution_from_scores(np.zeros(n_sims))

    rng = np.random.default_rng()

    # Pre-compute cumulative thresholds for PA outcomes
    k_thresh = matchup_rates.k_rate
    bb_thresh = k_thresh + matchup_rates.bb_rate
    hbp_thresh = bb_thresh + matchup_rates.hbp_rate
    # Everything beyond hbp_thresh is a ball in play

    # Contact outcome cumulative thresholds
    hr_thresh = matchup_rates.hr_per_contact
    triple_thresh = hr_thresh + matchup_rates.triple_per_contact
    double_thresh = triple_thresh + matchup_rates.double_per_contact
    single_thresh = double_thresh + matchup_rates.single_per_contact
    # Anything above single_thresh on a ball-in-play is a field out

    # Implied-run multiplier (neutral = 4.5 runs)
    implied_mult = (team_implied or 4.5) / 4.5

    # Sample PA counts for all sims at once
    pa_counts = rng.normal(expected_pa, 0.5, size=n_sims).round().clip(0).astype(int)
    max_pa = int(pa_counts.max()) if pa_counts.max() > 0 else 0

    scores = np.empty(n_sims, dtype=np.float64)

    for i in range(n_sims):
        pa = pa_counts[i]
        if pa == 0:
            scores[i] = 0.0
            continue

        # Vectorized PA resolution
        rolls = rng.random(pa)

        is_k = rolls < k_thresh
        is_bb = (~is_k) & (rolls < bb_thresh)
        is_hbp = (~is_k) & (~is_bb) & (rolls < hbp_thresh)
        is_bip = (~is_k) & (~is_bb) & (~is_hbp)  # ball in play

        n_bip = int(is_bip.sum())
        walks = int(is_bb.sum())
        hbps = int(is_hbp.sum())

        # Resolve balls in play
        singles = 0
        doubles = 0
        triples = 0
        home_runs = 0

        if n_bip > 0:
            contact_rolls = rng.random(n_bip)
            home_runs = int((contact_rolls < hr_thresh).sum())
            triples = int(((contact_rolls >= hr_thresh) & (contact_rolls < triple_thresh)).sum())
            doubles = int(((contact_rolls >= triple_thresh) & (contact_rolls < double_thresh)).sum())
            singles = int(((contact_rolls >= double_thresh) & (contact_rolls < single_thresh)).sum())
            # remainder are field outs

        # Runs and RBI via scaled Poisson
        exp_runs = matchup_rates.runs_per_pa * pa * implied_mult
        runs = int(rng.poisson(max(0.1, exp_runs)))

        exp_rbi = matchup_rates.rbi_per_pa * pa * implied_mult
        rbi = int(rng.poisson(max(0.1, exp_rbi)))
        # Every HR is at least 1 RBI
        rbi = max(rbi, home_runs)

        # Stolen bases: each time on first base (single/walk/HBP) is an SB opportunity
        times_on_first = singles + walks + hbps
        stolen_bases = 0
        if times_on_first > 0 and matchup_rates.sb_rate > 0:
            stolen_bases = int(rng.binomial(times_on_first, matchup_rates.sb_rate))

        statline = {
            "singles": singles,
            "doubles": doubles,
            "triples": triples,
            "home_runs": home_runs,
            "rbis": rbi,
            "runs": runs,
            "walks": walks,
            "hbps": hbps,
            "stolen_bases": stolen_bases,
            "caught_stealing": 0,
        }
        scores[i] = score_hitter_statline(statline, site)

    return _distribution_from_scores(scores)


# ---------------------------------------------------------------------------
# Pitcher simulation
# ---------------------------------------------------------------------------


def simulate_pitcher_game(
    pitcher_k_rate: float,
    pitcher_bb_rate: float,
    pitcher_hbp_rate: float,
    pitcher_hr_per_bf: float,
    pitcher_babip: float,
    expected_ip: float,
    expected_bf: int,
    team_implied: float | None = None,
    opp_implied: float | None = None,
    win_probability: float = 0.40,
    site: str = "dk",
    n_sims: int = 1000,
) -> SimulatedDistribution:
    """Simulate a pitcher's game *n_sims* times and return the score distribution.

    Each iteration samples IP, derives batters faced, resolves each BF via
    pitcher rates, computes earned runs, and checks for win/CG/CGSO/NH bonuses.

    Parameters
    ----------
    pitcher_k_rate : float
        Strikeout rate per batter faced.
    pitcher_bb_rate : float
        Walk rate per batter faced.
    pitcher_hbp_rate : float
        Hit-by-pitch rate per batter faced.
    pitcher_hr_per_bf : float
        Home-run rate per batter faced.
    pitcher_babip : float
        Batting average on balls in play (opponent).
    expected_ip : float
        Projected innings pitched.
    expected_bf : int
        Projected total batters faced.
    team_implied : float | None
        Pitcher's team implied run total (for win probability context).
    opp_implied : float | None
        Opposing team implied run total (unused directly in BF sim but
        available for future enhancements).
    win_probability : float
        Pre-computed probability this pitcher earns the win.
    site : str
        Scoring site key.
    n_sims : int
        Number of Monte Carlo iterations.

    Returns
    -------
    SimulatedDistribution
    """
    if expected_ip <= 0:
        return _distribution_from_scores(np.zeros(n_sims))

    rng = np.random.default_rng()

    # Cumulative BF-outcome thresholds
    k_thresh = pitcher_k_rate
    bb_thresh = k_thresh + pitcher_bb_rate
    hbp_thresh = bb_thresh + pitcher_hbp_rate
    # Beyond hbp_thresh → ball in play (HR or BABIP hit or out)

    # Ball-in-play sub-thresholds
    # pitcher_hr_per_bf is per BF, but we only apply it to BIP.
    # Convert: P(HR | BIP) = P(HR per BF) / P(BIP)
    bip_rate = max(0.01, 1.0 - k_thresh - pitcher_bb_rate - pitcher_hbp_rate)
    hr_per_bip = min(pitcher_hr_per_bf / bip_rate, 0.99)  # cap for safety

    # IP samples for all sims
    ip_raw = rng.normal(expected_ip, 1.0, size=n_sims).clip(0)

    scores = np.empty(n_sims, dtype=np.float64)

    for i in range(n_sims):
        ip = _round_ip_to_thirds(ip_raw[i])

        # Batters faced is proportional to IP (roughly 3.3 BF per IP)
        bf = max(0, round(ip * 3.3))
        if bf == 0:
            # Zero batters faced → minimal line
            statline = {
                "innings_pitched": 0.0,
                "strikeouts": 0,
                "earned_runs": 0,
                "hits_allowed": 0,
                "walks_allowed": 0,
                "hbps_allowed": 0,
                "wins": 0,
                "complete_game": False,
                "shutout": False,
                "no_hitter": False,
            }
            scores[i] = score_pitcher_statline(statline, site)
            continue

        # Vectorized BF resolution
        rolls = rng.random(bf)

        strikeouts = int((rolls < k_thresh).sum())
        walks = int(((rolls >= k_thresh) & (rolls < bb_thresh)).sum())
        hbps = int(((rolls >= bb_thresh) & (rolls < hbp_thresh)).sum())
        n_bip = int((rolls >= hbp_thresh).sum())

        # Resolve balls in play
        home_runs = 0
        hits_bip = 0  # non-HR hits
        if n_bip > 0:
            bip_rolls = rng.random(n_bip)
            home_runs = int((bip_rolls < hr_per_bip).sum())
            # Remaining BIP: BABIP determines hit vs out
            remaining = int((bip_rolls >= hr_per_bip).sum())
            if remaining > 0:
                hit_rolls = rng.random(remaining)
                hits_bip = int((hit_rolls < pitcher_babip).sum())

        total_hits = home_runs + hits_bip

        # Earned runs — run-expectancy approximation with noise
        er_expected = 0.5 * hits_bip + 1.4 * home_runs + 0.33 * walks
        er_noise_std = max(1.0, er_expected * 0.5)
        er = max(0, round(rng.normal(er_expected, er_noise_std)))

        # Win determination — need >= 5 IP and <= 3 ER (quality-start-ish)
        won = 1 if (rng.random() < win_probability and ip >= 5.0 and er <= 3) else 0

        # Bonus checks
        complete_game = ip >= 9.0
        shutout = complete_game and er == 0
        no_hitter = complete_game and total_hits == 0

        statline = {
            "innings_pitched": ip,
            "strikeouts": strikeouts,
            "earned_runs": er,
            "hits_allowed": total_hits,
            "walks_allowed": walks,
            "hbps_allowed": hbps,
            "wins": won,
            "complete_game": complete_game,
            "shutout": shutout,
            "no_hitter": no_hitter,
        }
        scores[i] = score_pitcher_statline(statline, site)

    return _distribution_from_scores(scores)
