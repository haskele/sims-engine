"""Contest model."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class Contest(Base):
    __tablename__ = "contests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    site: Mapped[str] = mapped_column(
        String(2), nullable=False, index=True
    )  # dk / fd
    external_id: Mapped[Optional[str]] = mapped_column(
        String(30), nullable=True, unique=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    entry_fee: Mapped[float] = mapped_column(Float, nullable=False)
    max_entries: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    field_size: Mapped[int] = mapped_column(Integer, nullable=False)
    prize_pool: Mapped[float] = mapped_column(Float, nullable=False)
    payout_structure: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )  # JSON: list of {place: int, payout: float}
    game_type: Mapped[str] = mapped_column(
        String(15), nullable=False, default="classic"
    )  # classic / showdown
    slate_id: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    slate_games: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )  # JSON: list of game IDs on the slate
    draft_group_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<Contest {self.name} ({self.site}, ${self.entry_fee})>"
