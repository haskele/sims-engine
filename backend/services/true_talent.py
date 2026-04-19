"""True-talent estimation module.

Builds stabilised rate profiles for hitters and pitchers by regressing
raw season stats toward league-average rates.  The regression strength
is controlled by the PA / BF sample-size constants in
``data/league_averages.json``.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from services.mlb_stats import get_player_season_stats

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cached league-average data
# ---------------------------------------------------------------------------

_league_avg: dict[str, Any] | None = None


def _load_league_averages() -> dict[str, Any]:
    """Load and cache ``data/league_averages.json``."""
    global _league_avg
    if _league_avg is not None:
        return _league_avg
    path = Path(__file__).resolve().parent.parent / "config_data" / "league_averages.json"
    if not path.exists():
        path = Path(__file__).resolve().parent.parent / "data" / "league_averages.json"
    with open(path, "r") as f:
        _league_avg = json.load(f)
    logger.info("Loaded league averages from %s", path)
    return _league_avg


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _regress(raw: float, sample: int, lg_avg: float, regression_n: int) -> float:
    """Regress *raw* toward *lg_avg* based on sample size."""
    if sample + regression_n == 0:
        return lg_avg
    return (raw * sample + lg_avg * regression_n) / (sample + regression_n)


def _safe_div(numerator: float, denominator: float, fallback: float = 0.0) -> float:
    if denominator == 0:
        return fallback
    return numerator / denominator


def _parse_ip(ip_value: Any) -> float:
    """Parse innings pitched from MLB API format (e.g. ``6.1`` = 6 1/3).

    The API encodes partial innings with the last digit representing
    thirds, so ``"6.2"`` means 6 and 2/3 innings.
    """
    ip_str = str(ip_value or "0")
    if "." in ip_str:
        whole, frac = ip_str.split(".", 1)
        return int(whole or 0) + int(frac or 0) / 3.0
    return float(ip_str)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class HitterProfile:
    mlb_id: int
    name: str
    team: str
    bat_side: str  # L / R / S

    k_rate: float  # K per PA
    bb_rate: float  # BB per PA
    hbp_rate: float  # HBP per PA
    hr_per_contact: float  # HR per ball in play
    triple_per_contact: float
    double_per_contact: float
    single_per_contact: float

    sb_rate: float  # SB per time on 1B
    cs_rate: float  # CS per SB attempt

    runs_per_pa: float
    rbi_per_pa: float

    pa_season: int
    games_played: int


@dataclass
class PitcherProfile:
    mlb_id: int
    name: str
    team: str
    pitch_hand: str  # L / R

    k_rate: float  # K per BF
    bb_rate: float  # BB per BF
    hbp_rate: float  # HBP per BF
    hr_per_bf: float  # HR per BF

    babip_against: float

    ip_per_start: float
    bf_season: int
    games_started: int


# ---------------------------------------------------------------------------
# Extraction helpers (pull raw counts from the MLB stats dict)
# ---------------------------------------------------------------------------


def _extract_hitting_stat(data: dict[str, Any]) -> dict[str, Any]:
    """Dig out the stat dict from ``get_player_season_stats`` response."""
    for block in data.get("stats", []):
        for split in block.get("splits", []):
            stat = split.get("stat")
            if stat is not None:
                return stat
    return {}


def _extract_pitching_stat(data: dict[str, Any]) -> dict[str, Any]:
    return _extract_hitting_stat(data)  # same nested structure


# ---------------------------------------------------------------------------
# Profile builders
# ---------------------------------------------------------------------------


async def build_hitter_profile(
    mlb_id: int,
    name: str,
    team: str,
    bat_side: str = "R",
    season: int = 2026,
) -> HitterProfile:
    """Build a regression-stabilised hitter profile from season stats.

    If the player has fewer than 30 PA, regression constants are doubled
    to pull rates more aggressively toward league averages.
    """
    lg = _load_league_averages()
    lg_hit = lg["hitting"]
    reg_pa = lg["regression_pa"]

    # Fetch season stats ------------------------------------------------
    raw_data = await get_player_season_stats(mlb_id, season, "hitting")
    s = _extract_hitting_stat(raw_data)

    pa = int(s.get("plateAppearances", 0))
    h = int(s.get("hits", 0))
    doubles = int(s.get("doubles", 0))
    triples = int(s.get("triples", 0))
    hr = int(s.get("homeRuns", 0))
    k = int(s.get("strikeOuts", 0))
    bb = int(s.get("baseOnBalls", 0))
    hbp = int(s.get("hitByPitch", 0))
    sb = int(s.get("stolenBases", 0))
    cs = int(s.get("caughtStealing", 0))
    runs = int(s.get("runs", 0))
    rbi = int(s.get("rbi", 0))
    gp = int(s.get("gamesPlayed", 0))

    singles = h - doubles - triples - hr

    # Regression multiplier — more aggressive for tiny samples
    reg_mult = 2.0 if pa < 30 else 1.0

    # Raw rates ---------------------------------------------------------
    raw_k = _safe_div(k, pa, lg_hit["k_rate"])
    raw_bb = _safe_div(bb, pa, lg_hit["bb_rate"])
    raw_hbp = _safe_div(hbp, pa, lg_hit["hbp_rate"])

    contacts = pa - k - bb - hbp
    raw_hr_c = _safe_div(hr, contacts, lg_hit["hr_per_contact"])
    raw_3b_c = _safe_div(triples, contacts, lg_hit["triple_per_contact"])
    raw_2b_c = _safe_div(doubles, contacts, lg_hit["double_per_contact"])
    raw_1b_c = _safe_div(singles, contacts, lg_hit["single_per_contact"])

    # SB rate: SB per time reaching base (excluding HR)
    times_on_base = h + bb + hbp - hr
    raw_sb = _safe_div(sb, times_on_base, lg_hit["sb_rate"])

    # CS rate: CS per SB attempt
    sb_attempts = sb + cs
    raw_cs = _safe_div(cs, sb_attempts, 0.25)  # ~25% league avg CS rate

    raw_runs = _safe_div(runs, pa, lg_hit["runs_per_pa"])
    raw_rbi = _safe_div(rbi, pa, lg_hit["rbi_per_pa"])

    # Regress each rate -------------------------------------------------
    def _r(raw: float, lg_key: str, reg_key: str, sample: int = pa) -> float:
        return _regress(raw, sample, lg_hit[lg_key], int(reg_pa[reg_key] * reg_mult))

    k_rate = _clamp(_r(raw_k, "k_rate", "k_rate"), 0.05, 0.50)
    bb_rate = _clamp(_r(raw_bb, "bb_rate", "bb_rate"), 0.01, 0.25)
    hbp_rate = _clamp(_r(raw_hbp, "hbp_rate", "hbp_rate"), 0.0, 0.05)

    # Contact-type rates regress against contact sample
    hr_per_contact = _clamp(
        _r(raw_hr_c, "hr_per_contact", "hr_rate", contacts), 0.005, 0.15
    )
    triple_per_contact = _clamp(
        _r(raw_3b_c, "triple_per_contact", "triple_rate", contacts), 0.0, 0.03
    )
    double_per_contact = _clamp(
        _r(raw_2b_c, "double_per_contact", "double_rate", contacts), 0.01, 0.12
    )
    single_per_contact = _clamp(
        _r(raw_1b_c, "single_per_contact", "babip", contacts), 0.10, 0.35
    )

    sb_rate = _clamp(
        _regress(raw_sb, times_on_base, lg_hit["sb_rate"], int(reg_pa["sb_rate"] * reg_mult)),
        0.0,
        0.40,
    )
    cs_rate = _clamp(raw_cs, 0.05, 0.50)  # CS rate not regressed heavily

    runs_per_pa = _clamp(_r(raw_runs, "runs_per_pa", "runs_per_pa"), 0.05, 0.25)
    rbi_per_pa = _clamp(_r(raw_rbi, "rbi_per_pa", "rbi_per_pa"), 0.03, 0.25)

    logger.info(
        "Hitter profile: %s (%d) — %d PA, k=%.3f bb=%.3f hr_c=%.3f",
        name,
        mlb_id,
        pa,
        k_rate,
        bb_rate,
        hr_per_contact,
    )

    return HitterProfile(
        mlb_id=mlb_id,
        name=name,
        team=team,
        bat_side=bat_side,
        k_rate=k_rate,
        bb_rate=bb_rate,
        hbp_rate=hbp_rate,
        hr_per_contact=hr_per_contact,
        triple_per_contact=triple_per_contact,
        double_per_contact=double_per_contact,
        single_per_contact=single_per_contact,
        sb_rate=sb_rate,
        cs_rate=cs_rate,
        runs_per_pa=runs_per_pa,
        rbi_per_pa=rbi_per_pa,
        pa_season=pa,
        games_played=gp,
    )


async def build_pitcher_profile(
    mlb_id: int,
    name: str,
    team: str,
    pitch_hand: str = "R",
    season: int = 2026,
) -> PitcherProfile:
    """Build a regression-stabilised pitcher profile from season stats."""
    lg = _load_league_averages()
    lg_pit = lg["pitching"]
    reg_bf = lg["regression_bf"]

    # Fetch season stats ------------------------------------------------
    raw_data = await get_player_season_stats(mlb_id, season, "pitching")
    s = _extract_pitching_stat(raw_data)

    ip = _parse_ip(s.get("inningsPitched", "0"))
    k = int(s.get("strikeOuts", 0))
    bb = int(s.get("baseOnBalls", 0))
    hbp = int(s.get("hitByPitch", 0))
    h = int(s.get("hits", 0))
    hr = int(s.get("homeRuns", 0))
    gs = int(s.get("gamesStarted", 0))

    # Batters faced — use API field if available, else estimate
    bf = int(s.get("battersFaced", 0))
    if bf == 0:
        # Estimate: each full inning retires 3 batters; add baserunners
        bf = int(ip * 3) + h + bb + hbp
    # If still 0 (no data at all), all rates will fall back to league avg
    # via _safe_div fallbacks and heavy regression

    # Regression multiplier for small samples
    reg_mult = 2.0 if bf < 50 else 1.0

    # Raw rates ---------------------------------------------------------
    raw_k = _safe_div(k, bf, lg_pit["k_rate"])
    raw_bb = _safe_div(bb, bf, lg_pit["bb_rate"])
    raw_hbp = _safe_div(hbp, bf, lg_pit["hbp_rate"])
    raw_hr = _safe_div(hr, bf, lg_pit["hr_per_bf"])

    # BABIP against: (H - HR) / (BF - K - HR - BB - HBP)
    bip = bf - k - hr - bb - hbp
    raw_babip = _safe_div(h - hr, bip, lg_pit["babip"])

    # Regress -----------------------------------------------------------
    def _r(raw: float, lg_key: str, reg_key: str, sample: int = bf) -> float:
        return _regress(raw, sample, lg_pit[lg_key], int(reg_bf[reg_key] * reg_mult))

    k_rate = _clamp(_r(raw_k, "k_rate", "k_rate"), 0.05, 0.45)
    bb_rate = _clamp(_r(raw_bb, "bb_rate", "bb_rate"), 0.02, 0.18)
    hbp_rate = _clamp(_r(raw_hbp, "hbp_rate", "hbp_rate"), 0.0, 0.03)
    hr_per_bf = _clamp(_r(raw_hr, "hr_per_bf", "hr_rate"), 0.005, 0.07)
    babip_against = _clamp(_r(raw_babip, "babip", "babip", bip if bip > 0 else 0), 0.220, 0.370)

    # IP per start (floor 4.0, ceiling 7.5) ----------------------------
    if gs > 0:
        raw_ip_per_start = ip / gs
    else:
        raw_ip_per_start = lg_pit["ip_per_start"]
    ip_per_start = _clamp(raw_ip_per_start, 4.0, 7.5)

    logger.info(
        "Pitcher profile: %s (%d) — %d BF, k=%.3f bb=%.3f hr=%.3f babip=%.3f ip/gs=%.1f",
        name,
        mlb_id,
        bf,
        k_rate,
        bb_rate,
        hr_per_bf,
        babip_against,
        ip_per_start,
    )

    return PitcherProfile(
        mlb_id=mlb_id,
        name=name,
        team=team,
        pitch_hand=pitch_hand,
        k_rate=k_rate,
        bb_rate=bb_rate,
        hbp_rate=hbp_rate,
        hr_per_bf=hr_per_bf,
        babip_against=babip_against,
        ip_per_start=ip_per_start,
        bf_season=bf,
        games_started=gs,
    )


# ---------------------------------------------------------------------------
# Batch builders
# ---------------------------------------------------------------------------


async def batch_build_hitter_profiles(
    players: list[dict[str, Any]],
    season: int = 2026,
) -> dict[int, HitterProfile]:
    """Build profiles for many hitters with concurrency-limited API calls.

    Each dict in *players* must have keys: ``mlb_id``, ``name``, ``team``,
    and optionally ``bat_side`` (defaults to ``"R"``).
    """
    sem = asyncio.Semaphore(15)
    results: dict[int, HitterProfile] = {}
    total = len(players)

    async def _build(idx: int, p: dict[str, Any]) -> None:
        async with sem:
            try:
                profile = await build_hitter_profile(
                    mlb_id=p["mlb_id"],
                    name=p["name"],
                    team=p["team"],
                    bat_side=p.get("bat_side", "R"),
                    season=season,
                )
                results[p["mlb_id"]] = profile
                if (idx + 1) % 10 == 0 or idx + 1 == total:
                    logger.info("Hitter profiles: %d / %d done", idx + 1, total)
            except Exception:
                logger.exception("Failed to build hitter profile for %s (%d)", p.get("name"), p.get("mlb_id"))

    await asyncio.gather(*[_build(i, p) for i, p in enumerate(players)])
    logger.info("Built %d / %d hitter profiles", len(results), total)
    return results


async def batch_build_pitcher_profiles(
    pitchers: list[dict[str, Any]],
    season: int = 2026,
) -> dict[int, PitcherProfile]:
    """Build profiles for many pitchers with concurrency-limited API calls.

    Each dict in *pitchers* must have keys: ``mlb_id``, ``name``, ``team``,
    and optionally ``pitch_hand`` (defaults to ``"R"``).
    """
    sem = asyncio.Semaphore(15)
    results: dict[int, PitcherProfile] = {}
    total = len(pitchers)

    async def _build(idx: int, p: dict[str, Any]) -> None:
        async with sem:
            try:
                profile = await build_pitcher_profile(
                    mlb_id=p["mlb_id"],
                    name=p["name"],
                    team=p["team"],
                    pitch_hand=p.get("pitch_hand", "R"),
                    season=season,
                )
                results[p["mlb_id"]] = profile
                if (idx + 1) % 5 == 0 or idx + 1 == total:
                    logger.info("Pitcher profiles: %d / %d done", idx + 1, total)
            except Exception:
                logger.exception("Failed to build pitcher profile for %s (%d)", p.get("name"), p.get("mlb_id"))

    await asyncio.gather(*[_build(i, p) for i, p in enumerate(pitchers)])
    logger.info("Built %d / %d pitcher profiles", len(results), total)
    return results
