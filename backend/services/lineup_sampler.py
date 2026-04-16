"""Lineup sampler: generate realistic opponent fields for contest simulation.

CORE DIFFERENTIATOR
===================
This module is the novel piece of the simulator.  Rather than assuming all
opponents build lineups the same way, it models *sub-populations* of DFS
players and constructs the opponent field as a mixture of those populations.

CURRENT STATE
-------------
A **baseline implementation** using ownership-weighted random sampling.
This is sufficient to run the simulator end-to-end.

PLANNED APPROACH (v2+)
-----------------------
1. **Historical lineup corpus** -- Collect completed contest results from DK
   (via ``scripts/scrape_contest_results.py``).  Each historical lineup
   becomes a training example with features:
     - Contest: entry fee tier, field size, game type (GPP vs cash)
     - Slate: number of games, top implied run totals, pitcher mismatch count
     - Lineup: stacking pattern (which team, how many), ownership concentration
       (sum of ln(own%) across roster), salary distribution, positional allocation

2. **Sub-population clustering** -- Cluster historical lineups into archetypes:
     a) **Sharp multi-entry (ME)**: 10-150 entries, diversified, leverage-aware,
        high salary efficiency, strong correlation stacks, low ownership per lineup.
     b) **Casual single-entry (SE)**: 1 entry, "name recognition" bias, under-
        utilise salary cap, less stacking, over-own star players.
     c) **Optimizer duplicates (OPT)**: near-identical to the mathematically
        optimal lineup; cluster tightly around 1-2 builds.
     d) **Contrarian ME**: experienced ME players who deliberately fade chalk.

3. **Archetype proportions by contest type** -- Learn from historical data
   what fraction of a field is each archetype.  Key relationships:
     - Entry fee ↑ → more sharps, fewer casuals
     - Field size ↑ → more optimizer dupes (GPP whales run 150-max entries)
     - Cash vs GPP → cash is almost entirely OPT builds

4. **Stacking model** -- Non-linear relationships learned from historical data:
     - Top-3 implied run total teams get stacked at ~3x the base rate
     - Teams vs weak opposing pitchers get disproportionate stacking
     - Stack sizes: 4-man most common in GPPs, 5-man in high-end tournaments
     - "Game stack" (both sides) vs "naked" stacking patterns

5. **Ownership model** -- For each archetype, model how ownership concentrates:
     - Casual: ownership ∝ name_recognition × salary (stars get over-owned)
     - Sharp: ownership adjusted by leverage (fade high-own, boost low-own)
     - Optimizer: ownership mirrors the "default" optimizer output
     - Ownership concentration varies with slate size (fewer games = more
       concentrated ownership on fewer players)

6. **Lineup construction per archetype** -- Given the archetype, build a
   synthetic lineup:
     a) Choose a primary stack team (weighted by implied runs + archetype bias)
     b) Determine stack size (archetype-specific distribution)
     c) Fill stack positions (random from that team's batting order, top 5 first)
     d) Choose a secondary "bring-back" from the opposing team (GPP only)
     e) Fill remaining slots by ownership-weighted or value-weighted sampling

7. **Calibration** -- Validate synthetic fields against real contest results:
     - Compare projected ownership distribution to actual
     - Compare lineup diversity (unique lineup count, exposure distribution)
     - Compare score distribution percentiles

INTERFACE
---------
The function signature is stable; the implementation will evolve.
"""

from __future__ import annotations

import logging
import random
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


def generate_opponent_field(
    contest_config: dict[str, Any],
    game_slate: list[dict[str, Any]],
    player_pool: list[dict[str, Any]],
    n_lineups: int,
    site: str = "dk",
) -> list[list[dict[str, Any]]]:
    """Generate a synthetic opponent field for contest simulation.

    Parameters
    ----------
    contest_config : dict
        Contest metadata.  Expected keys:
        - entry_fee : float
        - field_size : int
        - game_type : str ('classic' or 'showdown')
        - max_entries : int
    game_slate : list of dict
        Games on the slate.  Each dict should have:
        - home_team, away_team : str
        - home_implied, away_implied : float (Vegas implied runs)
    player_pool : list of dict
        Available players.  Each dict needs:
        - id : int
        - name : str
        - team : str
        - position : str
        - salary : int
        - median_pts : float
        - projected_ownership : float (0-100 scale)
    n_lineups : int
        Number of opponent lineups to generate.
    site : str
        'dk' or 'fd'.

    Returns
    -------
    list of list of dict
        Each inner list is a lineup (list of player assignment dicts with
        keys: player_id, name, position, salary, team).
    """
    from config import DK_ROSTER_SLOTS, FD_ROSTER_SLOTS

    salary_cap = 50000 if site == "dk" else 35000
    slots = list(DK_ROSTER_SLOTS if site == "dk" else FD_ROSTER_SLOTS)

    # ── Archetype mix (v1: simple proportions based on entry fee) ──
    entry_fee = contest_config.get("entry_fee", 20)
    if entry_fee <= 5:
        casual_pct, optimizer_pct, sharp_pct = 0.60, 0.30, 0.10
    elif entry_fee <= 25:
        casual_pct, optimizer_pct, sharp_pct = 0.40, 0.35, 0.25
    else:
        casual_pct, optimizer_pct, sharp_pct = 0.20, 0.35, 0.45

    n_casual = int(n_lineups * casual_pct)
    n_optimizer = int(n_lineups * optimizer_pct)
    n_sharp = n_lineups - n_casual - n_optimizer

    lineups: list[list[dict[str, Any]]] = []

    # Generate each archetype
    for _ in range(n_casual):
        lu = _build_casual_lineup(player_pool, slots, salary_cap)
        if lu:
            lineups.append(lu)

    for _ in range(n_optimizer):
        lu = _build_optimizer_lineup(player_pool, slots, salary_cap)
        if lu:
            lineups.append(lu)

    for _ in range(n_sharp):
        lu = _build_sharp_lineup(player_pool, slots, salary_cap, game_slate)
        if lu:
            lineups.append(lu)

    # Pad if some builds failed
    attempts = 0
    while len(lineups) < n_lineups and attempts < n_lineups * 2:
        lu = _build_casual_lineup(player_pool, slots, salary_cap)
        if lu:
            lineups.append(lu)
        attempts += 1

    random.shuffle(lineups)
    logger.info(
        "Generated opponent field: %d lineups (casual=%d, opt=%d, sharp=%d)",
        len(lineups),
        n_casual,
        n_optimizer,
        n_sharp,
    )
    return lineups[:n_lineups]


# ── Archetype builders ──────────────────────────────────────────────────────


def _build_casual_lineup(
    players: list[dict[str, Any]],
    slots: list[str],
    salary_cap: int,
) -> list[dict[str, Any]] | None:
    """Casual single-entry player: ownership-weighted, imperfect salary usage.

    Casuals tend to pick recognisable names (correlated with ownership and
    salary), don't optimise salary perfectly, and rarely stack intentionally.
    """
    return _ownership_weighted_build(
        players, slots, salary_cap, ownership_power=1.5, noise=0.4
    )


def _build_optimizer_lineup(
    players: list[dict[str, Any]],
    slots: list[str],
    salary_cap: int,
) -> list[dict[str, Any]] | None:
    """Optimizer-duplicate player: value-ranked, tight salary usage.

    These are the cookie-cutter "run an optimizer and submit" builds.
    Very high projected points, use most of the salary cap.
    """
    return _value_weighted_build(players, slots, salary_cap, noise=0.1)


def _build_sharp_lineup(
    players: list[dict[str, Any]],
    slots: list[str],
    salary_cap: int,
    game_slate: list[dict[str, Any]],
) -> list[dict[str, Any]] | None:
    """Sharp multi-entry player: leverage-aware, stacking, diversified.

    Sharps intentionally stack hitters from high-implied-run teams and bring
    back opposing batters.  They also fade very high ownership.
    """
    # Pick a stack team: weight by implied runs
    team_implied: dict[str, float] = {}
    for g in game_slate:
        ht = g.get("home_team")
        at = g.get("away_team")
        if ht:
            team_implied[ht] = g.get("home_implied") or 4.5
        if at:
            team_implied[at] = g.get("away_implied") or 4.5

    if not team_implied:
        return _value_weighted_build(players, slots, salary_cap, noise=0.2)

    # Weight stacking toward high-implied teams (non-linear: cube of implied)
    teams = list(team_implied.keys())
    weights = [max(team_implied[t], 1.0) ** 3 for t in teams]
    total_w = sum(weights)
    if total_w <= 0:
        stack_team = random.choice(teams)
    else:
        stack_team = random.choices(teams, weights=weights, k=1)[0]

    # Get stack size (3-5 hitters from the stack team)
    stack_size = random.choices([3, 4, 5], weights=[0.3, 0.5, 0.2], k=1)[0]

    # Separate stack players and others
    stack_players = [
        p for p in players if p["team"] == stack_team and "P" not in p["position"].split("/")
    ]
    # Sort by batting order / projection
    stack_players.sort(key=lambda p: p.get("median_pts", 0), reverse=True)

    # Build with stack preference
    return _stacked_build(
        players, slots, salary_cap, stack_players[:stack_size * 2], stack_size, noise=0.15
    )


# ── Core building blocks ────────────────────────────────────────────────────


def _eligible_for_slot(player: dict[str, Any], slot: str) -> bool:
    """Check if a player can fill a specific roster slot."""
    positions = player["position"].split("/")
    if slot == "UTIL":
        return "P" not in positions
    if slot == "C/1B":
        return "C" in positions or "1B" in positions
    return slot in positions


def _ownership_weighted_build(
    players: list[dict[str, Any]],
    slots: list[str],
    salary_cap: int,
    ownership_power: float = 1.5,
    noise: float = 0.3,
) -> list[dict[str, Any]] | None:
    """Build a lineup with ownership-weighted player selection."""
    remaining = salary_cap
    used: set[int] = set()
    lineup: list[dict[str, Any]] = []
    shuffled_slots = list(range(len(slots)))
    random.shuffle(shuffled_slots)

    for s_idx in shuffled_slots:
        slot = slots[s_idx]
        eligible = [
            p for p in players
            if _eligible_for_slot(p, slot)
            and p["id"] not in used
            and p["salary"] <= remaining
        ]
        if not eligible:
            return None

        # Weight by ownership^power + noise
        weights = []
        for p in eligible:
            own = max(p.get("projected_ownership", 1.0), 0.1)
            w = own ** ownership_power
            w *= random.uniform(1.0 - noise, 1.0 + noise)
            weights.append(max(w, 0.01))

        total_w = sum(weights)
        chosen = random.choices(eligible, weights=weights, k=1)[0]

        lineup.append({
            "player_id": chosen["id"],
            "name": chosen["name"],
            "position": slot,
            "salary": chosen["salary"],
            "team": chosen["team"],
        })
        used.add(chosen["id"])
        remaining -= chosen["salary"]

    return lineup


def _value_weighted_build(
    players: list[dict[str, Any]],
    slots: list[str],
    salary_cap: int,
    noise: float = 0.1,
) -> list[dict[str, Any]] | None:
    """Build a lineup emphasising points-per-dollar value."""
    remaining = salary_cap
    used: set[int] = set()
    lineup: list[dict[str, Any]] = []
    shuffled_slots = list(range(len(slots)))
    random.shuffle(shuffled_slots)

    for s_idx in shuffled_slots:
        slot = slots[s_idx]
        eligible = [
            p for p in players
            if _eligible_for_slot(p, slot)
            and p["id"] not in used
            and p["salary"] <= remaining
        ]
        if not eligible:
            return None

        # Rank by value = pts / salary, with small noise
        for p in eligible:
            base = p.get("median_pts", 0) / max(p["salary"], 1) * 1000
            p["_val"] = base * random.uniform(1.0 - noise, 1.0 + noise)

        eligible.sort(key=lambda p: p["_val"], reverse=True)
        # Pick from top 3
        top = eligible[: min(3, len(eligible))]
        chosen = random.choice(top)

        lineup.append({
            "player_id": chosen["id"],
            "name": chosen["name"],
            "position": slot,
            "salary": chosen["salary"],
            "team": chosen["team"],
        })
        used.add(chosen["id"])
        remaining -= chosen["salary"]

    return lineup


def _stacked_build(
    players: list[dict[str, Any]],
    slots: list[str],
    salary_cap: int,
    stack_candidates: list[dict[str, Any]],
    stack_size: int,
    noise: float = 0.15,
) -> list[dict[str, Any]] | None:
    """Build a lineup that stacks N hitters from a preferred team.

    Falls back to value-weighted for remaining slots.
    """
    remaining = salary_cap
    used: set[int] = set()
    lineup: list[dict[str, Any]] = []
    assigned_slots: set[int] = set()

    # First, try to place stack players
    stacked = 0
    for sp in stack_candidates:
        if stacked >= stack_size:
            break
        # Find a slot this player fits
        for s_idx, slot in enumerate(slots):
            if s_idx in assigned_slots:
                continue
            if _eligible_for_slot(sp, slot) and sp["salary"] <= remaining:
                lineup.append({
                    "player_id": sp["id"],
                    "name": sp["name"],
                    "position": slot,
                    "salary": sp["salary"],
                    "team": sp["team"],
                })
                used.add(sp["id"])
                remaining -= sp["salary"]
                assigned_slots.add(s_idx)
                stacked += 1
                break

    # Fill remaining slots with value-weighted picks
    for s_idx, slot in enumerate(slots):
        if s_idx in assigned_slots:
            continue
        eligible = [
            p for p in players
            if _eligible_for_slot(p, slot)
            and p["id"] not in used
            and p["salary"] <= remaining
        ]
        if not eligible:
            return None

        for p in eligible:
            base = p.get("median_pts", 0) / max(p["salary"], 1) * 1000
            p["_val"] = base * random.uniform(1.0 - noise, 1.0 + noise)
        eligible.sort(key=lambda p: p["_val"], reverse=True)
        top = eligible[: min(4, len(eligible))]
        chosen = random.choice(top)

        lineup.append({
            "player_id": chosen["id"],
            "name": chosen["name"],
            "position": slot,
            "salary": chosen["salary"],
            "team": chosen["team"],
        })
        used.add(chosen["id"])
        remaining -= chosen["salary"]

    return lineup
