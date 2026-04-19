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

_SALARY_DIRS = [
    Path(__file__).resolve().parent.parent / "dk-salaries",          # backend/dk-salaries (Docker)
    Path(__file__).resolve().parent.parent.parent / "dk salaries ",  # local dev (trailing space in folder name)
    Path(__file__).resolve().parent.parent.parent / "dk salaries",   # local dev (no trailing space)
    Path("/app/data/dk-salaries"),                                    # Fly.io volume
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

    # Convert to 24h for AM/PM label, then back to 12h for display
    if ampm == "pm" and hour != 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0
    display_hour = hour % 12 or 12
    time_str = f"{display_hour}:{minute} {'PM' if hour >= 12 else 'AM'} ET"

    return {
        "date": date_str,
        "time": time_str,
        "site": site,
        "slate_type": slate_type,
    }


def _slate_base_key(info: Dict[str, str]) -> str:
    """Extract a dedup key from parsed filename info, stripping v2/copy suffixes."""
    raw = info["slate_type"]
    base = re.sub(r"\s*\(\d+\)", "", raw)    # strip "(1)" copy markers
    base = re.sub(r"\s*v\d+$", "", base, flags=re.IGNORECASE)  # strip "v2"
    return f"{info['date']}_{info['time']}_{info['site']}_{base.strip()}"


def _is_v2(info: Dict[str, str]) -> bool:
    """Check if a parsed filename represents a v2/updated file."""
    return bool(re.search(r"v\d+", info["slate_type"], re.IGNORECASE))


def list_available_slates(
    target_date: Optional[date] = None,
    site: str = "dk",
) -> List[Dict[str, Any]]:
    """List available CSV-based slates for a given date.

    When both a base file and a v2 exist for the same slate, only the v2 is returned.
    """
    csv_dir = _find_csv_dir()
    if not csv_dir:
        return []

    # First pass: collect all candidates, keyed by base identity
    candidates: Dict[str, List[Tuple[Path, Dict[str, str]]]] = {}
    for csv_file in sorted(csv_dir.glob("*.csv")):
        info = _parse_filename(csv_file.name)
        if not info:
            continue
        if info["site"] != site:
            continue
        if target_date and info["date"] != target_date.isoformat():
            continue
        key = _slate_base_key(info)
        candidates.setdefault(key, []).append((csv_file, info))

    # Second pass: for each key, pick v2 over base
    slates: List[Dict[str, Any]] = []
    for key, entries in candidates.items():
        v2_entries = [(f, i) for f, i in entries if _is_v2(i)]
        chosen_file, chosen_info = v2_entries[-1] if v2_entries else entries[-1]

        teams = set()
        try:
            with open(chosen_file, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    team = row.get("Team", "").strip()
                    if team:
                        teams.add(team)
        except Exception:
            pass
        game_count = len(teams) // 2

        slate_type_lower = chosen_info["slate_type"].lower()
        game_type = "classic"
        if "showdown" in slate_type_lower or "captain" in slate_type_lower:
            game_type = "showdown"

        # Use clean display name (strip v2/copy suffixes)
        display_type = re.sub(r"\s*\(\d+\)", "", chosen_info["slate_type"])
        display_type = re.sub(r"\s*v\d+$", "", display_type, flags=re.IGNORECASE).strip()

        slate_id = chosen_file.stem
        slates.append({
            "slate_id": slate_id,
            "site": site,
            "draft_group_id": 0,
            "name": f"{display_type} ({chosen_info['time']})",
            "game_count": game_count,
            "start_time": f"{chosen_info['date']}T{chosen_info['time']}",
            "game_type": game_type,
            "games": [],
            "csv_path": str(chosen_file),
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
    Filters out:
      - Players with median projection < 0.25
      - Non-starting pitchers (relievers with projected IP < 3)
      - Players on the IL or marked Out
    """
    projections: List[Dict[str, Any]] = []
    try:
        with open(csv_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                proj = _parse_csv_row(row, site)
                if not proj:
                    continue

                # Filter: median >= 0.25
                if proj["median_pts"] < 0.25:
                    continue

                # Filter: skip IL and Out players
                status = row.get("Status", "").strip().upper()
                if status in ("IL", "O"):
                    continue

                # Ohtani dual-role: if listed as pitcher but low IP, reclassify as hitter
                if proj["is_pitcher"] and proj["player_name"] == "Shohei Ohtani":
                    ip = _safe_float(row.get("IP"), 0.0)
                    if ip is None or ip < 3.0:
                        proj["is_pitcher"] = False
                        proj["position"] = "OF"
                        proj["is_confirmed"] = proj["batting_order"] is not None
                        # Skip the pitcher filter below so he stays in the pool
                    # else: he is a starting pitcher, keep as-is

                # Filter pitchers: keep if starter (IP >= 3) OR (median > 3 pts AND ownership >= 1%)
                if proj["is_pitcher"]:
                    ip = _safe_float(row.get("IP"), 0.0)
                    ownership = proj.get("projected_ownership", 0) or 0
                    is_starter = ip is not None and ip >= 3.0
                    has_value = proj["median_pts"] >= 3.0 and ownership >= 1.0
                    if not is_starter and not has_value:
                        continue

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
    ip = _safe_float(row.get("IP"))  # used for starter detection

    # Projection points
    median_pts = _safe_float(row.get("dk_points")) or _safe_float(row.get("My Proj")) or 0.0
    floor_pts = _safe_float(row.get("dk_25_percentile")) or 0.0
    ceiling_pts = _safe_float(row.get("dk_75_percentile")) or 0.0

    # Ownership — keep 0 as meaningful (0% projected ownership)
    my_own = _safe_float(row.get("My Own"), 0.0)
    adj_own = _safe_float(row.get("Adj Own"), 0.0)
    ownership = adj_own if adj_own > 0 else my_own

    # Team implied total (Saber Team) and game total (Saber Total)
    saber_team = _safe_float(row.get("Saber Team"))
    saber_game_total = _safe_float(row.get("Saber Total"))

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
        "is_confirmed": (order is not None) if not is_pitcher else (ip is not None and ip >= 3.0),
        "floor_pts": floor_pts,
        "median_pts": median_pts,
        "ceiling_pts": ceiling_pts,
        "projected_ownership": ownership,
        "season_era": season_era,
        "season_k9": season_k9,
        "season_avg": season_avg,
        "season_ops": season_ops,
        "games_in_log": 0,
        "implied_total": saber_team,
        "team_implied": saber_team,
        "game_total": saber_game_total,
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


def _find_salary_dir() -> Optional[Path]:
    for d in _SALARY_DIRS:
        if d.exists() and any(d.glob("*.csv")):
            return d
    return None


def load_dk_salaries(
    target_date: Optional[date] = None,
    slate_name: str = "main",
) -> Dict[str, Dict[str, Any]]:
    """Load DK salary CSV and return a lookup: player_name -> {salary, dk_id, team, position, avg_pts}.

    The DK salary CSV has columns:
    Position, Name + ID, Name, ID, Roster Position, Salary, Game Info, TeamAbbrev, AvgPointsPerGame
    """
    sal_dir = _find_salary_dir()
    if not sal_dir:
        return {}

    d = target_date or date.today()
    date_str = d.isoformat().replace("-", "")

    # Find matching file — look for date and slate name in filename
    best_file = None
    for f in sorted(sal_dir.glob("*.csv"), key=lambda x: x.stat().st_mtime, reverse=True):
        fname_lower = f.name.lower()
        # Match by date fragments (e.g. "apr 17" or "04-17" or "0417")
        month_names = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
        month_name = month_names[d.month - 1]
        date_patterns = [
            f"{month_name} {d.day}",
            f"{d.month:02d}-{d.day:02d}",
            f"{d.month:02d}{d.day:02d}",
            date_str[4:],
        ]
        date_match = any(p in fname_lower for p in date_patterns)
        slate_match = slate_name.lower() in fname_lower
        if date_match and slate_match:
            best_file = f
            break
        if date_match and best_file is None:
            best_file = f

    if not best_file:
        logger.info("No DK salary CSV found for %s (%s)", d, slate_name)
        return {}

    result: Dict[str, Dict[str, Any]] = {}
    try:
        with open(best_file, "r", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                name = row.get("Name", "").strip()
                if not name:
                    continue
                salary = _safe_int(row.get("Salary"))
                dk_id = _safe_int(row.get("ID"))
                team = row.get("TeamAbbrev", "").strip()
                position = row.get("Position", "").strip()
                roster_pos = row.get("Roster Position", "").strip()
                avg_pts = _safe_float(row.get("AvgPointsPerGame"))
                if salary and salary > 0:
                    result[name] = {
                        "salary": salary,
                        "dk_id": dk_id,
                        "team": team,
                        "position": position,
                        "roster_position": roster_pos,
                        "avg_pts": avg_pts or 0.0,
                    }
    except Exception as exc:
        logger.error("Failed to load DK salary CSV %s: %s", best_file, exc)

    logger.info("Loaded %d DK salaries from %s", len(result), best_file.name)
    return result
