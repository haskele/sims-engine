"""Contest results analysis — stacking trends, ownership, field structure, sharp tracking.

Parses DraftKings contest-standings CSVs and produces structured analysis:
1. Player ownership distributions (actual vs. projected)
2. Stacking patterns (team stacks by size, correlation with placement)
3. Field structure (multi-entry users, max entries, user tiers)
4. Lineup construction tendencies (salary usage, position allocation)
5. Top performer / sharp user analysis for strategy extraction
6. Prematch lineup confirmation context per slate

Output feeds the simulation engine's lineup sampling model and optimizer tuning.
"""
from __future__ import annotations

import csv
import json
import re
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


POSITION_PATTERN = re.compile(
    r"(1B|2B|3B|SS|OF|C|P)\s+(.+?)(?=\s+(?:1B|2B|3B|SS|OF|C|P)\s|$)"
)

ROOT = Path(__file__).resolve().parent.parent.parent
PROJ_DIR = ROOT / "backend" / "projections"
SALARY_DIR = ROOT / "dk salaries "
CONTEST_DIR = ROOT / "contest results downloads" / "extracted"


# --------------------------------------------------------------------------
# Data structures
# --------------------------------------------------------------------------

@dataclass
class ParsedEntry:
    rank: int
    entry_id: str
    username: str
    entry_num: Optional[int]
    max_entries: Optional[int]
    points: float
    roster: Dict[str, str]  # slot (P1, C, 1B, 2B, 3B, SS, OF1, OF2, OF3) -> player
    players: List[str]


@dataclass
class SlateContext:
    """Prematch context for a given slate: teams, confirmed lineups, projections."""
    date: str
    slate_name: str
    proj_file: str
    teams: List[str]
    player_teams: Dict[str, str]  # player_name -> team
    player_opps: Dict[str, str]  # player_name -> opponent team
    confirmed_lineups: Dict[str, List[str]]  # team -> [player1, player2, ...] in order
    player_salaries: Dict[str, int]
    player_projections: Dict[str, float]  # player_name -> median projection
    player_positions: Dict[str, str]


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------

def parse_entry_name(name: str) -> Tuple[str, Optional[int], Optional[int]]:
    match = re.match(r"^(.+?)\s*\((\d+)/(\d+)\)$", name)
    if match:
        return match.group(1).strip(), int(match.group(2)), int(match.group(3))
    return name.strip(), None, None


def parse_lineup_string(lineup_str: str) -> Tuple[Dict[str, str], List[str]]:
    """Parse DK lineup string into roster dict and player list."""
    roster = {}
    players = []
    matches = POSITION_PATTERN.findall(lineup_str)
    pos_counts = Counter()
    for pos, player in matches:
        pos_counts[pos] += 1
        key = f"{pos}{pos_counts[pos]}" if pos_counts[pos] > 1 else pos
        name = player.strip()
        roster[key] = name
        players.append(name)
    return roster, players


def parse_contest_csv(filepath: str) -> List[ParsedEntry]:
    entries = []
    with open(filepath, encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        next(reader)  # skip headers
        for row in reader:
            if len(row) < 6 or not row[0].strip():
                continue
            try:
                rank = int(row[0])
            except ValueError:
                continue
            roster, players = parse_lineup_string(row[5])
            username, entry_num, max_entries = parse_entry_name(row[2])
            entries.append(ParsedEntry(
                rank=rank,
                entry_id=row[1],
                username=username,
                entry_num=entry_num,
                max_entries=max_entries,
                points=float(row[4]) if row[4] else 0.0,
                roster=roster,
                players=players,
            ))
    return entries


# --------------------------------------------------------------------------
# Slate context loading
# --------------------------------------------------------------------------

def load_slate_context(proj_file: str) -> SlateContext:
    """Load full prematch context from a projection CSV."""
    filepath = PROJ_DIR / proj_file
    player_teams = {}
    player_opps = {}
    confirmed: Dict[str, List[str]] = defaultdict(list)
    salaries = {}
    projections = {}
    positions = {}
    teams_set = set()

    with open(filepath) as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row.get("Name", "").strip()
            team = row.get("Team", "").strip()
            opp = row.get("Opp", "").strip()
            order = row.get("Order", "").strip()
            salary = int(row.get("Salary", 0) or 0)
            proj = float(row.get("My Proj", 0) or row.get("SS Proj", 0) or 0)
            pos = row.get("Pos", "").strip()

            if not name:
                continue

            player_teams[name] = team
            player_opps[name] = opp
            salaries[name] = salary
            projections[name] = proj
            positions[name] = pos
            teams_set.add(team)

            if order:
                try:
                    order_num = int(order)
                    confirmed[team].append((order_num, name))
                except ValueError:
                    confirmed[team].append((99, name))

    # Sort confirmed lineups by batting order
    confirmed_sorted = {}
    for team, players in confirmed.items():
        confirmed_sorted[team] = [p[1] for p in sorted(players, key=lambda x: x[0])]

    # Extract date and slate name from filename
    # e.g., "MLB_2026-04-15-705pm_DK_Main.csv"
    date_match = re.search(r"(\d{4}-\d{2}-\d{2})", proj_file)
    date_str = date_match.group(1) if date_match else ""

    return SlateContext(
        date=date_str,
        slate_name=proj_file.replace(".csv", ""),
        proj_file=proj_file,
        teams=sorted(teams_set),
        player_teams=player_teams,
        player_opps=player_opps,
        confirmed_lineups=confirmed_sorted,
        player_salaries=salaries,
        player_projections=projections,
        player_positions=positions,
    )


def match_contest_to_slate(entries: List[ParsedEntry]) -> Optional[str]:
    """Find the best matching projection file for a contest."""
    contest_players = set()
    for e in entries:
        contest_players.update(e.players)

    best_file = None
    best_overlap = 0

    for pfile in PROJ_DIR.glob("*.csv"):
        with open(pfile) as f:
            reader = csv.DictReader(f)
            file_players = {row.get("Name", "") for row in reader if row.get("Name")}

        overlap = len(contest_players & file_players)
        if overlap > best_overlap:
            best_overlap = overlap
            best_file = pfile.name

    return best_file


# --------------------------------------------------------------------------
# Stacking analysis
# --------------------------------------------------------------------------

def identify_stacks(entry: ParsedEntry, player_teams: Dict[str, str]) -> List[Dict[str, Any]]:
    """Identify team stacks in a lineup. Returns stacks of 2+ same-team hitters."""
    team_hitters: Dict[str, List[str]] = defaultdict(list)

    for slot, player in entry.roster.items():
        # Pitchers don't count toward hitter stacks
        if slot.startswith("P"):
            continue
        team = player_teams.get(player, "")
        if team:
            team_hitters[team].append(player)

    stacks = []
    for team, hitters in team_hitters.items():
        if len(hitters) >= 2:
            stacks.append({"team": team, "size": len(hitters), "players": hitters})

    return sorted(stacks, key=lambda s: s["size"], reverse=True)


def analyze_stacking(
    entries: List[ParsedEntry], player_teams: Dict[str, str]
) -> Dict[str, Any]:
    """Full stacking analysis across all entries."""
    stack_size_counts = Counter()
    primary_stack_sizes = Counter()  # largest stack per lineup
    team_stack_freq: Dict[str, Counter] = defaultdict(Counter)
    stack_by_rank: Dict[int, List[int]] = defaultdict(list)  # size -> [ranks]

    lineup_stacks = []
    bring_back_count = 0  # lineups with hitter from opposing pitcher's team

    for entry in entries:
        stacks = identify_stacks(entry, player_teams)
        primary_size = max((s["size"] for s in stacks), default=0)
        primary_stack_sizes[primary_size] += 1

        for stack in stacks:
            stack_size_counts[stack["size"]] += 1
            team_stack_freq[stack["team"]][stack["size"]] += 1
            stack_by_rank[stack["size"]].append(entry.rank)

        # Bring-back detection: hitter from opposing pitcher's team
        pitchers = [p for slot, p in entry.roster.items() if slot.startswith("P")]
        pitcher_opps = set()
        for p in pitchers:
            opp_team = ""
            for slot, player in entry.roster.items():
                if player == p:
                    continue
            # Actually need player_opps for this
            pass

        lineup_stacks.append({
            "rank": entry.rank,
            "primary_stack": primary_size,
            "stacks": stacks,
        })

    # Performance by primary stack size
    perf_by_stack = {}
    for size, count in primary_stack_sizes.most_common():
        ranks = [ls["rank"] for ls in lineup_stacks if ls["primary_stack"] == size]
        perf_by_stack[size] = {
            "count": count,
            "pct_of_field": round(count / len(entries) * 100, 1),
            "avg_rank": round(sum(ranks) / len(ranks), 1) if ranks else 0,
            "avg_percentile": round(
                sum(1 - r / len(entries) for r in ranks) / len(ranks) * 100, 1
            ) if ranks else 0,
        }

    # Most popular stacking teams
    popular_stacks = []
    for team, sizes in sorted(team_stack_freq.items(), key=lambda x: sum(x[1].values()), reverse=True)[:10]:
        total = sum(sizes.values())
        popular_stacks.append({
            "team": team,
            "total_stacks": total,
            "pct_of_lineups": round(total / len(entries) * 100, 1),
            "by_size": dict(sizes),
        })

    return {
        "primary_stack_distribution": perf_by_stack,
        "popular_stacking_teams": popular_stacks,
        "total_stacks_found": sum(stack_size_counts.values()),
        "avg_stacks_per_lineup": round(sum(stack_size_counts.values()) / len(entries), 2),
    }


# --------------------------------------------------------------------------
# Bring-back analysis
# --------------------------------------------------------------------------

def analyze_bring_backs(
    entries: List[ParsedEntry],
    player_teams: Dict[str, str],
    player_opps: Dict[str, str],
) -> Dict[str, Any]:
    """Analyze how often users bring back hitters from opposing pitcher's team."""
    bring_back_count = 0
    bring_back_by_rank: List[int] = []
    no_bring_back_by_rank: List[int] = []

    for entry in entries:
        pitchers = [p for slot, p in entry.roster.items() if slot.startswith("P")]
        hitters = {p for slot, p in entry.roster.items() if not slot.startswith("P")}

        # For each pitcher, check if any hitter is on the opposing team
        has_bring_back = False
        for pitcher in pitchers:
            pitcher_team = player_teams.get(pitcher, "")
            pitcher_opp = player_opps.get(pitcher, "")
            if not pitcher_opp:
                continue
            for hitter in hitters:
                hitter_team = player_teams.get(hitter, "")
                if hitter_team == pitcher_opp:
                    has_bring_back = True
                    break
            if has_bring_back:
                break

        if has_bring_back:
            bring_back_count += 1
            bring_back_by_rank.append(entry.rank)
        else:
            no_bring_back_by_rank.append(entry.rank)

    return {
        "bring_back_pct": round(bring_back_count / len(entries) * 100, 1) if entries else 0,
        "bring_back_avg_rank": round(sum(bring_back_by_rank) / len(bring_back_by_rank), 1) if bring_back_by_rank else 0,
        "no_bring_back_avg_rank": round(sum(no_bring_back_by_rank) / len(no_bring_back_by_rank), 1) if no_bring_back_by_rank else 0,
        "bring_back_count": bring_back_count,
        "no_bring_back_count": len(entries) - bring_back_count,
    }


# --------------------------------------------------------------------------
# Top performer / sharp user analysis
# --------------------------------------------------------------------------

def analyze_top_performers(
    entries: List[ParsedEntry],
    player_teams: Dict[str, str],
    slate: Optional[SlateContext] = None,
    top_pct: float = 5.0,
) -> Dict[str, Any]:
    """Analyze strategies of top-performing lineups and users.

    Identifies patterns that separate winners from the field:
    - Stack preferences
    - Salary allocation
    - Leverage (ownership differentials)
    - Correlation strategies
    """
    n_top = max(1, int(len(entries) * top_pct / 100))
    top_entries = entries[:n_top]  # already sorted by rank
    field_entries = entries

    # --- Ownership leverage (top vs field) ---
    field_ownership = Counter()
    top_ownership = Counter()

    for e in field_entries:
        field_ownership.update(e.players)
    for e in top_entries:
        top_ownership.update(e.players)

    leverage = []
    for player, top_count in top_ownership.most_common():
        field_count = field_ownership[player]
        top_pct_val = top_count / len(top_entries) * 100
        field_pct_val = field_count / len(field_entries) * 100
        diff = top_pct_val - field_pct_val
        leverage.append({
            "player": player,
            "top_ownership": round(top_pct_val, 1),
            "field_ownership": round(field_pct_val, 1),
            "leverage": round(diff, 1),
            "team": player_teams.get(player, ""),
        })

    leverage.sort(key=lambda x: x["leverage"], reverse=True)

    # --- Stack patterns in top lineups ---
    top_stacks = Counter()
    field_stacks = Counter()
    for e in top_entries:
        stacks = identify_stacks(e, player_teams)
        primary = max((s["size"] for s in stacks), default=0)
        top_stacks[primary] += 1
    for e in field_entries:
        stacks = identify_stacks(e, player_teams)
        primary = max((s["size"] for s in stacks), default=0)
        field_stacks[primary] += 1

    stack_comparison = {}
    for size in sorted(set(list(top_stacks.keys()) + list(field_stacks.keys()))):
        top_rate = top_stacks.get(size, 0) / len(top_entries) * 100 if top_entries else 0
        field_rate = field_stacks.get(size, 0) / len(field_entries) * 100 if field_entries else 0
        stack_comparison[size] = {
            "top_pct": round(top_rate, 1),
            "field_pct": round(field_rate, 1),
            "edge": round(top_rate - field_rate, 1),
        }

    # --- Salary usage in top lineups ---
    top_salaries = []
    field_salaries = []
    if slate:
        for e in top_entries:
            total_sal = sum(slate.player_salaries.get(p, 0) for p in e.players)
            top_salaries.append(total_sal)
        for e in field_entries:
            total_sal = sum(slate.player_salaries.get(p, 0) for p in e.players)
            field_salaries.append(total_sal)

    salary_analysis = {}
    if top_salaries and field_salaries:
        salary_analysis = {
            "top_avg_salary": round(statistics.mean(top_salaries)),
            "field_avg_salary": round(statistics.mean(field_salaries)),
            "top_salary_range": [min(top_salaries), max(top_salaries)],
        }

    # --- Confirmed lineup adherence ---
    confirmed_adherence = {}
    if slate and slate.confirmed_lineups:
        confirmed_players = set()
        for team, lineup in slate.confirmed_lineups.items():
            confirmed_players.update(lineup)

        top_confirmed_pct = []
        field_confirmed_pct = []
        for e in top_entries:
            hitters = [p for slot, p in e.roster.items() if not slot.startswith("P")]
            confirmed_count = sum(1 for p in hitters if p in confirmed_players)
            top_confirmed_pct.append(confirmed_count / len(hitters) * 100 if hitters else 0)
        for e in field_entries:
            hitters = [p for slot, p in e.roster.items() if not slot.startswith("P")]
            confirmed_count = sum(1 for p in hitters if p in confirmed_players)
            field_confirmed_pct.append(confirmed_count / len(hitters) * 100 if hitters else 0)

        confirmed_adherence = {
            "top_avg_confirmed_pct": round(statistics.mean(top_confirmed_pct), 1) if top_confirmed_pct else 0,
            "field_avg_confirmed_pct": round(statistics.mean(field_confirmed_pct), 1) if field_confirmed_pct else 0,
        }

    return {
        "top_n": n_top,
        "top_pct_threshold": top_pct,
        "leverage_players": leverage[:20],
        "underleverage_players": sorted(leverage, key=lambda x: x["leverage"])[:10],
        "stack_comparison": stack_comparison,
        "salary_analysis": salary_analysis,
        "confirmed_lineup_adherence": confirmed_adherence,
    }


def analyze_sharp_users(
    entries: List[ParsedEntry],
    player_teams: Dict[str, str],
    min_entries: int = 3,
) -> Dict[str, Any]:
    """Identify sharp/winning users and analyze their strategies.

    Sharp indicators: high avg percentile, consistent cashing, diverse builds.
    """
    user_entries: Dict[str, List[ParsedEntry]] = defaultdict(list)
    for e in entries:
        user_entries[e.username].append(e)

    total_entries = len(entries)
    user_stats = []

    for username, user_es in user_entries.items():
        if len(user_es) < min_entries:
            continue

        ranks = [e.rank for e in user_es]
        scores = [e.points for e in user_es]
        percentiles = [round((1 - r / total_entries) * 100, 1) for r in ranks]

        # Lineup diversity: how different are their lineups from each other?
        all_players = [set(e.players) for e in user_es]
        avg_overlap = 0
        pair_count = 0
        for i in range(len(all_players)):
            for j in range(i + 1, len(all_players)):
                overlap = len(all_players[i] & all_players[j])
                avg_overlap += overlap / 10  # normalized to 10-player lineups
                pair_count += 1
        avg_overlap = avg_overlap / pair_count if pair_count else 0

        # Stack strategy consistency
        stack_sizes = []
        for e in user_es:
            stacks = identify_stacks(e, player_teams)
            primary = max((s["size"] for s in stacks), default=0)
            stack_sizes.append(primary)

        user_stats.append({
            "username": username,
            "entries": len(user_es),
            "best_rank": min(ranks),
            "avg_rank": round(sum(ranks) / len(ranks), 1),
            "avg_percentile": round(sum(percentiles) / len(percentiles), 1),
            "best_score": max(scores),
            "avg_score": round(sum(scores) / len(scores), 2),
            "lineup_diversity": round(1 - avg_overlap, 3),
            "avg_primary_stack": round(sum(stack_sizes) / len(stack_sizes), 1),
            "stack_sizes": stack_sizes,
        })

    # Sort by avg percentile (best performers)
    user_stats.sort(key=lambda x: x["avg_percentile"], reverse=True)

    # Extract strategy patterns from top users
    top_users = user_stats[:10]
    strategy_summary = {
        "avg_lineup_diversity": round(
            statistics.mean(u["lineup_diversity"] for u in top_users), 3
        ) if top_users else 0,
        "avg_primary_stack_size": round(
            statistics.mean(u["avg_primary_stack"] for u in top_users), 1
        ) if top_users else 0,
        "avg_entries_per_user": round(
            statistics.mean(u["entries"] for u in top_users), 1
        ) if top_users else 0,
    }

    return {
        "sharp_users": top_users,
        "strategy_summary": strategy_summary,
        "total_multi_entry_users": len(user_stats),
    }


# --------------------------------------------------------------------------
# Full contest analysis
# --------------------------------------------------------------------------

def analyze_contest(
    entries: List[ParsedEntry],
    slate: Optional[SlateContext] = None,
) -> Dict[str, Any]:
    """Comprehensive analysis of a single contest."""
    if not entries:
        return {"error": "No entries"}

    # Load teams from slate context or projection file
    player_teams = slate.player_teams if slate else {}
    player_opps = slate.player_opps if slate else {}

    # --- Meta ---
    scores = [e.points for e in entries]
    user_counts = Counter(e.username for e in entries)
    unique_users = len(user_counts)
    multi_entry_users = sum(1 for c in user_counts.values() if c > 1)
    max_entries_observed = max(user_counts.values())

    # Try to get declared max from entry names
    declared_maxes = [e.max_entries for e in entries if e.max_entries]
    max_entries_declared = max(declared_maxes) if declared_maxes else max_entries_observed

    meta = {
        "entry_count": len(entries),
        "unique_users": unique_users,
        "multi_entry_users": multi_entry_users,
        "multi_entry_pct": round(multi_entry_users / unique_users * 100, 1),
        "max_entries_declared": max_entries_declared,
        "avg_entries_per_user": round(len(entries) / unique_users, 2),
        "scores": {
            "top": scores[0],
            "p10": round(scores[int(len(scores) * 0.1)], 2),
            "median": round(statistics.median(scores), 2),
            "p90": round(scores[int(len(scores) * 0.9)], 2),
            "bottom": scores[-1],
            "std": round(statistics.stdev(scores), 2) if len(scores) > 1 else 0,
        },
    }

    # --- Ownership ---
    player_counts = Counter()
    for e in entries:
        player_counts.update(e.players)

    ownership = []
    for player, count in player_counts.most_common():
        own_pct = round(count / len(entries) * 100, 2)
        team = player_teams.get(player, "")
        pos = slate.player_positions.get(player, "") if slate else ""
        salary = slate.player_salaries.get(player, 0) if slate else 0
        proj = slate.player_projections.get(player, 0) if slate else 0

        # Is this player in a confirmed lineup?
        is_confirmed = False
        batting_order = None
        if slate:
            for team_lineup in slate.confirmed_lineups.values():
                if player in team_lineup:
                    is_confirmed = True
                    batting_order = team_lineup.index(player) + 1
                    break

        ownership.append({
            "player": player,
            "team": team,
            "position": pos,
            "ownership_pct": own_pct,
            "roster_count": count,
            "salary": salary,
            "projection": proj,
            "is_confirmed": is_confirmed,
            "batting_order": batting_order,
        })

    # --- Stacking ---
    stacking = analyze_stacking(entries, player_teams)

    # --- Bring-backs ---
    bring_backs = analyze_bring_backs(entries, player_teams, player_opps)

    # --- Top performers ---
    top_perf = analyze_top_performers(entries, player_teams, slate, top_pct=5.0)

    # --- Sharp users ---
    sharps = analyze_sharp_users(entries, player_teams, min_entries=3)

    # --- Position concentration ---
    pos_players: Dict[str, Counter] = defaultdict(Counter)
    for e in entries:
        for slot, player in e.roster.items():
            clean_pos = re.sub(r"\d+$", "", slot)
            pos_players[clean_pos][player] += 1

    pos_concentration = {}
    for pos, counts in pos_players.items():
        total = sum(counts.values())
        top_3_players = counts.most_common(3)
        top_3_total = sum(c for _, c in top_3_players)
        pos_concentration[pos] = {
            "unique_players": len(counts),
            "top_3_concentration_pct": round(top_3_total / total * 100, 1),
            "top_3": [{"player": p, "pct": round(c / total * 100, 1)} for p, c in top_3_players],
        }

    # --- Slate context summary ---
    slate_summary = None
    if slate:
        confirmed_teams = [t for t, lineup in slate.confirmed_lineups.items() if len(lineup) >= 8]
        slate_summary = {
            "date": slate.date,
            "slate_name": slate.slate_name,
            "teams": slate.teams,
            "teams_with_confirmed_lineups": confirmed_teams,
            "total_confirmed_players": sum(len(l) for l in slate.confirmed_lineups.values()),
        }

    return {
        "meta": meta,
        "slate_context": slate_summary,
        "ownership": ownership[:60],
        "ownership_full": ownership,
        "stacking": stacking,
        "bring_backs": bring_backs,
        "top_performers": top_perf,
        "sharp_users": sharps,
        "position_concentration": pos_concentration,
        "unique_players_in_field": len(player_counts),
    }


# --------------------------------------------------------------------------
# Multi-contest runner
# --------------------------------------------------------------------------

def analyze_all_contests(contest_dir: str = None) -> Dict[str, Any]:
    """Analyze all contests with proper slate matching."""
    if contest_dir is None:
        contest_dir = str(CONTEST_DIR)

    results = {}
    csv_files = sorted(Path(contest_dir).glob("*.csv"))

    for csv_path in csv_files:
        cid_match = re.search(r"(\d+)", csv_path.stem)
        if not cid_match:
            continue
        cid = cid_match.group(1)

        entries = parse_contest_csv(str(csv_path))
        if not entries:
            continue

        # Match to slate and load context
        proj_file = match_contest_to_slate(entries)
        slate = None
        if proj_file:
            try:
                slate = load_slate_context(proj_file)
            except Exception as exc:
                print(f"  Warning: Could not load slate context from {proj_file}: {exc}")

        analysis = analyze_contest(entries, slate)
        analysis["contest_id"] = cid
        analysis["file"] = csv_path.name
        analysis["matched_slate"] = proj_file
        results[cid] = analysis

    # Cross-contest summary
    cross = _cross_contest_analysis(results) if len(results) > 1 else {}

    return {"contests": results, "cross_contest": cross}


def _cross_contest_analysis(results: Dict[str, Dict]) -> Dict[str, Any]:
    """Aggregate insights across all contests."""
    all_ownership: Dict[str, List[float]] = defaultdict(list)
    all_stack_dists: Dict[int, List[float]] = defaultdict(list)

    for cid, analysis in results.items():
        for p in analysis.get("ownership_full", []):
            all_ownership[p["player"]].append(p["ownership_pct"])

        for size, data in analysis.get("stacking", {}).get("primary_stack_distribution", {}).items():
            all_stack_dists[size].append(data["pct_of_field"])

    # Consistent chalk
    consistent_chalk = []
    for player, ownerships in all_ownership.items():
        if len(ownerships) >= 2 and statistics.mean(ownerships) > 10:
            consistent_chalk.append({
                "player": player,
                "avg_ownership": round(statistics.mean(ownerships), 1),
                "contests": len(ownerships),
                "range": [round(min(ownerships), 1), round(max(ownerships), 1)],
            })
    consistent_chalk.sort(key=lambda x: x["avg_ownership"], reverse=True)

    # Optimal stack sizes across contests
    stack_norms = {}
    for size, pcts in all_stack_dists.items():
        stack_norms[size] = {
            "avg_field_pct": round(statistics.mean(pcts), 1),
            "range": [round(min(pcts), 1), round(max(pcts), 1)],
        }

    return {
        "consistent_chalk": consistent_chalk[:20],
        "stack_size_norms": stack_norms,
        "total_unique_players_across_contests": len(all_ownership),
    }


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    contest_dir = sys.argv[1] if len(sys.argv) > 1 else str(CONTEST_DIR)
    print(f"Analyzing contests in: {contest_dir}")
    print("=" * 80)

    results = analyze_all_contests(contest_dir)

    for cid, analysis in results.get("contests", {}).items():
        meta = analysis["meta"]
        slate = analysis.get("slate_context")
        print(f"\n{'='*80}")
        print(f"Contest {cid}")
        if slate:
            print(f"  Slate: {slate['slate_name']} ({slate['date']})")
            print(f"  Teams: {', '.join(slate['teams'])}")
            print(f"  Confirmed lineups: {', '.join(slate['teams_with_confirmed_lineups'])}")
        print(f"{'='*80}")
        print(f"  Entries: {meta['entry_count']} | Users: {meta['unique_users']} | Multi-entry: {meta['multi_entry_pct']}%")
        print(f"  Max entries: {meta['max_entries_declared']} | Avg/user: {meta['avg_entries_per_user']}")
        print(f"  Scores: top={meta['scores']['top']} | p10={meta['scores']['p10']} | median={meta['scores']['median']} | std={meta['scores']['std']}")

        print(f"\n  TOP 20 OWNERSHIP:")
        print(f"  {'Player':<25} {'Team':<5} {'Pos':<4} {'Own%':>6} {'Salary':>7} {'Proj':>6} {'Confirmed'}")
        print(f"  {'-'*80}")
        for p in analysis["ownership"][:20]:
            conf = f"#{p['batting_order']}" if p["batting_order"] else ("Y" if p["is_confirmed"] else "")
            print(f"  {p['player']:<25} {p['team']:<5} {p['position']:<4} {p['ownership_pct']:>5.1f}% ${p['salary']:>5} {p['projection']:>6.1f} {conf}")

        stacking = analysis["stacking"]
        print(f"\n  STACKING (primary stack per lineup):")
        for size in sorted(stacking["primary_stack_distribution"].keys(), reverse=True):
            data = stacking["primary_stack_distribution"][size]
            print(f"    {size}-man: {data['pct_of_field']:>5.1f}% of field | avg percentile: {data['avg_percentile']:.1f}%")

        print(f"\n  Most stacked teams:")
        for t in stacking["popular_stacking_teams"][:5]:
            print(f"    {t['team']}: {t['pct_of_lineups']:.1f}% of lineups | sizes: {t['by_size']}")

        bb = analysis["bring_backs"]
        print(f"\n  BRING-BACKS: {bb['bring_back_pct']:.1f}% of lineups | avg rank w/ BB: {bb['bring_back_avg_rank']:.0f} vs w/o: {bb['no_bring_back_avg_rank']:.0f}")

        top = analysis["top_performers"]
        print(f"\n  TOP 5% LEVERAGE (over-owned in winning lineups):")
        for p in top["leverage_players"][:10]:
            print(f"    {p['player']:<25} top: {p['top_ownership']:>5.1f}% vs field: {p['field_ownership']:>5.1f}% (+{p['leverage']:.1f})")

        print(f"\n  TOP 5% UNDERLEVERAGE (under-owned in winning lineups):")
        for p in top["underleverage_players"][:5]:
            print(f"    {p['player']:<25} top: {p['top_ownership']:>5.1f}% vs field: {p['field_ownership']:>5.1f}% ({p['leverage']:.1f})")

        print(f"\n  Stack comparison (top 5% vs field):")
        for size, data in sorted(top["stack_comparison"].items(), reverse=True):
            if data["top_pct"] > 0 or data["field_pct"] > 0:
                print(f"    {size}-man: top={data['top_pct']:.1f}% vs field={data['field_pct']:.1f}% (edge: {data['edge']:+.1f})")

        sharps = analysis["sharp_users"]
        if sharps["sharp_users"]:
            print(f"\n  TOP SHARP USERS (3+ entries):")
            for u in sharps["sharp_users"][:5]:
                print(f"    {u['username']:<20} {u['entries']}e | avg pctl: {u['avg_percentile']:.1f}% | diversity: {u['lineup_diversity']:.2f} | avg stack: {u['avg_primary_stack']:.1f}")
            ss = sharps["strategy_summary"]
            print(f"\n  Sharp strategy summary: diversity={ss['avg_lineup_diversity']:.2f}, stack={ss['avg_primary_stack_size']:.1f}, entries={ss['avg_entries_per_user']:.0f}")

    # Cross-contest
    cross = results.get("cross_contest", {})
    if cross:
        print(f"\n{'='*80}")
        print("CROSS-CONTEST INSIGHTS")
        print(f"{'='*80}")
        print(f"\n  Stack size norms across all contests:")
        for size, data in sorted(cross.get("stack_size_norms", {}).items(), reverse=True):
            print(f"    {size}-man: avg {data['avg_field_pct']:.1f}% of field (range: {data['range']})")

        print(f"\n  Consistent chalk (>10% avg ownership, 2+ contests):")
        for p in cross.get("consistent_chalk", [])[:15]:
            print(f"    {p['player']:<25} avg: {p['avg_ownership']:.1f}% ({p['contests']} contests, range: {p['range']})")

    # Save JSON
    output_path = Path(contest_dir).parent / "analysis_results.json"
    json_results = {}
    for cid, analysis in results.get("contests", {}).items():
        # Remove full ownership for JSON brevity
        a = {k: v for k, v in analysis.items() if k != "ownership_full"}
        json_results[cid] = a

    json_results["cross_contest"] = cross

    with open(output_path, "w") as f:
        json.dump(json_results, f, indent=2, default=str)
    print(f"\n\nResults saved to: {output_path}")
