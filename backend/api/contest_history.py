"""Contest history: save results, query historical performance, get aggregate stats."""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.contest_history import ContestHistory

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/contest-history", tags=["contest-history"])


# ── Pydantic schemas ─────────────────────────────────────────────────────────


class EntryResult(BaseModel):
    entry_id: str
    rank: Optional[int] = None
    score: Optional[float] = None
    payout: float = 0.0


class ContestHistoryCreate(BaseModel):
    contest_id: str
    contest_name: Optional[str] = None
    contest_date: str  # YYYY-MM-DD
    site: str = "dk"
    entry_fee: Optional[float] = None
    field_size: Optional[int] = None
    prize_pool: Optional[float] = None
    game_type: str = "classic"
    total_entries: Optional[int] = None
    total_invested: Optional[float] = None
    total_won: Optional[float] = None
    entry_results: Optional[List[EntryResult]] = None
    sim_predicted_roi: Optional[float] = None
    sim_predicted_cash_rate: Optional[float] = None


class ContestHistoryOut(BaseModel):
    id: int
    contest_id: str
    contest_name: Optional[str] = None
    contest_date: str
    site: str
    entry_fee: Optional[float] = None
    field_size: Optional[int] = None
    prize_pool: Optional[float] = None
    game_type: str
    total_entries: Optional[int] = None
    total_invested: Optional[float] = None
    total_won: Optional[float] = None
    roi_pct: Optional[float] = None
    cash_count: Optional[int] = None
    entry_results: Optional[List[Dict[str, Any]]] = None
    sim_predicted_roi: Optional[float] = None
    sim_predicted_cash_rate: Optional[float] = None
    created_at: Optional[str] = None


class ContestHistoryListResponse(BaseModel):
    results: List[ContestHistoryOut]
    summary: Dict[str, Any]


class SummaryResponse(BaseModel):
    total_contests: int
    total_invested: float
    total_won: float
    overall_roi: Optional[float]
    avg_cash_rate: Optional[float]
    best_roi_day: Optional[Dict[str, Any]]
    worst_roi_day: Optional[Dict[str, Any]]


# ── Helpers ───────────────────────────────────────────────────────────────────


def _compute_derived_fields(body: ContestHistoryCreate) -> Dict[str, Any]:
    """Calculate total_invested, total_won, roi_pct, and cash_count from input."""
    entry_results = body.entry_results or []
    num_entries = body.total_entries or len(entry_results)

    # Total invested: explicit or computed from entry_fee * entries
    total_invested = body.total_invested
    if total_invested is None and body.entry_fee is not None and num_entries:
        total_invested = body.entry_fee * num_entries

    # Total won: explicit or summed from entry payouts
    total_won = body.total_won
    if total_won is None and entry_results:
        total_won = sum(er.payout for er in entry_results)

    # Cash count
    cash_count = sum(1 for er in entry_results if er.payout > 0) if entry_results else 0

    # ROI %
    roi_pct = None
    if total_invested and total_invested > 0 and total_won is not None:
        roi_pct = round((total_won - total_invested) / total_invested * 100, 2)

    return {
        "total_entries": num_entries or None,
        "total_invested": total_invested,
        "total_won": total_won,
        "roi_pct": roi_pct,
        "cash_count": cash_count,
    }


def _row_to_out(row: ContestHistory) -> ContestHistoryOut:
    """Convert a ContestHistory ORM instance to the API response model."""
    entry_results_parsed = None
    if row.entry_results:
        try:
            entry_results_parsed = json.loads(row.entry_results)
        except json.JSONDecodeError:
            entry_results_parsed = None

    return ContestHistoryOut(
        id=row.id,
        contest_id=row.contest_id,
        contest_name=row.contest_name,
        contest_date=row.contest_date,
        site=row.site,
        entry_fee=row.entry_fee,
        field_size=row.field_size,
        prize_pool=row.prize_pool,
        game_type=row.game_type,
        total_entries=row.total_entries,
        total_invested=row.total_invested,
        total_won=row.total_won,
        roi_pct=row.roi_pct,
        cash_count=row.cash_count,
        entry_results=entry_results_parsed,
        sim_predicted_roi=row.sim_predicted_roi,
        sim_predicted_cash_rate=row.sim_predicted_cash_rate,
        created_at=row.created_at.isoformat() if row.created_at else None,
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("/", response_model=ContestHistoryOut)
async def create_contest_history(
    body: ContestHistoryCreate,
    db: AsyncSession = Depends(get_db),
):
    """Save a contest result after a slate completes.

    Automatically calculates ROI, cash_count, and total_invested/total_won
    from the provided entry_results when not explicitly supplied.
    """
    derived = _compute_derived_fields(body)

    # Serialize entry_results to JSON text
    entry_results_json = None
    if body.entry_results:
        entry_results_json = json.dumps(
            [er.model_dump() for er in body.entry_results]
        )

    record = ContestHistory(
        contest_id=body.contest_id,
        contest_name=body.contest_name,
        contest_date=body.contest_date,
        site=body.site,
        entry_fee=body.entry_fee,
        field_size=body.field_size,
        prize_pool=body.prize_pool,
        game_type=body.game_type,
        total_entries=derived["total_entries"],
        total_invested=derived["total_invested"],
        total_won=derived["total_won"],
        roi_pct=derived["roi_pct"],
        cash_count=derived["cash_count"],
        entry_results=entry_results_json,
        sim_predicted_roi=body.sim_predicted_roi,
        sim_predicted_cash_rate=body.sim_predicted_cash_rate,
    )

    db.add(record)
    await db.flush()
    await db.refresh(record)

    return _row_to_out(record)


@router.get("/", response_model=ContestHistoryListResponse)
async def list_contest_history(
    date_from: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    site: Optional[str] = Query(None, description="Filter by site (dk, fd)"),
    db: AsyncSession = Depends(get_db),
):
    """List historical contest results with optional date range and site filter.

    Returns results plus a summary of total invested, total won, and overall ROI.
    """
    stmt = select(ContestHistory).order_by(ContestHistory.contest_date.desc())

    if date_from:
        stmt = stmt.where(ContestHistory.contest_date >= date_from)
    if date_to:
        stmt = stmt.where(ContestHistory.contest_date <= date_to)
    if site:
        stmt = stmt.where(ContestHistory.site == site)

    result = await db.execute(stmt)
    rows = result.scalars().all()

    results = [_row_to_out(r) for r in rows]

    # Compute summary across filtered results
    total_invested = sum(r.total_invested or 0 for r in rows)
    total_won = sum(r.total_won or 0 for r in rows)
    overall_roi = None
    if total_invested > 0:
        overall_roi = round((total_won - total_invested) / total_invested * 100, 2)

    return ContestHistoryListResponse(
        results=results,
        summary={
            "total_contests": len(rows),
            "total_invested": round(total_invested, 2),
            "total_won": round(total_won, 2),
            "overall_roi": overall_roi,
            "total_entries": sum(r.total_entries or 0 for r in rows),
        },
    )


@router.get("/summary", response_model=SummaryResponse)
async def get_summary(
    site: Optional[str] = Query(None, description="Filter by site (dk, fd)"),
    db: AsyncSession = Depends(get_db),
):
    """Aggregate stats across all saved contests.

    Returns total contests, invested, won, overall ROI, average cash rate,
    and the best and worst ROI days.
    """
    stmt = select(ContestHistory)
    if site:
        stmt = stmt.where(ContestHistory.site == site)

    result = await db.execute(stmt)
    rows = result.scalars().all()

    if not rows:
        return SummaryResponse(
            total_contests=0,
            total_invested=0.0,
            total_won=0.0,
            overall_roi=None,
            avg_cash_rate=None,
            best_roi_day=None,
            worst_roi_day=None,
        )

    total_invested = sum(r.total_invested or 0 for r in rows)
    total_won = sum(r.total_won or 0 for r in rows)

    overall_roi = None
    if total_invested > 0:
        overall_roi = round((total_won - total_invested) / total_invested * 100, 2)

    # Average cash rate: cash_count / total_entries across all contests
    total_cash = sum(r.cash_count or 0 for r in rows)
    total_entries = sum(r.total_entries or 0 for r in rows)
    avg_cash_rate = None
    if total_entries > 0:
        avg_cash_rate = round(total_cash / total_entries * 100, 2)

    # Aggregate by date to find best/worst ROI days
    daily: Dict[str, Dict[str, float]] = {}
    for r in rows:
        d = r.contest_date
        if d not in daily:
            daily[d] = {"invested": 0.0, "won": 0.0}
        daily[d]["invested"] += r.total_invested or 0
        daily[d]["won"] += r.total_won or 0

    best_roi_day = None
    worst_roi_day = None
    best_roi = float("-inf")
    worst_roi = float("inf")

    for date, vals in daily.items():
        if vals["invested"] > 0:
            day_roi = (vals["won"] - vals["invested"]) / vals["invested"] * 100
            if day_roi > best_roi:
                best_roi = day_roi
                best_roi_day = {
                    "date": date,
                    "invested": round(vals["invested"], 2),
                    "won": round(vals["won"], 2),
                    "roi_pct": round(day_roi, 2),
                }
            if day_roi < worst_roi:
                worst_roi = day_roi
                worst_roi_day = {
                    "date": date,
                    "invested": round(vals["invested"], 2),
                    "won": round(vals["won"], 2),
                    "roi_pct": round(day_roi, 2),
                }

    return SummaryResponse(
        total_contests=len(rows),
        total_invested=round(total_invested, 2),
        total_won=round(total_won, 2),
        overall_roi=overall_roi,
        avg_cash_rate=avg_cash_rate,
        best_roi_day=best_roi_day,
        worst_roi_day=worst_roi_day,
    )
