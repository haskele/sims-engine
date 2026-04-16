"""Projection endpoints: get, edit, bulk update, auto-generate, slate-scoped projections, and slate reports."""
from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.player import Player
from models.projection import Projection
from models.slate_report import SlateReport
from models.slate_history import SlateHistory
from services.csv_projections import (
    identify_featured_csv_slate,
    list_available_slates as list_csv_slates,
    load_csv_projections,
)
from services.lineup_scraper import (
    _normalise_team,
    apply_lineup_status,
    build_lineup_lookup,
    fetch_lineups,
)
from services.projections import build_player_projection
from services.slate_manager import fetch_dk_slates, identify_featured_slate
from services.dk_props import fetch_player_props
from services.name_matching import build_canonical_lookup, canonical_name, find_in_dict as find_name_in_dict
from services.vegas import fetch_fantasylabs_odds

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/projections", tags=["projections"])


# ── Pydantic schemas ────────────────────────────────────────────────────────


class ProjectionOut(BaseModel):
    id: int
    player_id: int
    game_id: int
    site: str
    floor_pts: float
    median_pts: float
    ceiling_pts: float
    projected_ownership: Optional[float] = None
    batting_order: Optional[int] = None
    is_confirmed: bool = False

    model_config = {"from_attributes": True}


class ProjectionUpdate(BaseModel):
    floor_pts: Optional[float] = None
    median_pts: Optional[float] = None
    ceiling_pts: Optional[float] = None
    projected_ownership: Optional[float] = None
    batting_order: Optional[int] = None
    is_confirmed: Optional[bool] = None


class BulkProjectionItem(BaseModel):
    player_id: int
    game_id: int
    site: str = "dk"
    floor_pts: float
    median_pts: float
    ceiling_pts: float
    projected_ownership: Optional[float] = None
    batting_order: Optional[int] = None
    is_confirmed: bool = False


class BulkProjectionRequest(BaseModel):
    projections: List[BulkProjectionItem]


class BulkProjectionResult(BaseModel):
    created: int
    updated: int
    errors: List[str] = []


class GenerateRequest(BaseModel):
    """Request to auto-generate projections for players in a game."""
    game_id: int
    site: str = "dk"
    player_ids: Optional[List[int]] = None
    implied_runs: Optional[float] = None
    opp_pitcher_k9: Optional[float] = None


class SlateOut(BaseModel):
    slate_id: str
    site: str
    name: str
    game_count: int
    start_time: Optional[str] = None
    game_type: str
    draft_group_id: int = 0
    is_historical: bool = False  # True when slate comes from SlateHistory (no live CSV)


class SlateProjectionOut(BaseModel):
    player_name: str
    mlb_id: Optional[int] = None
    team: str
    position: str
    opp_team: Optional[str] = None
    game_pk: Optional[int] = None
    venue: Optional[str] = None
    salary: Optional[int] = None
    batting_order: Optional[int] = None
    is_pitcher: bool = False
    is_confirmed: bool = False
    floor_pts: float
    median_pts: float
    ceiling_pts: float
    projected_ownership: Optional[float] = None
    season_era: Optional[float] = None
    season_k9: Optional[float] = None
    season_avg: Optional[float] = None
    season_ops: Optional[float] = None
    games_in_log: int = 0
    implied_total: Optional[float] = None
    team_implied: Optional[float] = None
    temperature: Optional[float] = None
    lineup_status: str = "unknown"  # "confirmed", "expected", "out", "unknown"
    dk_id: Optional[int] = None
    min_exposure: Optional[float] = None
    max_exposure: Optional[float] = None
    # DK Sportsbook player props
    k_line: Optional[str] = None      # Pitcher K prop, e.g. "4.5 (-154)"
    hr_line: Optional[str] = None     # Batter HR 1+, e.g. "+407"
    tb_line: Optional[str] = None     # Batter 2+ TB, e.g. "-110"
    hrr_line: Optional[str] = None    # Batter 2+ H+R+RBI, e.g. "-156"


# ── Slate-scoped endpoints (MUST be before /{projection_id} to avoid route conflict) ──


@router.get("/slates", response_model=List[SlateOut])
async def list_slates(
    site: str = Query("dk", pattern="^(dk|fd)$"),
    target_date: str = Query(None, description="YYYY-MM-DD, defaults to today"),
    db: AsyncSession = Depends(get_db),
):
    """List available DFS slates for a given date and site.

    Prioritises CSV-based slates (uploaded projection files) and falls
    back to the DK lobby API.  Any CSV-based slates found are persisted
    to SlateHistory so they remain available after the CSV files are
    deleted.  When no CSV slates exist for a date, historical records
    are returned instead.
    """
    try:
        d = date.fromisoformat(target_date) if target_date else date.today()
    except ValueError:
        raise HTTPException(400, "Invalid date, use YYYY-MM-DD")

    # Check for CSV-based slates first
    csv_slates = list_csv_slates(target_date=d, site=site)

    if csv_slates:
        # Persist each CSV slate to SlateHistory (upsert by slate_id)
        await _save_slates_to_history(db, csv_slates, d)

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
            for s in csv_slates
        ]

    # No CSV files -- check SlateHistory for this date
    history_slates = await _get_history_slates(db, d.isoformat(), site)
    if history_slates:
        return history_slates

    # Fallback to DK API
    if site == "dk":
        slates = await fetch_dk_slates(target_date=d)
    else:
        slates = []

    return [
        SlateOut(
            slate_id=s["slate_id"],
            site=s["site"],
            name=s["name"],
            game_count=s["game_count"],
            start_time=s.get("start_time"),
            game_type=s["game_type"],
            draft_group_id=s["draft_group_id"],
            is_historical=False,
        )
        for s in slates
    ]


class SlateHistoryDateGroup(BaseModel):
    date: str
    slates: List[SlateOut]


@router.get("/slates/history", response_model=List[SlateHistoryDateGroup])
async def list_slate_history(
    days: int = Query(30, ge=1, le=365),
    site: str = Query("dk", pattern="^(dk|fd)$"),
    db: AsyncSession = Depends(get_db),
):
    """Return all historical slate records from the past N days, grouped by date."""
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    stmt = (
        select(SlateHistory)
        .where(SlateHistory.slate_date >= cutoff, SlateHistory.site == site)
        .order_by(SlateHistory.slate_date.desc(), SlateHistory.created_at.desc())
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()

    # Group by date
    by_date: Dict[str, List[SlateOut]] = {}
    for r in rows:
        slate_out = SlateOut(
            slate_id=r.slate_id,
            site=r.site,
            name=r.name or r.slate_id,
            game_count=r.game_count or 0,
            start_time=r.start_time,
            game_type=r.game_type or "classic",
            draft_group_id=r.draft_group_id or 0,
            is_historical=True,
        )
        by_date.setdefault(r.slate_date, []).append(slate_out)

    return [
        SlateHistoryDateGroup(date=d, slates=slates)
        for d, slates in sorted(by_date.items(), reverse=True)
    ]


@router.get("/slates/featured/projections", response_model=List[SlateProjectionOut])
async def get_featured_slate_projections(
    site: str = Query("dk", pattern="^(dk|fd)$"),
    target_date: str = Query(None, description="YYYY-MM-DD"),
):
    """Get projections for the featured/main slate.

    Uses CSV projections when available, falls back to the pipeline.
    """
    try:
        d = date.fromisoformat(target_date) if target_date else date.today()
    except ValueError:
        raise HTTPException(400, "Invalid date, use YYYY-MM-DD")

    # Try CSV-based projections first
    csv_slates = list_csv_slates(target_date=d, site=site)
    if csv_slates:
        featured = identify_featured_csv_slate(csv_slates)
        if featured and featured.get("csv_path"):
            projections = load_csv_projections(featured["csv_path"], site)
            projections = await _overlay_lineup_status(projections, target_date=d.isoformat())
            projections = await _overlay_player_props(projections)
            return [
                SlateProjectionOut(**_sanitise_projection(p))
                for p in projections
            ]

    # Fallback to pipeline
    from services.daily_pipeline import run_daily_pipeline
    d_str = target_date or date.today().isoformat()
    result = await run_daily_pipeline(d_str, site)
    projections = result.get("projections", [])
    return [
        SlateProjectionOut(**_sanitise_projection(p))
        for p in projections
    ]


@router.get("/slates/{slate_id}/projections", response_model=List[SlateProjectionOut])
async def get_slate_projections(
    slate_id: str,
    site: str = Query("dk", pattern="^(dk|fd)$"),
    target_date: str = Query(None, description="YYYY-MM-DD"),
    db: AsyncSession = Depends(get_db),
):
    """Get projections scoped to a specific slate.

    Uses CSV projections when the slate_id matches a CSV filename.
    Automatically saves a slate report snapshot on each load.
    """
    try:
        d = date.fromisoformat(target_date) if target_date else date.today()
    except ValueError:
        raise HTTPException(400, "Invalid date, use YYYY-MM-DD")

    slate_name: Optional[str] = None
    game_count: Optional[int] = None
    projections: List[Dict[str, Any]] = []

    # Extract date from slate_id for lineup lookups (format: MLB_YYYY-MM-DD-...)
    slate_date_str = _extract_date_from_slate_id(slate_id) or d.isoformat()

    # Check if this slate_id matches a CSV file
    csv_slates = list_csv_slates(target_date=d, site=site)
    for cs in csv_slates:
        if cs["slate_id"] == slate_id and cs.get("csv_path"):
            slate_name = cs.get("name")
            game_count = cs.get("game_count")
            projections = load_csv_projections(cs["csv_path"], site)
            projections = await _overlay_lineup_status(projections, target_date=slate_date_str)
            projections = await _overlay_player_props(projections)
            break

    if not projections:
        # Fallback: try loading from a saved SlateReport snapshot (historical)
        report_result = await db.execute(
            select(SlateReport).where(
                SlateReport.slate_id == slate_id,
                SlateReport.report_date == d.isoformat(),
            )
        )
        report = report_result.scalar_one_or_none()
        if report and report.projections_snapshot:
            projections = json.loads(report.projections_snapshot)
            logger.info("Loaded historical projections from SlateReport: slate=%s date=%s", slate_id, d.isoformat())

    if not projections:
        # Final fallback to pipeline (only for today/recent)
        from services.daily_pipeline import run_daily_pipeline
        d_str = target_date or date.today().isoformat()
        result = await run_daily_pipeline(d_str, site)
        projections = result.get("projections", [])

    # Auto-save slate report snapshot (only when we have fresh CSV data)
    if projections and csv_slates:
        await _auto_save_slate_report(
            db=db,
            slate_id=slate_id,
            site=site,
            report_date=d.isoformat(),
            slate_name=slate_name,
            game_count=game_count,
            projections=projections,
        )

    return [
        SlateProjectionOut(**_sanitise_projection(p))
        for p in projections
    ]


# ── Core CRUD endpoints ───────────────────────────────────────────────────────


@router.get("/", response_model=List[ProjectionOut])
async def list_projections(
    game_id: Optional[int] = None,
    site: Optional[str] = Query(None, pattern="^(dk|fd)$"),
    db: AsyncSession = Depends(get_db),
):
    """List projections with optional filters."""
    stmt = select(Projection).order_by(Projection.median_pts.desc())
    if game_id:
        stmt = stmt.where(Projection.game_id == game_id)
    if site:
        stmt = stmt.where(Projection.site == site)
    result = await db.execute(stmt)
    return [ProjectionOut.model_validate(r) for r in result.scalars().all()]


@router.get("/{projection_id}", response_model=ProjectionOut)
async def get_projection(projection_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Projection).where(Projection.id == projection_id)
    )
    proj = result.scalar_one_or_none()
    if not proj:
        raise HTTPException(404, "Projection not found")
    return ProjectionOut.model_validate(proj)


@router.patch("/{projection_id}", response_model=ProjectionOut)
async def update_projection(
    projection_id: int,
    body: ProjectionUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Edit a single projection (manual override)."""
    result = await db.execute(
        select(Projection).where(Projection.id == projection_id)
    )
    proj = result.scalar_one_or_none()
    if not proj:
        raise HTTPException(404, "Projection not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(proj, field, value)
    await db.flush()
    await db.refresh(proj)
    return ProjectionOut.model_validate(proj)


@router.post("/bulk", response_model=BulkProjectionResult)
async def bulk_upsert_projections(
    body: BulkProjectionRequest, db: AsyncSession = Depends(get_db)
):
    """Create or update projections in bulk (upsert by player_id + game_id + site)."""
    created = 0
    updated = 0
    errors: List[str] = []

    for item in body.projections:
        try:
            result = await db.execute(
                select(Projection).where(
                    Projection.player_id == item.player_id,
                    Projection.game_id == item.game_id,
                    Projection.site == item.site,
                )
            )
            existing = result.scalar_one_or_none()

            if existing:
                existing.floor_pts = item.floor_pts
                existing.median_pts = item.median_pts
                existing.ceiling_pts = item.ceiling_pts
                if item.projected_ownership is not None:
                    existing.projected_ownership = item.projected_ownership
                if item.batting_order is not None:
                    existing.batting_order = item.batting_order
                existing.is_confirmed = item.is_confirmed
                updated += 1
            else:
                proj = Projection(
                    player_id=item.player_id,
                    game_id=item.game_id,
                    site=item.site,
                    floor_pts=item.floor_pts,
                    median_pts=item.median_pts,
                    ceiling_pts=item.ceiling_pts,
                    projected_ownership=item.projected_ownership,
                    batting_order=item.batting_order,
                    is_confirmed=item.is_confirmed,
                )
                db.add(proj)
                created += 1
        except Exception as exc:
            errors.append(
                f"player_id={item.player_id} game_id={item.game_id}: {exc}"
            )

    await db.flush()
    return BulkProjectionResult(created=created, updated=updated, errors=errors)


@router.post("/generate", response_model=BulkProjectionResult)
async def generate_projections(
    body: GenerateRequest, db: AsyncSession = Depends(get_db)
):
    """Auto-generate 3-bucket projections from MLB game logs."""
    if body.player_ids:
        result = await db.execute(
            select(Player).where(Player.id.in_(body.player_ids))
        )
        players = list(result.scalars().all())
    else:
        result = await db.execute(select(Player).where(Player.mlb_id.isnot(None)))
        players = list(result.scalars().all())

    if not players:
        raise HTTPException(400, "No players found to project")

    created = 0
    updated = 0
    errors: List[str] = []

    for player in players:
        if not player.mlb_id:
            errors.append(f"Player {player.id} ({player.name}): no mlb_id")
            continue

        is_pitcher = "P" in player.position.split("/")
        try:
            proj_data = await build_player_projection(
                player_id=player.mlb_id,
                site=body.site,
                is_pitcher=is_pitcher,
                batting_order=None,
                implied_runs=body.implied_runs,
                opp_pitcher_k9=body.opp_pitcher_k9,
            )
        except Exception as exc:
            errors.append(f"Player {player.id} ({player.name}): {exc}")
            continue

        result = await db.execute(
            select(Projection).where(
                Projection.player_id == player.id,
                Projection.game_id == body.game_id,
                Projection.site == body.site,
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            existing.floor_pts = proj_data["floor_pts"]
            existing.median_pts = proj_data["median_pts"]
            existing.ceiling_pts = proj_data["ceiling_pts"]
            updated += 1
        else:
            proj = Projection(
                player_id=player.id,
                game_id=body.game_id,
                site=body.site,
                floor_pts=proj_data["floor_pts"],
                median_pts=proj_data["median_pts"],
                ceiling_pts=proj_data["ceiling_pts"],
            )
            db.add(proj)
            created += 1

    await db.flush()
    return BulkProjectionResult(created=created, updated=updated, errors=errors)



# ── Slate report endpoints ─────────────────────────────────────────────────


class SlateReportSummary(BaseModel):
    id: int
    slate_id: str
    site: str
    report_date: str
    slate_name: Optional[str] = None
    game_count: Optional[int] = None
    player_count: Optional[int] = None
    created_at: Optional[str] = None

    model_config = {"from_attributes": True}


class SlateReportDetail(SlateReportSummary):
    projections_snapshot: Optional[List[Dict[str, Any]]] = None
    ownership_snapshot: Optional[List[Dict[str, Any]]] = None
    lineup_snapshot: Optional[List[Dict[str, Any]]] = None


class SlateReportOut(BaseModel):
    id: int
    slate_id: str
    report_date: str
    player_count: Optional[int] = None
    status: str = "saved"


@router.post("/slates/{slate_id}/report", response_model=SlateReportOut)
async def save_slate_report(
    slate_id: str,
    site: str = Query("dk", pattern="^(dk|fd)$"),
    target_date: str = Query(None, description="YYYY-MM-DD, defaults to today"),
    db: AsyncSession = Depends(get_db),
):
    """Save a snapshot of the current slate's projections, ownership, and lineup data.

    If a report already exists for this slate+date, it is updated (upsert).
    """
    try:
        d = date.fromisoformat(target_date) if target_date else date.today()
    except ValueError:
        raise HTTPException(400, "Invalid date, use YYYY-MM-DD")

    # Load current projection data for this slate
    slate_name: Optional[str] = None
    game_count: Optional[int] = None
    projections: List[Dict[str, Any]] = []

    csv_slates = list_csv_slates(target_date=d, site=site)
    for cs in csv_slates:
        if cs["slate_id"] == slate_id and cs.get("csv_path"):
            slate_name = cs.get("name")
            game_count = cs.get("game_count")
            projections = load_csv_projections(cs["csv_path"], site)
            projections = await _overlay_lineup_status(projections, target_date=d.isoformat())
            break

    if not projections:
        raise HTTPException(404, f"No projections found for slate {slate_id}")

    report = await _auto_save_slate_report(
        db=db,
        slate_id=slate_id,
        site=site,
        report_date=d.isoformat(),
        slate_name=slate_name,
        game_count=game_count,
        projections=projections,
    )

    return SlateReportOut(
        id=report.id,
        slate_id=report.slate_id,
        report_date=report.report_date,
        player_count=report.player_count,
        status="saved",
    )


@router.get("/reports", response_model=List[SlateReportSummary])
async def list_slate_reports(
    report_date: str = Query(None, alias="date", description="YYYY-MM-DD, defaults to today"),
    site: str = Query("dk", pattern="^(dk|fd)$"),
    db: AsyncSession = Depends(get_db),
):
    """List all slate reports for a given date and site."""
    try:
        d = date.fromisoformat(report_date) if report_date else date.today()
    except ValueError:
        raise HTTPException(400, "Invalid date, use YYYY-MM-DD")

    stmt = (
        select(SlateReport)
        .where(SlateReport.report_date == d.isoformat(), SlateReport.site == site)
        .order_by(SlateReport.created_at.desc())
    )
    result = await db.execute(stmt)
    reports = result.scalars().all()

    return [
        SlateReportSummary(
            id=r.id,
            slate_id=r.slate_id,
            site=r.site,
            report_date=r.report_date,
            slate_name=r.slate_name,
            game_count=r.game_count,
            player_count=r.player_count,
            created_at=r.created_at.isoformat() if r.created_at else None,
        )
        for r in reports
    ]


@router.get("/reports/{report_id}", response_model=SlateReportDetail)
async def get_slate_report(
    report_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get a specific slate report with full snapshot data."""
    result = await db.execute(
        select(SlateReport).where(SlateReport.id == report_id)
    )
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(404, "Slate report not found")

    return SlateReportDetail(
        id=report.id,
        slate_id=report.slate_id,
        site=report.site,
        report_date=report.report_date,
        slate_name=report.slate_name,
        game_count=report.game_count,
        player_count=report.player_count,
        created_at=report.created_at.isoformat() if report.created_at else None,
        projections_snapshot=json.loads(report.projections_snapshot) if report.projections_snapshot else None,
        ownership_snapshot=json.loads(report.ownership_snapshot) if report.ownership_snapshot else None,
        lineup_snapshot=json.loads(report.lineup_snapshot) if report.lineup_snapshot else None,
    )


# ── Lineup status endpoints ────────────────────────────────────────────────


class LineupStatusOut(BaseModel):
    team: str
    status: str  # confirmed / expected / unknown
    pitcher: Optional[str] = None
    batters: int = 0
    last_checked: Optional[str] = None


class PlayerLineupOut(BaseModel):
    name: str
    position: str
    batting_order: Optional[int] = None
    handedness: str = ""
    salary: Optional[int] = None


class TeamLineupOut(BaseModel):
    team: str
    status: str
    pitcher: Optional[PlayerLineupOut] = None
    batters: List[PlayerLineupOut] = []
    implied_total: Optional[float] = None


class WeatherOut(BaseModel):
    temperature: Optional[float] = None
    wind_speed: Optional[float] = None
    wind_dir: Optional[float] = None
    precip_pct: Optional[float] = None
    is_dome: bool = False


class GameLineupOut(BaseModel):
    away: TeamLineupOut
    home: TeamLineupOut
    game_time: str = ""
    vegas_total: Optional[float] = None
    vegas_spread: Optional[float] = None
    away_ml: Optional[int] = None
    home_ml: Optional[int] = None
    weather: Optional[WeatherOut] = None
    home_team_abbr: str = ""
    slate_teams: List[str] = []


class LiveGameState(BaseModel):
    away_team: str
    home_team: str
    away_score: int = 0
    home_score: int = 0
    inning: int = 0
    inning_half: str = ""  # "top" or "bottom"
    game_status: str = ""  # "Preview", "Live", "Final"
    game_pk: Optional[int] = None


@router.get("/lineups/status", response_model=List[LineupStatusOut])
async def get_lineup_status(
    force_refresh: bool = Query(False, description="Force refresh lineup data"),
    target_date: str = Query(None, description="YYYY-MM-DD, defaults to today"),
):
    """Get current lineup confirmation status for all teams.

    Fetches the latest lineup data from external sources.
    Results are cached for 90 seconds unless force_refresh=True.
    For future dates, uses MLB Stats API for probable pitchers.
    """
    games = await fetch_lineups(force_refresh=force_refresh, target_date=target_date)
    results = []
    for game in games:
        for tl in (game.away, game.home):
            results.append(LineupStatusOut(
                team=tl.team,
                status=tl.status,
                pitcher=tl.pitcher.name if tl.pitcher else None,
                batters=len(tl.batters),
                last_checked=tl.last_checked,
            ))
    return results


@router.get("/lineups/games", response_model=List[GameLineupOut])
async def get_game_lineups(
    site: str = Query("dk", pattern="^(dk|fd)$"),
    force_refresh: bool = Query(False, description="Force refresh lineup data"),
    target_date: str = Query(None, description="YYYY-MM-DD, defaults to today"),
):
    """Get full lineup data for all games.

    Returns complete game-by-game lineup info with pitcher names,
    batting orders, positions, handedness, salaries, weather, vegas
    odds, implied totals, and which teams are in each CSV slate.
    Used by the GameCenter tab.

    When live lineup data doesn't include batting orders for a team,
    projected batting orders from the CSV projections are used as a fallback.

    For future dates, uses MLB Stats API for probable pitchers and CSV
    projections for batting orders.
    """
    games = await fetch_lineups(force_refresh=force_refresh, target_date=target_date)

    # Load CSV projections to fill in projected batting orders, salaries, and implied totals
    csv_data = _build_projected_lineups_extended(site, target_date=target_date)
    projected_by_team = csv_data["lineups"]
    salary_lookup_raw = csv_data["salaries"]
    # Build canonical salary lookup for fuzzy name matching
    salary_lookup = build_canonical_lookup(salary_lookup_raw)
    csv_implied_lookup = csv_data["implied_totals"]  # team -> team implied runs (from Saber Team)
    csv_game_total_lookup = csv_data["game_totals"]  # team -> game O/U (from Saber Total)
    slate_teams_set = csv_data["slate_teams"]

    # Fetch real vegas odds from Fantasy Labs (moneylines, O/U, spread)
    fl_odds = await fetch_fantasylabs_odds(target_date=target_date)
    # Build lookup: (away_team, home_team) -> odds dict
    odds_by_matchup: Dict[tuple, Dict[str, Any]] = {}
    for odds in fl_odds:
        key = (odds["away_team"], odds["home_team"])
        odds_by_matchup[key] = odds

    # Fetch weather for each unique home team
    weather_cache: Dict[str, WeatherOut] = {}
    for game in games:
        home_team = game.home.team
        if home_team not in weather_cache:
            weather_cache[home_team] = await _get_game_weather(home_team)

    results = []
    for game in games:
        home_team = game.home.team
        away_team = game.away.team

        # Look up real vegas odds for this matchup
        matchup_odds = odds_by_matchup.get((away_team, home_team))

        def _team_out(tl, is_home: bool):
            team = tl.team
            pitcher_out = None
            if tl.pitcher:
                sal = salary_lookup.get(canonical_name(tl.pitcher.name))
                pitcher_out = PlayerLineupOut(
                    name=tl.pitcher.name,
                    position="P",
                    handedness=tl.pitcher.handedness,
                    salary=sal,
                )
            batters_out = [
                PlayerLineupOut(
                    name=b.name,
                    position=b.position,
                    batting_order=b.batting_order,
                    handedness=b.handedness,
                    salary=salary_lookup.get(canonical_name(b.name)),
                )
                for b in sorted(tl.batters, key=lambda x: x.batting_order or 99)
            ]

            # If live data has no batters, fill from CSV projected batting orders
            if not batters_out and team in projected_by_team:
                proj_team = projected_by_team[team]
                batters_out = proj_team["batters"]
                if not pitcher_out and proj_team.get("pitcher"):
                    pitcher_out = proj_team["pitcher"]

            status = tl.status
            if not tl.batters and batters_out and status == "unknown":
                status = "projected"

            # Implied total: prefer Fantasy Labs derived, fall back to CSV Saber Team
            imp_key = "home_implied" if is_home else "away_implied"
            imp_total = matchup_odds.get(imp_key) if matchup_odds else None
            if imp_total is None:
                imp_total = csv_implied_lookup.get(team)

            return TeamLineupOut(
                team=team,
                status=status,
                pitcher=pitcher_out,
                batters=batters_out,
                implied_total=imp_total,
            )

        away_out = _team_out(game.away, is_home=False)
        home_out = _team_out(game.home, is_home=True)

        # Vegas odds: prefer Fantasy Labs real lines, fall back to CSV
        away_ml = None
        home_ml = None
        vegas_total = None
        vegas_spread = None

        if matchup_odds:
            away_ml = matchup_odds.get("away_ml")
            home_ml = matchup_odds.get("home_ml")
            vegas_total = matchup_odds.get("game_total")
            vegas_spread = matchup_odds.get("spread")

        # Fallback: game total from CSV Saber Total
        if vegas_total is None:
            vegas_total = csv_game_total_lookup.get(away_team) or csv_game_total_lookup.get(home_team)

        if vegas_total:
            vegas_total = round(vegas_total, 1)
        if vegas_spread:
            vegas_spread = round(vegas_spread, 1)

        # Which slates include these teams
        game_slate_teams = []
        if away_team in slate_teams_set:
            game_slate_teams.append(away_team)
        if home_team in slate_teams_set:
            game_slate_teams.append(home_team)

        results.append(GameLineupOut(
            away=away_out,
            home=home_out,
            game_time=game.game_time,
            vegas_total=vegas_total,
            vegas_spread=vegas_spread,
            away_ml=away_ml,
            home_ml=home_ml,
            weather=weather_cache.get(home_team),
            home_team_abbr=home_team,
            slate_teams=game_slate_teams,
        ))
    return results


@router.get("/lineups/games/live", response_model=List[LiveGameState])
async def get_live_game_scores():
    """Get live scores for today's MLB games from the MLB Stats API."""
    import httpx
    from config import settings

    url = settings.mlb_schedule_url
    params = {
        "sportId": 1,
        "date": date.today().isoformat(),
        "hydrate": "linescore",
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.warning("MLB live scores fetch failed: %s", exc)
        return []

    results = []
    for date_entry in data.get("dates", []):
        for g in date_entry.get("games", []):
            home_team = g.get("teams", {}).get("home", {}).get("team", {})
            away_team = g.get("teams", {}).get("away", {}).get("team", {})

            home_abbr = home_team.get("abbreviation", "")
            away_abbr = away_team.get("abbreviation", "")

            # Normalise abbreviations
            home_abbr = _normalise_team(home_abbr) if home_abbr else ""
            away_abbr = _normalise_team(away_abbr) if away_abbr else ""

            abstract_state = g.get("status", {}).get("abstractGameState", "")

            linescore = g.get("linescore", {})
            inning = linescore.get("currentInning", 0) or 0
            inning_half = linescore.get("inningHalf", "").lower()

            home_runs = linescore.get("teams", {}).get("home", {}).get("runs", 0) or 0
            away_runs = linescore.get("teams", {}).get("away", {}).get("runs", 0) or 0

            if abstract_state == "Final":
                game_status = "Final"
            elif abstract_state == "Live":
                game_status = "Live"
            else:
                game_status = "Preview"

            results.append(LiveGameState(
                away_team=away_abbr,
                home_team=home_abbr,
                away_score=away_runs,
                home_score=home_runs,
                inning=inning,
                inning_half=inning_half if game_status == "Live" else "",
                game_status=game_status,
                game_pk=g.get("gamePk"),
            ))

    return results


# ── Helpers ────────────────────────────────────────────────────────────────


async def _save_slates_to_history(
    db: AsyncSession,
    csv_slates: List[Dict[str, Any]],
    target_date: date,
) -> None:
    """Persist CSV-based slates to SlateHistory (upsert by slate_id).

    Called whenever CSV slates are found so that the slate metadata
    survives after the CSV files are eventually deleted.
    """
    for s in csv_slates:
        slate_id = s["slate_id"]
        result = await db.execute(
            select(SlateHistory).where(SlateHistory.slate_id == slate_id)
        )
        existing = result.scalar_one_or_none()
        if existing:
            # Update in case name/game_count changed
            existing.name = s.get("name")
            existing.game_count = s.get("game_count")
            existing.start_time = s.get("start_time")
            existing.game_type = s.get("game_type", "classic")
            existing.draft_group_id = s.get("draft_group_id", 0)
        else:
            db.add(SlateHistory(
                slate_id=slate_id,
                site=s.get("site", "dk"),
                slate_date=target_date.isoformat(),
                name=s.get("name"),
                game_count=s.get("game_count"),
                game_type=s.get("game_type", "classic"),
                start_time=s.get("start_time"),
                draft_group_id=s.get("draft_group_id", 0),
            ))
    await db.flush()


async def _get_history_slates(
    db: AsyncSession,
    date_str: str,
    site: str,
) -> List[SlateOut]:
    """Load slates from SlateHistory for a given date and site."""
    stmt = (
        select(SlateHistory)
        .where(SlateHistory.slate_date == date_str, SlateHistory.site == site)
        .order_by(SlateHistory.created_at.desc())
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [
        SlateOut(
            slate_id=r.slate_id,
            site=r.site,
            name=r.name or r.slate_id,
            game_count=r.game_count or 0,
            start_time=r.start_time,
            game_type=r.game_type or "classic",
            draft_group_id=r.draft_group_id or 0,
            is_historical=True,
        )
        for r in rows
    ]


def _build_projected_lineups(site: str = "dk", target_date: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    """Build projected batting orders per team from CSV projections.

    Returns: {
        "NYY": {
            "pitcher": PlayerLineupOut or None,
            "batters": [PlayerLineupOut, ...] sorted by batting order,
        },
        ...
    }
    """
    extended = _build_projected_lineups_extended(site, target_date=target_date)
    return extended["lineups"]


def _build_projected_lineups_extended(
    site: str = "dk",
    target_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Build projected batting orders, salaries, implied totals, and slate teams.

    Args:
        site: DFS site ("dk" or "fd").
        target_date: Date in YYYY-MM-DD format.  None means today.

    Returns dict with keys:
      - lineups: {team: {pitcher, batters}}
      - salaries: {player_name: salary}
      - implied_totals: {team: implied_total}
      - slate_teams: set of team abbrevs in current slates
    """
    lineups: Dict[str, Dict[str, Any]] = {}
    salaries: Dict[str, int] = {}
    implied_totals: Dict[str, float] = {}
    game_totals: Dict[str, float] = {}  # team -> game O/U
    slate_teams: set = set()

    try:
        d = date.fromisoformat(target_date) if target_date else date.today()
        csv_slates = list_csv_slates(target_date=d, site=site)
        if not csv_slates:
            return {"lineups": lineups, "salaries": salaries, "implied_totals": implied_totals, "game_totals": game_totals, "slate_teams": slate_teams}
        featured = identify_featured_csv_slate(csv_slates)
        if not featured or not featured.get("csv_path"):
            return {"lineups": lineups, "salaries": salaries, "implied_totals": implied_totals, "game_totals": game_totals, "slate_teams": slate_teams}
        projections = load_csv_projections(featured["csv_path"], site)
    except Exception as exc:
        logger.warning("Failed to load CSV projections for GameCenter: %s", exc)
        return {"lineups": lineups, "salaries": salaries, "implied_totals": implied_totals, "game_totals": game_totals, "slate_teams": slate_teams}

    # Build salary lookup and collect slate teams
    for p in projections:
        name = p.get("player_name", "")
        sal = p.get("salary")
        team = p.get("team", "")
        if name and sal:
            salaries[name] = sal
        if team:
            slate_teams.add(team)
        # Capture team implied total (use first non-None per team)
        team_imp = p.get("team_implied") or p.get("implied_total")
        if team and team_imp and team not in implied_totals:
            implied_totals[team] = team_imp
        # Capture game total O/U (use first non-None per team)
        g_total = p.get("game_total")
        if team and g_total and team not in game_totals:
            game_totals[team] = g_total

    # Group by team for lineups
    by_team: Dict[str, List[Dict[str, Any]]] = {}
    for p in projections:
        team = p.get("team", "")
        if team:
            by_team.setdefault(team, []).append(p)

    for team, players in by_team.items():
        batters = []
        pitcher = None
        for p in players:
            if p.get("is_pitcher"):
                if pitcher is None:
                    pitcher = PlayerLineupOut(
                        name=p["player_name"],
                        position="P",
                        handedness="",
                        salary=p.get("salary"),
                    )
            elif p.get("batting_order"):
                batters.append(PlayerLineupOut(
                    name=p["player_name"],
                    position=p.get("position", "UTIL"),
                    batting_order=p["batting_order"],
                    handedness="",
                    salary=p.get("salary"),
                ))
        batters.sort(key=lambda b: b.batting_order or 99)
        lineups[team] = {"pitcher": pitcher, "batters": batters}

    # Also load teams from all slates for slate filtering
    for cs in csv_slates:
        if cs.get("csv_path"):
            try:
                all_projs = load_csv_projections(cs["csv_path"], site)
                for p in all_projs:
                    t = p.get("team", "")
                    if t:
                        slate_teams.add(t)
            except Exception:
                pass

    return {
        "lineups": lineups,
        "salaries": salaries,
        "implied_totals": implied_totals,
        "game_totals": game_totals,
        "slate_teams": slate_teams,
    }


# ── Stadium data for weather lookups ──────────────────────────────────────

STADIUM_DATA: Dict[str, Dict[str, Any]] = {
    "ARI": {"name": "Chase Field", "lat": 33.4455, "lon": -112.0667, "hpDir": 167, "dome": True},
    "ATL": {"name": "Truist Park", "lat": 33.8907, "lon": -84.4677, "hpDir": 225},
    "BAL": {"name": "Camden Yards", "lat": 39.2838, "lon": -76.6216, "hpDir": 218},
    "BOS": {"name": "Fenway Park", "lat": 42.3467, "lon": -71.0972, "hpDir": 199},
    "CHC": {"name": "Wrigley Field", "lat": 41.9484, "lon": -87.6553, "hpDir": 220},
    "CWS": {"name": "Guaranteed Rate", "lat": 41.8299, "lon": -87.6338, "hpDir": 197},
    "CIN": {"name": "Great American", "lat": 39.0975, "lon": -84.5067, "hpDir": 186},
    "CLE": {"name": "Progressive Field", "lat": 41.4962, "lon": -81.6852, "hpDir": 172},
    "COL": {"name": "Coors Field", "lat": 39.7561, "lon": -104.9942, "hpDir": 200},
    "DET": {"name": "Comerica Park", "lat": 42.3390, "lon": -83.0485, "hpDir": 208},
    "HOU": {"name": "Minute Maid", "lat": 29.7573, "lon": -95.3555, "hpDir": 172, "dome": True},
    "KC": {"name": "Kauffman", "lat": 39.0517, "lon": -94.4803, "hpDir": 180},
    "LAA": {"name": "Angel Stadium", "lat": 33.8003, "lon": -117.8827, "hpDir": 198},
    "LAD": {"name": "Dodger Stadium", "lat": 34.0739, "lon": -118.2400, "hpDir": 170},
    "MIA": {"name": "loanDepot Park", "lat": 25.7781, "lon": -80.2196, "hpDir": 13, "dome": True},
    "MIL": {"name": "American Family", "lat": 43.0280, "lon": -87.9712, "hpDir": 195, "dome": True},
    "MIN": {"name": "Target Field", "lat": 44.9818, "lon": -93.2775, "hpDir": 185},
    "NYM": {"name": "Citi Field", "lat": 40.7571, "lon": -73.8458, "hpDir": 202},
    "NYY": {"name": "Yankee Stadium", "lat": 40.8296, "lon": -73.9262, "hpDir": 194},
    "OAK": {"name": "Oakland Coliseum", "lat": 37.7516, "lon": -122.2005, "hpDir": 145},
    "ATH": {"name": "Oakland Coliseum", "lat": 37.7516, "lon": -122.2005, "hpDir": 145},
    "PHI": {"name": "Citizens Bank", "lat": 39.9061, "lon": -75.1665, "hpDir": 193},
    "PIT": {"name": "PNC Park", "lat": 40.4469, "lon": -80.0058, "hpDir": 135},
    "SD": {"name": "Petco Park", "lat": 32.7073, "lon": -117.1566, "hpDir": 192},
    "SF": {"name": "Oracle Park", "lat": 37.7786, "lon": -122.3893, "hpDir": 148},
    "SEA": {"name": "T-Mobile Park", "lat": 47.5914, "lon": -122.3325, "hpDir": 184, "dome": True},
    "STL": {"name": "Busch Stadium", "lat": 38.6226, "lon": -90.1928, "hpDir": 197},
    "TB": {"name": "Tropicana", "lat": 27.7683, "lon": -82.6534, "hpDir": 176, "dome": True},
    "TEX": {"name": "Globe Life", "lat": 32.7512, "lon": -97.0832, "hpDir": 214, "dome": True},
    "TOR": {"name": "Rogers Centre", "lat": 43.6414, "lon": -79.3894, "hpDir": 170, "dome": True},
    "WSH": {"name": "Nationals Park", "lat": 38.8730, "lon": -77.0074, "hpDir": 221},
}

# Weather cache per team (per server lifetime / request cycle)
_weather_cache: Dict[str, WeatherOut] = {}


async def _get_game_weather(home_team: str) -> WeatherOut:
    """Fetch weather for a stadium and return a WeatherOut object.

    Results are cached for the lifetime of the process to avoid
    duplicate Open-Meteo calls within the same day.
    """
    if home_team in _weather_cache:
        return _weather_cache[home_team]

    stadium = STADIUM_DATA.get(home_team)
    if not stadium:
        result = WeatherOut()
        _weather_cache[home_team] = result
        return result

    if stadium.get("dome"):
        result = WeatherOut(is_dome=True)
        _weather_cache[home_team] = result
        return result

    try:
        from services.weather import get_weather_forecast, extract_game_time_weather
        forecast = await get_weather_forecast(stadium["lat"], stadium["lon"])
        wx = extract_game_time_weather(forecast, game_hour=19)
        result = WeatherOut(
            temperature=wx.get("temperature"),
            wind_speed=wx.get("wind_speed"),
            wind_dir=wx.get("wind_dir"),
            precip_pct=wx.get("precip_pct"),
            is_dome=False,
        )
    except Exception as exc:
        logger.warning("Weather fetch failed for %s: %s", home_team, exc)
        result = WeatherOut()

    _weather_cache[home_team] = result
    return result


async def _overlay_lineup_status(
    projections: List[Dict[str, Any]],
    target_date: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Fetch latest lineup data and overlay it onto projections.

    This runs on every projection request (with caching) so that lineup
    changes, scratches, and pitcher swaps are always reflected.

    For future dates, uses MLB Stats API for probable pitchers.
    """
    try:
        games = await fetch_lineups(target_date=target_date)
        if games:
            lookup = build_lineup_lookup(games)
            projections = apply_lineup_status(projections, lookup)
    except Exception as exc:
        logger.warning("Lineup overlay failed (continuing with CSV status): %s", exc)
    return projections


async def _overlay_player_props(
    projections: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Fetch DK Sportsbook player props and overlay onto projections."""
    try:
        props = await fetch_player_props()
        if props:
            # Build canonical lookup for O(1) matching
            canonical_props = build_canonical_lookup(props)
            for p in projections:
                name = p.get("player_name", "")
                cn = canonical_name(name)
                player_props = canonical_props.get(cn)
                if player_props:
                    p["k_line"] = player_props.get("k_line")
                    p["hr_line"] = player_props.get("hr_line")
                    p["tb_line"] = player_props.get("tb_line")
                    p["hrr_line"] = player_props.get("hrr_line")
    except Exception as exc:
        logger.warning("Player props overlay failed: %s", exc)
    return projections


async def _auto_save_slate_report(
    *,
    db: AsyncSession,
    slate_id: str,
    site: str,
    report_date: str,
    slate_name: Optional[str],
    game_count: Optional[int],
    projections: List[Dict[str, Any]],
) -> SlateReport:
    """Upsert a slate report snapshot from the current projection data.

    Extracts ownership and lineup data from the projections list and
    saves everything as JSON columns. If a report already exists for
    this slate+date, it is updated in place.
    """
    # Build ownership snapshot: name, ownership, salary
    ownership_data = [
        {
            "name": p.get("player_name", ""),
            "ownership": p.get("projected_ownership"),
            "salary": p.get("salary"),
        }
        for p in projections
        if p.get("projected_ownership") is not None
    ]

    # Build lineup snapshot: group by team, capture batting order + status
    teams_seen: Dict[str, List[Dict[str, Any]]] = {}
    for p in projections:
        team = p.get("team", "")
        if not team:
            continue
        teams_seen.setdefault(team, []).append({
            "name": p.get("player_name", ""),
            "batting_order": p.get("batting_order"),
            "is_pitcher": p.get("is_pitcher", False),
            "lineup_status": p.get("lineup_status", "unknown"),
        })
    lineup_data = [
        {"team": team, "players": players}
        for team, players in sorted(teams_seen.items())
    ]

    projections_json = json.dumps([_sanitise_projection(p) for p in projections])
    ownership_json = json.dumps(ownership_data) if ownership_data else None
    lineup_json = json.dumps(lineup_data) if lineup_data else None

    # Upsert: check for existing report
    result = await db.execute(
        select(SlateReport).where(
            SlateReport.slate_id == slate_id,
            SlateReport.report_date == report_date,
        )
    )
    report = result.scalar_one_or_none()

    if report:
        report.site = site
        report.slate_name = slate_name
        report.game_count = game_count
        report.player_count = len(projections)
        report.projections_snapshot = projections_json
        report.ownership_snapshot = ownership_json
        report.lineup_snapshot = lineup_json
    else:
        report = SlateReport(
            slate_id=slate_id,
            site=site,
            report_date=report_date,
            slate_name=slate_name,
            game_count=game_count,
            player_count=len(projections),
            projections_snapshot=projections_json,
            ownership_snapshot=ownership_json,
            lineup_snapshot=lineup_json,
        )
        db.add(report)

    await db.flush()
    await db.refresh(report)
    logger.info("Slate report saved: slate=%s date=%s players=%d", slate_id, report_date, len(projections))
    return report


def _extract_date_from_slate_id(slate_id: str) -> Optional[str]:
    """Extract the YYYY-MM-DD date from a slate_id.

    Slate IDs follow the pattern: MLB_YYYY-MM-DD-HHMMam/pm_DK_Type
    Returns the date string or None if the pattern doesn't match.
    """
    import re as _re
    m = _re.search(r"(\d{4}-\d{2}-\d{2})", slate_id)
    return m.group(1) if m else None


def _sanitise_projection(p: Dict[str, Any]) -> Dict[str, Any]:
    """Ensure all fields in a projection dict are compatible with the Pydantic model."""
    return {
        "player_name": p.get("player_name", "Unknown"),
        "mlb_id": p.get("mlb_id"),
        "team": p.get("team", ""),
        "position": p.get("position", "UTIL"),
        "opp_team": p.get("opp_team"),
        "game_pk": p.get("game_pk"),
        "venue": p.get("venue"),
        "salary": p.get("salary"),
        "batting_order": p.get("batting_order"),
        "is_pitcher": p.get("is_pitcher", False),
        "is_confirmed": p.get("is_confirmed", False),
        "floor_pts": p.get("floor_pts", 0.0),
        "median_pts": p.get("median_pts", 0.0),
        "ceiling_pts": p.get("ceiling_pts", 0.0),
        "projected_ownership": p.get("projected_ownership"),
        "season_era": p.get("season_era"),
        "season_k9": p.get("season_k9"),
        "season_avg": p.get("season_avg"),
        "season_ops": p.get("season_ops"),
        "games_in_log": p.get("games_in_log", 0),
        "implied_total": p.get("implied_total"),
        "team_implied": p.get("team_implied"),
        "temperature": p.get("temperature"),
        "dk_id": p.get("dk_id"),
        "min_exposure": p.get("min_exposure"),
        "max_exposure": p.get("max_exposure"),
        "lineup_status": p.get("lineup_status", "unknown"),
        "k_line": p.get("k_line"),
        "hr_line": p.get("hr_line"),
        "tb_line": p.get("tb_line"),
        "hrr_line": p.get("hrr_line"),
    }
