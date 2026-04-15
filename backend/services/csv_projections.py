"""CSV-based projection loader for SaberSim exports.

Reads projection CSVs from the data directory and serves them through the API.
Filenames follow the pattern: MLB_YYYY-MM-DD-HHMMam/pm_DK_Type.csv
Example: MLB_2026-04-15-705pm_DK_Main.csv
"""
from __future__ import annotations

import csv
import logging
import re
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Search paths for CSV files
_CSV_DIRS = [
    Path(__file__).resolve().parent.parent / "projections",          # backend/projections (Docker /app/projections)
    Path(__file__).resolve().parent.parent.parent / "projections by slate - dk",  # local dev
    Path("/app/data/projections"),                                    # Fly.io volume
]


def _find_csv_dir() -> Optional[Path]:
    """Find the directory containing projection CSVs."""
    for d in _CSV_DIRS:
        if d.exists() and any(d.glob("*.csv")):
            return d
    return None


def _parse_filename(filename: str) -> Optional[Dict[str, str]]:
    """Parse slate info from a CSV filename.

    Pattern: MLB_YYYY-MM-DD-HHMMam/pm_DK_Type.csv
    Returns dict with keys: date, time, site, slate_type
    """
    m = re.match(
        r"MLB_(\d{4}-\d{2}-\d{2})-(\d{1,2})(\d{2})(am|pm)_([A-Z]+)_(.+)\.csv",
        filename,
        re.IGNORECASE,
    )
    if not m:
        return None
    date_str = m.group(1)
    hour = int(m.group(2))
    minute = m.group(3)
    ampm = m.group(4).lower()
    site = m.group(5).lower()
    slate_type = m.group(6)

    # Convert to 24h
    if ampm == "pm" and hour != 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0
    time_str = f"{hour}:{minute} {'PM' if hour >= 12 else 'AM'} ET"

    return {
        "date": date_str,
        "time": time_str,
        "site": site,
        "slate_type": slate_type,
    }


def list_available_slates(
    target_date: Optional[date] = None,
    site: str = "dk",
) -> List[Dict[str, Any]]:
    """List available CSV-based slates for a given date.

    Returns a list of slate dicts compatible with the API schema.
    """
    csv_dir = _find_csv_dir()
    if not csv_dir:
        return []

    slates: List[Dict[str, Any]] = []
    for csv_file in sorted(csv_dir.glob("*.csv")):
        info = _parse_filename(csv_file.name)
        if not info:
            continue
        if info["site"] != site:
            continue
        if target_date and info["date"] != target_date.isoformat():
            continue

        # Count unique teams to estimate game count
        teams = set()
        try:
            with open(csv_file, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    team = row.get("Team", "").strip()
                    if team:
                        teams.add(team)
        except Exception:
            pass
        game_count = len(teams) // 2

        # Determine game type
        slate_type_lower = info["slate_type"].lower()
        game_type = "classic"
        if "showdown" in slate_type_lower or "captain" in slate_type_lower:
            game_type = "showdown"

        slate_id = csv_file.stem  # filename without extension
        slates.append({
            "slate_id": slate_id,
            "site": site,
            "draft_group_id": 0,
            "name": f"{info['slate_type']} ({info['time']})",
            "game_count": game_count,
            "start_time": f"{info['date']}T{info['time']}",
            "game_type": game_type,
            "games": [],
            "csv_path": str(csv_file),
        })

    return slates


def identify_featured_csv_slate(
    slates: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Pick the main/featured slate from CSV-based slates."""
    if not slates:
        return None
    classic = [s for s in slates if s["game_type"] == "classic"]
    if not classic:
        classic = slates
    for s in classic:
        name_lower = s["name"].lower()
        if "main" in name_lower:
            return s
    # Fallback: most games
    return max(classic, key=lambda s: s["game_count"])


def load_csv_projections(
    csv_path: str,
    site: str = "dk",
) -> List[Dict[str, Any]]:
    """Load projections from a SaberSim CSV export.

    Maps CSV columns to the SlateProjectionOut-compatible format.
    """
    projections: List[Dict[str, Any]] = []
    try:
        with open(csv_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                proj = _parse_csv_row(row, site)
                if proj:
                    projections.append(proj)
    except Exception as exc:
        logger.error("Failed to load CSV projections from %s: %s", csv_path, exc)

    logger.info("Loaded %d projections from %s", len(projections), csv_path)
    return projections


def _parse_csv_row(row: Dict[str, str], site: str) -> Optional[Dict[str, Any]]:
    """Parse a single CSV row into a projection dict."""
    name = row.get("Name", "").strip()
    if not name:
        return None

    pos = row.get("Pos", "UTIL").strip()
    team = row.get("Team", "").strip()
    opp = row.get("Opp", "").strip()
    salary = _safe_int(row.get("Salary"))
    order = _safe_int(row.get("Order"))
    dfs_id = _safe_int(row.get("DFS ID"))

    is_pitcher = pos in ("P", "SP", "RP")

    # Projection points
    median_pts = _safe_float(row.get("dk_points")) or _safe_float(row.get("My Proj")) or 0.0
    floor_pts = _safe_float(row.get("dk_25_percentile")) or 0.0
    ceiling_pts = _safe_float(row.get("dk_75_percentile")) or 0.0

    # Ownership — keep 0 as meaningful (0% projected ownership)
    my_own = _safe_float(row.get("My Own"), 0.0)
    adj_own = _safe_float(row.get("Adj Own"), 0.0)
    ownership = adj_own if adj_own > 0 else my_own

    # Team implied total
    saber_total = _safe_float(row.get("Saber Total"))

    # Standard deviation
    dk_std = _safe_float(row.get("dk_std"))

    # Additional percentiles for simulation
    p85 = _safe_float(row.get("dk_85_percentile"))
    p95 = _safe_float(row.get("dk_95_percentile"))

    # Season stats from stat projections
    season_era = None
    season_k9 = None
    season_avg = None
    season_ops = None

    if is_pitcher:
        ip = _safe_float(row.get("IP"))
        er = _safe_float(row.get("ER"))
        k = _safe_float(row.get("K"))
        if ip and ip > 0:
            season_era = round((er / ip) * 9, 2) if er else None
            season_k9 = round((k / ip) * 9, 1) if k else None
    else:
        h = _safe_float(row.get("H"))
        pa = _safe_float(row.get("PA"))
        bb = _safe_float(row.get("BB"))
        hr = _safe_float(row.get("HR"))
        doubles = _safe_float(row.get("2B"))
        singles = _safe_float(row.get("1B"))
        if pa and pa > 0:
            ab = pa - (bb or 0)
            season_avg = round(h / ab, 3) if h and ab > 0 else None
            obp = (h + (bb or 0)) / pa if h else None
            slg = ((singles or 0) + 2 * (doubles or 0) + 3 * _safe_float(row.get("3B"), 0) + 4 * (hr or 0)) / ab if ab > 0 else None
            season_ops = round(obp + slg, 3) if obp and slg else None

    return {
        "player_name": name,
        "mlb_id": None,
        "dk_id": dfs_id,
        "team": team,
        "position": pos,
        "opp_team": opp,
        "game_pk": None,
        "venue": None,
        "salary": salary,
        "batting_order": order,
        "is_pitcher": is_pitcher,
        "is_confirmed": order is not None if not is_pitcher else True,
        "floor_pts": floor_pts,
        "median_pts": median_pts,
        "ceiling_pts": ceiling_pts,
        "projected_ownership": ownership,
        "season_era": season_era,
        "season_k9": season_k9,
        "season_avg": season_avg,
        "season_ops": season_ops,
        "games_in_log": 0,
        "implied_total": saber_total,
        "team_implied": saber_total,
        "temperature": None,
        # Extra fields for simulation
        "dk_std": dk_std,
        "p85": p85,
        "p95": p95,
        "min_exposure": _safe_float(row.get("Min Exp")),
        "max_exposure": _safe_float(row.get("Max Exp")),
        "value": _safe_float(row.get("Value")),
    }


def _safe_float(val: Optional[str], default: Optional[float] = None) -> Optional[float]:
    """Safely convert a string to float."""
    if val is None or val == "":
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _safe_int(val: Optional[str]) -> Optional[int]:
    """Safely convert a string to int."""
    if val is None or val == "":
        return None
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return None
