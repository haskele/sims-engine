"""Daily projection pipeline orchestrator.

Runs the full daily flow:
1. Fetch today's MLB schedule + probable pitchers
2. Fetch DK slates and player salaries for the main slate
3. Fetch Vegas lines and implied run totals
4. Fetch weather for all games
5. Check lineup statuses (confirmed vs projected)
6. Generate projections for all players on each slate
7. Store everything in the database

Can be triggered via API or run as a standalone script.
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

from config import settings
from services import dk_api, mlb_stats, vegas, weather
from services.projections import (
    build_hitter_projection,
    build_pitcher_projection,
    get_park_factor,
    get_park_factor_by_team,
)
from services.slate_manager import (
    DK_TO_MLB_TEAM,
    fetch_dk_slate_details,
    fetch_dk_slates,
    identify_featured_slate,
    normalise_dk_team,
)

logger = logging.getLogger(__name__)


# ── Pipeline step results ────────────────────────────────────────────────────


class PipelineStepResult:
    """Simple result container for a pipeline step."""

    def __init__(
        self,
        step: str,
        success: bool,
        detail: str,
        records: int = 0,
        data: Optional[Any] = None,
    ):
        self.step = step
        self.success = success
        self.detail = detail
        self.records = records
        self.data = data

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step": self.step,
            "success": self.success,
            "detail": self.detail,
            "records_affected": self.records,
        }


# ── Main pipeline ────────────────────────────────────────────────────────────


async def run_daily_pipeline(
    target_date: str = "2026-04-14",
    site: str = "dk",
    season: int = 2026,
) -> Dict[str, Any]:
    """Run the full daily projection pipeline.

    This is a standalone function that does NOT require the FastAPI app or
    database to be running. It fetches data from external APIs, generates
    projections in memory, and returns a comprehensive result dict.

    For database persistence, use the API endpoint which wraps this function
    and stores results via SQLAlchemy.

    Parameters
    ----------
    target_date : str
        Date string in YYYY-MM-DD format.
    site : str
        'dk' or 'fd'.
    season : int
        MLB season year for stats.

    Returns
    -------
    dict with keys: steps, games, slates, projections, summary
    """
    try:
        d = date.fromisoformat(target_date)
    except ValueError:
        return {"error": f"Invalid date: {target_date}"}

    steps: List[Dict[str, Any]] = []
    all_projections: List[Dict[str, Any]] = []

    # ── Step 1: Fetch MLB schedule + probable pitchers + lineups ──────────

    logger.info("Step 1: Fetching MLB schedule for %s", target_date)
    schedule_data: Dict[str, Any] = {}
    games: List[Dict[str, Any]] = []
    try:
        schedule_data = await mlb_stats.get_schedule(
            game_date=d,
            hydrate="probablePitcher,lineups,weather",
        )
        games = mlb_stats.parse_schedule_games(schedule_data)
        steps.append(
            PipelineStepResult(
                "fetch-schedule", True,
                f"Found {len(games)} games for {target_date}",
                len(games),
                data=games,
            ).to_dict()
        )
    except Exception as exc:
        logger.error("Schedule fetch failed: %s", exc)
        steps.append(
            PipelineStepResult(
                "fetch-schedule", False, f"Error: {exc}"
            ).to_dict()
        )

    if not games:
        return {
            "steps": steps,
            "games": [],
            "slates": [],
            "projections": [],
            "summary": {"total_games": 0, "total_projections": 0,
                         "note": "No games found for this date"},
        }

    # ── Step 2: Fetch DK slates and salaries ─────────────────────────────

    logger.info("Step 2: Fetching DK slates")
    slates: List[Dict[str, Any]] = []
    featured_slate: Optional[Dict[str, Any]] = None
    slate_details: Dict[str, Any] = {}
    draftables_by_name: Dict[str, Dict[str, Any]] = {}

    try:
        slates = await fetch_dk_slates(target_date=d)
        featured_slate = identify_featured_slate(slates)
        slate_msg = f"Found {len(slates)} slates"
        if featured_slate:
            slate_msg += f", featured: {featured_slate['name']} (DG-{featured_slate['draft_group_id']})"
            # Fetch detailed info for featured slate
            try:
                slate_details = await fetch_dk_slate_details(
                    featured_slate["draft_group_id"]
                )
                for dr in slate_details.get("draftables", []):
                    # Index by player name (lowercase) for matching
                    name = (dr.get("displayName") or "").strip()
                    if name:
                        draftables_by_name[name.lower()] = dr
                slate_msg += f", {len(draftables_by_name)} draftable players"
            except Exception as exc2:
                logger.warning("Slate details fetch failed: %s", exc2)

        steps.append(
            PipelineStepResult(
                "fetch-dk-slates", True, slate_msg,
                len(slates),
            ).to_dict()
        )
    except Exception as exc:
        logger.error("DK slates fetch failed: %s", exc)
        steps.append(
            PipelineStepResult(
                "fetch-dk-slates", False, f"Error: {exc}"
            ).to_dict()
        )

    # ── Step 3: Fetch Vegas lines ────────────────────────────────────────

    logger.info("Step 3: Fetching Vegas lines")
    odds_by_game: Dict[str, Dict[str, Any]] = {}
    try:
        raw_odds = await vegas.get_mlb_odds()
        parsed_odds = vegas.parse_odds(raw_odds)
        # Index by home team name for matching
        for od in parsed_odds:
            home = od.get("home_team", "")
            if home:
                odds_by_game[home.lower()] = od
        steps.append(
            PipelineStepResult(
                "fetch-vegas", True,
                f"Found odds for {len(parsed_odds)} games",
                len(parsed_odds),
            ).to_dict()
        )
    except Exception as exc:
        logger.error("Vegas fetch failed: %s", exc)
        steps.append(
            PipelineStepResult(
                "fetch-vegas", False, f"Error: {exc}"
            ).to_dict()
        )

    # ── Step 4: Fetch weather for all games ──────────────────────────────

    logger.info("Step 4: Fetching weather")
    weather_by_venue: Dict[str, Dict[str, Any]] = {}
    weather_updated = 0
    # Load park factors for coordinates
    from services.projections import _load_park_factors
    pf_data = _load_park_factors()
    venue_coords: Dict[str, Tuple[float, float]] = {}
    for park_name, info in pf_data.items():
        venue_coords[park_name.lower()] = (info.get("lat", 0), info.get("lon", 0))

    for game in games:
        venue_name = game.get("venue", "")
        if not venue_name:
            continue
        # Skip domes
        venue_lower = venue_name.lower()
        is_dome = False
        for park_name, info in pf_data.items():
            if park_name.lower() in venue_lower or venue_lower in park_name.lower():
                if info.get("roof") == "dome":
                    is_dome = True
                break
        if is_dome:
            weather_by_venue[venue_name] = {
                "temperature": 72, "wind_speed": 0, "wind_dir": 0, "precip_pct": 0
            }
            continue

        # Find coordinates
        coords = None
        for park_name, (lat, lon) in venue_coords.items():
            if park_name in venue_lower or venue_lower in park_name:
                coords = (lat, lon)
                break

        if not coords or (coords[0] == 0 and coords[1] == 0):
            continue

        try:
            forecast = await weather.get_weather_forecast(
                coords[0], coords[1], target_date=d
            )
            # Determine game hour from start time
            game_hour = 19  # default 7 PM
            game_time_str = game.get("game_time")
            if game_time_str:
                try:
                    dt = datetime.fromisoformat(
                        game_time_str.replace("Z", "+00:00")
                    )
                    # Convert UTC to ET (approx -4 or -5)
                    game_hour = (dt.hour - 4) % 24
                except (ValueError, TypeError):
                    pass

            wx = weather.extract_game_time_weather(forecast, game_hour=game_hour)
            weather_by_venue[venue_name] = wx
            weather_updated += 1
        except Exception as exc:
            logger.debug("Weather fetch failed for %s: %s", venue_name, exc)

    steps.append(
        PipelineStepResult(
            "fetch-weather", True,
            f"Fetched weather for {weather_updated} venues",
            weather_updated,
        ).to_dict()
    )

    # ── Step 5: Check lineup statuses ────────────────────────────────────

    logger.info("Step 5: Checking lineup statuses")
    confirmed_count = 0
    projected_count = 0
    for game in games:
        home_lu = game.get("home_lineup", [])
        away_lu = game.get("away_lineup", [])
        if home_lu and away_lu:
            confirmed_count += 1
            game["lineup_status"] = "confirmed"
        else:
            projected_count += 1
            game["lineup_status"] = "projected"

    steps.append(
        PipelineStepResult(
            "check-lineups", True,
            f"Confirmed: {confirmed_count}, Projected: {projected_count}",
            confirmed_count + projected_count,
        ).to_dict()
    )

    # ── Step 5b: Fetch team rosters for name->MLB ID mapping ───────────

    logger.info("Step 5b: Fetching team rosters for player ID mapping")
    mlb_name_lookup: Dict[str, Dict[str, Any]] = {}
    team_ids_in_games = set()
    for game in games:
        ht_id = game.get("home_team_id")
        at_id = game.get("away_team_id")
        if ht_id:
            team_ids_in_games.add(ht_id)
        if at_id:
            team_ids_in_games.add(at_id)

    if team_ids_in_games:
        try:
            mlb_name_lookup = await mlb_stats.get_rosters_for_teams(
                list(team_ids_in_games), season=season
            )
            steps.append(
                PipelineStepResult(
                    "fetch-rosters", True,
                    f"Loaded rosters: {len(mlb_name_lookup)} players from {len(team_ids_in_games)} teams",
                    len(mlb_name_lookup),
                ).to_dict()
            )
        except Exception as exc:
            logger.warning("Roster fetch failed: %s", exc)
            steps.append(
                PipelineStepResult(
                    "fetch-rosters", False, f"Error: {exc}"
                ).to_dict()
            )

    # ── Step 6: Generate projections for all players ─────────────────────

    logger.info("Step 6: Generating projections")
    projection_count = 0
    error_count = 0

    for game_idx, game in enumerate(games):
        game_pk = game.get("game_pk")
        home_abbr = game.get("home_team_abbr", "")
        away_abbr = game.get("away_team_abbr", "")
        venue_name = game.get("venue", "")
        lineup_status = game.get("lineup_status", "projected")
        is_confirmed = lineup_status == "confirmed"

        # Match Vegas data to this game
        game_odds = _match_odds_to_game(odds_by_game, home_abbr, away_abbr)
        home_implied = game_odds.get("home_implied") if game_odds else None
        away_implied = game_odds.get("away_implied") if game_odds else None
        total = game_odds.get("total") if game_odds else None

        # Get weather for this venue
        wx = _match_weather(weather_by_venue, venue_name)
        temp = wx.get("temperature") if wx else None
        wind = wx.get("wind_speed") if wx else None

        # ── Project Pitchers ─────────────────────────────────────────

        for pitcher_key, team_abbr, opp_implied, own_implied in [
            ("home_pitcher_id", home_abbr, away_implied, home_implied),
            ("away_pitcher_id", away_abbr, home_implied, away_implied),
        ]:
            pitcher_mlb_id = game.get(pitcher_key)
            pitcher_name = game.get(pitcher_key.replace("_id", "_name"), "Unknown")
            if not pitcher_mlb_id:
                continue

            # Look up salary from draftables
            salary = _find_salary(draftables_by_name, pitcher_name)

            try:
                proj = await build_pitcher_projection(
                    mlb_player_id=pitcher_mlb_id,
                    site=site,
                    season=season,
                    opp_implied_runs=opp_implied,
                    team_implied_runs=own_implied,
                    venue=venue_name,
                    home_team_abbr=home_abbr,
                    temperature=temp,
                    wind_speed=wind,
                    salary=salary,
                )
                proj_entry = {
                    "player_name": pitcher_name,
                    "mlb_id": pitcher_mlb_id,
                    "team": team_abbr,
                    "position": "SP",
                    "opp_team": away_abbr if team_abbr == home_abbr else home_abbr,
                    "game_pk": game_pk,
                    "venue": venue_name,
                    "salary": salary,
                    "batting_order": None,
                    "is_pitcher": True,
                    "is_confirmed": True,  # Probable pitchers are always "confirmed"
                    "floor_pts": proj["floor_pts"],
                    "median_pts": proj["median_pts"],
                    "ceiling_pts": proj["ceiling_pts"],
                    "projected_ownership": None,
                    "season_era": proj.get("season_era"),
                    "season_k9": proj.get("season_k9"),
                    "ip_per_gs": proj.get("ip_per_gs"),
                    "games_in_log": proj.get("games_in_log", 0),
                    "implied_total": total,
                    "team_implied": own_implied,
                    "opp_implied": opp_implied,
                    "temperature": temp,
                }
                all_projections.append(proj_entry)
                projection_count += 1
            except Exception as exc:
                logger.warning(
                    "Pitcher projection failed for %s (%d): %s",
                    pitcher_name, pitcher_mlb_id, exc,
                )
                error_count += 1

        # ── Get opposing pitcher info for hitter matchups ────────────

        home_pitcher_id = game.get("home_pitcher_id")
        away_pitcher_id = game.get("away_pitcher_id")

        # Use pitcher hand from schedule hydration first, then fall back
        home_pitcher_hand = game.get("home_pitcher_hand")
        home_pitcher_k9: Optional[float] = None
        away_pitcher_hand = game.get("away_pitcher_hand")
        away_pitcher_k9: Optional[float] = None

        for pid, label in [
            (home_pitcher_id, "home"),
            (away_pitcher_id, "away"),
        ]:
            if pid:
                try:
                    # Fetch hand if not from schedule
                    current_hand = home_pitcher_hand if label == "home" else away_pitcher_hand
                    if not current_hand:
                        info = await mlb_stats.get_player_info(pid)
                        hand = info.get("pitchHand", {}).get("code", "R")
                        if label == "home":
                            home_pitcher_hand = hand
                        else:
                            away_pitcher_hand = hand

                    # Get K/9 from season stats
                    p_stats_raw = await mlb_stats.get_player_season_stats(
                        pid, season=season, group="pitching"
                    )
                    for sb in p_stats_raw.get("stats", []):
                        for sp in sb.get("splits", []):
                            k9 = sp.get("stat", {}).get("strikeoutsPer9Inn")
                            if k9 is not None:
                                if label == "home":
                                    home_pitcher_k9 = float(k9)
                                else:
                                    away_pitcher_k9 = float(k9)
                            break
                except Exception:
                    pass

        # ── Project Hitters ──────────────────────────────────────────

        # Collect hitters from confirmed lineups or draftables
        hitters_to_project: List[Dict[str, Any]] = []

        # If lineups are confirmed, use those
        for side, lineup_key, team_abbr, implied, opp_p_hand, opp_p_k9 in [
            ("home", "home_lineup", home_abbr, home_implied,
             away_pitcher_hand, away_pitcher_k9),
            ("away", "away_lineup", away_abbr, away_implied,
             home_pitcher_hand, home_pitcher_k9),
        ]:
            lineup_ids = game.get(lineup_key, [])
            if lineup_ids:
                for order_idx, player_mlb_id in enumerate(lineup_ids, 1):
                    if not player_mlb_id:
                        continue
                    hitters_to_project.append({
                        "mlb_id": player_mlb_id,
                        "team": team_abbr,
                        "batting_order": order_idx,
                        "implied_runs": implied,
                        "opp_pitcher_hand": opp_p_hand,
                        "opp_pitcher_k9": opp_p_k9,
                        "is_confirmed": True,
                        "side": side,
                    })

        # Also add draftable hitters from this game who aren't in lineups
        for dname, dr in draftables_by_name.items():
            dr_team = normalise_dk_team(dr.get("teamAbbreviation", ""))
            if dr_team not in (home_abbr, away_abbr):
                continue
            pos = dr.get("position", "")
            if pos in ("SP", "RP", "P"):
                continue

            # Try to find MLB ID: first from DK data, then from roster lookup
            dr_mlb_id = _extract_mlb_id_from_draftable(dr)
            if not dr_mlb_id:
                # Match by name against MLB roster lookup
                dr_mlb_id = _resolve_mlb_id(
                    dname, mlb_name_lookup
                )
            if not dr_mlb_id:
                # Still can't match -- skip silently (common for bench players)
                continue

            # Check if already in lineups
            already_added = any(
                h["mlb_id"] == dr_mlb_id for h in hitters_to_project
            )
            if already_added:
                continue

            # This player is on the slate but not in a confirmed lineup
            if dr_team == home_abbr:
                implied = home_implied
                opp_p_hand_val = away_pitcher_hand
                opp_p_k9_val = away_pitcher_k9
            else:
                implied = away_implied
                opp_p_hand_val = home_pitcher_hand
                opp_p_k9_val = home_pitcher_k9

            hitters_to_project.append({
                "mlb_id": dr_mlb_id,
                "team": dr_team,
                "batting_order": None,
                "implied_runs": implied,
                "opp_pitcher_hand": opp_p_hand_val,
                "opp_pitcher_k9": opp_p_k9_val,
                "is_confirmed": False,
                "side": "home" if dr_team == home_abbr else "away",
                "dk_name": dr.get("displayName", ""),
                "dk_salary": dr.get("salary"),
                "dk_position": pos,
            })

        # Generate projections for each hitter
        for hitter in hitters_to_project:
            h_mlb_id = hitter["mlb_id"]
            h_team = hitter["team"]
            h_order = hitter.get("batting_order")
            h_implied = hitter.get("implied_runs")
            h_opp_hand = hitter.get("opp_pitcher_hand")
            h_opp_k9 = hitter.get("opp_pitcher_k9")
            h_confirmed = hitter.get("is_confirmed", False)

            # Try to get player name and info
            player_name = hitter.get("dk_name", "")
            batter_hand = None
            salary = hitter.get("dk_salary")

            if not player_name:
                try:
                    info = await mlb_stats.get_player_info(h_mlb_id)
                    player_name = info.get("fullName", f"Player-{h_mlb_id}")
                    batter_hand = info.get("batSide", {}).get("code")
                except Exception:
                    player_name = f"Player-{h_mlb_id}"

            # Look up salary if not from draftable
            if salary is None:
                salary = _find_salary(draftables_by_name, player_name)

            opp_team = away_abbr if h_team == home_abbr else home_abbr

            try:
                proj = await build_hitter_projection(
                    mlb_player_id=h_mlb_id,
                    site=site,
                    season=season,
                    batting_order=h_order,
                    implied_runs=h_implied,
                    opp_pitcher_k9=h_opp_k9,
                    opp_pitcher_hand=h_opp_hand,
                    batter_hand=batter_hand,
                    venue=venue_name,
                    home_team_abbr=home_abbr,
                    temperature=temp,
                    wind_speed=wind,
                    salary=salary,
                )

                position = hitter.get("dk_position", "UTIL")

                proj_entry = {
                    "player_name": player_name,
                    "mlb_id": h_mlb_id,
                    "team": h_team,
                    "position": position,
                    "opp_team": opp_team,
                    "game_pk": game_pk,
                    "venue": venue_name,
                    "salary": salary,
                    "batting_order": h_order,
                    "is_pitcher": False,
                    "is_confirmed": h_confirmed,
                    "floor_pts": proj["floor_pts"],
                    "median_pts": proj["median_pts"],
                    "ceiling_pts": proj["ceiling_pts"],
                    "projected_ownership": None,
                    "season_avg": proj.get("season_avg"),
                    "season_ops": proj.get("season_ops"),
                    "games_in_log": proj.get("games_in_log", 0),
                    "implied_total": total,
                    "team_implied": h_implied,
                    "opp_implied": None,
                    "temperature": temp,
                }
                all_projections.append(proj_entry)
                projection_count += 1
            except Exception as exc:
                logger.debug(
                    "Hitter projection failed for %s (%d): %s",
                    player_name, h_mlb_id, exc,
                )
                error_count += 1

    steps.append(
        PipelineStepResult(
            "generate-projections", True,
            f"Generated {projection_count} projections ({error_count} errors)",
            projection_count,
        ).to_dict()
    )

    # ── Step 7: Build summary ────────────────────────────────────────────

    pitchers = [p for p in all_projections if p["is_pitcher"]]
    hitters = [p for p in all_projections if not p["is_pitcher"]]
    confirmed = [p for p in all_projections if p["is_confirmed"]]

    # Sort by median for top picks
    pitchers_sorted = sorted(pitchers, key=lambda x: x["median_pts"], reverse=True)
    hitters_sorted = sorted(hitters, key=lambda x: x["median_pts"], reverse=True)

    summary = {
        "date": target_date,
        "site": site,
        "total_games": len(games),
        "total_projections": projection_count,
        "total_pitchers": len(pitchers),
        "total_hitters": len(hitters),
        "confirmed_lineups": confirmed_count,
        "projected_lineups": projected_count,
        "confirmed_players": len(confirmed),
        "slates_found": len(slates),
        "featured_slate": (
            {
                "name": featured_slate["name"],
                "draft_group_id": featured_slate["draft_group_id"],
                "game_count": featured_slate["game_count"],
            }
            if featured_slate
            else None
        ),
        "top_5_pitchers": [
            {
                "name": p["player_name"],
                "team": p["team"],
                "salary": p.get("salary"),
                "median": p["median_pts"],
                "ceiling": p["ceiling_pts"],
                "era": p.get("season_era"),
                "k9": p.get("season_k9"),
            }
            for p in pitchers_sorted[:5]
        ],
        "top_10_hitters": [
            {
                "name": p["player_name"],
                "team": p["team"],
                "position": p["position"],
                "salary": p.get("salary"),
                "order": p.get("batting_order"),
                "median": p["median_pts"],
                "ceiling": p["ceiling_pts"],
                "confirmed": p["is_confirmed"],
            }
            for p in hitters_sorted[:10]
        ],
        "errors": error_count,
    }

    logger.info(
        "Pipeline complete: %d games, %d projections (%d P, %d H), %d errors",
        len(games), projection_count, len(pitchers), len(hitters), error_count,
    )

    return {
        "steps": steps,
        "games": [
            {
                "game_pk": g["game_pk"],
                "home": g["home_team_abbr"],
                "away": g["away_team_abbr"],
                "venue": g["venue"],
                "home_pitcher": g.get("home_pitcher_name"),
                "away_pitcher": g.get("away_pitcher_name"),
                "lineup_status": g.get("lineup_status", "unknown"),
            }
            for g in games
        ],
        "slates": [
            {
                "slate_id": s["slate_id"],
                "name": s["name"],
                "game_count": s["game_count"],
                "game_type": s["game_type"],
            }
            for s in slates
        ],
        "projections": all_projections,
        "summary": summary,
    }


# ── Helpers ──────────────────────────────────────────────────────────────────

# Map of common MLB team full names to abbreviations for vegas matching
_TEAM_NAME_TO_ABBR: Dict[str, str] = {
    "arizona diamondbacks": "ARI", "diamondbacks": "ARI", "d-backs": "ARI",
    "atlanta braves": "ATL", "braves": "ATL",
    "baltimore orioles": "BAL", "orioles": "BAL",
    "boston red sox": "BOS", "red sox": "BOS",
    "chicago cubs": "CHC", "cubs": "CHC",
    "chicago white sox": "CWS", "white sox": "CWS",
    "cincinnati reds": "CIN", "reds": "CIN",
    "cleveland guardians": "CLE", "guardians": "CLE",
    "colorado rockies": "COL", "rockies": "COL",
    "detroit tigers": "DET", "tigers": "DET",
    "houston astros": "HOU", "astros": "HOU",
    "kansas city royals": "KC", "royals": "KC",
    "los angeles angels": "LAA", "angels": "LAA",
    "los angeles dodgers": "LAD", "dodgers": "LAD",
    "miami marlins": "MIA", "marlins": "MIA",
    "milwaukee brewers": "MIL", "brewers": "MIL",
    "minnesota twins": "MIN", "twins": "MIN",
    "new york mets": "NYM", "mets": "NYM",
    "new york yankees": "NYY", "yankees": "NYY",
    "oakland athletics": "OAK", "athletics": "OAK", "a's": "OAK",
    "philadelphia phillies": "PHI", "phillies": "PHI",
    "pittsburgh pirates": "PIT", "pirates": "PIT",
    "san diego padres": "SD", "padres": "SD",
    "san francisco giants": "SF", "giants": "SF",
    "seattle mariners": "SEA", "mariners": "SEA",
    "st. louis cardinals": "STL", "cardinals": "STL",
    "tampa bay rays": "TB", "rays": "TB",
    "texas rangers": "TEX", "rangers": "TEX",
    "toronto blue jays": "TOR", "blue jays": "TOR",
    "washington nationals": "WSH", "nationals": "WSH",
}


def _match_odds_to_game(
    odds_by_home: Dict[str, Dict[str, Any]],
    home_abbr: str,
    away_abbr: str,
) -> Optional[Dict[str, Any]]:
    """Match Vegas odds to a game by team abbreviation."""
    # Try direct match first
    for key, odds in odds_by_home.items():
        # Resolve team names
        home_match = _name_matches_abbr(key, home_abbr)
        if home_match:
            return odds
    return None


def _name_matches_abbr(team_name: str, abbr: str) -> bool:
    """Check if a team full name matches an abbreviation."""
    name_lower = team_name.lower()
    resolved = _TEAM_NAME_TO_ABBR.get(name_lower)
    if resolved and resolved == abbr:
        return True
    # Also check if any partial match
    for full_name, ab in _TEAM_NAME_TO_ABBR.items():
        if ab == abbr and (full_name in name_lower or name_lower in full_name):
            return True
    return False


def _match_weather(
    weather_by_venue: Dict[str, Dict[str, Any]],
    venue_name: str,
) -> Optional[Dict[str, Any]]:
    """Match weather data to a venue."""
    if venue_name in weather_by_venue:
        return weather_by_venue[venue_name]
    venue_lower = venue_name.lower()
    for key, wx in weather_by_venue.items():
        if key.lower() in venue_lower or venue_lower in key.lower():
            return wx
    return None


def _find_salary(
    draftables_by_name: Dict[str, Dict[str, Any]],
    player_name: str,
) -> Optional[int]:
    """Look up a player's salary from the draftables index."""
    if not player_name:
        return None
    name_lower = player_name.lower().strip()
    dr = draftables_by_name.get(name_lower)
    if dr:
        return dr.get("salary")
    # Try partial match (last name)
    parts = name_lower.split()
    if len(parts) >= 2:
        last = parts[-1]
        for key, dr_val in draftables_by_name.items():
            if last in key:
                return dr_val.get("salary")
    return None


def _extract_mlb_id_from_draftable(dr: Dict[str, Any]) -> Optional[int]:
    """Try to extract an MLB Stats API player ID from a DK draftable.

    DK draftables have a ``playerAttributes`` or ``draftStatAttributes`` list
    that sometimes contains the MLB ID.  Otherwise we rely on name matching
    after the fact.
    """
    # Check draftStatAttributes for MLB player ID
    for attr in dr.get("draftStatAttributes", []):
        if attr.get("id") in (90, 91):  # MLB Stats API ID
            try:
                return int(attr.get("value"))
            except (ValueError, TypeError):
                pass
    # Also check competition -> competitionId as game_pk reference
    # But we need player ID not game ID, so return None if not found
    return None


def _resolve_mlb_id(
    dk_name: str,
    mlb_name_lookup: Dict[str, Dict[str, Any]],
) -> Optional[int]:
    """Resolve a DK player name to an MLB player ID via the roster lookup.

    Tries exact match first, then partial matches (last name).
    """
    if not dk_name:
        return None
    name_lower = dk_name.lower().strip()

    # Exact match
    if name_lower in mlb_name_lookup:
        return mlb_name_lookup[name_lower].get("mlb_id")

    # Partial match: last name + first initial
    parts = name_lower.split()
    if len(parts) >= 2:
        last_name = parts[-1]
        first_initial = parts[0][0] if parts[0] else ""
        candidates: List[Dict[str, Any]] = []
        for roster_name, info in mlb_name_lookup.items():
            roster_parts = roster_name.split()
            if len(roster_parts) >= 2:
                roster_last = roster_parts[-1]
                roster_first_init = roster_parts[0][0] if roster_parts[0] else ""
                if roster_last == last_name and roster_first_init == first_initial:
                    candidates.append(info)
        if len(candidates) == 1:
            return candidates[0].get("mlb_id")

    return None


# ── CLI entry point ──────────────────────────────────────────────────────────


async def _run_cli(target_date: str, site: str) -> None:
    """CLI-friendly wrapper that prints results."""
    import pprint

    result = await run_daily_pipeline(target_date, site)

    print("\n" + "=" * 70)
    print(f"  DAILY PIPELINE RESULTS: {target_date} ({site.upper()})")
    print("=" * 70)

    # Print steps
    print("\n-- Pipeline Steps --")
    for step in result.get("steps", []):
        status = "OK" if step["success"] else "FAIL"
        print(f"  [{status}] {step['step']}: {step['detail']}")

    # Print games
    games_list = result.get("games", [])
    print(f"\n-- Games ({len(games_list)}) --")
    for g in games_list:
        print(
            f"  {g['away']} @ {g['home']} | {g['venue']} | "
            f"Pitchers: {g.get('away_pitcher', 'TBD')} vs {g.get('home_pitcher', 'TBD')} | "
            f"Lineups: {g.get('lineup_status', '?')}"
        )

    # Print summary
    summary = result.get("summary", {})
    print(f"\n-- Summary --")
    print(f"  Total projections: {summary.get('total_projections', 0)}")
    print(f"  Pitchers: {summary.get('total_pitchers', 0)}")
    print(f"  Hitters: {summary.get('total_hitters', 0)}")
    print(f"  Confirmed players: {summary.get('confirmed_players', 0)}")

    fs = summary.get("featured_slate")
    if fs:
        print(f"  Featured slate: {fs['name']} (DG-{fs['draft_group_id']}, {fs['game_count']} games)")
    else:
        print("  Featured slate: None found")

    # Print top pitchers
    print("\n-- Top 5 Pitchers --")
    for i, p in enumerate(summary.get("top_5_pitchers", []), 1):
        sal_str = f"${p['salary']}" if p.get("salary") else "N/A"
        print(
            f"  {i}. {p['name']} ({p['team']}) | Salary: {sal_str} | "
            f"Median: {p['median']:.1f} | Ceiling: {p['ceiling']:.1f} | "
            f"ERA: {p.get('era', 'N/A')} | K/9: {p.get('k9', 'N/A')}"
        )

    # Print top hitters
    print("\n-- Top 10 Hitters --")
    for i, p in enumerate(summary.get("top_10_hitters", []), 1):
        sal_str = f"${p['salary']}" if p.get("salary") else "N/A"
        order_str = f"#{p['order']}" if p.get("order") else "N/A"
        conf_str = "Y" if p.get("confirmed") else "N"
        print(
            f"  {i}. {p['name']} ({p['team']}, {p['position']}) | "
            f"Salary: {sal_str} | Order: {order_str} | "
            f"Median: {p['median']:.1f} | Ceiling: {p['ceiling']:.1f} | "
            f"Confirmed: {conf_str}"
        )

    print(f"\n  Errors: {summary.get('errors', 0)}")
    print("=" * 70)
