"""Team model."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Integer, Float, String, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(60), nullable=False, unique=True)
    abbreviation: Mapped[str] = mapped_column(String(5), nullable=False, unique=True)
    league: Mapped[str] = mapped_column(String(2), nullable=False)  # AL / NL
    division: Mapped[str] = mapped_column(String(10), nullable=False)  # East/Central/West
    stadium_name: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    stadium_lat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    stadium_lon: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    stadium_roof: Mapped[str] = mapped_column(
        String(15), nullable=False, default="open"
    )  # open / retractable / dome
    mlb_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, unique=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<Team {self.abbreviation} ({self.name})>"
