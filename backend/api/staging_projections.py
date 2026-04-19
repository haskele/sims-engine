"""Staging projection API: serves home-grown sim-based projections.

Provides an alternative to the SaberSim CSV-based projection endpoints,
using the sim-based projection pipeline (true-talent profiles, matchup
model, Monte Carlo simulation).

Slates are pulled live from the DraftKings lobby API so every available
DK slate shows up, just like production.

Endpoints:
  GET /staging/projections/slates           — List real DK slates
  GET /staging/projections/slates/featured/projections — Run pipeline, return projections
  GET /staging/projections/generate         — Force regenerate projections
"""
from __future__ import annotations

import logging
import time
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from api.projections import (
    SlateOut, SlateProjectionOut, _sanitise_projection,
    GameLineupOut, TeamLineupOut, PlayerLineupOut, WeatherOut, LiveGameState,
)
from services.constants import normalise_dk_team as _normalise_dk_team
from services.dk_api import get_draftables
from services.name_matching import canonical_name, find_in_dict as find_name_in_dict
from services.slate_manager import fetch_dk_slates, identify_featured_slate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/staging/projections", tags=["staging"])

# ---------------------------------------------------------------------------
# Module-level projection cache (timestamp, projections)
# ---------------------------------------------------------------------------

_projection_cache: Dict[str, tuple[float, list[dict]]] = {}
_CACHE_TTL = 300  # 5 minutes

# ---------------------------------------------------------------------------
# Persistent slate cache: survives server restarts by writing to the Fly.io
# volume (/app/data).  Once a slate is discovered for a date, it's available
# for the rest of the day regardless of whether DK removes it from their
# lobby after games start.
# ---------------------------------------------------------------------------

from pathlib import Path as _Path
import json as _json

_SLATE_CACHE_DIR = _Path("/app/data/slate_cache")
_slate_cache: Dict[str, List[Dict]] = {}


def _load_slate_cache(date_key: str) -> List[Dict]:
    """Load cached slates, merging in-memory and disk data.

    Always reads from disk and merges with in-memory cache so that
    slates added by the seed endpoint (or a prior server instance)
    are picked up even when the in-memory cache already has entries.
    """
    in_memory = _slate_cache.get(date_key, [])
    cache_file = _SLATE_CACHE_DIR / f"{date_key}.json"
    if cache_file.exists():
        try:
            with open(cache_file) as f:
                from_disk = _json.load(f)
            # Merge: disk slates that aren't already in memory
            existing_ids = {s["slate_id"] for s in in_memory}
            for s in from_disk:
                if s["slate_id"] not in existing_ids:
                    in_memory.append(s)
                    existing_ids.add(s["slate_id"])
            if in_memory:
                _slate_cache[date_key] = in_memory
        except Exception as exc:
            logger.warning("Failed to read slate cache for %s: %s", date_key, exc)
    return in_memory


def _save_slate_cache(date_key: str, slates: List[Dict]) -> None:
    """Persist slate cache to disk so it survives deploys."""
    try:
        _SLATE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_file = _SLATE_CACHE_DIR / f"{date_key}.json"
        with open(cache_file, "w") as f:
            _json.dump(slates, f, default=str)
    except Exception as exc:
        logger.warning("Failed to write slate cache for %s: %s", date_key, exc)


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class GenerateResult(BaseModel):
    status: str
    projection_count: int
    elapsed_seconds: float
    target_date: str
    site: str
    n_sims: int


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/slates", response_model=List[SlateOut])
async def list_staging_slates(
    site: str = Query("dk", pattern="^(dk|fd)$"),
    target_date: str = Query(None, description="YYYY-MM-DD, defaults to today"),
):
    """Return all DK slates from the lobby API for the target date.

    Pulls the same real slates that DraftKings shows in their lobby,
    filtered to the requested site. Uses a server-side cache so that
    once a slate is discovered, it persists for the rest of the day
    even if DK removes it from the lobby after games start (enabling
    late swap).
    """
    try:
        d = date.fromisoformat(target_date) if target_date else date.today()
    except ValueError:
        raise HTTPException(400, "Invalid date, use YYYY-MM-DD")

    date_key = d.isoformat()

    # Load persisted slates from disk (survives deploys/restarts)
    cached_slates = _load_slate_cache(date_key)

    # Fetch fresh slates from DK lobby
    fresh_slates: List[Dict] = []
    try:
        fresh_slates = await fetch_dk_slates(target_date=d)
    except Exception as exc:
        logger.warning("Failed to fetch DK slates from lobby: %s", exc)

    # Merge fresh slates into the persistent cache
    existing_ids = {s["slate_id"] for s in cached_slates}
    changed = False
    for s in fresh_slates:
        if s["slate_id"] not in existing_ids:
            cached_slates.append(s)
            existing_ids.add(s["slate_id"])
            changed = True

    # Update in-memory cache and persist to disk if anything new was added
    _slate_cache[date_key] = cached_slates
    if changed:
        _save_slate_cache(date_key, cached_slates)

    if not cached_slates:
        return []

    # Filter by site and game_type, sort main slate first
    filtered = [
        s for s in cached_slates
        if s.get("site", "dk") == site and s.get("game_type") == "classic"
    ]
    filtered.sort(key=lambda s: s.get("game_count", 0), reverse=True)

    return [
        SlateOut(
            slate_id=s["slate_id"],
            site=s["site"],
            name=s["name"],
            game_count=s["game_count"],
            start_time=s.get("start_time"),
            game_type=s["game_type"],
            draft_group_id=s.get("draft_group_id", 0),
            is_historical=False,
        )
        for s in filtered
    ]


@router.post("/slates/seed")
async def seed_slate_cache(
    target_date: str = Query(None, description="YYYY-MM-DD, defaults to today"),
):
    """Manually seed a slate into the persistent cache (for recovery after deploys)."""
    from pydantic import BaseModel as _BM

    try:
        d = date.fromisoformat(target_date) if target_date else date.today()
    except ValueError:
        raise HTTPException(400, "Invalid date, use YYYY-MM-DD")

    date_key = d.isoformat()

    # Try fetching fresh from DK first
    fresh: List[Dict] = []
    try:
        fresh = await fetch_dk_slates(target_date=d)
    except Exception:
        pass

    # Also try fetching all draftgroups via the DK draftables endpoint
    # for slates that DK already removed from the lobby
    if not fresh or len(fresh) < 2:
        try:
            from services.dk_api import get_draftables
            # Try known main slate IDs by looking at cached projections
            for cache_key, (ts, projs) in _projection_cache.items():
                if cache_key.startswith(date_key):
                    # We have projections — extract dk_ids to find the draft group
                    dk_ids = {p.get("dk_id") for p in projs if p.get("dk_id")}
                    if dk_ids:
                        logger.info("Found %d dk_ids in projection cache for recovery", len(dk_ids))
                    break
        except Exception:
            pass

    cached = _load_slate_cache(date_key)
    existing_ids = {s["slate_id"] for s in cached}
    added = 0
    for s in fresh:
        if s["slate_id"] not in existing_ids:
            cached.append(s)
            existing_ids.add(s["slate_id"])
            added += 1

    _slate_cache[date_key] = cached
    _save_slate_cache(date_key, cached)

    return {"status": "ok", "date": date_key, "total_slates": len(cached), "added": added}


@router.post("/slates/inject")
async def inject_slate(
    slate_id: str = Query(...),
    name: str = Query("Main Slate"),
    game_count: int = Query(14),
    start_time: str = Query(None),
    target_date: str = Query(None),
):
    """Manually inject a slate that DK has removed from the lobby."""
    try:
        d = date.fromisoformat(target_date) if target_date else date.today()
    except ValueError:
        raise HTTPException(400, "Invalid date")
    date_key = d.isoformat()
    cached = _load_slate_cache(date_key)
    existing_ids = {s["slate_id"] for s in cached}
    if slate_id in existing_ids:
        return {"status": "already_exists", "total": len(cached)}
    new_slate = {
        "slate_id": slate_id,
        "site": "dk",
        "draft_group_id": int(slate_id),
        "name": name,
        "game_count": game_count,
        "start_time": start_time,
        "game_type": "classic",
        "games": [],
        "sport": "MLB",
    }
    cached.append(new_slate)
    _slate_cache[date_key] = cached
    _save_slate_cache(date_key, cached)
    return {"status": "ok", "injected": slate_id, "total": len(cached)}


@router.get("/slates/featured/projections", response_model=List[SlateProjectionOut])
async def get_featured_staging_projections(
    site: str = Query("dk", pattern="^(dk|fd)$"),
    target_date: str = Query(None, description="YYYY-MM-DD, defaults to today"),
    n_sims: int = Query(1000, ge=100, le=10000, description="Monte Carlo iterations"),
):
    """Run the sim-based pipeline and return projections for the featured slate.

    Results are cached for 5 minutes. First call may take 30-60 seconds
    while true-talent profiles are fetched from the MLB Stats API.
    """
    try:
        d = date.fromisoformat(target_date) if target_date else date.today()
    except ValueError:
        raise HTTPException(400, "Invalid date, use YYYY-MM-DD")

    date_str = d.isoformat()
    cache_key = f"{date_str}-{site}"

    # Check cache
    if cache_key in _projection_cache:
        ts, cached = _projection_cache[cache_key]
        if time.time() - ts < _CACHE_TTL:
            logger.info(
                "Returning cached staging projections (%d players, %.0fs old)",
                len(cached), time.time() - ts,
            )
            return [
                SlateProjectionOut(**_sanitise_projection(p))
                for p in cached
            ]

    # Generate fresh projections
    from services.projection_pipeline import generate_projections

    logger.info("Generating staging projections for %s (site=%s, n_sims=%d)", date_str, site, n_sims)
    t0 = time.time()

    try:
        projections = await generate_projections(
            target_date=date_str,
            site=site,
            n_sims=n_sims,
        )
    except Exception as exc:
        logger.error("Projection pipeline failed: %s", exc, exc_info=True)
        raise HTTPException(500, f"Projection pipeline failed: {exc}")

    elapsed = time.time() - t0
    logger.info("Generated %d projections in %.1fs", len(projections), elapsed)

    # Cache results
    _projection_cache[cache_key] = (time.time(), projections)

    return [
        SlateProjectionOut(**_sanitise_projection(p))
        for p in projections
    ]


@router.get("/slates/{slate_id}/projections", response_model=List[SlateProjectionOut])
async def get_slate_staging_projections(
    slate_id: str,
    site: str = Query("dk", pattern="^(dk|fd)$"),
    target_date: str = Query(None, description="YYYY-MM-DD, defaults to today"),
    n_sims: int = Query(1000, ge=100, le=10000, description="Monte Carlo iterations"),
):
    """Return projections for a specific DK slate (draft group).

    Uses DK draftables as the player list to ensure every player on the
    slate gets a projection. Overlays sim-engine projections where available,
    falls back to FPPG-based estimates for players without a sim projection.
    """
    try:
        d = date.fromisoformat(target_date) if target_date else date.today()
    except ValueError:
        raise HTTPException(400, "Invalid date, use YYYY-MM-DD")

    date_str = d.isoformat()
    cache_key = f"{date_str}-{site}"

    # Get or generate full-day projections
    if cache_key in _projection_cache:
        ts, cached = _projection_cache[cache_key]
        if time.time() - ts < _CACHE_TTL:
            all_projs = cached
        else:
            all_projs = await _generate_and_cache(date_str, site, n_sims, cache_key)
    else:
        all_projs = await _generate_and_cache(date_str, site, n_sims, cache_key)

    # Fetch draftables for this slate
    try:
        dg_id = int(slate_id)
    except (ValueError, TypeError):
        raise HTTPException(400, "Invalid slate_id")

    try:
        draftables = await get_draftables(dg_id)
    except Exception as exc:
        logger.warning("Could not fetch draftables for DG-%d: %s", dg_id, exc)
        draftables = []

    if not draftables:
        return [SlateProjectionOut(**_sanitise_projection(p)) for p in all_projs]

    # Index sim projections by canonical name, raw lowercase, mlb_id, and
    # team+last_name for robust matching across name format differences
    proj_by_canonical: Dict[str, dict] = {}
    proj_by_lower: Dict[str, dict] = {}
    proj_by_mlb_id: Dict[int, dict] = {}
    proj_by_team_last: Dict[str, list] = {}  # "TEAM:lastname" -> [proj, ...]
    for p in all_projs:
        pname = p.get("player_name", "").strip()
        if pname:
            proj_by_lower[pname.lower()] = p
            proj_by_canonical[canonical_name(pname)] = p
            # Index by team + last name for fallback matching
            parts = pname.split()
            if parts:
                last_name = parts[-1].lower()
                team_key = (p.get("team", "") or "").upper()
                if team_key:
                    tl_key = f"{team_key}:{last_name}"
                    proj_by_team_last.setdefault(tl_key, []).append(p)
        # Index by MLB ID (most reliable match key)
        mlb_id = p.get("mlb_id")
        if mlb_id:
            proj_by_mlb_id[mlb_id] = p

    # Build set of projected starter/PLR pitcher mlb_ids and canonical names
    # (for filtering non-starting SPs from DK draftables)
    projected_pitcher_mlb_ids: set[int] = set()
    projected_pitcher_canonicals: set[str] = set()
    projected_pitcher_teams: set[str] = set()
    for p in all_projs:
        if p.get("is_pitcher") and p.get("team"):
            projected_pitcher_teams.add(p["team"].upper())
            pname = p.get("player_name", "").strip()
            if pname:
                projected_pitcher_canonicals.add(canonical_name(pname))
            pid = p.get("mlb_id")
            if pid:
                projected_pitcher_mlb_ids.add(pid)

    def _find_sim_proj(name: str, dk_id: int | None = None, team: str = "") -> dict | None:
        """Find a sim projection by mlb_id, exact name, canonical, team+last, or fuzzy match."""
        # Strategy 1: Exact lowercase match
        hit = proj_by_lower.get(name.lower())
        if hit:
            return hit

        # Strategy 2: Canonical name match (handles Jr./Sr., accents, nicknames)
        hit = proj_by_canonical.get(canonical_name(name))
        if hit:
            return hit

        # Strategy 3: Team + last name match (handles "Ronald Acuna" vs "Ronald Acuna Jr.")
        if team:
            parts = name.split()
            if parts:
                last_name = parts[-1].lower()
                tl_key = f"{team.upper()}:{last_name}"
                candidates = proj_by_team_last.get(tl_key, [])
                if len(candidates) == 1:
                    return candidates[0]
                elif len(candidates) > 1:
                    # Multiple matches on same team with same last name —
                    # try to narrow by first initial
                    first_initial = name[0].lower() if name else ""
                    for c in candidates:
                        cn = c.get("player_name", "")
                        if cn and cn[0].lower() == first_initial:
                            return c

        # Strategy 4: Fuzzy fallback (last name + first initial)
        result = find_name_in_dict(name, proj_by_lower)
        if result:
            return result[1]

        return None

    def _find_sim_proj_by_mlb_id(mlb_id: int | None) -> dict | None:
        """Find a sim projection directly by MLB ID."""
        if mlb_id:
            return proj_by_mlb_id.get(mlb_id)
        return None

    def _is_projected_pitcher(name: str, team: str, mlb_id: int | None = None) -> bool:
        """Check if a pitcher name/id matches a projected starter or PLR."""
        if mlb_id and mlb_id in projected_pitcher_mlb_ids:
            return True
        if canonical_name(name) in projected_pitcher_canonicals:
            return True
        return False

    # Build team->game context from sim projections (for fallback lookups)
    team_game_ctx: Dict[str, dict] = {}
    for p in all_projs:
        t = p.get("team", "")
        if t and t not in team_game_ctx and p.get("opp_team"):
            team_game_ctx[t] = {
                "opp_team": p.get("opp_team"),
                "is_home": p.get("is_home"),
                "game_pk": p.get("game_pk"),
                "venue": p.get("venue"),
                "team_implied": p.get("team_implied"),
                "game_total": p.get("game_total"),
            }

    # Build the set of teams actually on this slate from DK competition fields.
    # DK draftables sometimes include a handful of stray players from other
    # games. We identify slate games as those with ≥5 players, then only
    # include teams from those games.
    from collections import Counter as _Counter
    _game_player_count: dict[tuple[str, str], int] = {}
    for dk in draftables:
        comp = dk.get("competition") or {}
        comp_name = comp.get("name", "")
        if " @ " in comp_name:
            parts = [p.strip() for p in comp_name.split(" @ ")]
            if len(parts) == 2:
                game_key = (_normalise_dk_team(parts[0]), _normalise_dk_team(parts[1]))
                _game_player_count[game_key] = _game_player_count.get(game_key, 0) + 1
    slate_teams: set[str] = set()
    for (away, home), count in _game_player_count.items():
        if count >= 5:
            slate_teams.add(away)
            slate_teams.add(home)
    if slate_teams:
        logger.info("Slate DG-%d teams from competitions: %s", dg_id, sorted(slate_teams))

    # Collect unmatched RP draftables for batch sim-based RP projection
    unmatched_rp_draftables: list[dict] = []
    _seen_pre: set[str] = set()
    for dk in draftables:
        _name = dk.get("displayName", "").strip()
        if not _name or _name.lower() in _seen_pre:
            continue
        _seen_pre.add(_name.lower())
        _pos = dk.get("position", "")
        _team = _normalise_dk_team(dk.get("teamAbbreviation", ""))
        if slate_teams and _team not in slate_teams:
            continue
        if _pos in ("RP",) and not _find_sim_proj(_name, team=_team):
            unmatched_rp_draftables.append(dk)

    # Build RP projections via sim engine (appearance rate, recent usage, etc.)
    rp_proj_by_name: Dict[str, dict] = {}
    if unmatched_rp_draftables:
        from services.rp_projections import build_rp_projections
        try:
            rp_projs = await build_rp_projections(
                draftables=unmatched_rp_draftables,
                salary_lookup={},
                target_date=date_str,
                site=site,
                n_sims=n_sims,
            )
            for rp in rp_projs:
                rp_name = rp.get("player_name", "").strip().lower()
                if rp_name:
                    rp_proj_by_name[rp_name] = rp
            logger.info("Built %d RP sim projections for slate DG-%d", len(rp_proj_by_name), dg_id)
        except Exception as exc:
            logger.warning("RP projection batch failed for DG-%d: %s", dg_id, exc)

    # Build output: one entry per DK draftable player
    # Dedup by DK playerId (handles same player listed at multiple positions)
    results: list[dict] = []
    seen: set[str] = set()
    seen_dk_ids: set[int] = set()
    unmatched_names: list[str] = []

    for dk in draftables:
        name = dk.get("displayName", "").strip()
        if not name:
            continue
        name_lower = name.lower()
        if name_lower in seen:
            continue

        # Dedup by DK playerId: if DK lists the same player at multiple
        # positions (e.g., Willson Contreras at 1B and C), only keep the
        # first occurrence (highest salary since DK sorts by salary desc)
        dk_id = dk.get("playerId")
        if dk_id and dk_id in seen_dk_ids:
            continue
        if dk_id:
            seen_dk_ids.add(dk_id)
        seen.add(name_lower)

        salary = dk.get("salary", 0) or 0
        team = _normalise_dk_team(dk.get("teamAbbreviation", ""))
        position = dk.get("position", "UTIL")
        is_pitcher = position in ("SP", "RP", "P")

        # Skip players whose team isn't on this slate
        if slate_teams and team not in slate_teams:
            logger.debug("Skipping %s (%s) — team not on slate", name, team)
            continue

        # Extract opponent and home/away from DK competition field (e.g., "STL @ HOU")
        opp_team = _extract_dk_opponent(dk, team)
        dk_is_home = _extract_dk_is_home(dk, team)

        # Try to find a sim projection (multi-strategy matching)
        sim_proj = _find_sim_proj(name, dk_id=dk_id, team=team)

        # If name-based matching failed, try MLB ID lookup
        # (pipeline projections carry mlb_id; DK playerId sometimes == mlb_id)
        if not sim_proj and dk_id:
            sim_proj = _find_sim_proj_by_mlb_id(dk_id)

        if sim_proj:
            # Overlay DK salary/id onto the sim projection
            proj = dict(sim_proj)
            proj["salary"] = salary or proj.get("salary")
            proj["dk_id"] = dk_id or proj.get("dk_id")
            # Use DK team as source of truth (handles mid-season trades
            # where pipeline may still have the old team)
            proj["team"] = team
            if not proj.get("opp_team"):
                proj["opp_team"] = opp_team
            if opp_team:
                proj["opp_team"] = opp_team
            if proj.get("is_home") is None or dk_is_home is not None:
                proj["is_home"] = dk_is_home
            # Always use DK position (never DH — not a DK position)
            if position and position not in ("UTIL",):
                proj["position"] = position
            elif proj.get("position") in (None, "", "UTIL", "DH"):
                proj["position"] = position or "UTIL"
            # Mark projected starters
            if is_pitcher:
                proj["is_projected_starter"] = True
        elif name_lower in rp_proj_by_name:
            # Use sim-based RP projection (includes appearance rate, usage penalties)
            proj = dict(rp_proj_by_name[name_lower])
            proj["salary"] = salary or proj.get("salary")
            proj["dk_id"] = dk_id or proj.get("dk_id")
            ctx = team_game_ctx.get(team, {})
            if not proj.get("opp_team"):
                proj["opp_team"] = opp_team or ctx.get("opp_team")
            if proj.get("is_home") is None:
                proj["is_home"] = dk_is_home if dk_is_home is not None else ctx.get("is_home")
            if not proj.get("game_pk"):
                proj["game_pk"] = ctx.get("game_pk")
            if not proj.get("venue"):
                proj["venue"] = ctx.get("venue")
            if is_pitcher:
                proj["is_projected_starter"] = False
        else:
            # No sim projection found — log for diagnostics
            if is_pitcher or salary >= 3000:
                unmatched_names.append(f"{name} ({team}, {position}, ${salary})")

            # Task #2: Remove non-starting SPs entirely.
            # If this is an SP on a team where we have a projected pitcher,
            # and this player is NOT the projected starter, skip them.
            if position == "SP" and team.upper() in projected_pitcher_teams:
                if not _is_projected_pitcher(name, team):
                    continue  # Skip non-starting SP entirely

            # No sim projection — build a FPPG-based estimate
            fppg = _extract_dk_fppg(dk)
            base = max(fppg, 3.0) if fppg > 0 else (12.0 if is_pitcher else 6.0)

            # Deflate bench hitters by 70% — players in the starting lineup
            # get full sim projections from the pipeline. Unmatched hitters are
            # bench players who may not play; reduced projection reflects that.
            if not is_pitcher:
                base = base * 0.30

            # Pull game context from other players on same team
            ctx = team_game_ctx.get(team, {})
            if not opp_team:
                opp_team = ctx.get("opp_team")

            proj = {
                "player_name": name,
                "mlb_id": None,
                "dk_id": dk_id,
                "team": team,
                "position": position,
                "opp_team": opp_team,
                "is_home": dk_is_home if dk_is_home is not None else ctx.get("is_home"),
                "game_pk": ctx.get("game_pk"),
                "venue": ctx.get("venue"),
                "salary": salary,
                "batting_order": None,
                "is_pitcher": is_pitcher,
                "is_bench": not is_pitcher,
                "is_confirmed": False,
                "is_projected_starter": False if position == "SP" else None,
                "floor_pts": round(base * 0.3, 2),
                "median_pts": round(base, 2),
                "ceiling_pts": round(base * 2.5, 2),
                "projected_ownership": None,
                "season_era": None,
                "season_k9": None,
                "season_avg": None,
                "season_ops": None,
                "games_in_log": 0,
                "implied_total": ctx.get("team_implied"),
                "team_implied": ctx.get("team_implied"),
                "game_total": ctx.get("game_total"),
                "temperature": None,
            }

        results.append(proj)

    # Diagnostic logging: report unmatched players for debugging name mismatches
    if unmatched_names:
        logger.warning(
            "Slate DG-%d: %d draftables failed name matching: %s",
            dg_id, len(unmatched_names),
            "; ".join(unmatched_names[:20]),  # Cap at 20 to avoid log spam
        )

    # ------------------------------------------------------------------
    # Issue #8: Remove non-lineup batters for teams with confirmed lineups.
    # Build a set of confirmed players per team from pipeline projections.
    # For confirmed teams, exclude batters not in the confirmed lineup.
    # ------------------------------------------------------------------
    confirmed_teams: set[str] = set()
    confirmed_players_by_team: dict[str, set[str]] = {}

    for p in all_projs:
        team = p.get("team", "")
        if not team:
            continue
        # A player is in the confirmed lineup if is_confirmed=True and has a batting_order
        if p.get("is_confirmed") and p.get("batting_order") is not None and not p.get("is_pitcher"):
            confirmed_teams.add(team)
            confirmed_players_by_team.setdefault(team, set()).add(
                canonical_name(p.get("player_name", ""))
            )
        # Pitchers with is_confirmed=True also indicate the team has a lineup
        if p.get("is_confirmed") and p.get("is_pitcher"):
            confirmed_teams.add(team)

    if confirmed_teams:
        filtered_results: list[dict] = []
        for r in results:
            team = r.get("team", "")
            is_pitcher = r.get("is_pitcher", False)

            # Only filter batters on confirmed teams
            if not is_pitcher and team in confirmed_teams:
                player_cn = canonical_name(r.get("player_name", ""))
                team_confirmed_set = confirmed_players_by_team.get(team, set())
                if team_confirmed_set and player_cn not in team_confirmed_set:
                    # This batter is not in the confirmed lineup — exclude
                    continue
            filtered_results.append(r)

        logger.info(
            "Filtered %d non-lineup batters from confirmed teams",
            len(results) - len(filtered_results),
        )
        results = filtered_results

    matched_count = sum(1 for r in results if r.get("games_in_log", 0) > 0 or (r.get("is_confirmed") is True))
    logger.info(
        "Slate DG-%d: %d players (%d sim-matched, %d RP sim, %d fallback)",
        dg_id, len(results), matched_count, len(rp_proj_by_name),
        len(results) - matched_count - len(rp_proj_by_name),
    )

    return [SlateProjectionOut(**_sanitise_projection(p)) for p in results]


def _extract_dk_fppg(draftable: dict) -> float:
    """Extract FPPG from a draftable's stat attributes."""
    for attr in draftable.get("draftStatAttributes", []):
        # DK uses id=90 (FPPG) or id=408 (projected pts) depending on sport/season
        if attr.get("id") in (90, 408):
            try:
                return float(attr.get("value", 0))
            except (ValueError, TypeError):
                pass
    return 0.0


def _extract_dk_opponent(draftable: dict, player_team: str) -> Optional[str]:
    """Extract opponent team abbreviation from a DK draftable's competition field.

    The competition.name format is "AWAY @ HOME" (e.g., "STL @ HOU").
    Normalises both sides so ATH/OAK etc. match correctly.
    """
    comp = draftable.get("competition") or {}
    comp_name = comp.get("name", "")
    if " @ " not in comp_name:
        return None
    parts = [p.strip() for p in comp_name.split(" @ ")]
    if len(parts) != 2:
        return None
    away_raw, home_raw = parts
    away = _normalise_dk_team(away_raw)
    home = _normalise_dk_team(home_raw)
    pt = player_team.upper()
    if pt == away:
        return home
    if pt == home:
        return away
    return None


def _extract_dk_is_home(draftable: dict, player_team: str) -> Optional[bool]:
    """Determine if a player is on the home team from the DK competition field."""
    comp = draftable.get("competition") or {}
    comp_name = comp.get("name", "")
    if " @ " not in comp_name:
        return None
    parts = [p.strip() for p in comp_name.split(" @ ")]
    if len(parts) != 2:
        return None
    _away_raw, home_raw = parts
    home = _normalise_dk_team(home_raw)
    return player_team.upper() == home


async def _generate_and_cache(
    date_str: str, site: str, n_sims: int, cache_key: str,
) -> list[dict]:
    """Run the projection pipeline and store results in cache."""
    from services.projection_pipeline import generate_projections

    logger.info("Generating staging projections for %s (site=%s, n_sims=%d)", date_str, site, n_sims)
    t0 = time.time()

    try:
        projections = await generate_projections(
            target_date=date_str, site=site, n_sims=n_sims,
        )
    except Exception as exc:
        logger.error("Projection pipeline failed: %s", exc, exc_info=True)
        raise HTTPException(500, f"Projection pipeline failed: {exc}")

    elapsed = time.time() - t0
    logger.info("Generated %d projections in %.1fs", len(projections), elapsed)
    _projection_cache[cache_key] = (time.time(), projections)
    return projections


@router.get("/debug/cache")
async def debug_cache(
    site: str = Query("dk", pattern="^(dk|fd)$"),
    target_date: str = Query(None),
):
    """Debug: show what's in the projection cache."""
    try:
        d = date.fromisoformat(target_date) if target_date else date.today()
    except ValueError:
        raise HTTPException(400, "Invalid date")
    cache_key = f"{d.isoformat()}-{site}"
    if cache_key not in _projection_cache:
        return {"status": "empty", "cache_key": cache_key, "keys": list(_projection_cache.keys())}
    ts, projs = _projection_cache[cache_key]
    sample = []
    for p in projs[:10]:
        sample.append({
            "player_name": p.get("player_name"),
            "team": p.get("team"),
            "median_pts": p.get("median_pts"),
            "mlb_id": p.get("mlb_id"),
            "is_pitcher": p.get("is_pitcher"),
        })
    return {
        "status": "found",
        "cache_key": cache_key,
        "total": len(projs),
        "age_seconds": round(time.time() - ts, 1),
        "sample": sample,
    }


@router.get("/generate", response_model=GenerateResult)
async def force_generate_projections(
    site: str = Query("dk", pattern="^(dk|fd)$"),
    target_date: str = Query(None, description="YYYY-MM-DD, defaults to today"),
    n_sims: int = Query(1000, ge=100, le=10000, description="Monte Carlo iterations"),
):
    """Force regenerate projections (bypasses cache). Useful for testing.

    Returns a summary of the generation run rather than the full projection list.
    Use the featured projections endpoint to retrieve the full data.
    """
    try:
        d = date.fromisoformat(target_date) if target_date else date.today()
    except ValueError:
        raise HTTPException(400, "Invalid date, use YYYY-MM-DD")

    date_str = d.isoformat()
    cache_key = f"{date_str}-{site}"

    from services.projection_pipeline import generate_projections

    logger.info("Force-generating projections for %s (site=%s, n_sims=%d)", date_str, site, n_sims)
    t0 = time.time()

    try:
        projections = await generate_projections(
            target_date=date_str,
            site=site,
            n_sims=n_sims,
        )
    except Exception as exc:
        logger.error("Projection pipeline failed: %s", exc, exc_info=True)
        raise HTTPException(500, f"Projection pipeline failed: {exc}")

    elapsed = time.time() - t0

    # Update cache
    _projection_cache[cache_key] = (time.time(), projections)

    return GenerateResult(
        status="ok",
        projection_count=len(projections),
        elapsed_seconds=round(elapsed, 1),
        target_date=date_str,
        site=site,
        n_sims=n_sims,
    )


# ---------------------------------------------------------------------------
# Game Center endpoints (lineups + overlays for staging)
# ---------------------------------------------------------------------------


@router.get("/lineups/games", response_model=List[GameLineupOut])
async def get_staging_game_lineups(
    site: str = Query("dk", pattern="^(dk|fd)$"),
    force_refresh: bool = Query(False),
    target_date: str = Query(None, description="YYYY-MM-DD, defaults to today"),
    slate_id: str = Query(None, description="Slate ID for filtering"),
):
    """Game Center for staging: lineups from RotoGrinders + sim projection overlays."""
    from services.lineup_scraper import fetch_lineups
    from services.vegas import fetch_fantasylabs_odds
    from services.name_matching import canonical_name
    import asyncio as _aio

    try:
        d = date.fromisoformat(target_date) if target_date else date.today()
    except ValueError:
        raise HTTPException(400, "Invalid date, use YYYY-MM-DD")

    date_str = d.isoformat()
    cache_key = f"{date_str}-{site}"

    # Get cached projections for median_pts / salary overlay
    proj_by_lower: Dict[str, dict] = {}
    proj_by_canonical: Dict[str, dict] = {}
    if cache_key in _projection_cache:
        ts, cached_projs = _projection_cache[cache_key]
        if time.time() - ts < _CACHE_TTL:
            for p in cached_projs:
                pname = p.get("player_name", "").strip()
                if pname:
                    proj_by_lower[pname.lower()] = p
                    proj_by_canonical[canonical_name(pname)] = p

    def _overlay_lookup(name: str):
        proj = proj_by_lower.get(name.strip().lower())
        if not proj:
            proj = proj_by_canonical.get(canonical_name(name))
        if not proj:
            result = find_name_in_dict(name, proj_by_lower)
            if result:
                proj = result[1]
        if proj:
            return proj.get("salary"), proj.get("median_pts"), proj.get("opener_status")
        return None, None, None

    # Fetch lineups + odds in parallel
    async def _fetch_lineups():
        try:
            return await fetch_lineups(force_refresh=force_refresh, target_date=date_str)
        except Exception:
            return []

    async def _fetch_odds():
        try:
            return await fetch_fantasylabs_odds(target_date=date_str)
        except Exception:
            return []

    games, fl_odds = await _aio.gather(_fetch_lineups(), _fetch_odds())

    odds_by_matchup: Dict[tuple, dict] = {}
    for od in fl_odds:
        odds_by_matchup[(od["away_team"], od["home_team"])] = od

    # Determine slate teams for filtering
    slate_teams_set: set[str] = set()
    if slate_id:
        try:
            dg_id = int(slate_id)
            draftables = await get_draftables(dg_id)
            slate_teams_set = {d.get("teamAbbreviation", "") for d in draftables if d.get("teamAbbreviation")}
        except Exception:
            pass

    results = []
    for game in games:
        home_team = game.home.team
        away_team = game.away.team

        matchup_odds = odds_by_matchup.get((away_team, home_team))

        def _overlay(name):
            return _overlay_lookup(name)

        def _team_out(tl, is_home):
            pitcher_out = None
            if tl.pitcher:
                sal, pts, opener_st = _overlay(tl.pitcher.name)
                pitcher_out = PlayerLineupOut(
                    name=tl.pitcher.name, position="P",
                    handedness=tl.pitcher.handedness, salary=sal, median_pts=pts,
                    opener_status=opener_st,
                )
            batters_out = []
            for b in sorted(tl.batters, key=lambda x: x.batting_order or 99):
                sal, pts, opener_st = _overlay(b.name)
                batters_out.append(PlayerLineupOut(
                    name=b.name, position=b.position,
                    batting_order=b.batting_order, handedness=b.handedness,
                    salary=sal, median_pts=pts,
                    opener_status=opener_st,
                ))
            imp_key = "home_implied" if is_home else "away_implied"
            imp_total = matchup_odds.get(imp_key) if matchup_odds else None
            return TeamLineupOut(
                team=tl.team, status=tl.status,
                pitcher=pitcher_out, batters=batters_out,
                implied_total=imp_total,
            )

        away_out = _team_out(game.away, False)
        home_out = _team_out(game.home, True)

        vegas_total = matchup_odds.get("game_total") if matchup_odds else None
        vegas_spread = matchup_odds.get("spread") if matchup_odds else None
        away_ml = matchup_odds.get("away_ml") if matchup_odds else None
        home_ml = matchup_odds.get("home_ml") if matchup_odds else None

        game_slate_teams = []
        if slate_teams_set:
            if away_team in slate_teams_set:
                game_slate_teams.append(away_team)
            if home_team in slate_teams_set:
                game_slate_teams.append(home_team)

        results.append(GameLineupOut(
            away=away_out, home=home_out,
            game_time=game.game_time,
            vegas_total=round(vegas_total, 1) if vegas_total else None,
            vegas_spread=round(vegas_spread, 1) if vegas_spread else None,
            away_ml=away_ml, home_ml=home_ml,
            weather=None,
            home_team_abbr=home_team,
            slate_teams=game_slate_teams,
        ))

    return results


@router.get("/lineups/games/live", response_model=List[LiveGameState])
async def get_staging_live_scores():
    """Proxy to the production live scores endpoint."""
    from api.projections import get_live_game_scores
    return await get_live_game_scores()


@router.post("/odds/clear-lock")
async def clear_odds_prematch_lock(
    target_date: str = Query(None, description="YYYY-MM-DD, defaults to today"),
):
    """Clear the prematch odds lock for a date, allowing fresh odds to be fetched.

    Use this if odds were locked before all game lines were posted, or if
    you need to refresh odds during the prematch window (e.g. lineup changes
    affecting lines before first pitch).
    """
    from services.vegas import clear_prematch_lock

    try:
        d = date.fromisoformat(target_date) if target_date else date.today()
    except ValueError:
        raise HTTPException(400, "Invalid date, use YYYY-MM-DD")

    was_locked = clear_prematch_lock(d.isoformat())
    return {
        "status": "cleared" if was_locked else "no_lock_existed",
        "date": d.isoformat(),
    }
