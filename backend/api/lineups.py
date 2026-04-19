"""Lineup build, list, and export endpoints."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import date
from functools import partial
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.lineup import Lineup
from models.player import Player
from models.projection import Projection
from services.csv_projections import (
    identify_featured_csv_slate,
    list_available_slates as list_csv_slates,
    load_csv_projections,
)
from services.optimizer import PlayerPool, generate_lineup_pool, optimize_lineup

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/lineups", tags=["lineups"])


# ── Pydantic schemas ────────────────────────────────────────────────────────


class LineupPlayerSlot(BaseModel):
    player_id: int
    position: str
    salary: int


class LineupOut(BaseModel):
    id: int
    contest_id: int
    entry_id: Optional[str] = None
    user_name: Optional[str] = None
    players: List[LineupPlayerSlot]
    total_salary: int
    total_points: Optional[float] = None
    finish_position: Optional[int] = None
    is_user: bool = False

    model_config = {"from_attributes": True}


class LineupCreate(BaseModel):
    contest_id: int
    entry_id: Optional[str] = None
    user_name: Optional[str] = None
    players: List[LineupPlayerSlot]
    is_user: bool = False


class OptimizeRequest(BaseModel):
    """Request to build optimised lineups from the player pool."""
    game_id: int
    site: str = "dk"
    n_lineups: int = 20
    min_unique: int = 3
    locked_player_ids: List[int] = []
    excluded_player_ids: List[int] = []
    exposure_limits: Dict[int, List[float]] = {}  # player_id -> [min_pct, max_pct]
    objective: str = "median_pts"


class OptimizeResult(BaseModel):
    lineups: List[List[Dict[str, Any]]]
    count: int


class StackExposure(BaseModel):
    """Min/max exposure for a specific stack size on a team."""
    min_pct: float = 0.0   # 0-100
    max_pct: float = 100.0  # 0-100


class TeamStackConfig(BaseModel):
    """Stack exposure settings for a team."""
    stack_3: Optional[StackExposure] = None
    stack_4: Optional[StackExposure] = None
    stack_5: Optional[StackExposure] = None


class CSVOptimizeRequest(BaseModel):
    """Request to build optimised lineups from CSV-based projections."""
    site: str = "dk"
    n_lineups: int = 20
    min_unique: int = 3
    locked_names: List[str] = []
    excluded_names: List[str] = []
    exposure_overrides: Dict[str, List[float]] = {}  # player_name -> [min_pct, max_pct]
    stack_exposures: Dict[str, TeamStackConfig] = {}  # team_abbr -> stack config
    objective: str = "median_pts"
    target_date: Optional[str] = None
    slate_id: Optional[str] = None
    variance: float = 0.15  # 0.0 = no variance, 1.0 = max variance
    skew: str = "neutral"   # "neutral", "ceiling", "floor"
    min_salary: Optional[int] = None  # minimum total salary floor

    def validated_n_lineups(self) -> int:
        return min(max(self.n_lineups, 1), 10000)


class LateSwapPlayer(BaseModel):
    name: str
    position: str
    salary: int
    dk_id: Optional[int] = None


class LateSwapRequest(BaseModel):
    """Request to check for scratched players and find replacements."""
    lineup: List[LateSwapPlayer]
    excluded_players: List[str] = []
    site: str = "dk"
    target_date: Optional[str] = None


class SwapDetail(BaseModel):
    out: str
    in_player: str  # "in" is reserved keyword
    reason: str
    pts_diff: float


class LateSwapResponse(BaseModel):
    original_lineup: List[Dict[str, Any]]
    updated_lineup: List[Dict[str, Any]]
    swaps: List[SwapDetail]
    total_salary: int
    total_median: float


# ── Endpoints ───────────────────────────────────────────────────────────────


@router.get("/", response_model=List[LineupOut])
async def list_lineups(
    contest_id: Optional[int] = None,
    is_user: Optional[bool] = None,
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
):
    """List lineups, optionally filtered by contest and user flag."""
    stmt = select(Lineup).order_by(Lineup.created_at.desc()).limit(limit)
    if contest_id is not None:
        stmt = stmt.where(Lineup.contest_id == contest_id)
    if is_user is not None:
        stmt = stmt.where(Lineup.is_user == is_user)
    result = await db.execute(stmt)
    rows = result.scalars().all()

    out = []
    for r in rows:
        try:
            players = json.loads(r.players) if isinstance(r.players, str) else r.players
        except (json.JSONDecodeError, TypeError):
            players = []
        out.append(
            LineupOut(
                id=r.id,
                contest_id=r.contest_id,
                entry_id=r.entry_id,
                user_name=r.user_name,
                players=[LineupPlayerSlot(**p) for p in players],
                total_salary=r.total_salary,
                total_points=r.total_points,
                finish_position=r.finish_position,
                is_user=r.is_user,
            )
        )
    return out


@router.post("/", response_model=LineupOut, status_code=201)
async def create_lineup(body: LineupCreate, db: AsyncSession = Depends(get_db)):
    """Store a lineup."""
    players_json = json.dumps([p.model_dump() for p in body.players])
    total_salary = sum(p.salary for p in body.players)

    lineup = Lineup(
        contest_id=body.contest_id,
        entry_id=body.entry_id,
        user_name=body.user_name,
        players=players_json,
        total_salary=total_salary,
        is_user=body.is_user,
    )
    db.add(lineup)
    await db.flush()
    await db.refresh(lineup)

    return LineupOut(
        id=lineup.id,
        contest_id=lineup.contest_id,
        entry_id=lineup.entry_id,
        user_name=lineup.user_name,
        players=body.players,
        total_salary=total_salary,
        total_points=None,
        finish_position=None,
        is_user=lineup.is_user,
    )


@router.post("/optimize", response_model=OptimizeResult)
async def optimize_lineups(
    body: OptimizeRequest, db: AsyncSession = Depends(get_db)
):
    """Generate optimised lineups from the player pool + projections.

    Pulls all projections for the given game/site, merges with player salary
    data, and runs the optimizer to produce N diverse lineups.
    """
    # Fetch projections
    result = await db.execute(
        select(Projection)
        .where(Projection.game_id == body.game_id, Projection.site == body.site)
    )
    projections = result.scalars().all()
    if not projections:
        raise HTTPException(400, "No projections found for this game/site")

    # Fetch players
    player_ids = [p.player_id for p in projections]
    result = await db.execute(select(Player).where(Player.id.in_(player_ids)))
    players_db = {p.id: p for p in result.scalars().all()}

    # Build pool
    pool_data: list[dict[str, Any]] = []
    for proj in projections:
        player = players_db.get(proj.player_id)
        if not player:
            continue
        salary = player.dk_salary if body.site == "dk" else player.fd_salary
        if not salary:
            continue
        pool_data.append(
            {
                "id": player.id,
                "name": player.name,
                "team": player.team,
                "position": player.position,
                "salary": salary,
                "floor_pts": proj.floor_pts,
                "median_pts": proj.median_pts,
                "ceiling_pts": proj.ceiling_pts,
                "ownership": proj.projected_ownership or 0,
            }
        )

    if not pool_data:
        raise HTTPException(400, "No players with salary data in projection set")

    pool = PlayerPool(pool_data)

    # Convert exposure limits
    exposure = None
    if body.exposure_limits:
        exposure = {
            pid: (bounds[0], bounds[1])
            for pid, bounds in body.exposure_limits.items()
            if len(bounds) == 2
        }

    lineups = await asyncio.to_thread(
        generate_lineup_pool,
        pool=pool,
        n_lineups=min(body.n_lineups, 150),
        site=body.site,
        objective=body.objective,
        min_unique=body.min_unique,
        exposure_limits=exposure,
    )

    return OptimizeResult(lineups=lineups, count=len(lineups))


@router.post("/optimize-csv", response_model=OptimizeResult)
async def optimize_lineups_csv(body: CSVOptimizeRequest):
    """Generate optimised lineups from CSV-based projections.

    Loads projections from the selected or featured CSV slate for the given
    date/site, builds a PuLP player pool, and runs the optimizer.
    """
    try:
        d = date.fromisoformat(body.target_date) if body.target_date else date.today()
    except ValueError:
        raise HTTPException(400, "Invalid date format, use YYYY-MM-DD")

    # Load CSV projections — use specific slate if provided, otherwise featured
    csv_slates = list_csv_slates(target_date=d, site=body.site)
    if not csv_slates:
        raise HTTPException(400, "No CSV projection files found for this date/site")

    chosen_slate = None
    if body.slate_id:
        for cs in csv_slates:
            if cs["slate_id"] == body.slate_id:
                chosen_slate = cs
                break
    if not chosen_slate:
        chosen_slate = identify_featured_csv_slate(csv_slates)
    if not chosen_slate or not chosen_slate.get("csv_path"):
        raise HTTPException(400, "No matching slate found")

    projections = load_csv_projections(chosen_slate["csv_path"], body.site)
    if not projections:
        raise HTTPException(400, "No projections loaded from CSV")

    # Build player pool for the optimizer
    # Position mapping: outfield sub-positions → OF for slot eligibility
    pool_data: list[dict[str, Any]] = []
    name_to_id: dict[str, int] = {}  # for exposure/lock lookups

    for i, p in enumerate(projections):
        pid = i + 1
        name = p["player_name"]
        name_to_id[name] = pid

        salary = p.get("salary") or 0
        if salary <= 0:
            continue

        # Map positions for optimizer slot eligibility
        raw_pos = p.get("position", "UTIL")
        if p.get("is_pitcher"):
            opt_pos = "P"
        else:
            # Normalise outfield sub-positions (LF, CF, RF → OF)
            parts = raw_pos.split("/")
            mapped = []
            for pp in parts:
                if pp in ("LF", "CF", "RF"):
                    if "OF" not in mapped:
                        mapped.append("OF")
                else:
                    mapped.append(pp)
            opt_pos = "/".join(mapped) if mapped else raw_pos

        pool_data.append({
            "id": pid,
            "name": name,
            "team": p.get("team", ""),
            "position": opt_pos,
            "salary": salary,
            "floor_pts": p.get("floor_pts", 0),
            "median_pts": p.get("median_pts", 0),
            "ceiling_pts": p.get("ceiling_pts", 0),
            "ownership": p.get("projected_ownership", 0) or 0,
            "dk_id": p.get("dk_id"),
        })

    if not pool_data:
        raise HTTPException(400, "No players with salary data in projection set")

    pool = PlayerPool(pool_data)

    # Build exposure limits: start with CSV defaults, apply overrides
    exposure: dict[int, tuple[float, float]] = {}
    for p in projections:
        pid = name_to_id.get(p["player_name"])
        if pid is None:
            continue
        min_exp = (p.get("min_exposure") or 0) / 100.0
        max_exp = (p.get("max_exposure") or 100) / 100.0
        if min_exp > 0 or max_exp < 1.0:
            exposure[pid] = (min_exp, max_exp)

    # Apply frontend overrides (name → pct values)
    for name, bounds in body.exposure_overrides.items():
        pid = name_to_id.get(name)
        if pid and len(bounds) == 2:
            exposure[pid] = (bounds[0] / 100.0, bounds[1] / 100.0)

    # Locked / excluded
    locked = [name_to_id[n] for n in body.locked_names if n in name_to_id]
    excluded = [name_to_id[n] for n in body.excluded_names if n in name_to_id]

    # Validate skew parameter
    valid_skews = ("neutral", "ceiling", "floor")
    skew = body.skew if body.skew in valid_skews else "neutral"
    # Clamp variance to [0, 1]
    variance = max(0.0, min(1.0, body.variance))

    # Build stack exposure rules: team -> {stack_size: (min_pct, max_pct)}
    stack_exposures: Dict[str, Dict[int, tuple]] = {}
    for team, config in body.stack_exposures.items():
        team_stacks: Dict[int, tuple] = {}
        for sz, se in [(3, config.stack_3), (4, config.stack_4), (5, config.stack_5)]:
            if se:
                team_stacks[sz] = (se.min_pct / 100.0, se.max_pct / 100.0)
        if team_stacks:
            stack_exposures[team] = team_stacks

    # Run the PuLP optimizer in a thread to avoid blocking the event loop
    n = body.validated_n_lineups()
    lineups = await asyncio.to_thread(
        generate_lineup_pool,
        pool=pool,
        n_lineups=n,
        site=body.site,
        objective=body.objective,
        min_unique=body.min_unique,
        exposure_limits=exposure if exposure else None,
        stack_rules=None,
        locked=locked if locked else None,
        excluded=excluded if excluded else None,
        variance=variance,
        skew=skew,
        stack_exposures=stack_exposures if stack_exposures else None,
        min_salary=body.min_salary,
    )

    # Enrich lineup results with dk_id for export
    id_to_data = {p["id"]: p for p in pool_data}
    enriched = []
    for lu in lineups:
        enriched_lu = []
        for slot in lu:
            pdata = id_to_data.get(slot["player_id"], {})
            slot["dk_id"] = pdata.get("dk_id")
            enriched_lu.append(slot)
        enriched.append(enriched_lu)

    return OptimizeResult(lineups=enriched, count=len(enriched))


@router.post("/optimize-staging", response_model=OptimizeResult)
async def optimize_lineups_staging(body: CSVOptimizeRequest):
    """Generate optimised lineups from the staging projection pipeline.

    Uses the sim-engine projection cache instead of CSV files. Same optimizer
    logic as optimize-csv but fed by the home-grown projection model.
    """
    import time as _time
    from api.staging_projections import _projection_cache, get_slate_staging_projections
    from api.projections import _sanitise_projection

    try:
        d = date.fromisoformat(body.target_date) if body.target_date else date.today()
    except ValueError:
        raise HTTPException(400, "Invalid date format, use YYYY-MM-DD")

    date_str = d.isoformat()
    cache_key = f"{date_str}-{body.site}"

    # Get projections: try per-slate if slate_id provided, else use cached full-day
    projections: list[dict] = []
    if body.slate_id:
        from fastapi import Request
        from api.staging_projections import get_slate_staging_projections
        from starlette.datastructures import QueryParams
        try:
            result = await get_slate_staging_projections(
                slate_id=body.slate_id,
                site=body.site,
                target_date=body.target_date,
                n_sims=1000,
            )
            projections = [p.dict() for p in result]
        except Exception as exc:
            logger.warning("Failed to get slate projections for optimizer: %s", exc)

    if not projections:
        # Fall back to full-day cache
        if cache_key in _projection_cache:
            ts, cached = _projection_cache[cache_key]
            if _time.time() - ts < 600:
                projections = [_sanitise_projection(p) for p in cached]

    if not projections:
        # Try generating fresh
        from services.projection_pipeline import generate_projections
        try:
            raw = await generate_projections(target_date=date_str, site=body.site, n_sims=1000)
            _projection_cache[cache_key] = (_time.time(), raw)
            projections = [_sanitise_projection(p) for p in raw]
        except Exception as exc:
            raise HTTPException(500, f"Projection pipeline failed: {exc}")

    if not projections:
        raise HTTPException(400, "No projections available for this date/site")

    # Build player pool (same logic as optimize-csv)
    pool_data: list[dict[str, Any]] = []
    name_to_id: dict[str, int] = {}

    for i, p in enumerate(projections):
        pid = i + 1
        name = p.get("player_name", "")
        if not name:
            continue
        name_to_id[name] = pid

        salary = p.get("salary") or 0
        if salary <= 0:
            continue

        raw_pos = p.get("position", "UTIL")
        if p.get("is_pitcher"):
            opt_pos = "P"
        else:
            parts = raw_pos.split("/")
            mapped = []
            for pp in parts:
                if pp in ("LF", "CF", "RF"):
                    if "OF" not in mapped:
                        mapped.append("OF")
                else:
                    mapped.append(pp)
            opt_pos = "/".join(mapped) if mapped else raw_pos

        pool_data.append({
            "id": pid,
            "name": name,
            "team": p.get("team", ""),
            "position": opt_pos,
            "salary": salary,
            "floor_pts": p.get("floor_pts", 0),
            "median_pts": p.get("median_pts", 0),
            "ceiling_pts": p.get("ceiling_pts", 0),
            "ownership": p.get("projected_ownership", 0) or 0,
            "dk_id": p.get("dk_id"),
        })

    if not pool_data:
        raise HTTPException(400, "No players with salary data in projection set")

    pool = PlayerPool(pool_data)

    exposure: dict[int, tuple[float, float]] = {}
    for p in projections:
        pid = name_to_id.get(p.get("player_name", ""))
        if pid is None:
            continue
        min_exp = (p.get("min_exposure") or 0) / 100.0
        max_exp = (p.get("max_exposure") or 100) / 100.0
        if min_exp > 0 or max_exp < 1.0:
            exposure[pid] = (min_exp, max_exp)

    for name, bounds in body.exposure_overrides.items():
        pid = name_to_id.get(name)
        if pid and len(bounds) == 2:
            exposure[pid] = (bounds[0] / 100.0, bounds[1] / 100.0)

    locked = [name_to_id[n] for n in body.locked_names if n in name_to_id]
    excluded = [name_to_id[n] for n in body.excluded_names if n in name_to_id]

    valid_skews = ("neutral", "ceiling", "floor")
    skew = body.skew if body.skew in valid_skews else "neutral"
    variance = max(0.0, min(1.0, body.variance))

    stack_exposures: Dict[str, Dict[int, tuple]] = {}
    for team, config in body.stack_exposures.items():
        team_stacks: Dict[int, tuple] = {}
        for sz, se in [(3, config.stack_3), (4, config.stack_4), (5, config.stack_5)]:
            if se:
                team_stacks[sz] = (se.min_pct / 100.0, se.max_pct / 100.0)
        if team_stacks:
            stack_exposures[team] = team_stacks

    n = body.validated_n_lineups()
    lineups = await asyncio.to_thread(
        generate_lineup_pool,
        pool=pool,
        n_lineups=n,
        site=body.site,
        objective=body.objective,
        min_unique=body.min_unique,
        exposure_limits=exposure if exposure else None,
        stack_rules=None,
        locked=locked if locked else None,
        excluded=excluded if excluded else None,
        variance=variance,
        skew=skew,
        stack_exposures=stack_exposures if stack_exposures else None,
        min_salary=body.min_salary,
    )

    id_to_data = {p["id"]: p for p in pool_data}
    enriched = []
    for lu in lineups:
        enriched_lu = []
        for slot in lu:
            pdata = id_to_data.get(slot["player_id"], {})
            slot["dk_id"] = pdata.get("dk_id")
            enriched_lu.append(slot)
        enriched.append(enriched_lu)

    return OptimizeResult(lineups=enriched, count=len(enriched))


@router.post("/late-swap", response_model=LateSwapResponse)
async def check_late_swap(body: LateSwapRequest):
    """Check a lineup for scratched players and suggest optimal replacements.

    Loads current CSV projections, identifies players who are scratched
    (not in projections or status=Out), and finds the best same-position
    replacement that fits the salary cap.
    """
    try:
        d = date.fromisoformat(body.target_date) if body.target_date else date.today()
    except ValueError:
        raise HTTPException(400, "Invalid date format, use YYYY-MM-DD")

    # Load projections: try CSV first, fall back to staging cache
    projections: list[dict] = []
    csv_slates = list_csv_slates(target_date=d, site=body.site)
    if csv_slates:
        featured = identify_featured_csv_slate(csv_slates)
        if featured and featured.get("csv_path"):
            projections = load_csv_projections(featured["csv_path"], body.site)

    if not projections:
        import time as _time
        from api.staging_projections import _projection_cache
        from api.projections import _sanitise_projection

        date_str = d.isoformat()
        cache_key = f"{date_str}-{body.site}"
        if cache_key in _projection_cache:
            ts, cached = _projection_cache[cache_key]
            if _time.time() - ts < 600:
                projections = [_sanitise_projection(p) for p in cached]

    if not projections:
        raise HTTPException(400, "No projections available for this date/site")

    # Build lookup: player_name (lowercase) -> projection dict
    proj_by_name: Dict[str, Dict[str, Any]] = {}
    for p in projections:
        proj_by_name[p["player_name"].lower()] = p

    # Build excluded set (lowercase)
    excluded_lower = {n.lower() for n in body.excluded_players}
    # Also exclude all current lineup players (can't double-up)
    for slot in body.lineup:
        excluded_lower.add(slot.name.lower())

    # DK salary cap
    salary_cap = 50000

    # Compute current total salary excluding any player that will be swapped
    # We'll figure out swaps first, then compute final salary
    original_lineup = [
        {
            "name": slot.name,
            "position": slot.position,
            "salary": slot.salary,
            "dk_id": slot.dk_id,
            "median_pts": proj_by_name.get(slot.name.lower(), {}).get("median_pts", 0),
        }
        for slot in body.lineup
    ]

    swaps: List[Dict[str, Any]] = []
    updated_lineup = []

    for slot in body.lineup:
        name_lower = slot.name.lower()
        proj = proj_by_name.get(name_lower)

        # A player is "scratched" if:
        # 1. Not in projections at all
        # 2. Has is_confirmed=False and batting_order is None (for hitters)
        # 3. Their projection is effectively zero
        is_scratched = False
        reason = ""
        if proj is None:
            is_scratched = True
            reason = "not in projections"
        elif not proj.get("is_confirmed", False) and proj.get("median_pts", 0) < 0.5:
            is_scratched = True
            reason = "scratched"

        if is_scratched:
            # Find replacement: same position eligibility, highest median, fits salary
            # Calculate remaining salary budget if we remove this player
            other_salary = sum(
                s.salary for s in body.lineup if s.name.lower() != name_lower
            )
            available_salary = salary_cap - other_salary

            # Map position for matching: handle OF sub-positions
            slot_pos = slot.position.upper()
            dk_slot = slot_pos
            if dk_slot in ("LF", "CF", "RF"):
                dk_slot = "OF"
            if dk_slot in ("SP", "RP"):
                dk_slot = "P"

            best_replacement = None
            best_median = -1.0

            for candidate in projections:
                cand_name_lower = candidate["player_name"].lower()
                if cand_name_lower in excluded_lower:
                    continue
                if (candidate.get("salary") or 0) > available_salary:
                    continue
                if (candidate.get("salary") or 0) <= 0:
                    continue
                if not candidate.get("is_confirmed", False):
                    continue

                # Check position eligibility
                cand_pos = candidate.get("position", "").upper()
                cand_positions = set()
                for pp in cand_pos.split("/"):
                    pp = pp.strip()
                    if pp in ("LF", "CF", "RF"):
                        cand_positions.add("OF")
                    elif pp in ("SP", "RP"):
                        cand_positions.add("P")
                    else:
                        cand_positions.add(pp)

                if dk_slot not in cand_positions:
                    continue

                cand_median = candidate.get("median_pts", 0)
                if cand_median > best_median:
                    best_median = cand_median
                    best_replacement = candidate

            if best_replacement:
                old_median = proj.get("median_pts", 0) if proj else 0
                pts_diff = round(best_replacement.get("median_pts", 0) - old_median, 2)
                swaps.append({
                    "out": slot.name,
                    "in_player": best_replacement["player_name"],
                    "reason": reason,
                    "pts_diff": pts_diff,
                })
                updated_lineup.append({
                    "name": best_replacement["player_name"],
                    "position": slot.position,  # keep the slot position
                    "salary": best_replacement.get("salary", 0),
                    "dk_id": best_replacement.get("dk_id"),
                    "median_pts": best_replacement.get("median_pts", 0),
                })
                # Add replacement to excluded so they can't be used twice
                excluded_lower.add(best_replacement["player_name"].lower())
            else:
                # No valid replacement found, keep original
                updated_lineup.append({
                    "name": slot.name,
                    "position": slot.position,
                    "salary": slot.salary,
                    "dk_id": slot.dk_id,
                    "median_pts": proj.get("median_pts", 0) if proj else 0,
                })
        else:
            # Player is active, keep them
            updated_lineup.append({
                "name": slot.name,
                "position": slot.position,
                "salary": slot.salary,
                "dk_id": slot.dk_id,
                "median_pts": proj.get("median_pts", 0) if proj else 0,
            })

    total_salary = sum(p["salary"] for p in updated_lineup)
    total_median = round(sum(p["median_pts"] for p in updated_lineup), 2)

    return LateSwapResponse(
        original_lineup=original_lineup,
        updated_lineup=updated_lineup,
        swaps=[SwapDetail(**s) for s in swaps],
        total_salary=total_salary,
        total_median=total_median,
    )


@router.get("/export/dk")
async def export_dk_csv(
    contest_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Export user lineups for a contest as DK-uploadable CSV text.

    Returns plain text in DraftKings CSV format.
    """
    from fastapi.responses import PlainTextResponse

    result = await db.execute(
        select(Lineup).where(
            Lineup.contest_id == contest_id, Lineup.is_user == True
        )
    )
    lineups = result.scalars().all()
    if not lineups:
        raise HTTPException(404, "No user lineups for this contest")

    from config import DK_ROSTER_SLOTS

    header = ",".join(DK_ROSTER_SLOTS)
    rows = [header]

    for lu in lineups:
        try:
            players = json.loads(lu.players) if isinstance(lu.players, str) else lu.players
        except (json.JSONDecodeError, TypeError):
            continue

        # Build slot -> dk_id mapping
        slot_map: dict[str, int] = {}
        for p in players:
            # Look up dk_id from database
            pr = await db.execute(select(Player).where(Player.id == p["player_id"]))
            player = pr.scalar_one_or_none()
            if player and player.dk_id:
                slot_map[p["position"]] = player.dk_id

        # Build row in slot order
        row_parts = []
        for slot in DK_ROSTER_SLOTS:
            dk_id = slot_map.get(slot, "")
            row_parts.append(str(dk_id))
        rows.append(",".join(row_parts))

    return PlainTextResponse("\n".join(rows), media_type="text/csv")
