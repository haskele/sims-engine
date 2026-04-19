"""Engine registry — pluggable simulation engine selection.

Engines define how the opponent field's sharpness, archetype mix, and
ownership parameters are computed.  Each engine must implement three functions:

    compute_field_sharpness(contest_config: dict) -> float
    get_archetype_mix(sharpness: float) -> tuple[float, float, float]
    get_ownership_params(sharpness: float) -> dict[str, float]

Register engines by name, then retrieve them at runtime to swap strategies
without changing the simulator or lineup sampler code.
"""
from __future__ import annotations

import logging
from typing import Any, Protocol

logger = logging.getLogger(__name__)


# ── Engine protocol ────────────────────────────────────────────────────────────


class SimEngine(Protocol):
    """Interface that every simulation engine must satisfy.

    Engines are modules or classes that expose these three callables.
    Using Protocol so there's no inheritance requirement — any object with
    matching signatures works.
    """

    def compute_field_sharpness(self, contest_config: dict[str, Any]) -> float:
        """Derive a 0-1 sharpness score from contest attributes."""
        ...

    def get_archetype_mix(self, sharpness: float) -> tuple[float, float, float]:
        """Return (casual_pct, optimizer_pct, sharp_pct) based on sharpness."""
        ...

    def get_ownership_params(self, sharpness: float) -> dict[str, float]:
        """Return ownership power and noise params for lineup builders."""
        ...


# ── Registry ───────────────────────────────────────────────────────────────────

_registry: dict[str, SimEngine] = {}


def register_engine(name: str, engine: SimEngine) -> None:
    """Register an engine instance under a unique name.

    Parameters
    ----------
    name : str
        Short identifier (e.g. "archetype_v1", "ownership_mc").
    engine : SimEngine
        Any object implementing compute_field_sharpness, get_archetype_mix,
        and get_ownership_params.
    """
    if name in _registry:
        logger.warning("Overwriting existing engine registration: %s", name)
    _registry[name] = engine
    logger.debug("Registered engine: %s", name)


def get_engine(name: str) -> SimEngine:
    """Retrieve a registered engine by name.

    Raises KeyError if the engine hasn't been registered.
    """
    if name not in _registry:
        available = ", ".join(_registry.keys()) or "(none)"
        raise KeyError(
            f"Engine '{name}' not found. Available engines: {available}"
        )
    return _registry[name]


def list_engines() -> list[str]:
    """Return names of all registered engines."""
    return list(_registry.keys())
