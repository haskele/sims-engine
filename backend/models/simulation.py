"""SimulationResult model."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class SimulationResult(Base):
    __tablename__ = "simulation_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    contest_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("contests.id"), nullable=True
    )
    sim_count: Mapped[int] = mapped_column(Integer, nullable=False)
    lineup_pool_size: Mapped[int] = mapped_column(Integer, nullable=False)
    config: Mapped[str] = mapped_column(Text, nullable=False)  # JSON
    results: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON
    status: Mapped[str] = mapped_column(
        String(15), nullable=False, default="pending"
    )  # pending / running / complete / error

    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    contest = relationship("Contest")

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<SimulationResult {self.id} status={self.status}>"
