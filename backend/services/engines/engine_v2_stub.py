"""Engine v2 stub: Flat ownership Monte Carlo.

This engine treats the entire opponent field as a single population that
builds lineups purely from projected ownership percentages -- no archetype
segmentation, no stacking model.  It's the simplest possible baseline:
ownership IS the field.

Use cases:
- Quick back-of-envelope EV estimation
- Baseline comparison to validate that archetype/stacking engines add value
- Slates where ownership data is high-quality and field behavior is uniform

TODO: Replace placeholder logic with actual flat-ownership implementation:
  1. compute_field_sharpness → could be a no-op (return fixed 0.5) or derive
     a simpler score that only adjusts ownership concentration, not archetypes.
  2. get_archetype_mix → return (1.0, 0.0, 0.0) since there's only one
     population, or remove the concept entirely.
  3. get_ownership_params → return params that directly map projected
     ownership into lineup selection weights with minimal transformation.
"""
from __future__ import annotations

import logging
from typing import Any

from services.engines.registry import register_engine

# Delegate to engine_v1 as placeholder -- swap out when implementing
from services.engines.engine_v1 import (
    compute_field_sharpness as _v1_sharpness,
    get_archetype_mix as _v1_mix,
    get_ownership_params as _v1_params,
)

logger = logging.getLogger(__name__)


class OwnershipMCEngine:
    """Flat ownership Monte Carlo engine (stub).

    Currently delegates to engine_v1.  To implement the real version:

    1. compute_field_sharpness:
       TODO — Return a fixed moderate sharpness (e.g. 0.5) or derive from
       entry fee only.  The flat MC approach doesn't need archetype-level
       granularity.

    2. get_archetype_mix:
       TODO — Return (1.0, 0.0, 0.0) to signal "one homogeneous population".
       The lineup sampler will treat the entire field as casual-style builders
       using ownership weights.

    3. get_ownership_params:
       TODO — Return params tuned for direct ownership mapping:
         - ownership_power ~1.0 (linear relationship to projected ownership)
         - low noise (~0.10) for the MC sampling
         - variance controlled by a single knob passed in contest_config
    """

    def compute_field_sharpness(self, contest_config: dict[str, Any]) -> float:
        # TODO: Replace with flat-ownership logic
        # For a pure ownership MC, sharpness may not matter -- consider
        # returning a constant or using only entry_fee as a signal.
        return _v1_sharpness(contest_config)

    def get_archetype_mix(self, sharpness: float) -> tuple[float, float, float]:
        # TODO: Replace with (1.0, 0.0, 0.0) for single-population model.
        # When implemented, the lineup sampler should build ALL lineups using
        # the same ownership-weighted approach (no sharp/optimizer distinction).
        return _v1_mix(sharpness)

    def get_ownership_params(self, sharpness: float) -> dict[str, float]:
        # TODO: Replace with flat ownership params:
        # return {
        #     "casual_ownership_power": 1.0,
        #     "casual_noise": 0.10,
        #     "optimizer_noise": 0.10,
        #     "sharp_noise": 0.10,
        #     "ownership_variance": 0.20,
        # }
        return _v1_params(sharpness)


register_engine("ownership_mc", OwnershipMCEngine())
