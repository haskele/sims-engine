"""Monte Carlo contest simulator.

Runs N iterations of:
1. Sample player scores from projection distributions.
2. Generate opponent field using lineup_sampler.
3. Score all lineups.
4. Apply payout structure, calculate user ROI.

Aggregates across iterations to produce: avg ROI, cash rate, win rate, std dev.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

import numpy as np

from services.lineup_sampler import generate_opponent_field
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
    ):
        self.sim_count = sim_count
        self.contest_config = contest_config or {}
        self.game_slate = game_slate or []
        self.player_pool = player_pool or []
        self.user_lineups = user_lineups or []
        self.site = site

    def to_dict(self) -> dict[str, Any]:
        return {
            "sim_count": self.sim_count,
            "contest_entry_fee": self.contest_config.get("entry_fee"),
            "contest_field_size": self.contest_config.get("field_size"),
            "user_lineup_count": len(self.user_lineups),
            "site": self.site,
        }


class SimulationResults:
    """Aggregated simulation results."""

    def __init__(self):
        self.roi_values: list[float] = []
        self.cash_flags: list[bool] = []
        self.win_flags: list[bool] = []
        self.entry_profits: list[float] = []

    def record(self, profit: float, cashed: bool, won: bool) -> None:
        self.entry_profits.append(profit)
        self.cash_flags.append(cashed)
        self.win_flags.append(won)

    def summarise(self, entry_fee: float) -> dict[str, Any]:
        n = len(self.entry_profits)
        if n == 0:
            return {
                "sim_count": 0,
                "avg_roi": 0.0,
                "roi_std": 0.0,
                "p25_roi": 0.0,
                "p75_roi": 0.0,
                "top_roi": 0.0,
                "cash_rate": 0.0,
                "win_rate": 0.0,
                "avg_profit": 0.0,
                "median_profit": 0.0,
            }
        profits = np.array(self.entry_profits)
        fee = max(entry_fee, 0.01)
        return {
            "sim_count": n,
            "avg_roi": round(float(np.mean(profits)) / fee * 100, 2),
            "roi_std": round(float(np.std(profits)) / fee * 100, 2),
            "p25_roi": round(float(np.percentile(profits, 25)) / fee * 100, 2),
            "p75_roi": round(float(np.percentile(profits, 75)) / fee * 100, 2),
            "top_roi": round(float(np.max(profits)) / fee * 100, 2),
            "cash_rate": round(sum(self.cash_flags) / n * 100, 2),
            "win_rate": round(sum(self.win_flags) / n * 100, 4),
            "avg_profit": round(float(np.mean(profits)), 2),
            "median_profit": round(float(np.median(profits)), 2),
            "p10_profit": round(float(np.percentile(profits, 10)), 2),
            "p90_profit": round(float(np.percentile(profits, 90)), 2),
        }


def _build_payout_lookup(
    payout_structure: list[dict[str, Any]], field_size: int
) -> list[tuple[int, float]]:
    """Convert a payout structure JSON into (max_place, payout) sorted list.

    Supports formats:
    - [{"minPosition": 1, "maxPosition": 1, "payout": 10000}, ...]
    - [{"place": 1, "payout": 10000}, ...]
    """
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
    """Get payout for a given finish position."""
    for max_pos, payout in payout_lookup:
        if finish <= max_pos:
            return payout
    return 0.0


def _score_lineup(
    lineup: list[dict[str, Any]],
    score_map: dict[int, float],
) -> float:
    """Sum simulated scores for all players in a lineup."""
    total = 0.0
    for slot in lineup:
        pid = slot.get("player_id")
        if pid is not None:
            total += score_map.get(pid, 0.0)
    return total


def run_simulation(config: SimulationConfig) -> dict[str, Any]:
    """Execute a full Monte Carlo contest simulation.

    Parameters
    ----------
    config : SimulationConfig

    Returns
    -------
    dict with keys: status, results, elapsed_seconds
    """
    started = time.time()
    logger.info(
        "Starting simulation: %d sims, %d user lineups, field=%d",
        config.sim_count,
        len(config.user_lineups),
        config.contest_config.get("field_size", 0),
    )

    entry_fee = config.contest_config.get("entry_fee", 0)
    field_size = config.contest_config.get("field_size", 100)
    payout_raw = config.contest_config.get("payout_structure", [])

    if isinstance(payout_raw, str):
        payout_raw = json.loads(payout_raw)
    payout_lookup = _build_payout_lookup(payout_raw, field_size)

    # Build projection lookup: player_id -> (floor, median, ceiling)
    proj_map: dict[int, tuple[float, float, float]] = {}
    for p in config.player_pool:
        proj_map[p["id"]] = (
            p.get("floor_pts", 0.0),
            p.get("median_pts", 0.0),
            p.get("ceiling_pts", 0.0),
        )

    # Number of opponent lineups to generate
    n_opponents = max(field_size - len(config.user_lineups), 1)

    # Pre-generate opponent field (same field for all sims for speed in v1;
    # v2 can re-sample per sim for more variance)
    opponent_lineups = generate_opponent_field(
        contest_config=config.contest_config,
        game_slate=config.game_slate,
        player_pool=config.player_pool,
        n_lineups=n_opponents,
        site=config.site,
    )

    all_lineups = config.user_lineups + opponent_lineups
    user_count = len(config.user_lineups)

    # Per-user-lineup results
    per_lineup_results: list[SimulationResults] = [
        SimulationResults() for _ in range(user_count)
    ]

    max_time = 180  # 3-minute safety net
    for sim_i in range(config.sim_count):
        if sim_i > 0 and sim_i % 500 == 0:
            elapsed_check = time.time() - started
            if elapsed_check > max_time:
                logger.warning("Simulation timed out at iteration %d / %d (%.1fs)", sim_i, config.sim_count, elapsed_check)
                break

        # 1. Sample scores for all players
        score_map: dict[int, float] = {}
        for pid, (floor_p, med_p, ceil_p) in proj_map.items():
            score_map[pid] = sample_player_score(floor_p, med_p, ceil_p)

        # 2. Score all lineups
        all_scores: list[tuple[int, float]] = []
        for lu_idx, lu in enumerate(all_lineups):
            pts = _score_lineup(lu, score_map)
            all_scores.append((lu_idx, pts))

        # 3. Rank by score descending
        all_scores.sort(key=lambda x: -x[1])
        rank_map: dict[int, int] = {}
        for rank, (lu_idx, _) in enumerate(all_scores, start=1):
            rank_map[lu_idx] = rank

        # 4. Calculate payouts for user lineups
        for u_idx in range(user_count):
            finish = rank_map.get(u_idx, field_size)
            payout = _get_payout(finish, payout_lookup)
            profit = payout - entry_fee
            cashed = payout > 0
            won = finish == 1
            per_lineup_results[u_idx].record(profit, cashed, won)

    # Aggregate
    lineup_summaries = []
    for u_idx in range(user_count):
        summary = per_lineup_results[u_idx].summarise(entry_fee)
        summary["lineup_index"] = u_idx
        lineup_summaries.append(summary)

    # Overall (average across user lineups)
    if lineup_summaries:
        overall = {
            "avg_roi": round(
                np.mean([s["avg_roi"] for s in lineup_summaries]), 2
            ),
            "p25_roi": round(
                np.mean([s["p25_roi"] for s in lineup_summaries]), 2
            ),
            "p75_roi": round(
                np.mean([s["p75_roi"] for s in lineup_summaries]), 2
            ),
            "top_roi": round(
                np.max([s["top_roi"] for s in lineup_summaries]), 2
            ),
            "cash_rate": round(
                np.mean([s["cash_rate"] for s in lineup_summaries]), 2
            ),
            "win_rate": round(
                np.mean([s["win_rate"] for s in lineup_summaries]), 4
            ),
        }
    else:
        overall = {"avg_roi": 0, "p25_roi": 0, "p75_roi": 0, "top_roi": 0, "cash_rate": 0, "win_rate": 0}

    # ROI distribution histogram (all user lineup profits pooled)
    all_profits = []
    for res in per_lineup_results:
        all_profits.extend(res.entry_profits)
    if all_profits:
        all_roi = np.array(all_profits) / max(entry_fee, 0.01) * 100
        # Bin into 20 buckets from min to max
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
    logger.info("Simulation complete in %.1fs", elapsed)

    return {
        "status": "complete",
        "elapsed_seconds": elapsed,
        "overall": overall,
        "per_lineup": lineup_summaries,
        "roi_distribution": roi_distribution,
    }
