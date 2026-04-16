"""SlateReport model -- daily snapshots of projection/ownership/lineup data."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class SlateReport(Base):
    __tablename__ = "slate_reports"
    __table_args__ = (
        UniqueConstraint("slate_id", "report_date", name="uix_slate_report"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slate_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    site: Mapped[str] = mapped_column(String(2), default="dk")
    report_date: Mapped[str] = mapped_column(String(10), nullable=False, index=True)  # YYYY-MM-DD
    slate_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    game_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    player_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Snapshot data stored as JSON text
    projections_snapshot: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ownership_snapshot: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    lineup_snapshot: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<SlateReport slate={self.slate_id} date={self.report_date}>"
