"""SlateHistory model -- persistent record of every slate seen, so old slates survive CSV deletion."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class SlateHistory(Base):
    __tablename__ = "slate_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slate_id: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    site: Mapped[str] = mapped_column(String(2), default="dk")
    slate_date: Mapped[str] = mapped_column(String(10), nullable=False, index=True)  # YYYY-MM-DD
    name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    game_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    game_type: Mapped[str] = mapped_column(String, default="classic")
    start_time: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    draft_group_id: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<SlateHistory slate={self.slate_id} date={self.slate_date}>"
