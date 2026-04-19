"""Simulation endpoints — per-contest simulation with lineup assignment and export."""
from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

import numpy as np
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from services.simulator import SimulationConfig, run_simulation, assign_lineups_to_entries, assign_portfolio_lineups
from services.csv_projections import list_available_slates, load_csv_projections, identify_featured_csv_slate

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/simulations", tags=["simulations"])


# ── In-memory store for latest sim results per contest ──────────────────────
_sim_results: Dict[str, Dict[str, Any]] = {}


# ── Pydantic schemas ────────────────────────────────────────────────────────


class InlineContestConfig(BaseModel):
    entry_fee: float = 20.0
    field_size: int = 1000
    game_type: str = "classic"
    max_entries: int = 150
    payout_structure: List[Dict[str, Any]] = []
    contest_id: Optional[str] = None


class InlineSimulationRequest(BaseModel):
    sim_count: int = 10000
    site: str = "dk"
    slate_id: Optional[str] = None
    contest_config: InlineContestConfig
    user_lineups: List[List[Dict[str, Any]]]
    pool_variance: float = 0.3
    pool_strategy: str = "ownership"


class ContestSimRequest(BaseModel):
    """Run sims for a specific uploaded contest."""
    contest_id: str
    sim_count: int = 10000
    site: str = "dk"
    slate_id: Optional[str] = None
    user_lineups: List[List[Dict[str, Any]]]
    pool_variance: float = 0.3
    pool_strategy: str = "ownership"
    target_date: Optional[str] = None


class PortfolioContestInfo(BaseModel):
    """Contest info sent from the frontend when backend has no in-memory data."""
    contest_id: str
    contest_name: str = ""
    entry_fee: float = 20.0
    field_size: Optional[int] = None
    max_entries_per_user: Optional[int] = None
    prize_pool: Optional[float] = None
    payout_structure: Optional[List[Dict[str, Any]]] = None
    game_type: str = "classic"
    entry_count: int = 0
    entry_ids: List[str] = []


class PortfolioSimRequest(BaseModel):
    """Run sims across ALL uploaded contests at once."""
    sim_count: int = 10000
    site: str = "dk"
    slate_id: Optional[str] = None
    user_lineups: List[List[Dict[str, Any]]]
    pool_variance: float = 0.3
    pool_strategy: str = "ownership"
    target_date: Optional[str] = None
    allow_cross_contest_duplicates: bool = False
    contests: Optional[List[PortfolioContestInfo]] = None


class AssignLineupsRequest(BaseModel):
    """Assign specific lineups to entries for a contest."""
    contest_id: str
    assignments: Dict[str, int]  # entry_id -> lineup_index


class UpdateEntryLineupRequest(BaseModel):
    """Manually edit a single entry's lineup assignment."""
    contest_id: str
    entry_id: str
    lineup_index: int


# ── Helpers ─────────────────────────────────────────────────────────────────


def _load_player_pool(site: str, slate_id: Optional[str] = None, target_date: Optional[str] = None):
    """Load player pool from CSV projections, falling back to staging cache."""
    import time as _time

    try:
        d = date.fromisoformat(target_date) if target_date else None
    except ValueError:
        d = None

    # Try CSV projections first
    slates = list_available_slates(site=site, target_date=d)
    csv_path = None

    if slate_id:
        for s in slates:
            if s["slate_id"] == slate_id:
                csv_path = s["csv_path"]
                break

    if not csv_path and slates:
        featured = identify_featured_csv_slate(slates)
        if featured:
            csv_path = featured["csv_path"]

    if csv_path:
        raw_projections = load_csv_projections(csv_path, site)
        player_pool = []
        for i, p in enumerate(raw_projections):
            player_pool.append({
                "id": i + 1,
                "name": p["player_name"],
                "team": p["team"],
                "position": p["position"],
                "salary": p.get("salary", 3000),
                "floor_pts": p.get("floor_pts", 0),
                "median_pts": p.get("median_pts", 0),
                "ceiling_pts": p.get("ceiling_pts", 0),
                "projected_ownership": p.get("projected_ownership", 5.0),
            })
        return player_pool, csv_path

    # Fall back to staging projection cache
    from api.staging_projections import _projection_cache
    from api.projections import _sanitise_projection

    date_str = (d or date.today()).isoformat()
    cache_key = f"{date_str}-{site}"
    if cache_key in _projection_cache:
        ts, cached = _projection_cache[cache_key]
        if _time.time() - ts < 600:
            raw_projections = [_sanitise_projection(p) for p in cached]
            player_pool = []
            for i, p in enumerate(raw_projections):
                salary = p.get("salary") or 0
                if salary <= 0:
                    continue
                player_pool.append({
                    "id": i + 1,
                    "name": p.get("player_name", ""),
                    "team": p.get("team", ""),
                    "position": p.get("position", "UTIL"),
                    "salary": salary,
                    "floor_pts": p.get("floor_pts", 0),
                    "median_pts": p.get("median_pts", 0),
                    "ceiling_pts": p.get("ceiling_pts", 0),
                    "projected_ownership": p.get("projected_ownership", 5.0) or 5.0,
                })
            if player_pool:
                return player_pool, f"staging-cache:{cache_key}"

    return [], None


def _resolve_lineups(user_lineups, name_to_id, player_pool=None):
    """Convert user lineups to simulator format with player_id.

    Uses exact match first, then canonical name matching, then salary+team fallback.
    """
    from services.name_matching import canonical_name

    canon_to_id: Dict[str, int] = {}
    for name, pid in name_to_id.items():
        canon_to_id[canonical_name(name)] = pid

    # Build salary+team lookup as last resort
    salary_team_to_id: Dict[str, int] = {}
    if player_pool:
        for p in player_pool:
            key = f"{p.get('salary', 0)}_{p.get('team', '').lower()}"
            salary_team_to_id.setdefault(key, p["id"])

    resolved = []
    unmatched = set()
    for lu_idx, lu in enumerate(user_lineups):
        resolved_lu = []
        for slot in lu:
            raw_name = slot.get("name", "")
            pid = name_to_id.get(raw_name, 0)
            if pid == 0 and raw_name:
                pid = canon_to_id.get(canonical_name(raw_name), 0)
            if pid == 0 and raw_name:
                unmatched.add(raw_name)
            resolved_lu.append({
                "player_id": pid,
                "name": raw_name,
                "position": slot.get("position", ""),
                "salary": slot.get("salary", 0),
                "team": slot.get("team", ""),
            })
        resolved.append(resolved_lu)

    if unmatched:
        logger.warning("Unmatched players in user lineups (%d): %s", len(unmatched), list(unmatched)[:10])

    matched_counts = []
    for lu_idx, lu in enumerate(resolved):
        matched = sum(1 for s in lu if s["player_id"] != 0)
        matched_counts.append(matched)
    logger.info("Lineup resolution: %d lineups, matched players per lineup: %s", len(resolved), matched_counts)

    return resolved


# ── Endpoints ───────────────────────────────────────────────────────────────


@router.post("/run-inline")
async def run_inline_simulation(body: InlineSimulationRequest):
    """Run simulation with provided lineups and contest config (no DK entries needed)."""
    if not body.user_lineups:
        raise HTTPException(400, "No user lineups provided")

    body.sim_count = min(body.sim_count, 50000)

    player_pool, csv_path = _load_player_pool(body.site, body.slate_id)
    if not player_pool:
        raise HTTPException(400, "No projection CSV found for this slate")

    name_to_id = {p["name"]: p["id"] for p in player_pool}
    resolved_lineups = _resolve_lineups(body.user_lineups, name_to_id, player_pool)

    contest_cfg = {
        "entry_fee": body.contest_config.entry_fee,
        "field_size": body.contest_config.field_size,
        "game_type": body.contest_config.game_type,
        "max_entries": body.contest_config.max_entries,
        "payout_structure": body.contest_config.payout_structure,
    }

    sim_config = SimulationConfig(
        sim_count=body.sim_count,
        contest_config=contest_cfg,
        game_slate=[],
        player_pool=player_pool,
        user_lineups=resolved_lineups,
        site=body.site,
        pool_variance=body.pool_variance,
        pool_strategy=body.pool_strategy,
    )

    results = await asyncio.to_thread(run_simulation, sim_config)

    # Store results for potential later export
    cid = body.contest_config.contest_id or "inline"
    _sim_results[cid] = {
        "results": results,
        "user_lineups": body.user_lineups,
        "resolved_lineups": resolved_lineups,
        "player_pool": player_pool,
        "contest_config": contest_cfg,
    }

    # Auto-assign lineups to entries if contest has entries
    if body.contest_config.contest_id:
        from api.dk_entries import _current_data as dk_data
        if dk_data:
            contest_entries = [e for e in dk_data.entries if e.contest_id == body.contest_config.contest_id]
            if contest_entries and results.get("per_lineup"):
                assignments = assign_lineups_to_entries(
                    results["per_lineup"], len(contest_entries)
                )
                entry_assignments = {}
                for i, entry in enumerate(contest_entries):
                    entry_assignments[entry.entry_id] = assignments[i]
                results["entry_assignments"] = entry_assignments

    return results


@router.post("/contest-sim")
async def run_contest_simulation(body: ContestSimRequest):
    """Run simulation for a specific uploaded DK contest.

    Uses contest's field_size, entry_fee, payout_structure from uploaded data.
    Returns sim results with auto-assigned lineups to entries.
    """
    from api.dk_entries import _current_data as dk_data

    if not dk_data:
        raise HTTPException(400, "No DK entries uploaded — upload a CSV first")
    if not body.user_lineups:
        raise HTTPException(400, "No user lineups provided")

    body.sim_count = min(body.sim_count, 50000)

    contest_info = None
    for c in dk_data.contests:
        if c.contest_id == body.contest_id:
            contest_info = c
            break
    if not contest_info:
        raise HTTPException(404, f"Contest {body.contest_id} not found")

    player_pool, csv_path = _load_player_pool(body.site, body.slate_id, body.target_date)
    if not player_pool:
        raise HTTPException(400, "No projection CSV found")

    name_to_id = {p["name"]: p["id"] for p in player_pool}
    resolved_lineups = _resolve_lineups(body.user_lineups, name_to_id, player_pool)

    payout_structure = contest_info.payout_structure or []
    contest_cfg = {
        "entry_fee": contest_info.entry_fee_numeric,
        "field_size": contest_info.field_size or 1000,
        "game_type": contest_info.game_type,
        "max_entries": contest_info.max_entries_per_user or 150,
        "payout_structure": payout_structure,
    }

    sim_config = SimulationConfig(
        sim_count=body.sim_count,
        contest_config=contest_cfg,
        game_slate=[],
        player_pool=player_pool,
        user_lineups=resolved_lineups,
        site=body.site,
        pool_variance=body.pool_variance,
        pool_strategy=body.pool_strategy,
    )

    results = await asyncio.to_thread(run_simulation, sim_config)

    # Auto-assign lineups to contest entries
    contest_entries = [e for e in dk_data.entries if e.contest_id == body.contest_id]
    entry_assignments = {}
    if contest_entries and results.get("per_lineup"):
        assignments = assign_lineups_to_entries(
            results["per_lineup"], len(contest_entries)
        )
        for i, entry in enumerate(contest_entries):
            entry_assignments[entry.entry_id] = assignments[i]

    results["entry_assignments"] = entry_assignments
    results["contest_id"] = body.contest_id
    results["contest_name"] = contest_info.contest_name
    results["entry_count"] = len(contest_entries)
    results["entry_fee"] = contest_info.entry_fee_numeric

    _sim_results[body.contest_id] = {
        "results": results,
        "user_lineups": body.user_lineups,
        "resolved_lineups": resolved_lineups,
        "player_pool": player_pool,
        "contest_config": contest_cfg,
    }

    return results


@router.post("/portfolio-sim")
async def run_portfolio_simulation(body: PortfolioSimRequest):
    """Run simulation across ALL uploaded contests simultaneously.

    For each contest: runs Monte Carlo with its own field_size/payout structure.
    Then assigns lineups across the entire portfolio to maximize diversity + ROI.
    """
    from api.dk_entries import _current_data as dk_data

    if not body.user_lineups:
        raise HTTPException(400, "No user lineups provided")

    # Use backend in-memory data if available, otherwise fall back to frontend-provided contests
    use_dk_data = dk_data and dk_data.contests
    use_frontend_contests = not use_dk_data and body.contests and len(body.contests) > 0

    if not use_dk_data and not use_frontend_contests:
        raise HTTPException(400, "No contests found — upload a DK entries CSV or provide contest data")

    body.sim_count = min(body.sim_count, 50000)

    player_pool, csv_path = _load_player_pool(body.site, body.slate_id, body.target_date)
    if not player_pool:
        raise HTTPException(400, "No projection CSV found")

    name_to_id = {p["name"]: p["id"] for p in player_pool}
    resolved_lineups = _resolve_lineups(body.user_lineups, name_to_id, player_pool)

    # Build unified contest list from whichever source is available
    contest_list = []
    if use_dk_data:
        for c in dk_data.contests:
            contest_list.append({
                "contest_id": c.contest_id,
                "contest_name": c.contest_name,
                "entry_fee": c.entry_fee_numeric,
                "field_size": c.field_size or 1000,
                "game_type": c.game_type,
                "max_entries": c.max_entries_per_user or 150,
                "payout_structure": c.payout_structure or [],
                "prize_pool": c.prize_pool,
                "entry_count": c.entry_count,
                "entry_ids": c.entry_ids,
            })
    else:
        for c in body.contests:
            contest_list.append({
                "contest_id": c.contest_id,
                "contest_name": c.contest_name,
                "entry_fee": c.entry_fee,
                "field_size": c.field_size or 1000,
                "game_type": c.game_type,
                "max_entries": c.max_entries_per_user or 150,
                "payout_structure": c.payout_structure or [],
                "prize_pool": c.prize_pool,
                "entry_count": c.entry_count or len(c.entry_ids),
                "entry_ids": c.entry_ids,
            })

    # Run sims for each contest in parallel
    async def _sim_one_contest(contest_info):
        contest_cfg = {
            "entry_fee": contest_info["entry_fee"],
            "field_size": contest_info["field_size"],
            "game_type": contest_info["game_type"],
            "max_entries": contest_info["max_entries"],
            "payout_structure": contest_info["payout_structure"],
        }
        sim_config = SimulationConfig(
            sim_count=body.sim_count,
            contest_config=contest_cfg,
            game_slate=[],
            player_pool=player_pool,
            user_lineups=resolved_lineups,
            site=body.site,
            pool_variance=body.pool_variance,
            pool_strategy=body.pool_strategy,
        )
        result = await asyncio.to_thread(run_simulation, sim_config)
        result["contest_id"] = contest_info["contest_id"]
        result["contest_name"] = contest_info["contest_name"]
        result["entry_count"] = contest_info["entry_count"]
        result["entry_fee"] = contest_info["entry_fee"]
        result["field_size"] = contest_info["field_size"]
        result["prize_pool"] = contest_info["prize_pool"]
        return result

    # Run contests sequentially to avoid OOM on small machines
    contest_results = []
    for c in contest_list:
        result = await _sim_one_contest(c)
        contest_results.append(result)

    # Portfolio-wide lineup assignment
    portfolio_input = []
    for cr in contest_results:
        portfolio_input.append({
            "contest_id": cr["contest_id"],
            "entry_count": cr["entry_count"],
            "entry_fee": cr["entry_fee"],
            "per_lineup": cr.get("per_lineup", []),
        })

    portfolio_assignments = assign_portfolio_lineups(
        portfolio_input, len(body.user_lineups),
        allow_cross_contest_duplicates=body.allow_cross_contest_duplicates,
    )

    # Apply assignments to each contest result and store.
    # Portfolio metrics are based on the *assigned* lineups, not all candidates.
    total_investment = 0.0
    total_expected_profit = 0.0
    total_entries = 0
    weighted_cash_sum = 0.0
    weighted_top10_sum = 0.0
    weighted_win_sum = 0.0

    for cr in contest_results:
        cid = cr["contest_id"]
        # Find entry IDs from the contest list (works for both dk_data and frontend contests)
        matching_contest = next((c for c in contest_list if c["contest_id"] == cid), None)
        entry_ids = matching_contest["entry_ids"] if matching_contest else []
        # If dk_data available, use actual entry objects for richer assignment
        if use_dk_data:
            contest_entries = [e for e in dk_data.entries if e.contest_id == cid]
            entry_ids = [e.entry_id for e in contest_entries]
        lineup_indices = portfolio_assignments.get(cid, [])

        entry_assignments = {}
        for i, eid in enumerate(entry_ids):
            lu_idx = lineup_indices[i] if i < len(lineup_indices) else 0
            entry_assignments[eid] = lu_idx

        cr["entry_assignments"] = entry_assignments

        entry_fee = cr.get("entry_fee", 0)
        n_entries = cr["entry_count"]
        total_investment += entry_fee * n_entries
        total_entries += n_entries

        # Compute weighted metrics from the actually-assigned lineups
        per_lineup = {s["lineup_index"]: s for s in cr.get("per_lineup", [])}
        for lu_idx in lineup_indices:
            summary = per_lineup.get(lu_idx, {})
            roi = summary.get("avg_roi", 0)
            total_expected_profit += roi / 100 * entry_fee
            weighted_cash_sum += summary.get("cash_rate", 0)
            weighted_top10_sum += summary.get("top_10_rate", 0)
            weighted_win_sum += summary.get("win_rate", 0)

        # Contest-level metrics from assigned lineups (not all candidates)
        if lineup_indices:
            assigned_metrics = [per_lineup.get(idx, {}) for idx in lineup_indices]
            cr["assigned_overall"] = {
                "avg_roi": round(float(np.mean([m.get("avg_roi", 0) for m in assigned_metrics])), 2),
                "cash_rate": round(float(np.mean([m.get("cash_rate", 0) for m in assigned_metrics])), 2),
                "top_10_rate": round(float(np.mean([m.get("top_10_rate", 0) for m in assigned_metrics])), 2),
                "win_rate": round(float(np.mean([m.get("win_rate", 0) for m in assigned_metrics])), 4),
            }

        _sim_results[cid] = {
            "results": cr,
            "user_lineups": body.user_lineups,
            "resolved_lineups": resolved_lineups,
            "player_pool": player_pool,
            "contest_config": {
                "entry_fee": entry_fee,
                "field_size": cr.get("field_size", 1000),
            },
        }

    # Portfolio-level summary
    portfolio_roi = round(total_expected_profit / max(total_investment, 0.01) * 100, 2)
    portfolio_summary = {
        "total_contests": len(contest_results),
        "total_entries": total_entries,
        "total_investment": round(total_investment, 2),
        "expected_profit": round(total_expected_profit, 2),
        "portfolio_roi": portfolio_roi,
        "avg_cash_rate": round(weighted_cash_sum / max(total_entries, 1), 2),
        "avg_top_10_rate": round(weighted_top10_sum / max(total_entries, 1), 2),
        "avg_win_rate": round(weighted_win_sum / max(total_entries, 1), 4),
    }

    # Lineup usage across portfolio
    usage_counts = {}
    for cid, indices in portfolio_assignments.items():
        for idx in indices:
            usage_counts[idx] = usage_counts.get(idx, 0) + 1
    lineup_exposure = [
        {"lineup_index": idx, "entry_count": count, "pct": round(count / max(total_entries, 1) * 100, 1)}
        for idx, count in sorted(usage_counts.items())
    ]

    return {
        "status": "complete",
        "portfolio": portfolio_summary,
        "lineup_exposure": lineup_exposure,
        "contests": contest_results,
    }


@router.post("/assign-lineups")
async def assign_lineups(body: AssignLineupsRequest):
    """Manually set lineup assignments for contest entries."""
    cid = body.contest_id
    if cid not in _sim_results:
        raise HTTPException(404, "No sim results found for this contest — run a simulation first")

    stored = _sim_results[cid]
    results = stored["results"]
    results["entry_assignments"] = body.assignments

    return {"status": "ok", "entry_assignments": body.assignments}


@router.post("/update-entry")
async def update_entry_lineup(body: UpdateEntryLineupRequest):
    """Update a single entry's lineup assignment."""
    cid = body.contest_id
    if cid not in _sim_results:
        raise HTTPException(404, "No sim results found for this contest")

    stored = _sim_results[cid]
    results = stored["results"]
    assignments = results.get("entry_assignments", {})
    assignments[body.entry_id] = body.lineup_index
    results["entry_assignments"] = assignments

    return {"status": "ok", "entry_id": body.entry_id, "lineup_index": body.lineup_index}


@router.post("/export-csv")
async def export_contest_csv(
    contest_id: str = Query(...),
):
    """Export the current lineup assignments as a DK-uploadable CSV.

    Uses entry IDs and player IDs from the originally uploaded DK CSV.
    Format: Entry ID, Contest Name, Contest ID, Entry Fee, SP, SP, C, 1B, 2B, 3B, SS, OF, OF, OF
    Player cells: "PlayerName (DK_ID)"
    """
    from api.dk_entries import _current_data as dk_data
    from services.dk_entries import build_dk_id_lookup

    if not dk_data:
        raise HTTPException(400, "No DK entries uploaded")

    if contest_id not in _sim_results:
        raise HTTPException(404, "No sim results for this contest — run a simulation first")

    stored = _sim_results[contest_id]
    results = stored["results"]
    user_lineups = stored["user_lineups"]
    assignments = results.get("entry_assignments", {})

    contest_entries = [e for e in dk_data.entries if e.contest_id == contest_id]
    if not contest_entries:
        raise HTTPException(404, f"No entries found for contest {contest_id}")

    # Build name→dk_id lookup from the uploaded player pool
    dk_id_lookup = build_dk_id_lookup(dk_data.player_pool)
    # Also build a name normalization map from pool: lowercase name → name_with_id
    name_with_id_lookup: Dict[str, str] = {}
    for p in dk_data.player_pool:
        name_with_id_lookup[p.name.lower()] = p.name_with_id

    roster_slots = dk_data.roster_slots

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Entry ID", "Contest Name", "Contest ID", "Entry Fee"] + roster_slots)

    for entry in contest_entries:
        lineup_idx = assignments.get(entry.entry_id, 0)
        if lineup_idx < 0 or lineup_idx >= len(user_lineups):
            lineup_idx = 0

        lineup = user_lineups[lineup_idx] if user_lineups else []

        slot_values = _build_slot_values(lineup, roster_slots, dk_id_lookup, name_with_id_lookup)

        writer.writerow([
            entry.entry_id,
            entry.contest_name,
            entry.contest_id,
            entry.entry_fee,
        ] + slot_values)

    csv_text = output.getvalue()

    return PlainTextResponse(
        csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=DKLineups_{contest_id}.csv"},
    )


@router.post("/export-all-csv")
async def export_all_csv():
    """Export lineup assignments for ALL contests as a single DK-uploadable CSV."""
    from api.dk_entries import _current_data as dk_data
    from services.dk_entries import build_dk_id_lookup

    if not dk_data:
        raise HTTPException(400, "No DK entries uploaded")

    if not _sim_results:
        raise HTTPException(404, "No sim results — run a simulation first")

    dk_id_lookup = build_dk_id_lookup(dk_data.player_pool)
    name_with_id_lookup: Dict[str, str] = {}
    for p in dk_data.player_pool:
        name_with_id_lookup[p.name.lower()] = p.name_with_id

    roster_slots = dk_data.roster_slots

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Entry ID", "Contest Name", "Contest ID", "Entry Fee"] + roster_slots)

    for entry in dk_data.entries:
        cid = entry.contest_id
        stored = _sim_results.get(cid)
        if not stored:
            continue

        results = stored["results"]
        user_lineups = stored["user_lineups"]
        assignments = results.get("entry_assignments", {})

        lineup_idx = assignments.get(entry.entry_id, 0)
        if lineup_idx < 0 or lineup_idx >= len(user_lineups):
            lineup_idx = 0

        lineup = user_lineups[lineup_idx] if user_lineups else []
        slot_values = _build_slot_values(lineup, roster_slots, dk_id_lookup, name_with_id_lookup)

        writer.writerow([
            entry.entry_id,
            entry.contest_name,
            entry.contest_id,
            entry.entry_fee,
        ] + slot_values)

    csv_text = output.getvalue()
    return PlainTextResponse(
        csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=DKLineups_Portfolio.csv"},
    )


@router.get("/results/{contest_id}")
async def get_sim_results(contest_id: str):
    """Get stored simulation results for a contest."""
    if contest_id not in _sim_results:
        raise HTTPException(404, "No sim results for this contest")

    stored = _sim_results[contest_id]
    return stored["results"]


def _build_slot_values(
    lineup: list[dict[str, Any]],
    roster_slots: list[str],
    dk_id_lookup: dict[str, int],
    name_with_id_lookup: dict[str, str],
) -> list[str]:
    """Build DK-format slot values: 'PlayerName (DK_ID)' for each roster slot."""
    position_players: Dict[str, list] = {}
    for player in lineup:
        pos = player.get("position", "UTIL").upper().strip()
        dk_slot = _pos_to_slot(pos)
        position_players.setdefault(dk_slot, []).append(player)

    used = set()
    slot_values = []
    for slot in roster_slots:
        assigned = False
        candidates = position_players.get(slot, [])
        for player in candidates:
            pname = player.get("name", "")
            pid = id(player)
            if pid in used:
                continue

            # Try to get name_with_id from uploaded pool
            nwid = name_with_id_lookup.get(pname.lower())
            if nwid:
                slot_values.append(nwid)
                used.add(pid)
                assigned = True
                break

            # Fall back to building from dk_id lookup
            dk_id = dk_id_lookup.get(pname.lower())
            if dk_id:
                slot_values.append(f"{pname} ({dk_id})")
                used.add(pid)
                assigned = True
                break

        if not assigned:
            slot_values.append("")

    return slot_values


def _pos_to_slot(pos: str) -> str:
    if pos in ("P", "SP", "RP"):
        return "SP"
    if pos in ("C", "1B", "2B", "3B", "SS"):
        return pos
    if pos in ("OF", "LF", "CF", "RF"):
        return "OF"
    parts = pos.split("/")
    for p in parts:
        p = p.strip()
        if p in ("C", "1B", "2B", "3B", "SS"):
            return p
        if p in ("OF", "LF", "CF", "RF"):
            return "OF"
    return "UTIL"
