"""Lineup model."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class Lineup(Base):
    __tablename__ = "lineups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    contest_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("contests.id"), nullable=False, index=True
    )
    entry_id: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    user_name: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    players: Mapped[str] = mapped_column(
        Text, nullable=False
    )  # JSON: list of {player_id, position, salary}
    total_salary: Mapped[int] = mapped_column(Integer, nullable=False)
    total_points: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    finish_position: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    is_user: Mapped[bool] = mapped_column(Boolean, default=False)

    contest = relationship("Contest")

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<Lineup {self.id} contest={self.contest_id} pts={self.total_points}>"
