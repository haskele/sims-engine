"""Game model."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class Game(Base):
    __tablename__ = "games"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[datetime] = mapped_column(Date, nullable=False, index=True)
    time: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)  # "7:05 PM ET"
    home_team_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("teams.id"), nullable=False
    )
    away_team_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("teams.id"), nullable=False
    )
    venue: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    home_pitcher_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("players.id"), nullable=True
    )
    away_pitcher_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("players.id"), nullable=True
    )
    home_lineup: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )  # JSON: ordered list of player_ids
    away_lineup: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )  # JSON: ordered list of player_ids
    lineup_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)

    # Vegas lines
    vegas_home_ml: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    vegas_away_ml: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    vegas_total: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    vegas_home_implied: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    vegas_away_implied: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Weather
    wind_speed: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    wind_dir: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # degrees
    temperature: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # Fahrenheit
    precip_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    mlb_game_pk: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, unique=True)

    # Relationships
    home_team = relationship("Team", foreign_keys=[home_team_id])
    away_team = relationship("Team", foreign_keys=[away_team_id])
    home_pitcher = relationship("Player", foreign_keys=[home_pitcher_id])
    away_pitcher = relationship("Player", foreign_keys=[away_pitcher_id])

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<Game {self.id} {self.date}>"
