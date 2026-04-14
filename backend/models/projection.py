"""Projection model."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class Projection(Base):
    __tablename__ = "projections"
    __table_args__ = (
        UniqueConstraint("player_id", "game_id", "site", name="uq_player_game_site"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("players.id"), nullable=False, index=True
    )
    game_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("games.id"), nullable=False, index=True
    )
    site: Mapped[str] = mapped_column(String(2), nullable=False)  # dk / fd
    floor_pts: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    median_pts: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    ceiling_pts: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    projected_ownership: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    batting_order: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )  # 1-9, null for pitchers
    is_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)

    player = relationship("Player")
    game = relationship("Game")

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"<Projection player={self.player_id} game={self.game_id} "
            f"med={self.median_pts}>"
        )
