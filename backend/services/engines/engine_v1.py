"""Engine v1: Contest-aware field sharpness.

Computes a 0-1 field_sharpness score from contest attributes and uses it to
control archetype mix, ownership adherence, and lineup optimality in the
opponent field.

Sharpness signals:
- max_entries_per_user: 1 → sharp (SE), 150 → loose (ME GPP)
- game_type: cash/h2h/50-50 → sharp, classic/tournament → loose
- field_size: <100 → sharp, 1000+ → loose
- entry_fee: $20+ → sharper, $1-5 → softer

These combine into a single 0-1 score that adjusts:
- Archetype proportions (casual/optimizer/sharp)
- Ownership power and noise in lineup construction
- Variance in ownership-weighted field generation
"""
from __future__ import annotations

import logging
from typing import Any

from services.engines.registry import register_engine

logger = logging.getLogger(__name__)

CASH_GAME_TYPES = {"h2h", "double_up", "50/50", "head-to-head", "cash", "fifty50"}


def compute_field_sharpness(contest_config: dict[str, Any]) -> float:
    """Derive a 0-1 sharpness score from contest attributes.

    0.0 = very soft field (low-stakes large GPP, casual players)
    1.0 = very sharp field (high-stakes SE cash, experienced players)
    """
    max_entries = contest_config.get("max_entries", 150)
    game_type = (contest_config.get("game_type") or "classic").lower()
    field_size = contest_config.get("field_size", 1000)
    entry_fee = contest_config.get("entry_fee", 5)

    # Component 1: Max entries per user (SE=sharp, ME=loose)
    # 1 entry → 1.0, 3 entries → ~0.7, 20 → ~0.3, 150 → 0.0
    if max_entries <= 1:
        entries_score = 1.0
    elif max_entries >= 150:
        entries_score = 0.0
    else:
        entries_score = max(0.0, 1.0 - (max_entries - 1) / 149)

    # Component 2: Game type (cash=sharp, GPP=loose)
    is_cash = game_type in CASH_GAME_TYPES
    type_score = 0.85 if is_cash else 0.2

    # Component 3: Field size (<100=sharp, 1000+=loose)
    if field_size <= 50:
        size_score = 1.0
    elif field_size >= 5000:
        size_score = 0.0
    else:
        size_score = max(0.0, 1.0 - (field_size - 50) / 4950)

    # Component 4: Entry fee ($1→soft, $5→moderate, $20+→sharp)
    if entry_fee >= 50:
        fee_score = 1.0
    elif entry_fee >= 20:
        fee_score = 0.75 + 0.25 * ((entry_fee - 20) / 30)
    elif entry_fee >= 5:
        fee_score = 0.3 + 0.45 * ((entry_fee - 5) / 15)
    else:
        fee_score = max(0.0, entry_fee / 5 * 0.3)

    # Weighted combination — entries and game type matter most
    sharpness = (
        0.30 * entries_score
        + 0.25 * type_score
        + 0.20 * size_score
        + 0.25 * fee_score
    )

    sharpness = max(0.0, min(1.0, sharpness))

    logger.info(
        "Field sharpness=%.2f (entries=%d→%.2f, type=%s→%.2f, field=%d→%.2f, fee=$%.0f→%.2f)",
        sharpness, max_entries, entries_score, game_type, type_score,
        field_size, size_score, entry_fee, fee_score,
    )
    return sharpness


def get_archetype_mix(sharpness: float) -> tuple[float, float, float]:
    """Return (casual_pct, optimizer_pct, sharp_pct) based on sharpness.

    Sharp fields have more optimizers and sharps, fewer casuals.
    """
    casual_pct = max(0.05, 0.65 - 0.55 * sharpness)
    sharp_pct = min(0.60, 0.05 + 0.55 * sharpness)
    optimizer_pct = 1.0 - casual_pct - sharp_pct
    return casual_pct, optimizer_pct, sharp_pct


def get_ownership_params(sharpness: float) -> dict[str, float]:
    """Return ownership power and noise params for lineup builders.

    Sharp fields track projected ownership more closely (higher power, less noise).
    Soft fields have more noise and flatter ownership weighting.
    """
    return {
        "casual_ownership_power": 1.2 + 0.6 * sharpness,
        "casual_noise": max(0.15, 0.45 - 0.25 * sharpness),
        "optimizer_noise": max(0.05, 0.15 - 0.08 * sharpness),
        "sharp_noise": max(0.08, 0.20 - 0.10 * sharpness),
        "ownership_variance": max(0.08, 0.40 - 0.28 * sharpness),
    }


# ── Engine wrapper & registration ─────────────────────────────────────────────


class _EngineV1:
    """Wraps module-level functions into the SimEngine protocol."""

    def compute_field_sharpness(self, contest_config: dict[str, Any]) -> float:
        return compute_field_sharpness(contest_config)

    def get_archetype_mix(self, sharpness: float) -> tuple[float, float, float]:
        return get_archetype_mix(sharpness)

    def get_ownership_params(self, sharpness: float) -> dict[str, float]:
        return get_ownership_params(sharpness)


register_engine("archetype_v1", _EngineV1())
