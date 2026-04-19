"""Monte Carlo contest simulator — per-contest simulation with lineup assignment.

For each contest:
1. Build ownership-weighted opponent field.
2. Run N iterations: sample scores, score all lineups, rank, compute payouts.
3. Assign user lineups to contest entries based on which lineups perform best.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

import numpy as np

from services.lineup_sampler import generate_opponent_field, generate_ownership_field
from services.projections import sample_player_score

logger = logging.getLogger(__name__)


class SimulationConfig:
    """Configuration for a simulation run."""

    def __init__(
        self,
        sim_count: int = 10000,
        contest_config: dict[str, Any] | None = None,
        game_slate: list[dict[str, Any]] | None = None,
        player_pool: list[dict[str, Any]] | None = None,
        user_lineups: list[list[dict[str, Any]]] | None = None,
        site: str = "dk",
        pool_variance: float = 0.3,
        pool_strategy: str = "ownership",
    ):
        self.sim_count = sim_count
        self.contest_config = contest_config or {}
        self.game_slate = game_slate or []
        self.player_pool = player_pool or []
        self.user_lineups = user_lineups or []
        self.site = site
        self.pool_variance = pool_variance
        self.pool_strategy = pool_strategy

    def to_dict(self) -> dict[str, Any]:
        return {
            "sim_count": self.sim_count,
            "contest_entry_fee": self.contest_config.get("entry_fee"),
            "contest_field_size": self.contest_config.get("field_size"),
            "user_lineup_count": len(self.user_lineups),
            "site": self.site,
            "pool_variance": self.pool_variance,
            "pool_strategy": self.pool_strategy,
        }


MAX_OPPONENT_LINEUPS = 3000

class SimulationResults:
    """Aggregated simulation results for a single lineup — running aggregates, not lists."""

    def __init__(self, roi_bins: int = 20):
        self.n = 0
        self.profit_sum = 0.0
        self.cash_count = 0
        self.win_count = 0
        self.top10_count = 0
        self._profit_reservoir: list[float] = []
        self._reservoir_size = 2000

    def record(self, profit: float, cashed: bool, won: bool, top_10: bool) -> None:
        self.n += 1
        self.profit_sum += profit
        if cashed:
            self.cash_count += 1
        if won:
            self.win_count += 1
        if top_10:
            self.top10_count += 1
        if len(self._profit_reservoir) < self._reservoir_size:
            self._profit_reservoir.append(profit)
        else:
            import random
            j = random.randint(0, self.n - 1)
            if j < self._reservoir_size:
                self._profit_reservoir[j] = profit

    def summarise(self, entry_fee: float) -> dict[str, Any]:
        n = self.n
        if n == 0:
            return {
                "sim_count": 0,
                "avg_roi": 0.0,
                "cash_rate": 0.0,
                "win_rate": 0.0,
                "top_10_rate": 0.0,
                "avg_profit": 0.0,
                "median_profit": 0.0,
            }
        fee = max(entry_fee, 0.01)
        avg_profit = self.profit_sum / n
        median_profit = float(np.median(self._profit_reservoir)) if self._profit_reservoir else 0.0
        return {
            "sim_count": n,
            "avg_roi": round(avg_profit / fee * 100, 2),
            "cash_rate": round(self.cash_count / n * 100, 2),
            "win_rate": round(self.win_count / n * 100, 4),
            "top_10_rate": round(self.top10_count / n * 100, 2),
            "avg_profit": round(avg_profit, 2),
            "median_profit": round(median_profit, 2),
        }

    @property
    def entry_profits(self) -> list[float]:
        return self._profit_reservoir


def _build_payout_lookup(
    payout_structure: list[dict[str, Any]], field_size: int
) -> list[tuple[int, float]]:
    entries: list[tuple[int, float]] = []
    for item in payout_structure:
        if "maxPosition" in item:
            max_pos = item["maxPosition"]
            payout = item.get("payout", 0)
        elif "place" in item:
            max_pos = item["place"]
            payout = item.get("payout", 0)
        else:
            continue
        entries.append((max_pos, float(payout)))
    entries.sort(key=lambda x: x[0])
    return entries


def _get_payout(finish: int, payout_lookup: list[tuple[int, float]]) -> float:
    for max_pos, payout in payout_lookup:
        if finish <= max_pos:
            return payout
    return 0.0


def _score_lineup(
    lineup: list[dict[str, Any]],
    score_map: dict[int, float],
) -> float:
    total = 0.0
    for slot in lineup:
        pid = slot.get("player_id")
        if pid is not None:
            total += score_map.get(pid, 0.0)
    return total


def _precompute_lineup_matrix(
    all_lineups: list[list[dict[str, Any]]],
    pid_to_idx: dict[int, int],
    n_players: int,
) -> np.ndarray:
    """Build a (num_lineups x num_players) binary matrix for vectorized scoring."""
    n_lineups = len(all_lineups)
    matrix = np.zeros((n_lineups, n_players), dtype=np.float32)
    for lu_idx, lu in enumerate(all_lineups):
        for slot in lu:
            pid = slot.get("player_id")
            if pid is not None and pid in pid_to_idx:
                matrix[lu_idx, pid_to_idx[pid]] = 1.0
    return matrix


def run_simulation(config: SimulationConfig) -> dict[str, Any]:
    """Execute a full Monte Carlo contest simulation.

    Returns dict with: status, results per lineup, overall stats, roi distribution,
    and recommended lineup-to-entry assignments.
    """
    started = time.time()
    logger.info(
        "Starting simulation: %d sims, %d user lineups, field=%d, strategy=%s, variance=%.2f",
        config.sim_count,
        len(config.user_lineups),
        config.contest_config.get("field_size", 0),
        config.pool_strategy,
        config.pool_variance,
    )

    entry_fee = config.contest_config.get("entry_fee", 0)
    field_size = config.contest_config.get("field_size", 100)
    payout_raw = config.contest_config.get("payout_structure", [])

    if isinstance(payout_raw, str):
        payout_raw = json.loads(payout_raw)
    payout_lookup = _build_payout_lookup(payout_raw, field_size)

    # Build arrays for vectorized score sampling
    pids = []
    floors_list = []
    medians_list = []
    ceilings_list = []
    for p in config.player_pool:
        pids.append(p["id"])
        floors_list.append(p.get("floor_pts", 0.0))
        medians_list.append(p.get("median_pts", 0.0))
        ceilings_list.append(p.get("ceiling_pts", 0.0))

    pid_to_idx = {pid: i for i, pid in enumerate(pids)}
    n_players = len(pids)
    medians_arr = np.array(medians_list, dtype=np.float64)
    floors_arr = np.array(floors_list, dtype=np.float64)
    ceilings_arr = np.array(ceilings_list, dtype=np.float64)
    spreads = ceilings_arr - floors_arr
    std_devs = np.maximum(spreads / 2.0, 0.5)
    clip_lo = np.minimum(floors_arr * 0.5, 0.0)
    clip_hi = ceilings_arr * 1.5
    # Zero out std_dev for players with no ceiling
    zero_mask = ceilings_arr <= 0

    n_opponents = max(field_size - len(config.user_lineups), 1)
    n_opponents = min(n_opponents, MAX_OPPONENT_LINEUPS)
    user_count = len(config.user_lineups)

    if config.pool_strategy == "ownership":
        opponent_lineups = generate_ownership_field(
            player_pool=config.player_pool,
            n_lineups=n_opponents,
            variance=config.pool_variance,
            site=config.site,
            contest_config=config.contest_config,
        )
    else:
        opponent_lineups = generate_opponent_field(
            contest_config=config.contest_config,
            game_slate=config.game_slate,
            player_pool=config.player_pool,
            n_lineups=n_opponents,
            site=config.site,
        )

    all_lineups = config.user_lineups + opponent_lineups

    # Precompute lineup-player matrix for vectorized scoring
    lineup_matrix = _precompute_lineup_matrix(all_lineups, pid_to_idx, n_players)
    n_total_lineups = len(all_lineups)

    # Diagnostic: check user lineup diversity
    for u_idx, lu in enumerate(config.user_lineups[:5]):
        matched = sum(1 for s in lu if s.get("player_id", 0) in pid_to_idx)
        total = len(lu)
        logger.info("User lineup %d: %d/%d players matched, row sum=%.0f",
                     u_idx, matched, total, float(lineup_matrix[u_idx].sum()))
    if user_count >= 2:
        diff = float(np.sum(np.abs(lineup_matrix[0] - lineup_matrix[1])))
        logger.info("Lineup 0 vs 1 difference: %.1f slots differ", diff / 2)

    per_lineup_results: list[SimulationResults] = [
        SimulationResults() for _ in range(user_count)
    ]
    lineup_total_scores = np.zeros(user_count)

    # Vectorized payout lookup array (rank -> payout)
    # Scale sim ranks to the real field size so payouts match actual contest odds
    payout_by_rank = np.zeros(n_total_lineups + 1, dtype=np.float64)
    scale_factor = field_size / n_total_lineups if n_total_lineups > 0 else 1.0
    for rank in range(1, n_total_lineups + 1):
        scaled_rank = max(1, round(rank * scale_factor))
        payout_by_rank[rank] = _get_payout(scaled_rank, payout_lookup)

    top_10_threshold = max(1, int(field_size * 0.10 / scale_factor))

    # How many sim ranks actually cash?
    cash_positions = sum(1 for r in range(1, n_total_lineups + 1) if payout_by_rank[r] > 0)
    logger.info(
        "Payout scaling: field_size=%d, sim_lineups=%d, scale=%.2f, "
        "cash_positions=%d/%d (%.1f%%), top10_threshold=%d",
        field_size, n_total_lineups, scale_factor,
        cash_positions, n_total_lineups,
        cash_positions / max(n_total_lineups, 1) * 100,
        top_10_threshold,
    )

    max_time = 180
    actual_sims = 0
    for sim_i in range(config.sim_count):
        if sim_i > 0 and sim_i % 1000 == 0:
            elapsed_check = time.time() - started
            if elapsed_check > max_time:
                logger.warning("Simulation timed out at iteration %d / %d (%.1fs)", sim_i, config.sim_count, elapsed_check)
                break

        actual_sims += 1

        # Vectorized score sampling — one numpy call for all players
        scores = np.random.normal(medians_arr, std_devs)
        scores = np.clip(scores, clip_lo, clip_hi)
        scores[zero_mask] = 0.0

        # Matrix multiply: lineup_matrix (L x P) @ scores (P,) -> lineup_scores (L,)
        lineup_scores = lineup_matrix @ scores

        # Rank by descending score
        order = np.argsort(-lineup_scores)
        ranks = np.empty(n_total_lineups, dtype=np.int32)
        ranks[order] = np.arange(1, n_total_lineups + 1)

        # Record results for user lineups
        user_ranks = ranks[:user_count]
        user_payouts = payout_by_rank[user_ranks]
        user_profits = user_payouts - entry_fee

        for u_idx in range(user_count):
            per_lineup_results[u_idx].record(
                float(user_profits[u_idx]),
                user_payouts[u_idx] > 0,
                user_ranks[u_idx] == 1,
                int(user_ranks[u_idx]) <= top_10_threshold,
            )

        lineup_total_scores += lineup_scores[:user_count]

    # Aggregate per-lineup
    lineup_summaries = []
    for u_idx in range(user_count):
        summary = per_lineup_results[u_idx].summarise(entry_fee)
        summary["lineup_index"] = u_idx
        summary["avg_score"] = round(float(lineup_total_scores[u_idx] / max(actual_sims, 1)), 2)
        lineup_summaries.append(summary)

    # Overall (average across user lineups)
    if lineup_summaries:
        overall = {
            "avg_roi": round(float(np.mean([s["avg_roi"] for s in lineup_summaries])), 2),
            "cash_rate": round(float(np.mean([s["cash_rate"] for s in lineup_summaries])), 2),
            "win_rate": round(float(np.mean([s["win_rate"] for s in lineup_summaries])), 4),
            "top_10_rate": round(float(np.mean([s["top_10_rate"] for s in lineup_summaries])), 2),
        }
    else:
        overall = {"avg_roi": 0, "cash_rate": 0, "win_rate": 0, "top_10_rate": 0}

    # ROI distribution histogram
    all_profits = []
    for res in per_lineup_results:
        all_profits.extend(res.entry_profits)
    if all_profits:
        all_roi = np.array(all_profits) / max(entry_fee, 0.01) * 100
        hist_counts, hist_edges = np.histogram(all_roi, bins=20)
        roi_distribution = [
            {
                "bin_start": round(float(hist_edges[i]), 1),
                "bin_end": round(float(hist_edges[i + 1]), 1),
                "count": int(hist_counts[i]),
            }
            for i in range(len(hist_counts))
        ]
    else:
        roi_distribution = []

    elapsed = round(time.time() - started, 2)
    logger.info("Simulation complete in %.1fs (%d iters)", elapsed, actual_sims)

    return {
        "status": "complete",
        "elapsed_seconds": elapsed,
        "actual_sims": actual_sims,
        "overall": overall,
        "per_lineup": lineup_summaries,
        "roi_distribution": roi_distribution,
    }


def assign_lineups_to_entries(
    lineup_summaries: list[dict[str, Any]],
    n_entries: int,
) -> list[int]:
    """Assign unique lineups to contest entries by ROI rank.

    Never assigns the same lineup twice within a contest.
    If n_entries > available lineups, only the top n_lineups entries get assigned.
    """
    if not lineup_summaries:
        return [0] * min(n_entries, 1)

    ranked = sorted(lineup_summaries, key=lambda s: s["avg_roi"], reverse=True)
    assignments = []
    for i in range(min(n_entries, len(ranked))):
        assignments.append(ranked[i]["lineup_index"])
    return assignments


def assign_portfolio_lineups(
    contest_results: list[dict[str, Any]],
    n_lineups: int,
    allow_cross_contest_duplicates: bool = False,
) -> dict[str, list[int]]:
    """Assign lineups across a portfolio — no duplicates within a contest, ever.

    When allow_cross_contest_duplicates is False (default), each lineup is used
    in at most one contest across the entire portfolio. Higher-stakes contests
    get first pick.

    When True, lineups can be reused across contests but still never within
    the same contest.
    """
    if not contest_results or n_lineups == 0:
        return {}

    globally_used: set[int] = set()
    assignments: dict[str, list[int]] = {}

    sorted_contests = sorted(
        contest_results,
        key=lambda c: c.get("entry_fee", 0),
        reverse=True,
    )

    for contest in sorted_contests:
        cid = contest["contest_id"]
        n_entries = contest.get("entry_count", 0)
        per_lineup = contest.get("per_lineup", [])

        if not per_lineup or n_entries == 0:
            assignments[cid] = []
            continue

        ranked = sorted(per_lineup, key=lambda s: s.get("avg_roi", 0), reverse=True)

        contest_assignments = []
        contest_used: set[int] = set()

        for _ in range(n_entries):
            best_idx = None

            for summary in ranked:
                lu_idx = summary["lineup_index"]
                if lu_idx >= n_lineups:
                    continue
                if lu_idx in contest_used:
                    continue
                if not allow_cross_contest_duplicates and lu_idx in globally_used:
                    continue
                best_idx = lu_idx
                break

            if best_idx is None:
                break

            contest_assignments.append(best_idx)
            contest_used.add(best_idx)
            globally_used.add(best_idx)

        assignments[cid] = contest_assignments

    return assignments
