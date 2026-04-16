"""Lineup optimizer using PuLP (linear programming).

Supports DraftKings and FanDuel roster formats with:
- Salary cap constraints
- Position eligibility (multi-position players)
- Min/max exposure per player across a lineup set
- Team stacking constraints
- Uniqueness constraints for generating diverse lineup pools

Performance: uses a hybrid approach for large pools —
  ILP for the first N lineups (exact optimal), then greedy for the rest.
  Pre-computes eligible sets and pre-filters low-projection players.
"""
from __future__ import annotations

import logging
import random
import time
from typing import Any

import pulp

from config import DK_ROSTER_SLOTS, FD_ROSTER_SLOTS, settings

logger = logging.getLogger(__name__)

# ── Tuning constants ───────────────────────────────────────────────────────
# Number of ILP solves before switching to greedy in hybrid mode
ILP_LINEUP_THRESHOLD = 20
# Percentile cutoff for pre-filtering low-projection players (0-100)
PREFILTER_PERCENTILE = 10
# Max seconds per ILP solve (safety net)
ILP_TIME_LIMIT = 5


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
        # Pre-computed eligible sets — populated lazily per slot configuration
        self._eligible_cache: dict[str, list[dict[str, Any]]] = {}

    def get(self, player_id: int) -> dict[str, Any] | None:
        return self._by_id.get(player_id)

    def eligible(self, slot: str) -> list[dict[str, Any]]:
        """Return players eligible for a given roster slot (cached)."""
        if slot in self._eligible_cache:
            return self._eligible_cache[slot]

        if slot == "UTIL":
            result = [p for p in self.players if "P" not in p["position"].split("/")]
        elif slot == "C/1B":
            result = [
                p
                for p in self.players
                if "C" in p["position"].split("/") or "1B" in p["position"].split("/")
            ]
        else:
            result = [p for p in self.players if slot in p["position"].split("/")]

        self._eligible_cache[slot] = result
        return result

    def eligible_ids(self, slot: str) -> set[int]:
        """Return set of player IDs eligible for a given roster slot (cached)."""
        cache_key = f"_ids_{slot}"
        if cache_key in self._eligible_cache:
            return self._eligible_cache[cache_key]
        ids = {p["id"] for p in self.eligible(slot)}
        self._eligible_cache[cache_key] = ids
        return ids

    @property
    def teams(self) -> set[str]:
        return {p["team"] for p in self.players}

    def prefiltered(
        self,
        slots: list[str],
        percentile: int = PREFILTER_PERCENTILE,
        locked: list[int] | None = None,
    ) -> "PlayerPool":
        """Return a smaller pool with low-projection players removed.

        Keeps any player who is:
        - Above the percentile threshold on median_pts, OR
        - The only eligible player for some slot, OR
        - In the locked set
        """
        locked_set = set(locked or [])
        pts_values = [p.get("median_pts", 0) for p in self.players]
        if not pts_values:
            return self

        pts_values.sort()
        cutoff_idx = max(0, int(len(pts_values) * percentile / 100) - 1)
        cutoff = pts_values[cutoff_idx]

        # Identify players who are the sole eligible for any slot
        essential_ids: set[int] = set()
        for slot in set(slots):
            elig = self.eligible(slot)
            if len(elig) <= 2:  # keep if very few options
                essential_ids.update(p["id"] for p in elig)

        kept = [
            p for p in self.players
            if p.get("median_pts", 0) >= cutoff
            or p["id"] in essential_ids
            or p["id"] in locked_set
        ]

        if len(kept) < len(self.players):
            logger.info(
                "Pre-filter: %d -> %d players (cutoff=%.1f pts)",
                len(self.players), len(kept), cutoff,
            )
        return PlayerPool(kept)


def _apply_skew(
    players: list[dict[str, Any]],
    objective: str,
    skew: str,
) -> dict[int, float]:
    """Compute skew-adjusted projections for each player.

    Returns a mapping of player id -> effective projection value.
    """
    result: dict[int, float] = {}
    for p in players:
        base = p.get(objective, p.get("median_pts", 0))
        if skew == "ceiling":
            ceiling = p.get("ceiling_pts", base)
            base = 0.6 * base + 0.4 * ceiling
        elif skew == "floor":
            floor = p.get("floor_pts", base)
            base = 0.6 * base + 0.4 * floor
        result[p["id"]] = base
    return result


def _apply_variance(
    effective_pts: dict[int, float],
    players: list[dict[str, Any]],
    variance: float,
) -> dict[int, float]:
    """Apply random Gaussian noise to projections based on floor/ceiling range.

    Returns a new mapping of player id -> noisy projection value.
    """
    if variance <= 0:
        return dict(effective_pts)
    noisy: dict[int, float] = {}
    for p in players:
        pid = p["id"]
        base = effective_pts[pid]
        ceiling = p.get("ceiling_pts", 0)
        floor = p.get("floor_pts", 0)
        spread = ceiling - floor
        if spread > 0:
            noise = random.gauss(0, variance * spread / 3)
        else:
            noise = 0.0
        noisy[pid] = base + noise
    return noisy


def optimize_lineup(
    pool: PlayerPool,
    site: str = "dk",
    objective: str = "median_pts",
    locked: list[int] | None = None,
    excluded: list[int] | None = None,
    previous_lineups: list[list[int]] | None = None,
    min_unique: int = 3,
    variance: float = 0.0,
    skew: str = "neutral",
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
    variance : 0.0-1.0, amount of random noise to add to projections.
    skew : 'neutral', 'ceiling', or 'floor' — blend projections toward
        ceiling or floor values before optimization.

    Returns
    -------
    list of dicts [{player_id, position, salary, pts}] or None if infeasible.
    """
    locked = locked or []
    excluded = excluded or []
    previous_lineups = previous_lineups or []
    salary_cap = settings.dk_salary_cap if site == "dk" else settings.fd_salary_cap
    slots = DK_ROSTER_SLOTS if site == "dk" else FD_ROSTER_SLOTS

    excluded_set = set(excluded)

    # Compute effective projections: skew first, then variance noise
    players = pool.players
    effective_pts = _apply_skew(players, objective, skew)
    noisy_pts = _apply_variance(effective_pts, players, variance)

    prob = pulp.LpProblem("DFS_Lineup", pulp.LpMaximize)

    # Pre-compute eligible ID sets for each slot (uses pool cache)
    slot_eligible: list[set[int]] = []
    for s_idx in range(len(slots)):
        slot_eligible.append(pool.eligible_ids(slots[s_idx]))

    # Decision variables: x[i][s] = 1 if player i fills slot s
    # Only create variables for (player, slot) pairs where the player is eligible
    slot_indices = list(range(len(slots)))
    x = {}
    for p in players:
        pid = p["id"]
        if pid in excluded_set:
            continue  # skip excluded players entirely — no variables needed
        for s_idx in slot_indices:
            if pid in slot_eligible[s_idx]:
                x[(pid, s_idx)] = pulp.LpVariable(
                    f"x_{pid}_{s_idx}", cat=pulp.LpBinary
                )

    # Objective: maximise total (noisy) projected points
    prob += pulp.lpSum(
        x[(p["id"], s_idx)] * noisy_pts[p["id"]]
        for p in players
        if p["id"] not in excluded_set
        for s_idx in slot_indices
        if (p["id"], s_idx) in x
    )

    # Constraint: each slot filled exactly once (only eligible players contribute)
    for s_idx in slot_indices:
        elig = slot_eligible[s_idx]
        prob += (
            pulp.lpSum(
                x[(p["id"], s_idx)]
                for p in players
                if p["id"] in elig and p["id"] not in excluded_set
            )
            == 1,
            f"slot_{s_idx}_filled",
        )

    # Constraint: each player used at most once across all slots
    for p in players:
        pid = p["id"]
        if pid in excluded_set:
            continue
        vars_for_player = [
            x[(pid, s_idx)] for s_idx in slot_indices if (pid, s_idx) in x
        ]
        if vars_for_player:
            prob += (
                pulp.lpSum(vars_for_player) <= 1,
                f"player_{pid}_once",
            )

    # Salary cap
    prob += (
        pulp.lpSum(
            x[(p["id"], s_idx)] * p["salary"]
            for p in players
            if p["id"] not in excluded_set
            for s_idx in slot_indices
            if (p["id"], s_idx) in x
        )
        <= salary_cap,
        "salary_cap",
    )

    # Locked players
    for pid in locked:
        vars_for_player = [
            x[(pid, s_idx)] for s_idx in slot_indices if (pid, s_idx) in x
        ]
        if vars_for_player:
            prob += (
                pulp.lpSum(vars_for_player) == 1,
                f"lock_{pid}",
            )

    # Uniqueness from previous lineups
    for li, prev in enumerate(previous_lineups):
        prev_set = set(prev)
        prob += (
            pulp.lpSum(
                x[(p["id"], s_idx)]
                for p in players
                if p["id"] not in prev_set and p["id"] not in excluded_set
                for s_idx in slot_indices
                if (p["id"], s_idx) in x
            )
            >= min_unique,
            f"unique_from_{li}",
        )

    # Solve with time limit to prevent hanging
    prob.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=ILP_TIME_LIMIT))

    if prob.status != pulp.constants.LpStatusOptimal:
        logger.warning("Optimizer: no feasible solution found (status=%d)", prob.status)
        return None

    # Extract result — report the original (un-noised) projection, not the
    # noisy value used for optimization, so the UI shows true projections.
    result = []
    for s_idx in slot_indices:
        for p in players:
            pid = p["id"]
            if (pid, s_idx) not in x:
                continue
            val = pulp.value(x[(pid, s_idx)])
            if val and val > 0.5:
                result.append(
                    {
                        "player_id": pid,
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
    locked: list[int] | None = None,
    excluded: list[int] | None = None,
    variance: float = 0.0,
    skew: str = "neutral",
    stack_exposures: dict[str, dict[int, tuple[float, float]]] | None = None,
) -> list[list[dict[str, Any]]]:
    """Generate a diverse pool of optimised lineups.

    Uses a hybrid approach for speed:
    - First ``ILP_LINEUP_THRESHOLD`` lineups via ILP (exact optimal)
    - Remaining lineups via greedy heuristic (much faster, still high quality)

    The pool is pre-filtered to remove very low-projection players, reducing
    ILP variable count significantly.

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
    locked : Player IDs that must appear in every lineup.
    excluded : Player IDs that must not appear in any lineup.
    variance : 0.0-1.0, amount of random noise to add to projections per
        lineup iteration. Creates natural diversity across the pool.
    skew : 'neutral', 'ceiling', or 'floor' — blend projections toward
        ceiling or floor values before optimization.

    Returns
    -------
    list of lineups, each a list of player assignment dicts.
    """
    t_start = time.time()
    exposure_limits = exposure_limits or {}
    stack_exposures = stack_exposures or {}
    stack_rules = stack_rules or []
    base_locked = locked or []
    base_excluded = excluded or []

    slots = DK_ROSTER_SLOTS if site == "dk" else FD_ROSTER_SLOTS

    # Pre-filter low-projection players to shrink the ILP
    filtered_pool = pool.prefiltered(slots, locked=base_locked)

    lineups: list[list[dict[str, Any]]] = []
    previous: list[list[int]] = []

    # ── Phase 1: ILP solves (exact optimal, up to threshold) ──────────────
    n_ilp = min(n_lineups, ILP_LINEUP_THRESHOLD)

    for i in range(n_ilp):
        iter_excluded = _compute_exposure_exclusions(
            base_excluded, lineups, exposure_limits
        )

        lu = optimize_lineup(
            filtered_pool,
            site=site,
            objective=objective,
            locked=base_locked,
            excluded=iter_excluded,
            previous_lineups=previous,
            min_unique=min_unique,
            variance=variance,
            skew=skew,
        )
        if lu is None:
            logger.warning("ILP: could not generate lineup %d/%d, stopping ILP phase", i + 1, n_ilp)
            break

        # Check stack exposure compliance — reject lineups that violate max stack limits
        if stack_exposures and not _lineup_stack_compliant(lu, lineups, stack_exposures, n_lineups):
            # Try a few more times with higher variance to find compliant lineup
            retry_lu = None
            for _ in range(3):
                retry_lu = optimize_lineup(
                    filtered_pool, site=site, objective=objective,
                    locked=base_locked, excluded=iter_excluded,
                    previous_lineups=previous, min_unique=min_unique,
                    variance=min(1.0, variance + 0.3), skew=skew,
                )
                if retry_lu and _lineup_stack_compliant(retry_lu, lineups, stack_exposures, n_lineups):
                    break
                retry_lu = None
            if retry_lu:
                lu = retry_lu
            # If still non-compliant, keep it anyway (best-effort)

        lineups.append(lu)
        previous.append([p["player_id"] for p in lu])

    ilp_count = len(lineups)
    ilp_elapsed = time.time() - t_start
    logger.info(
        "ILP phase: %d lineups in %.2fs (%.3fs/lineup)",
        ilp_count, ilp_elapsed, ilp_elapsed / max(ilp_count, 1),
    )

    # ── Phase 2: Greedy heuristic for remaining lineups ───────────────────
    max_total_time = 180  # 3-minute safety net for entire generation
    n_greedy = n_lineups - len(lineups)
    if n_greedy > 0:
        t_greedy = time.time()
        greedy_failures = 0
        max_greedy_failures = max(20, n_greedy // 2)

        for i in range(n_greedy):
            if time.time() - t_start > max_total_time:
                logger.warning("Greedy: hit %ds time limit at lineup %d", max_total_time, len(lineups))
                break
            if greedy_failures >= max_greedy_failures:
                logger.warning(
                    "Greedy: too many failures (%d), stopping", greedy_failures
                )
                break

            iter_excluded = _compute_exposure_exclusions(
                base_excluded, lineups, exposure_limits
            )

            # Scale randomness: start moderate, increase for later lineups
            # to push diversity
            progress = i / max(n_greedy, 1)
            randomness = 0.15 + 0.35 * progress  # 0.15 → 0.50

            lu = greedy_lineup(
                pool,
                site=site,
                randomness=randomness,
                objective=objective,
                locked=base_locked,
                excluded=iter_excluded,
                previous_lineups=previous,
                min_unique=min_unique,
            )
            if lu is None:
                greedy_failures += 1
                continue

            lineups.append(lu)
            previous.append([p["player_id"] for p in lu])

        greedy_elapsed = time.time() - t_greedy
        greedy_count = len(lineups) - ilp_count
        logger.info(
            "Greedy phase: %d lineups in %.2fs (%.3fs/lineup)",
            greedy_count, greedy_elapsed,
            greedy_elapsed / max(greedy_count, 1),
        )

    # ── Phase 3: Constraint relaxation if under target ─────────────────────
    # When exposure constraints make it impossible to generate enough lineups,
    # progressively relax them to get closer to the target count while
    # keeping lineups as optimal as possible.
    if len(lineups) < n_lineups and exposure_limits:
        shortfall = n_lineups - len(lineups)
        logger.info(
            "Relaxation: %d/%d lineups generated, attempting constraint relaxation for %d more",
            len(lineups), n_lineups, shortfall,
        )
        # Try progressively relaxed exposure limits
        for relax_step, relax_factor in enumerate([0.25, 0.50, 0.75, 1.0], 1):
            if len(lineups) >= n_lineups:
                break
            if time.time() - t_start > max_total_time:
                logger.warning("Relaxation: hit %ds time limit", max_total_time)
                break

            # Relax: scale max_exposure up toward 1.0, min_exposure down toward 0.0
            relaxed = {}
            for pid, (mn, mx) in exposure_limits.items():
                new_min = mn * (1.0 - relax_factor)
                new_max = min(1.0, mx + (1.0 - mx) * relax_factor)
                relaxed[pid] = (new_min, new_max)

            remaining = n_lineups - len(lineups)
            logger.info("Relaxation step %d (factor=%.0f%%): targeting %d more lineups",
                        relax_step, relax_factor * 100, remaining)

            greedy_failures = 0
            max_failures = max(15, remaining)

            for _ in range(remaining):
                if greedy_failures >= max_failures:
                    break
                if time.time() - t_start > max_total_time:
                    break

                iter_excluded = _compute_exposure_exclusions(
                    base_excluded, lineups, relaxed
                )
                progress = len(lineups) / max(n_lineups, 1)
                randomness = 0.15 + 0.35 * progress

                lu = greedy_lineup(
                    pool, site=site, randomness=randomness,
                    objective=objective, locked=base_locked,
                    excluded=iter_excluded, previous_lineups=previous,
                    min_unique=max(1, min_unique - relax_step),  # also relax uniqueness
                )
                if lu is None:
                    greedy_failures += 1
                    continue

                lineups.append(lu)
                previous.append([p["player_id"] for p in lu])

        if len(lineups) < n_lineups:
            logger.warning(
                "Relaxation: only generated %d/%d lineups even after full relaxation",
                len(lineups), n_lineups,
            )

    total_elapsed = time.time() - t_start
    logger.info(
        "Generated %d/%d lineups in %.2fs (%d ILP + %d greedy/relaxed)",
        len(lineups), n_lineups, total_elapsed,
        ilp_count, len(lineups) - ilp_count,
    )
    return lineups


def _compute_exposure_exclusions(
    base_excluded: list[int],
    lineups: list[list[dict[str, Any]]],
    exposure_limits: dict[int, tuple[float, float]],
) -> list[int]:
    """Determine which players to exclude based on max exposure limits."""
    iter_excluded: list[int] = list(base_excluded)
    if not lineups or not exposure_limits:
        return iter_excluded

    excluded_set = set(iter_excluded)
    n_lineups = len(lineups)

    # Pre-compute player appearance counts across all lineups
    counts: dict[int, int] = {}
    for lu in lineups:
        for p in lu:
            pid = p["player_id"]
            counts[pid] = counts.get(pid, 0) + 1

    for pid, (_, max_exp) in exposure_limits.items():
        if pid in excluded_set:
            continue
        if counts.get(pid, 0) / max(n_lineups, 1) >= max_exp:
            iter_excluded.append(pid)

    return iter_excluded


def _lineup_stack_compliant(
    lineup: list[dict[str, Any]],
    existing_lineups: list[list[dict[str, Any]]],
    stack_exposures: dict[str, dict[int, tuple[float, float]]],
    n_target: int,
) -> bool:
    """Check if adding this lineup would violate any max stack exposure limits."""
    # Count batters per team in the new lineup
    team_counts: dict[str, int] = {}
    for p in lineup:
        t = p.get("team", "")
        if t and p.get("position") != "P":
            team_counts[t] = team_counts.get(t, 0) + 1

    # Count existing stack appearances
    existing_stack_counts: dict[str, dict[int, int]] = {}
    for lu in existing_lineups:
        lu_teams: dict[str, int] = {}
        for p in lu:
            t = p.get("team", "")
            if t and p.get("position") != "P":
                lu_teams[t] = lu_teams.get(t, 0) + 1
        for t, cnt in lu_teams.items():
            if t not in existing_stack_counts:
                existing_stack_counts[t] = {}
            for sz in (3, 4, 5):
                if cnt >= sz:
                    existing_stack_counts[t][sz] = existing_stack_counts[t].get(sz, 0) + 1

    # Check if adding this lineup would exceed any max exposure
    n_after = len(existing_lineups) + 1
    for team, size_limits in stack_exposures.items():
        for sz, (_, max_pct) in size_limits.items():
            current = existing_stack_counts.get(team, {}).get(sz, 0)
            new_has_stack = team_counts.get(team, 0) >= sz
            if new_has_stack:
                if (current + 1) / n_target > max_pct:
                    return False

    return True


def _check_stack_exposures(
    lineups: list[list[dict[str, Any]]],
    stack_exposures: dict[str, dict[int, tuple[float, float]]],
    n_target: int,
) -> dict[str, dict[int, str]]:
    """Check team stack exposure compliance and return guidance.

    stack_exposures: {team: {stack_size: (min_pct, max_pct)}}

    Returns {team: {stack_size: "needs_more"|"at_max"|"ok"}} guidance dict
    for the next lineup to generate.
    """
    if not stack_exposures:
        return {}

    n_lineups = max(len(lineups), 1)
    # Count stacks per team per size across existing lineups
    stack_counts: dict[str, dict[int, int]] = {}  # team -> {size -> count}
    for lu in lineups:
        team_counts: dict[str, int] = {}
        for p in lu:
            t = p.get("team", "")
            if t and p.get("position") != "P":  # Only count batters for stacks
                team_counts[t] = team_counts.get(t, 0) + 1
        for t, cnt in team_counts.items():
            if t not in stack_counts:
                stack_counts[t] = {}
            for sz in (3, 4, 5):
                if cnt >= sz:
                    stack_counts[t][sz] = stack_counts[t].get(sz, 0) + 1

    guidance: dict[str, dict[int, str]] = {}
    for team, size_limits in stack_exposures.items():
        guidance[team] = {}
        for sz, (min_pct, max_pct) in size_limits.items():
            current_count = stack_counts.get(team, {}).get(sz, 0)
            current_pct = current_count / n_lineups
            # How many more we'd need at minimum
            needed_at_min = min_pct * n_target - current_count
            if needed_at_min > (n_target - n_lineups):
                # Must prioritize this stack
                guidance[team][sz] = "needs_more"
            elif current_pct >= max_pct:
                guidance[team][sz] = "at_max"
            else:
                guidance[team][sz] = "ok"

    return guidance


def greedy_lineup(
    pool: PlayerPool,
    site: str = "dk",
    randomness: float = 0.2,
    objective: str = "median_pts",
    locked: list[int] | None = None,
    excluded: list[int] | None = None,
    previous_lineups: list[list[int]] | None = None,
    min_unique: int = 3,
) -> list[dict[str, Any]] | None:
    """Build a lineup using a greedy heuristic with randomness.

    Faster than ILP; useful for generating large numbers of lineups.
    Each slot is filled by picking from the top-N eligible players with
    probability proportional to their projection, plus noise.

    Now supports locked/excluded players and uniqueness checks so it can
    serve as a drop-in alternative to ILP in the hybrid generator.

    Parameters
    ----------
    pool : PlayerPool
    site : 'dk' or 'fd'
    randomness : 0-1, controls how much noise to add to value rankings.
    objective : Projection field to use for value calculations.
    locked : Player IDs that must be in the lineup.
    excluded : Player IDs that must not be in the lineup.
    previous_lineups : Already-generated lineups (lists of player IDs).
    min_unique : Minimum player differences from each previous lineup.

    Returns
    -------
    list of player assignment dicts, or None if failed.
    """
    locked = locked or []
    excluded_set = set(excluded or [])
    previous_lineups = previous_lineups or []
    salary_cap = settings.dk_salary_cap if site == "dk" else settings.fd_salary_cap
    slots = DK_ROSTER_SLOTS if site == "dk" else FD_ROSTER_SLOTS

    # Multiple attempts — randomness means some attempts may fail
    for _attempt in range(10):
        lineup = _greedy_attempt(
            pool, slots, salary_cap, randomness, objective,
            locked, excluded_set, previous_lineups, min_unique,
        )
        if lineup is not None:
            return lineup

    return None


def _greedy_attempt(
    pool: PlayerPool,
    slots: list[str],
    salary_cap: int,
    randomness: float,
    objective: str,
    locked: list[int],
    excluded_set: set[int],
    previous_lineups: list[list[int]],
    min_unique: int,
) -> list[dict[str, Any]] | None:
    """Single greedy attempt — returns a lineup or None."""
    remaining_salary = salary_cap
    used_ids: set[int] = set()
    result: list[dict[str, Any]] = []

    locked_set = set(locked)
    locked_by_id = {p["id"]: p for p in pool.players if p["id"] in locked_set}

    # Shuffle slot order to add variety
    slot_order = list(range(len(slots)))
    random.shuffle(slot_order)

    # Pre-assign locked players to their first eligible slot
    locked_assigned: dict[int, int] = {}  # pid -> s_idx
    if locked_set:
        temp_order = list(slot_order)
        for pid in locked:
            player = locked_by_id.get(pid)
            if not player:
                continue
            for s_idx in temp_order:
                if s_idx in locked_assigned.values():
                    continue
                elig_ids = pool.eligible_ids(slots[s_idx])
                if pid in elig_ids:
                    locked_assigned[pid] = s_idx
                    used_ids.add(pid)
                    remaining_salary -= player["salary"]
                    result.append({
                        "player_id": pid,
                        "name": player["name"],
                        "position": slots[s_idx],
                        "salary": player["salary"],
                        "pts": player.get(objective, player.get("median_pts", 0)),
                        "team": player["team"],
                    })
                    break

    for s_idx in slot_order:
        if s_idx in locked_assigned.values():
            continue  # already filled by a locked player

        slot_name = slots[s_idx]
        eligible = [
            p
            for p in pool.eligible(slot_name)
            if p["id"] not in used_ids
            and p["id"] not in excluded_set
            and p["salary"] <= remaining_salary
        ]

        if not eligible:
            return None  # infeasible

        # Value = pts / salary * 1000, with noise
        obj_key = objective
        scored = []
        for p in eligible:
            pts = p.get(obj_key, p.get("median_pts", 0))
            base_val = pts / max(p["salary"], 1) * 1000
            noise = random.gauss(0, randomness * base_val) if randomness > 0 else 0
            scored.append((p, base_val + noise))

        scored.sort(key=lambda x: x[1], reverse=True)

        # Pick from top candidates with weighted probability
        top_n = min(5, len(scored))
        weights = [max(s[1], 0.01) for s in scored[:top_n]]
        total_w = sum(weights)
        if total_w <= 0:
            chosen = scored[0][0]
        else:
            r = random.random() * total_w
            cumulative = 0.0
            chosen = scored[0][0]
            for j in range(top_n):
                cumulative += weights[j]
                if r <= cumulative:
                    chosen = scored[j][0]
                    break

        result.append(
            {
                "player_id": chosen["id"],
                "name": chosen["name"],
                "position": slot_name,
                "salary": chosen["salary"],
                "pts": chosen.get(objective, chosen.get("median_pts", 0)),
                "team": chosen["team"],
            }
        )
        used_ids.add(chosen["id"])
        remaining_salary -= chosen["salary"]

    # Validate uniqueness against previous lineups
    if previous_lineups:
        lineup_ids = {p["player_id"] for p in result}
        for prev in previous_lineups:
            prev_set = set(prev)
            n_different = len(lineup_ids - prev_set)
            if n_different < min_unique:
                return None  # not unique enough, caller will retry

    return result
