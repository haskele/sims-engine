"""Player model."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Integer, String, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class Player(Base):
    __tablename__ = "players"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    team: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    position: Mapped[str] = mapped_column(String(20), nullable=False)  # e.g. "1B/OF"
    bats: Mapped[str] = mapped_column(String(1), nullable=False)  # L / R / S
    throws: Mapped[str] = mapped_column(String(1), nullable=False)  # L / R
    dk_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, unique=True)
    fd_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, unique=True)
    dk_salary: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    fd_salary: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    mlb_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, unique=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<Player {self.name} ({self.team}, {self.position})>"
