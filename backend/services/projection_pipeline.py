"""Sim-based projection pipeline orchestrator.

Generates projections for a full slate by:
1. Fetching schedule, lineups, DK salaries, and Vegas odds
2. Building true-talent profiles for all hitters and pitchers
3. Computing matchup rates for each hitter vs opposing pitcher
4. Running Monte Carlo simulations for each player
5. Merging DK salary data and archiving inputs/outputs

This replaces the SaberSim CSV dependency with home-grown projections.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from services import mlb_stats
from services.constants import DK_TEAM_ALIAS
from services.csv_projections import load_dk_salaries
from services.dk_api import get_salaries_csv
from services.slate_manager import fetch_dk_slates, identify_featured_slate
from services.lineup_scraper import (
    fetch_lineups,
    GameLineup,
    PlayerLineup as LineupPlayerInfo,
    TeamLineup as LineupTeamInfo,
)
from services.matchup import compute_matchup_rates, get_park_factors
from services.name_matching import canonical_name, find_in_dict as find_name_in_dict
from services.opportunity import (
    expected_hitter_pa,
    expected_pitcher_bf,
    expected_pitcher_ip,
    pitcher_win_probability,
)
from services.pa_simulator import simulate_hitter_game, simulate_pitcher_game
from services.true_talent import (
    HitterProfile,
    PitcherProfile,
    batch_build_hitter_profiles,
    batch_build_pitcher_profiles,
)
from services.vegas import fetch_fantasylabs_odds

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def generate_projections(
    target_date: str,
    site: str = "dk",
    n_sims: int = 1000,
) -> list[dict]:
    """Generate projections for all players on today's slate.

    Returns list of dicts compatible with SlateProjectionOut schema.
    """
    t0 = time.time()

    try:
        date_obj = date.fromisoformat(target_date)
    except ValueError:
        logger.error("Invalid date: %s", target_date)
        return []

    # ------------------------------------------------------------------
    # Step 1: Fetch schedule
    # ------------------------------------------------------------------
    logger.info("Pipeline step 1: Fetch schedule for %s", target_date)
    schedule_data = await mlb_stats.get_schedule(game_date=date_obj)
    games = mlb_stats.parse_schedule_games(schedule_data)
    if not games:
        logger.warning("No games found for %s", target_date)
        return []
    # Normalize team abbreviations (MLB API returns AZ, ATH; we use ARI, OAK)
    for g in games:
        for key in ("home_team_abbr", "away_team_abbr"):
            raw = g.get(key, "")
            g[key] = DK_TEAM_ALIAS.get(raw, raw)
    logger.info("Found %d games", len(games))

    # ------------------------------------------------------------------
    # Step 2: Fetch lineups
    # ------------------------------------------------------------------
    logger.info("Pipeline step 2: Fetch lineups")
    lineup_games: list[GameLineup] = []
    try:
        lineup_games = await fetch_lineups(target_date=target_date)
    except Exception as exc:
        logger.warning("Lineup fetch failed (continuing with schedule data): %s", exc)

    # Build quick lookup: team -> GameLineup + side
    lineup_by_team: dict[str, Tuple[GameLineup, str]] = {}
    for lg in lineup_games:
        lineup_by_team[lg.away.team] = (lg, "away")
        lineup_by_team[lg.home.team] = (lg, "home")

    # ------------------------------------------------------------------
    # Step 3: Fetch DK salaries (API first, local CSV fallback)
    # ------------------------------------------------------------------
    logger.info("Pipeline step 3: Fetch DK salaries")
    salary_lookup: dict[str, dict[str, Any]] = {}
    try:
        salary_lookup = await _fetch_dk_salaries_api()
    except Exception as exc:
        logger.warning("DK salary API fetch failed: %s", exc)

    if not salary_lookup:
        logger.info("API salaries empty; falling back to local CSV")
        try:
            salary_lookup = load_dk_salaries(target_date=date_obj)
        except Exception as exc:
            logger.warning("DK salary CSV load also failed: %s", exc)

    # ------------------------------------------------------------------
    # Step 4: Fetch Vegas odds
    # ------------------------------------------------------------------
    logger.info("Pipeline step 4: Fetch Vegas odds")
    odds_by_team: dict[str, dict[str, Any]] = {}
    all_odds: list[dict] = []
    try:
        all_odds = await fetch_fantasylabs_odds(target_date=target_date)
        for od in all_odds:
            away = od.get("away_team", "")
            home = od.get("home_team", "")
            if away:
                odds_by_team[away] = od
            if home:
                odds_by_team[home] = od
    except Exception as exc:
        logger.warning("Vegas odds fetch failed: %s", exc)

    # ------------------------------------------------------------------
    # Step 5: Build roster lookups (for resolving MLB IDs)
    # ------------------------------------------------------------------
    logger.info("Pipeline step 5: Fetch team rosters for MLB ID resolution")
    team_ids: set[int] = set()
    for g in games:
        if g.get("home_team_id"):
            team_ids.add(g["home_team_id"])
        if g.get("away_team_id"):
            team_ids.add(g["away_team_id"])

    roster_lookup: dict[str, dict[str, Any]] = {}
    if team_ids:
        try:
            roster_lookup = await mlb_stats.get_rosters_for_teams(list(team_ids))
        except Exception as exc:
            logger.warning("Roster fetch failed: %s", exc)

    # ------------------------------------------------------------------
    # Step 6: Build player lists from lineups
    # ------------------------------------------------------------------
    logger.info("Pipeline step 6: Build player lists from lineups")

    hitter_inputs: list[dict[str, Any]] = []
    pitcher_inputs: list[dict[str, Any]] = []

    # Map game_pk -> game info for venue/opp lookups
    game_info_by_pk: dict[int, dict] = {}
    for g in games:
        gpk = g.get("game_pk")
        if gpk:
            game_info_by_pk[gpk] = g

    # Build a game lookup: (home_team, away_team) -> game info
    game_info_by_teams: dict[Tuple[str, str], dict] = {}
    for g in games:
        key = (g.get("home_team_abbr", ""), g.get("away_team_abbr", ""))
        game_info_by_teams[key] = g

    # Track per-game pitcher info for matchup lookups
    # team -> pitcher PlayerInfo from lineup data
    pitcher_by_team: dict[str, dict[str, Any]] = {}

    # Track opener status: player name (lower) -> "PO" or "PLR"
    opener_status_lookup: dict[str, str] = {}

    for lg in lineup_games:
        for side_attr, side_label in [("home", "home"), ("away", "away")]:
            team_lineup = getattr(lg, side_attr)
            team = team_lineup.team
            is_confirmed = team_lineup.status in ("confirmed", "expected")

            # Detect opener/PLR: if the lineup has a long_reliever, the
            # listed pitcher is an opener (PO) and the reliever is PLR
            has_plr = team_lineup.long_reliever is not None

            # Pitcher
            if team_lineup.pitcher:
                p = team_lineup.pitcher
                mlb_id = _resolve_mlb_id(p.name, roster_lookup)
                pitch_hand = p.handedness if p.handedness else "R"

                if not p.handedness and mlb_id:
                    roster_entry = _find_roster_entry_by_id(mlb_id, roster_lookup)
                    if roster_entry:
                        pitch_hand = roster_entry.get("pitch_hand", "R")

                pitcher_info = {
                    "mlb_id": mlb_id,
                    "name": p.name,
                    "team": team,
                    "pitch_hand": pitch_hand,
                    "is_confirmed": True,
                    "opener_status": "PO" if has_plr else None,
                }
                pitcher_inputs.append(pitcher_info)
                pitcher_by_team[team] = pitcher_info
                if has_plr:
                    opener_status_lookup[p.name.lower().strip()] = "PO"

            # Probable Long Reliever (PLR) — project as a pitcher too
            if team_lineup.long_reliever:
                plr = team_lineup.long_reliever
                plr_mlb_id = _resolve_mlb_id(plr.name, roster_lookup)
                plr_hand = plr.handedness if plr.handedness else "R"

                if not plr.handedness and plr_mlb_id:
                    roster_entry = _find_roster_entry_by_id(plr_mlb_id, roster_lookup)
                    if roster_entry:
                        plr_hand = roster_entry.get("pitch_hand", "R")

                pitcher_inputs.append({
                    "mlb_id": plr_mlb_id,
                    "name": plr.name,
                    "team": team,
                    "pitch_hand": plr_hand,
                    "is_confirmed": True,
                    "opener_status": "PLR",
                })
                opener_status_lookup[plr.name.lower().strip()] = "PLR"

            # Batters
            for b in team_lineup.batters:
                mlb_id = _resolve_mlb_id(b.name, roster_lookup)
                bat_side = b.handedness if b.handedness else "R"

                # Try to get bat side from roster if not in lineup data
                if not b.handedness and mlb_id:
                    roster_entry = _find_roster_entry_by_id(mlb_id, roster_lookup)
                    if roster_entry:
                        bat_side = roster_entry.get("bat_side", "R")

                hitter_inputs.append({
                    "mlb_id": mlb_id,
                    "name": b.name,
                    "team": team,
                    "bat_side": bat_side,
                    "batting_order": b.batting_order,
                    "position": b.position or "UTIL",
                    "is_confirmed": is_confirmed,
                })

    # If we got no lineup data, fall back to schedule data for pitchers
    # and build synthetic lineup_by_team for game lookups
    if not lineup_games:
        logger.info("No lineup data; building from schedule pitchers")
        for g in games:
            home_abbr = g.get("home_team_abbr", "")
            away_abbr = g.get("away_team_abbr", "")

            home_pitcher = None
            away_pitcher = None

            for side, abbr in [("home", home_abbr), ("away", away_abbr)]:
                pid = g.get(f"{side}_pitcher_id")
                pname = g.get(f"{side}_pitcher_name")
                phand = g.get(f"{side}_pitcher_hand") or "R"
                if pid and pname:
                    pitcher_info = {
                        "mlb_id": pid,
                        "name": pname,
                        "team": abbr,
                        "pitch_hand": phand,
                        "is_confirmed": True,
                    }
                    pitcher_inputs.append(pitcher_info)
                    pitcher_by_team[abbr] = pitcher_info

                    pl = LineupPlayerInfo(
                        name=pname, team=abbr, position="P",
                        is_pitcher=True, handedness=phand,
                    )
                    if side == "home":
                        home_pitcher = pl
                    else:
                        away_pitcher = pl

            # Build a synthetic GameLineup so pitcher projection can find its game
            synthetic_game = GameLineup(
                away=LineupTeamInfo(team=away_abbr, status="expected", pitcher=away_pitcher),
                home=LineupTeamInfo(team=home_abbr, status="expected", pitcher=home_pitcher),
            )
            lineup_by_team[away_abbr] = (synthetic_game, "away")
            lineup_by_team[home_abbr] = (synthetic_game, "home")

    # ------------------------------------------------------------------
    # Step 6b: For teams WITHOUT posted lineups, use recent starters
    # ------------------------------------------------------------------
    teams_today: set[str] = set()
    for g in games:
        teams_today.add(g.get("home_team_abbr", ""))
        teams_today.add(g.get("away_team_abbr", ""))
    teams_today.discard("")

    # Determine which teams have confirmed/expected lineups — skip them
    teams_with_lineup_status: set[str] = set()
    for lg in lineup_games:
        if lg.away.status in ("confirmed", "expected") and lg.away.batters:
            teams_with_lineup_status.add(lg.away.team)
        if lg.home.status in ("confirmed", "expected") and lg.home.batters:
            teams_with_lineup_status.add(lg.home.team)

    teams_with_batters: set[str] = {h["team"] for h in hitter_inputs}
    teams_missing_batters = teams_today - teams_with_batters - teams_with_lineup_status

    if teams_missing_batters:
        logger.info(
            "Teams missing batters (%d): %s — fetching recent starters",
            len(teams_missing_batters), ", ".join(sorted(teams_missing_batters)),
        )
        from services.recent_lineups import get_recent_starters_bulk

        try:
            recent = await get_recent_starters_bulk(
                list(teams_missing_batters),
                lookback_days=3,
                as_of_date=target_date,
            )
        except Exception as exc:
            logger.warning("Recent starters fetch failed: %s", exc)
            recent = {}

        for team, starters in recent.items():
            if not starters:
                continue

            # Group starters by position to detect platoons
            by_position: dict[str, list] = {}
            for s in starters:
                pos = s.position or "UTIL"
                by_position.setdefault(pos, []).append(s)

            # Build a likely 9-man lineup, handling platoons:
            # If a position has multiple starters across recent days
            # but they never started together, only pick one per lineup.
            selected: list = []
            for pos, players in by_position.items():
                if pos in ("P", "SP", "RP"):
                    continue
                if len(players) == 1:
                    selected.append(players[0])
                else:
                    # Platoon: pick the player who started most recently/frequently
                    # All players get projected, but each is marked with their
                    # share of starts so the per-slate overlay can include them
                    for p in players:
                        selected.append(p)

            # Cap at 9 batters (sorted by frequency, then most recent)
            selected.sort(key=lambda s: (-s.games_started, s.dates_started[-1] if s.dates_started else ""), reverse=False)
            selected.sort(key=lambda s: s.games_started, reverse=True)

            for idx, s in enumerate(selected):
                mlb_id = s.mlb_id
                bat_side = "R"
                roster_entry = _find_roster_entry_by_id(mlb_id, roster_lookup)
                if roster_entry:
                    bat_side = roster_entry.get("bat_side", "R")

                pos = s.position or "UTIL"
                if pos == "DH":
                    pos = "UTIL"
                hitter_inputs.append({
                    "mlb_id": mlb_id,
                    "name": s.name,
                    "team": team,
                    "bat_side": bat_side,
                    "batting_order": None,
                    "position": pos,
                    "is_confirmed": False,
                    "lineup_status": "projected_recent",
                })

            # Ensure team has a game entry in lineup_by_team
            if team not in lineup_by_team:
                _ensure_synthetic_lineup(team, games, lineup_by_team)

        logger.info(
            "Added %d hitters from recent starters for %d teams",
            sum(1 for h in hitter_inputs if h["team"] in teams_missing_batters),
            len([t for t in teams_missing_batters if recent.get(t)]),
        )

    # Final fallback: any team still missing batters, use DK draftables
    teams_still_missing = teams_today - {h["team"] for h in hitter_inputs}
    if teams_still_missing and salary_lookup:
        logger.info("DK draftables fallback for teams: %s", ", ".join(sorted(teams_still_missing)))
        for name, info in salary_lookup.items():
            team = info.get("team", "").upper()
            pos = info.get("position", "").upper()
            if team not in teams_still_missing:
                continue
            if pos in ("SP", "RP", "P"):
                continue

            mlb_id = _resolve_mlb_id(name, roster_lookup)
            bat_side = "R"
            if mlb_id:
                roster_entry = _find_roster_entry_by_id(mlb_id, roster_lookup)
                if roster_entry:
                    bat_side = roster_entry.get("bat_side", "R")

            hitter_inputs.append({
                "mlb_id": mlb_id,
                "name": name,
                "team": team,
                "bat_side": bat_side,
                "batting_order": None,
                "position": pos or "UTIL",
                "is_confirmed": False,
            })

            if team not in lineup_by_team:
                _ensure_synthetic_lineup(team, games, lineup_by_team)

    # ------------------------------------------------------------------
    # Deduplicate hitter_inputs by mlb_id (Task #7 fix).
    # Recent starters (step 6b) may add a player who's already in the
    # confirmed lineup from step 6, or a player at multiple positions.
    # Keep the first (confirmed/higher-priority) occurrence per mlb_id.
    # ------------------------------------------------------------------
    _seen_mlb_ids: set[int] = set()
    _deduped_hitters: list[dict[str, Any]] = []
    for h in hitter_inputs:
        mid = h.get("mlb_id")
        if mid:
            if mid in _seen_mlb_ids:
                continue
            _seen_mlb_ids.add(mid)
        _deduped_hitters.append(h)
    if len(_deduped_hitters) < len(hitter_inputs):
        logger.info(
            "Deduplicated hitter_inputs: %d -> %d (removed %d duplicates by mlb_id)",
            len(hitter_inputs), len(_deduped_hitters),
            len(hitter_inputs) - len(_deduped_hitters),
        )
    hitter_inputs = _deduped_hitters

    logger.info(
        "Projecting %d hitters, %d pitchers across %d games",
        len(hitter_inputs), len(pitcher_inputs), len(games),
    )

    # ------------------------------------------------------------------
    # Step 7: Batch build true-talent profiles
    # ------------------------------------------------------------------
    logger.info("Pipeline step 7: Build true-talent profiles")

    # Filter to players with MLB IDs
    hitters_with_id = [h for h in hitter_inputs if h.get("mlb_id")]
    pitchers_with_id = [p for p in pitcher_inputs if p.get("mlb_id")]

    hitter_profiles: dict[int, HitterProfile] = {}
    pitcher_profiles: dict[int, PitcherProfile] = {}

    if hitters_with_id:
        hitter_profiles = await batch_build_hitter_profiles(hitters_with_id)
    if pitchers_with_id:
        pitcher_profiles = await batch_build_pitcher_profiles(pitchers_with_id)

    logger.info(
        "Built %d hitter profiles, %d pitcher profiles",
        len(hitter_profiles), len(pitcher_profiles),
    )

    # ------------------------------------------------------------------
    # Steps 8-9: Simulate each player
    # ------------------------------------------------------------------
    logger.info("Pipeline step 8-9: Simulate all players (n_sims=%d)", n_sims)

    projections: list[dict] = []

    # --- Hitters ---
    for h in hitter_inputs:
        try:
            proj = _project_hitter(
                h, hitter_profiles, pitcher_profiles, pitcher_by_team,
                lineup_by_team, game_info_by_teams, odds_by_team, site, n_sims,
            )
            if proj:
                projections.append(proj)
        except Exception as exc:
            logger.warning(
                "Hitter projection failed for %s: %s", h.get("name"), exc,
            )

    # --- Pitchers ---
    for p in pitcher_inputs:
        try:
            proj = _project_pitcher(
                p, pitcher_profiles, lineup_by_team,
                game_info_by_teams, odds_by_team, site, n_sims,
            )
            if proj:
                projections.append(proj)
        except Exception as exc:
            logger.warning(
                "Pitcher projection failed for %s: %s", p.get("name"), exc,
            )

    # ------------------------------------------------------------------
    # Step 10: Merge DK salaries + opener status
    # ------------------------------------------------------------------
    logger.info("Pipeline step 10: Merge DK salaries")
    _merge_salaries(projections, salary_lookup)

    # Apply opener status tags (PO / PLR)
    if opener_status_lookup:
        for proj in projections:
            pname = proj.get("player_name", "").lower().strip()
            if pname in opener_status_lookup:
                proj["opener_status"] = opener_status_lookup[pname]

    # ------------------------------------------------------------------
    # Step 11: Archive daily inputs and projections
    # ------------------------------------------------------------------
    logger.info("Pipeline step 11: Archive daily data")
    _archive_daily(
        target_date, projections, games, lineup_games, all_odds,
        salary_lookup, n_sims, site,
    )

    elapsed = time.time() - t0
    logger.info(
        "Pipeline complete: %d projections in %.1fs",
        len(projections), elapsed,
    )

    return projections


# ---------------------------------------------------------------------------
# DK salary API fetcher
# ---------------------------------------------------------------------------


async def _fetch_dk_salaries_api() -> dict[str, dict[str, Any]]:
    """Fetch DK salaries from the DraftKings draftables API.

    Merges salaries across ALL classic slates to cover every player on every
    slate. Uses the highest salary when a player appears on multiple slates.
    Returns a dict keyed by player name, matching load_dk_salaries format.
    """
    from services.dk_api import get_draftables

    slates = await fetch_dk_slates()
    if not slates:
        logger.warning("No DK slates found via API")
        return {}

    classic = sorted(
        [s for s in slates if s["game_type"] == "classic"],
        key=lambda s: s["game_count"],
        reverse=True,
    )
    if not classic:
        classic = slates

    result: dict[str, dict[str, Any]] = {}
    for candidate in classic:
        dg_id = candidate.get("draft_group_id")
        if not dg_id:
            continue

        logger.info("Fetching salaries from DG-%d (%s, %d games)",
                     dg_id, candidate.get("name", ""), candidate.get("game_count", 0))
        try:
            draftables = await get_draftables(dg_id)
        except Exception as exc:
            logger.warning("Draftables fetch failed for DG-%d: %s", dg_id, exc)
            continue

        if not draftables:
            continue

        for d in draftables:
            name = d.get("displayName", "").strip()
            salary = d.get("salary", 0)
            if not name or not salary or salary <= 0:
                continue

            existing = result.get(name)
            if existing and existing.get("salary", 0) >= salary:
                continue

            result[name] = {
                "salary": salary,
                "dk_id": d.get("playerId"),
                "team": d.get("teamAbbreviation", ""),
                "position": d.get("position", ""),
                "roster_position": d.get("rosterSlotId", ""),
                "avg_pts": _extract_fppg(d),
            }

    if result:
        logger.info("Fetched %d DK salaries from API (%d slates)", len(result), len(classic))
    else:
        logger.warning("No DK slate had draftable players")
    return result


def _extract_fppg(draftable: dict) -> float:
    """Extract FPPG from a draftable's stat attributes."""
    for attr in draftable.get("draftStatAttributes", []):
        if attr.get("id") in (90, 408):
            try:
                return float(attr.get("value", 0))
            except (ValueError, TypeError):
                pass
    return 0.0


# ---------------------------------------------------------------------------
# Per-player projection helpers
# ---------------------------------------------------------------------------


def _project_hitter(
    h: dict[str, Any],
    hitter_profiles: dict[int, HitterProfile],
    pitcher_profiles: dict[int, PitcherProfile],
    pitcher_by_team: dict[str, dict[str, Any]],
    lineup_by_team: dict[str, Tuple[GameLineup, str]],
    game_info_by_teams: dict[Tuple[str, str], dict],
    odds_by_team: dict[str, dict[str, Any]],
    site: str,
    n_sims: int,
) -> Optional[dict]:
    """Generate a projection dict for one hitter."""
    mlb_id = h.get("mlb_id")
    name = h["name"]
    team = h["team"]
    batting_order = h.get("batting_order")

    # Find which game this hitter is in
    game_lg, side = lineup_by_team.get(team, (None, None))
    if not game_lg:
        return None

    opp_side = "home" if side == "away" else "away"
    opp_team_lineup = getattr(game_lg, opp_side)
    own_team_lineup = getattr(game_lg, side)
    opp_team = opp_team_lineup.team

    # Find the game info from schedule
    if side == "home":
        game_key = (team, opp_team)
    else:
        game_key = (opp_team, team)
    game_info = game_info_by_teams.get(game_key)
    # Try reverse if not found
    if not game_info:
        game_info = game_info_by_teams.get((opp_team, team))
    home_team_abbr = game_info.get("home_team_abbr", "") if game_info else ""

    # Get hitter profile
    profile = hitter_profiles.get(mlb_id) if mlb_id else None
    if not profile:
        # No profile available -- use salary-based defaults
        return _default_hitter_projection(h, opp_team, game_info, odds_by_team)

    # Get opposing pitcher profile for matchup model
    opp_pitcher_info = pitcher_by_team.get(opp_team)
    opp_pitcher_id = opp_pitcher_info.get("mlb_id") if opp_pitcher_info else None

    opp_profile: PitcherProfile
    if opp_pitcher_id and opp_pitcher_id in pitcher_profiles:
        opp_profile = pitcher_profiles[opp_pitcher_id]
    else:
        # No real profile available -- use league-average stub
        opp_profile = _get_league_avg_pitcher(opp_team, opp_pitcher_info)

    # Park factors
    park_hr, park_runs = get_park_factors(home_team_abbr)

    # Compute matchup rates
    rates = compute_matchup_rates(
        hitter=profile,
        pitcher=opp_profile,
        park_hr_factor=park_hr,
        park_runs_factor=park_runs,
        weather_mult=1.0,
    )

    # Vegas data
    odds = odds_by_team.get(team, {})
    team_implied = _get_team_implied(team, opp_team, odds_by_team)
    game_total = odds.get("game_total")

    # Expected PA
    exp_pa = expected_hitter_pa(
        batting_order=batting_order,
        team_implied=team_implied,
        game_total=game_total,
    )

    # Simulate
    dist = simulate_hitter_game(
        matchup_rates=rates,
        expected_pa=exp_pa,
        site=site,
        n_sims=n_sims,
        team_implied=team_implied,
    )

    result = {
        "player_name": name,
        "mlb_id": mlb_id,
        "dk_id": None,
        "team": team,
        "position": h.get("position", "UTIL"),
        "opp_team": opp_team,
        "is_home": side == "home",
        "game_pk": game_info.get("game_pk") if game_info else None,
        "venue": game_info.get("venue") if game_info else None,
        "salary": None,
        "batting_order": batting_order,
        "is_pitcher": False,
        "is_confirmed": h.get("is_confirmed", False),
        "floor_pts": round(dist.p10, 2),
        "median_pts": round(dist.mean, 2),
        "ceiling_pts": round(dist.p90, 2),
        "projected_ownership": None,
        "season_era": None,
        "season_k9": None,
        "season_avg": _season_avg_from_profile(profile),
        "season_ops": _season_ops_from_profile(profile),
        "games_in_log": 0,
        "implied_total": team_implied,
        "team_implied": team_implied,
        "game_total": game_total,
        "temperature": None,
        "dk_std": round(dist.std, 2),
        "p85": round(dist.p90, 2),
        "p95": round(dist.ceiling, 2),
    }
    # Propagate lineup_status from recent-starter fallback
    if h.get("lineup_status"):
        result["lineup_status"] = h["lineup_status"]
    return result


def _project_pitcher(
    p: dict[str, Any],
    pitcher_profiles: dict[int, PitcherProfile],
    lineup_by_team: dict[str, Tuple[GameLineup, str]],
    game_info_by_teams: dict[Tuple[str, str], dict],
    odds_by_team: dict[str, dict[str, Any]],
    site: str,
    n_sims: int,
) -> Optional[dict]:
    """Generate a projection dict for one pitcher."""
    mlb_id = p.get("mlb_id")
    name = p["name"]
    team = p["team"]

    # Find which game this pitcher is in
    game_lg, side = lineup_by_team.get(team, (None, None))
    if not game_lg:
        return None

    opp_side = "home" if side == "away" else "away"
    opp_team_lineup = getattr(game_lg, opp_side)
    opp_team = opp_team_lineup.team

    # Find game info
    if side == "home":
        game_key = (team, opp_team)
    else:
        game_key = (opp_team, team)
    game_info = game_info_by_teams.get(game_key)
    if not game_info:
        game_info = game_info_by_teams.get((opp_team, team))

    # Get pitcher profile
    profile = pitcher_profiles.get(mlb_id) if mlb_id else None
    if not profile:
        return _default_pitcher_projection(p, opp_team, game_info, odds_by_team)

    # Vegas data
    team_implied = _get_team_implied(team, opp_team, odds_by_team)
    opp_implied = _get_team_implied(opp_team, team, odds_by_team)
    game_total_odds = odds_by_team.get(team, {}).get("game_total")

    # Expected IP / BF — adjusted for opener/PLR roles
    opener_status = p.get("opener_status")
    if opener_status == "PO":
        exp_ip = 1.5  # Opener: 1-2 innings
    elif opener_status == "PLR":
        exp_ip = min(profile.ip_per_start, 4.0) if profile.ip_per_start > 0 else 3.5
    else:
        exp_ip = expected_pitcher_ip(
            ip_per_start=profile.ip_per_start,
            opp_implied=opp_implied,
        )
    exp_bf = expected_pitcher_bf(
        ip=exp_ip,
        k_rate=profile.k_rate,
        bb_rate=profile.bb_rate,
    )

    # Win probability
    win_prob = pitcher_win_probability(team_implied, opp_implied)

    # Simulate
    dist = simulate_pitcher_game(
        pitcher_k_rate=profile.k_rate,
        pitcher_bb_rate=profile.bb_rate,
        pitcher_hbp_rate=profile.hbp_rate,
        pitcher_hr_per_bf=profile.hr_per_bf,
        pitcher_babip=profile.babip_against,
        expected_ip=exp_ip,
        expected_bf=exp_bf,
        team_implied=team_implied,
        opp_implied=opp_implied,
        win_probability=win_prob,
        site=site,
        n_sims=n_sims,
    )

    # Season stats for display
    season_era = None
    season_k9 = None
    if profile.bf_season > 0 and profile.games_started > 0:
        ip_total = profile.ip_per_start * profile.games_started
        if ip_total > 0:
            # Approximate ERA from rates
            contact_rate = 1.0 - profile.k_rate - profile.bb_rate - profile.hbp_rate
            hit_rate = profile.babip_against * contact_rate
            er_per_bf = (hit_rate * 0.5 + profile.hr_per_bf * 1.4 + profile.bb_rate * 0.33)
            bf_per_ip = profile.bf_season / ip_total if ip_total > 0 else 3.5
            season_era = round(er_per_bf * bf_per_ip * 9, 2)
            season_k9 = round(profile.k_rate * bf_per_ip * 9, 1)

    return {
        "player_name": name,
        "mlb_id": mlb_id,
        "dk_id": None,
        "team": team,
        "position": "SP",
        "opp_team": opp_team,
        "is_home": side == "home",
        "game_pk": game_info.get("game_pk") if game_info else None,
        "venue": game_info.get("venue") if game_info else None,
        "salary": None,
        "batting_order": None,
        "is_pitcher": True,
        "is_confirmed": p.get("is_confirmed", True),
        "floor_pts": round(dist.p10, 2),
        "median_pts": round(dist.mean, 2),
        "ceiling_pts": round(dist.p90, 2),
        "projected_ownership": None,
        "season_era": season_era,
        "season_k9": season_k9,
        "season_avg": None,
        "season_ops": None,
        "games_in_log": 0,
        "implied_total": game_total_odds,
        "team_implied": team_implied,
        "game_total": game_total_odds,
        "temperature": None,
        "dk_std": round(dist.std, 2),
        "p85": round(dist.p90, 2),
        "p95": round(dist.ceiling, 2),
    }


# ---------------------------------------------------------------------------
# Salary merging
# ---------------------------------------------------------------------------


def _merge_salaries(
    projections: list[dict],
    salary_lookup: dict[str, dict[str, Any]],
) -> None:
    """Merge DK salary data into projections by name matching."""
    if not salary_lookup:
        return

    for proj in projections:
        name = proj.get("player_name", "")
        if not name:
            continue

        # Try canonical match first
        cn = canonical_name(name)
        match = None
        for sal_name, sal_info in salary_lookup.items():
            if canonical_name(sal_name) == cn:
                match = sal_info
                break

        # Fuzzy fallback
        if match is None:
            result = find_name_in_dict(name, salary_lookup)
            if result:
                _, match = result

        if match:
            proj["salary"] = match.get("salary")
            proj["dk_id"] = match.get("dk_id")
            # Use DK position if we don't have one
            if proj.get("position") in (None, "UTIL", ""):
                dk_pos = match.get("position", "")
                if dk_pos:
                    proj["position"] = dk_pos


# ---------------------------------------------------------------------------
# Default projections (when no profile available)
# ---------------------------------------------------------------------------


def _default_hitter_projection(
    h: dict, opp_team: str, game_info: Optional[dict],
    odds_by_team: dict[str, dict],
) -> dict:
    """Generate a baseline hitter projection when no MLB stats are available."""
    team = h["team"]
    team_implied = _get_team_implied(team, opp_team, odds_by_team)

    # Conservative defaults: league-average hitter in neutral park
    base_pts = 6.0  # DK league-average hitter projection
    if team_implied:
        # Scale by team implied (4.5 is baseline)
        base_pts *= (team_implied / 4.5)

    result = {
        "player_name": h["name"],
        "mlb_id": h.get("mlb_id"),
        "dk_id": None,
        "team": team,
        "position": h.get("position", "UTIL"),
        "opp_team": opp_team,
        "is_home": (game_info.get("home_team_abbr", "") == team) if game_info else None,
        "game_pk": game_info.get("game_pk") if game_info else None,
        "venue": game_info.get("venue") if game_info else None,
        "salary": None,
        "batting_order": h.get("batting_order"),
        "is_pitcher": False,
        "is_confirmed": h.get("is_confirmed", False),
        "floor_pts": round(base_pts * 0.3, 2),
        "median_pts": round(base_pts, 2),
        "ceiling_pts": round(base_pts * 2.5, 2),
        "projected_ownership": None,
        "season_era": None,
        "season_k9": None,
        "season_avg": None,
        "season_ops": None,
        "games_in_log": 0,
        "implied_total": team_implied,
        "team_implied": team_implied,
        "game_total": odds_by_team.get(team, {}).get("game_total"),
        "temperature": None,
        "dk_std": round(base_pts * 0.6, 2),
        "p85": round(base_pts * 2.0, 2),
        "p95": round(base_pts * 3.0, 2),
    }
    # Propagate lineup_status from recent-starter fallback
    if h.get("lineup_status"):
        result["lineup_status"] = h["lineup_status"]
    return result


def _default_pitcher_projection(
    p: dict, opp_team: str, game_info: Optional[dict],
    odds_by_team: dict[str, dict],
) -> dict:
    """Generate a baseline pitcher projection when no MLB stats are available."""
    team = p["team"]
    team_implied = _get_team_implied(team, opp_team, odds_by_team)
    opp_implied = _get_team_implied(opp_team, team, odds_by_team)

    # Conservative defaults: league-average starter
    base_pts = 14.0  # DK league-average SP projection
    if opp_implied:
        # Tough lineups reduce pitcher points
        base_pts *= (4.5 / max(opp_implied, 2.0))
        base_pts = min(base_pts, 25.0)

    return {
        "player_name": p["name"],
        "mlb_id": p.get("mlb_id"),
        "dk_id": None,
        "team": team,
        "position": "SP",
        "opp_team": opp_team,
        "is_home": (game_info.get("home_team_abbr", "") == team) if game_info else None,
        "game_pk": game_info.get("game_pk") if game_info else None,
        "venue": game_info.get("venue") if game_info else None,
        "salary": None,
        "batting_order": None,
        "is_pitcher": True,
        "is_confirmed": p.get("is_confirmed", True),
        "floor_pts": round(base_pts * 0.2, 2),
        "median_pts": round(base_pts, 2),
        "ceiling_pts": round(base_pts * 2.0, 2),
        "projected_ownership": None,
        "season_era": None,
        "season_k9": None,
        "season_avg": None,
        "season_ops": None,
        "games_in_log": 0,
        "implied_total": odds_by_team.get(team, {}).get("game_total"),
        "team_implied": team_implied,
        "game_total": odds_by_team.get(team, {}).get("game_total"),
        "temperature": None,
        "dk_std": round(base_pts * 0.5, 2),
        "p85": round(base_pts * 1.8, 2),
        "p95": round(base_pts * 2.5, 2),
    }


# ---------------------------------------------------------------------------
# Vegas / odds helpers
# ---------------------------------------------------------------------------


def _get_team_implied(
    team: str, opp_team: str, odds_by_team: dict[str, dict],
) -> Optional[float]:
    """Extract the team implied run total from the odds lookup."""
    odds = odds_by_team.get(team)
    if not odds:
        odds = odds_by_team.get(opp_team)
    if not odds:
        return None

    # The odds dict has away_team/home_team and away_implied/home_implied
    if odds.get("home_team") == team:
        return odds.get("home_implied")
    elif odds.get("away_team") == team:
        return odds.get("away_implied")
    return None


def _find_opponent(team: str, games: list[dict]) -> Optional[str]:
    """Find the opposing team abbreviation from the schedule."""
    for g in games:
        if g.get("home_team_abbr") == team:
            return g.get("away_team_abbr")
        if g.get("away_team_abbr") == team:
            return g.get("home_team_abbr")
    return None


def _ensure_synthetic_lineup(
    team: str,
    games: list[dict],
    lineup_by_team: dict[str, Tuple[GameLineup, str]],
) -> None:
    """Create a synthetic GameLineup entry for a team if one doesn't exist."""
    if team in lineup_by_team:
        return
    opp_team = _find_opponent(team, games)
    if not opp_team:
        return
    is_home = any(g.get("home_team_abbr") == team for g in games)
    home_abbr = team if is_home else opp_team
    away_abbr = opp_team if is_home else team
    synthetic_game = GameLineup(
        away=LineupTeamInfo(team=away_abbr, status="expected", pitcher=None),
        home=LineupTeamInfo(team=home_abbr, status="expected", pitcher=None),
    )
    lineup_by_team[away_abbr] = (synthetic_game, "away")
    lineup_by_team[home_abbr] = (synthetic_game, "home")


# ---------------------------------------------------------------------------
# Name / ID resolution helpers
# ---------------------------------------------------------------------------


def _resolve_mlb_id(
    player_name: str,
    roster_lookup: dict[str, dict[str, Any]],
) -> Optional[int]:
    """Resolve a player name to an MLB ID via the roster lookup.

    The roster lookup is keyed by lowercase full name.
    """
    if not player_name or not roster_lookup:
        return None

    name_lower = player_name.lower().strip()

    # Direct match
    entry = roster_lookup.get(name_lower)
    if entry:
        return entry.get("mlb_id")

    # Canonical name match
    cn = canonical_name(player_name)
    for roster_name, info in roster_lookup.items():
        if canonical_name(roster_name) == cn:
            return info.get("mlb_id")

    # Fuzzy: last name + first initial
    result = find_name_in_dict(player_name, roster_lookup)
    if result:
        _, info = result
        return info.get("mlb_id")

    return None


def _find_roster_entry_by_id(
    mlb_id: int,
    roster_lookup: dict[str, dict[str, Any]],
) -> Optional[dict[str, Any]]:
    """Find a roster entry by MLB ID (reverse lookup)."""
    for _, info in roster_lookup.items():
        if info.get("mlb_id") == mlb_id:
            return info
    return None


# ---------------------------------------------------------------------------
# League-average pitcher stub
# ---------------------------------------------------------------------------


def _get_league_avg_pitcher(
    team: str, pitcher_info: Optional[dict] = None,
) -> PitcherProfile:
    """Create a league-average PitcherProfile for matchup calculations.

    Used when the actual pitcher profile couldn't be built (no MLB ID, etc.).
    """
    return PitcherProfile(
        mlb_id=pitcher_info.get("mlb_id", 0) if pitcher_info else 0,
        name=pitcher_info.get("name", "Unknown") if pitcher_info else "Unknown",
        team=team,
        pitch_hand=pitcher_info.get("pitch_hand", "R") if pitcher_info else "R",
        k_rate=0.223,
        bb_rate=0.083,
        hbp_rate=0.012,
        hr_per_bf=0.030,
        babip_against=0.296,
        ip_per_start=5.5,
        bf_season=0,
        games_started=0,
    )


# ---------------------------------------------------------------------------
# Season stat display helpers
# ---------------------------------------------------------------------------


def _season_avg_from_profile(profile: HitterProfile) -> Optional[float]:
    """Approximate batting average from a hitter profile's contact rates."""
    contact_rate = 1.0 - profile.k_rate - profile.bb_rate - profile.hbp_rate
    if contact_rate <= 0:
        return None
    hit_rate = contact_rate * (
        profile.single_per_contact
        + profile.double_per_contact
        + profile.triple_per_contact
        + profile.hr_per_contact
    )
    # BA = hits / AB, AB ~= PA - BB - HBP - SF (approximate)
    ab_rate = 1.0 - profile.bb_rate - profile.hbp_rate
    if ab_rate <= 0:
        return None
    return round(hit_rate / ab_rate, 3)


def _season_ops_from_profile(profile: HitterProfile) -> Optional[float]:
    """Approximate OPS from a hitter profile."""
    contact_rate = 1.0 - profile.k_rate - profile.bb_rate - profile.hbp_rate
    if contact_rate <= 0:
        return None

    singles = contact_rate * profile.single_per_contact
    doubles = contact_rate * profile.double_per_contact
    triples = contact_rate * profile.triple_per_contact
    hrs = contact_rate * profile.hr_per_contact
    hits = singles + doubles + triples + hrs

    # OBP = (H + BB + HBP) / PA
    obp = hits + profile.bb_rate + profile.hbp_rate

    # SLG = TB / AB; AB ~= PA - BB - HBP
    ab_rate = 1.0 - profile.bb_rate - profile.hbp_rate
    if ab_rate <= 0:
        return None
    tb = singles + 2 * doubles + 3 * triples + 4 * hrs
    slg = tb / ab_rate

    return round(obp + slg, 3)


# ---------------------------------------------------------------------------
# Daily archive
# ---------------------------------------------------------------------------


def _archive_daily(
    target_date: str,
    projections: list[dict],
    games: list[dict],
    lineup_games: list[GameLineup],
    odds: list[dict],
    salary_lookup: dict[str, dict],
    n_sims: int,
    site: str,
) -> None:
    """Save daily inputs, projections, and metadata to the archive directory."""
    archive_dir = _DATA_DIR / "daily_archive" / target_date
    try:
        archive_dir.mkdir(parents=True, exist_ok=True)

        # inputs.json: schedule, lineup summary, odds, salary summary
        lineup_summary = []
        for lg in lineup_games:
            lineup_summary.append({
                "away": {
                    "team": lg.away.team,
                    "status": lg.away.status,
                    "pitcher": lg.away.pitcher.name if lg.away.pitcher else None,
                    "batter_count": len(lg.away.batters),
                },
                "home": {
                    "team": lg.home.team,
                    "status": lg.home.status,
                    "pitcher": lg.home.pitcher.name if lg.home.pitcher else None,
                    "batter_count": len(lg.home.batters),
                },
            })

        inputs_data = {
            "schedule": [
                {
                    "game_pk": g.get("game_pk"),
                    "home": g.get("home_team_abbr"),
                    "away": g.get("away_team_abbr"),
                    "venue": g.get("venue"),
                    "home_pitcher": g.get("home_pitcher_name"),
                    "away_pitcher": g.get("away_pitcher_name"),
                }
                for g in games
            ],
            "lineups": lineup_summary,
            "odds": odds,
            "salaries_summary": {
                "total_players": len(salary_lookup),
                "teams": list({v.get("team", "") for v in salary_lookup.values() if v.get("team")}),
            },
        }
        _write_json(archive_dir / "inputs.json", inputs_data)

        # projections.json
        _write_json(archive_dir / "projections.json", projections)

        # metadata.json
        metadata = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "target_date": target_date,
            "n_sims": n_sims,
            "site": site,
            "version": "1.0.0",
            "total_projections": len(projections),
            "hitters": len([p for p in projections if not p.get("is_pitcher")]),
            "pitchers": len([p for p in projections if p.get("is_pitcher")]),
        }
        _write_json(archive_dir / "metadata.json", metadata)

        logger.info("Archived daily data to %s", archive_dir)
    except Exception as exc:
        logger.warning("Daily archive failed: %s", exc)


def _write_json(path: Path, data: Any) -> None:
    """Write JSON data to a file."""
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)
