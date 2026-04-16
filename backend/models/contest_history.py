"""ContestHistory model -- stores contest results for historical ROI tracking."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class ContestHistory(Base):
    __tablename__ = "contest_history"
    __table_args__ = (
        UniqueConstraint("contest_id", "contest_date", name="uix_contest_history"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    contest_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    contest_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    contest_date: Mapped[str] = mapped_column(
        String(10), nullable=False, index=True
    )  # YYYY-MM-DD
    site: Mapped[str] = mapped_column(String(2), default="dk")
    entry_fee: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    field_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    prize_pool: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    game_type: Mapped[str] = mapped_column(String(15), default="classic")

    # Results
    total_entries: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )  # user's entry count
    total_invested: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )  # total $ spent
    total_won: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )  # total $ won
    roi_pct: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )  # (won - invested) / invested * 100
    cash_count: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )  # entries that cashed

    # Lineup data (JSON)
    entry_results: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )  # JSON array of {entry_id, rank, score, payout}

    # Simulation comparison
    sim_predicted_roi: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sim_predicted_cash_rate: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"<ContestHistory {self.contest_id} "
            f"date={self.contest_date} roi={self.roi_pct}%>"
        )
