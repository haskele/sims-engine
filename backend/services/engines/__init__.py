"""Simulation engines — pluggable opponent field generation strategies.

Usage:
    from services.engines import get_engine, list_engines

    engine = get_engine("archetype_v1")
    sharpness = engine.compute_field_sharpness(contest_config)
    mix = engine.get_archetype_mix(sharpness)
    params = engine.get_ownership_params(sharpness)

Available engines (auto-registered on import):
    - "archetype_v1"  — contest-aware 3-archetype model (casual/optimizer/sharp)
    - "ownership_mc"  — flat ownership Monte Carlo (stub)
"""

from services.engines.registry import (
    SimEngine,
    get_engine,
    list_engines,
    register_engine,
)

# Auto-register built-in engines by importing their modules.
# Each module calls register_engine() at module level.
import services.engines.engine_v1  # noqa: F401
import services.engines.engine_v2_stub  # noqa: F401

__all__ = [
    "SimEngine",
    "get_engine",
    "list_engines",
    "register_engine",
]
