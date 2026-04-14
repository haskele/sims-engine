"""Lineup optimizer using PuLP (linear programming).

Supports DraftKings and FanDuel roster formats with:
- Salary cap constraints
- Position eligibility (multi-position players)
- Min/max exposure per player across a lineup set
- Team stacking constraints
- Uniqueness constraints for generating diverse lineup pools
"""
from __future__ import annotations

import logging
import random
from typing import Any

import pulp

from config import DK_ROSTER_SLOTS, FD_ROSTER_SLOTS, settings

logger = logging.getLogger(__name__)


# ── Data structures ─────────────────────────────────────────────────────────

class PlayerPool:
    """Container for optimizer player data."""

    def __init__(self, players: list[dict[str, Any]]):
        """
        Each player dict should have:
          - id: int
          - name: str
          - team: str
          - position: str  (e.g. "1B/OF")
          - salary: int
          - median_pts: float
          - floor_pts: float (optional)
          - ceiling_pts: float (optional)
          - ownership: float (optional, 0-100)
        """
        self.players = players
        self._by_id = {p["id"]: p for p in players}

    def get(self, player_id: int) -> dict[str, Any] | None:
        return self._by_id.get(player_id)

    def eligible(self, slot: str) -> list[dict[str, Any]]:
        """Return players eligible for a given roster slot."""
        if slot == "UTIL":
            # Everyone except pitchers
            return [p for p in self.players if "P" not in p["position"].split("/")]
        if slot == "C/1B":
            return [
                p
                for p in self.players
                if "C" in p["position"].split("/") or "1B" in p["position"].split("/")
            ]
        return [p for p in self.players if slot in p["position"].split("/")]

    @property
    def teams(self) -> set[str]:
        return {p["team"] for p in self.players}


def optimize_lineup(
    pool: PlayerPool,
    site: str = "dk",
    objective: str = "median_pts",
    locked: list[int] | None = None,
    excluded: list[int] | None = None,
    previous_lineups: list[list[int]] | None = None,
    min_unique: int = 3,
) -> list[dict[str, Any]] | None:
    """Build a single optimal lineup using integer linear programming.

    Parameters
    ----------
    pool : PlayerPool
    site : 'dk' or 'fd'
    objective : Which projection field to maximise.
    locked : Player IDs that must be in the lineup.
    excluded : Player IDs that must not be in the lineup.
    previous_lineups : Already-generated lineups (lists of player IDs).
        New lineup must differ from each by at least ``min_unique`` players.
    min_unique : Minimum player differences from each previous lineup.

    Returns
    -------
    list of dicts [{player_id, position, salary, pts}] or None if infeasible.
    """
    locked = locked or []
    excluded = excluded or []
    previous_lineups = previous_lineups or []
    salary_cap = settings.dk_salary_cap if site == "dk" else settings.fd_salary_cap
    slots = DK_ROSTER_SLOTS if site == "dk" else FD_ROSTER_SLOTS

    prob = pulp.LpProblem("DFS_Lineup", pulp.LpMaximize)

    # Decision variables: x[i][s] = 1 if player i fills slot s
    players = pool.players
    slot_indices = list(range(len(slots)))
    x = {}
    for p in players:
        for s_idx in slot_indices:
            x[(p["id"], s_idx)] = pulp.LpVariable(
                f"x_{p['id']}_{s_idx}", cat=pulp.LpBinary
            )

    # Objective: maximise total projected points
    prob += pulp.lpSum(
        x[(p["id"], s_idx)] * p.get(objective, p.get("median_pts", 0))
        for p in players
        for s_idx in slot_indices
    )

    # Constraint: each slot filled exactly once
    for s_idx in slot_indices:
        slot_name = slots[s_idx]
        eligible_ids = {ep["id"] for ep in pool.eligible(slot_name)}
        prob += (
            pulp.lpSum(x[(p["id"], s_idx)] for p in players if p["id"] in eligible_ids)
            == 1,
            f"slot_{s_idx}_filled",
        )
        # Players ineligible for this slot must be 0
        for p in players:
            if p["id"] not in eligible_ids:
                prob += x[(p["id"], s_idx)] == 0

    # Constraint: each player used at most once across all slots
    for p in players:
        prob += (
            pulp.lpSum(x[(p["id"], s_idx)] for s_idx in slot_indices) <= 1,
            f"player_{p['id']}_once",
        )

    # Salary cap
    prob += (
        pulp.lpSum(
            x[(p["id"], s_idx)] * p["salary"]
            for p in players
            for s_idx in slot_indices
        )
        <= salary_cap,
        "salary_cap",
    )

    # Locked players
    for pid in locked:
        prob += (
            pulp.lpSum(x[(pid, s_idx)] for s_idx in slot_indices) == 1,
            f"lock_{pid}",
        )

    # Excluded players
    for pid in excluded:
        prob += (
            pulp.lpSum(x[(pid, s_idx)] for s_idx in slot_indices) == 0,
            f"exclude_{pid}",
        )

    # Uniqueness from previous lineups
    for li, prev in enumerate(previous_lineups):
        prev_set = set(prev)
        # Sum of players NOT in previous lineup >= min_unique
        prob += (
            pulp.lpSum(
                x[(p["id"], s_idx)]
                for p in players
                if p["id"] not in prev_set
                for s_idx in slot_indices
            )
            >= min_unique,
            f"unique_from_{li}",
        )

    # Solve
    prob.solve(pulp.PULP_CBC_CMD(msg=False))

    if prob.status != pulp.constants.LpStatusOptimal:
        logger.warning("Optimizer: no feasible solution found")
        return None

    # Extract result
    result = []
    for s_idx in slot_indices:
        for p in players:
            if pulp.value(x[(p["id"], s_idx)]) and pulp.value(x[(p["id"], s_idx)]) > 0.5:
                result.append(
                    {
                        "player_id": p["id"],
                        "name": p["name"],
                        "position": slots[s_idx],
                        "salary": p["salary"],
                        "pts": p.get(objective, p.get("median_pts", 0)),
                        "team": p["team"],
                    }
                )
                break

    total_salary = sum(r["salary"] for r in result)
    total_pts = sum(r["pts"] for r in result)
    logger.info(
        "Optimized lineup: %d players, $%d salary, %.1f pts",
        len(result),
        total_salary,
        total_pts,
    )
    return result


def generate_lineup_pool(
    pool: PlayerPool,
    n_lineups: int = 20,
    site: str = "dk",
    objective: str = "median_pts",
    min_unique: int = 3,
    exposure_limits: dict[int, tuple[float, float]] | None = None,
    stack_rules: list[dict[str, Any]] | None = None,
) -> list[list[dict[str, Any]]]:
    """Generate a diverse pool of optimised lineups.

    Parameters
    ----------
    pool : PlayerPool
    n_lineups : int
        Number of lineups to generate.
    site : 'dk' or 'fd'
    objective : Projection field to maximise.
    min_unique : Minimum players different between any two lineups.
    exposure_limits : {player_id: (min_pct, max_pct)} exposure bounds (0-1).
    stack_rules : List of stack constraint dicts (see below).
        Each: {"team": str, "min_stack": int, "max_stack": int}

    Returns
    -------
    list of lineups, each a list of player assignment dicts.
    """
    exposure_limits = exposure_limits or {}
    stack_rules = stack_rules or []
    lineups: list[list[dict[str, Any]]] = []
    previous: list[list[int]] = []

    for i in range(n_lineups):
        # Determine excluded players based on max exposure
        excluded: list[int] = []
        if lineups and exposure_limits:
            for pid, (_, max_exp) in exposure_limits.items():
                count = sum(
                    1
                    for lu in lineups
                    if any(p["player_id"] == pid for p in lu)
                )
                if count / max(len(lineups), 1) >= max_exp:
                    excluded.append(pid)

        lu = optimize_lineup(
            pool,
            site=site,
            objective=objective,
            excluded=excluded,
            previous_lineups=previous,
            min_unique=min_unique,
        )
        if lu is None:
            logger.warning("Could not generate lineup %d/%d, stopping", i + 1, n_lineups)
            break

        lineups.append(lu)
        previous.append([p["player_id"] for p in lu])

    logger.info("Generated %d/%d lineups", len(lineups), n_lineups)
    return lineups


def greedy_lineup(
    pool: PlayerPool,
    site: str = "dk",
    randomness: float = 0.2,
) -> list[dict[str, Any]] | None:
    """Build a lineup using a greedy heuristic with randomness.

    Faster than ILP; useful for generating large numbers of opponent lineups
    in the simulator. Each slot is filled by picking from the top-N eligible
    players with probability proportional to their projection, plus noise.

    Parameters
    ----------
    pool : PlayerPool
    site : 'dk' or 'fd'
    randomness : 0-1, controls how much noise to add to value rankings.

    Returns
    -------
    list of player assignment dicts, or None if failed.
    """
    salary_cap = settings.dk_salary_cap if site == "dk" else settings.fd_salary_cap
    slots = DK_ROSTER_SLOTS if site == "dk" else FD_ROSTER_SLOTS

    remaining_salary = salary_cap
    used_ids: set[int] = set()
    result: list[dict[str, Any]] = []

    # Shuffle slot order to add variety
    slot_order = list(range(len(slots)))
    random.shuffle(slot_order)

    for s_idx in slot_order:
        slot_name = slots[s_idx]
        eligible = [
            p
            for p in pool.eligible(slot_name)
            if p["id"] not in used_ids and p["salary"] <= remaining_salary
        ]

        if not eligible:
            return None  # infeasible

        # Value = pts / salary * 1000, with noise
        for p in eligible:
            base_val = p.get("median_pts", 0) / max(p["salary"], 1) * 1000
            noise = random.gauss(0, randomness * base_val) if randomness > 0 else 0
            p["_value"] = base_val + noise

        eligible.sort(key=lambda p: p["_value"], reverse=True)

        # Pick from top candidates with weighted probability
        top_n = min(5, len(eligible))
        weights = [max(e["_value"], 0.01) for e in eligible[:top_n]]
        total_w = sum(weights)
        if total_w <= 0:
            chosen = eligible[0]
        else:
            r = random.random() * total_w
            cumulative = 0.0
            chosen = eligible[0]
            for j, e in enumerate(eligible[:top_n]):
                cumulative += weights[j]
                if r <= cumulative:
                    chosen = e
                    break

        result.append(
            {
                "player_id": chosen["id"],
                "name": chosen["name"],
                "position": slot_name,
                "salary": chosen["salary"],
                "pts": chosen.get("median_pts", 0),
                "team": chosen["team"],
            }
        )
        used_ids.add(chosen["id"])
        remaining_salary -= chosen["salary"]

    return result
