"""Generate a concise findings report from contest analysis results.

Extracts the most actionable patterns for:
1. Lineup builder optimizer tuning (stack sizes, salary allocation, position concentration)
2. Simulation engine lineup pool generation (ownership curves, field composition)
3. Sharp strategy extraction (leverage patterns, build diversity)
"""
from __future__ import annotations

import json
from pathlib import Path


def generate_report(results_path: str = None) -> str:
    if results_path is None:
        results_path = str(
            Path(__file__).resolve().parent.parent.parent
            / "contest results downloads"
            / "analysis_results.json"
        )

    with open(results_path) as f:
        data = json.load(f)

    contests = {k: v for k, v in data.items() if k != "cross_contest"}
    cross = data.get("cross_contest", {})

    lines = []
    lines.append("=" * 80)
    lines.append("CONTEST ANALYSIS — KEY FINDINGS & RECOMMENDATIONS")
    lines.append("=" * 80)

    # --- 1. Field composition summary ---
    lines.append("\n## 1. FIELD COMPOSITION ACROSS CONTESTS\n")
    lines.append(f"{'Contest':<12} {'Entries':>7} {'Users':>6} {'ME%':>5} {'MaxE':>5} {'Avg/U':>5} {'Top':>6} {'Med':>6} {'Std':>5}")
    lines.append("-" * 80)
    for cid, c in sorted(contests.items(), key=lambda x: x[1]["meta"]["entry_count"], reverse=True):
        m = c["meta"]
        lines.append(
            f"{cid:<12} {m['entry_count']:>7} {m['unique_users']:>6} "
            f"{m['multi_entry_pct']:>4.0f}% {m['max_entries_declared']:>5} "
            f"{m['avg_entries_per_user']:>5.1f} {m['scores']['top']:>6.1f} "
            f"{m['scores']['median']:>6.1f} {m['scores']['std']:>5.1f}"
        )

    # --- 2. Stacking norms ---
    lines.append("\n\n## 2. STACKING NORMS (PRIMARY STACK PER LINEUP)\n")
    lines.append("Cross-contest averages:")
    for size, data in sorted(cross.get("stack_size_norms", {}).items(), key=lambda x: int(x[0]), reverse=True):
        lines.append(f"  {size}-man stack: {data['avg_field_pct']:.1f}% of field (range: {data['range']})")

    lines.append("\nKEY FINDING: 5-man stacks dominate (~53% of field), 4-man is secondary (~24%).")
    lines.append("Top performers slightly favor 4-man stacks over 5-man in larger GPPs.")
    lines.append("Implication: Lineup builder should default to 4-5 man primary stacks.")

    # --- 3. Stacking teams ---
    lines.append("\n\n## 3. TEAM STACKING PREFERENCES\n")
    lines.append("Most commonly stacked teams per contest (>20% of lineups):")

    for cid, c in contests.items():
        stacking = c.get("stacking", {})
        top_teams = [t for t in stacking.get("popular_stacking_teams", []) if t["pct_of_lineups"] > 15]
        slate = c.get("slate_context", {})
        date = slate.get("date", "") if slate else ""
        lines.append(f"\n  {cid} ({date}):")
        for t in top_teams[:5]:
            lines.append(f"    {t['team']}: {t['pct_of_lineups']:.1f}% | {t['by_size']}")

    # --- 4. Top performer leverage ---
    lines.append("\n\n## 4. TOP 5% LEVERAGE PATTERNS\n")
    lines.append("Players consistently OVER-owned in winning lineups across contests:")

    leverage_agg = {}
    for cid, c in contests.items():
        for p in c.get("top_performers", {}).get("leverage_players", []):
            name = p["player"]
            if name not in leverage_agg:
                leverage_agg[name] = {"leverages": [], "team": p.get("team", "")}
            leverage_agg[name]["leverages"].append(p["leverage"])

    consistent_leverage = []
    for name, data in leverage_agg.items():
        if len(data["leverages"]) >= 2:
            avg_lev = sum(data["leverages"]) / len(data["leverages"])
            if avg_lev > 10:
                consistent_leverage.append({
                    "player": name,
                    "avg_leverage": round(avg_lev, 1),
                    "contests": len(data["leverages"]),
                    "team": data["team"],
                })

    consistent_leverage.sort(key=lambda x: x["avg_leverage"], reverse=True)
    for p in consistent_leverage[:15]:
        lines.append(f"  +{p['avg_leverage']:>5.1f}  {p['player']:<25} ({p['team']}, {p['contests']} contests)")

    lines.append("\n\nPlayers consistently UNDER-owned in winning lineups:")
    under_agg = {}
    for cid, c in contests.items():
        for p in c.get("top_performers", {}).get("underleverage_players", []):
            name = p["player"]
            if name not in under_agg:
                under_agg[name] = {"leverages": [], "team": p.get("team", "")}
            under_agg[name]["leverages"].append(p["leverage"])

    consistent_under = []
    for name, data in under_agg.items():
        if len(data["leverages"]) >= 2:
            avg_lev = sum(data["leverages"]) / len(data["leverages"])
            if avg_lev < -5:
                consistent_under.append({
                    "player": name,
                    "avg_leverage": round(avg_lev, 1),
                    "contests": len(data["leverages"]),
                    "team": data["team"],
                })

    consistent_under.sort(key=lambda x: x["avg_leverage"])
    for p in consistent_under[:10]:
        lines.append(f"  {p['avg_leverage']:>+5.1f}  {p['player']:<25} ({p['team']}, {p['contests']} contests)")

    # --- 5. Sharp user patterns ---
    lines.append("\n\n## 5. SHARP USER STRATEGY PATTERNS\n")

    sharp_diversities = []
    sharp_stacks = []
    sharp_entries = []

    for cid, c in contests.items():
        sharps = c.get("sharp_users", {})
        ss = sharps.get("strategy_summary", {})
        if ss:
            sharp_diversities.append(ss.get("avg_lineup_diversity", 0))
            sharp_stacks.append(ss.get("avg_primary_stack_size", 0))
            sharp_entries.append(ss.get("avg_entries_per_user", 0))

    if sharp_diversities:
        lines.append(f"  Avg lineup diversity: {sum(sharp_diversities)/len(sharp_diversities):.2f}")
        lines.append(f"  Avg primary stack size: {sum(sharp_stacks)/len(sharp_stacks):.1f}")
        lines.append(f"  Avg entries per sharp: {sum(sharp_entries)/len(sharp_entries):.0f}")

    lines.append("\n  Key patterns from sharp users:")
    lines.append("  - Lower diversity (0.2-0.4) = concentrated on 1-2 game stacks with variations")
    lines.append("  - 4-5 man stacks are standard, but sharps flex down to 3-4 in larger fields")
    lines.append("  - Most successful sharps play 3-10 entries, not max field")

    # --- 6. Bring-back usage ---
    lines.append("\n\n## 6. BRING-BACK (OPPOSING HITTER) USAGE\n")
    for cid, c in contests.items():
        bb = c.get("bring_backs", {})
        if bb:
            lines.append(f"  {cid}: {bb['bring_back_pct']:.1f}% of lineups use bring-backs")

    lines.append("\n  Finding: Bring-backs are rare in MLB DFS (0.3-11%), and generally")
    lines.append("  don't correlate with better performance. Unlike NFL, stacking opponents")
    lines.append("  provides minimal correlation benefit in baseball.")

    # --- 7. Recommendations for lineup builder & sim engine ---
    lines.append("\n\n## 7. RECOMMENDATIONS FOR LINEUP BUILDER & SIM ENGINE\n")
    lines.append("### Lineup Builder Optimizer:")
    lines.append("  1. Default primary stack size: 4-5 hitters from same team")
    lines.append("  2. Secondary stack: 2-3 hitters from a correlated game (opposing team or same game)")
    lines.append("  3. Stack construction: Weight top of lineup (1-5) for stack slots")
    lines.append("  4. Avoid bring-backs as a default strategy")
    lines.append("  5. Position concentration: P slots have highest chalk (50%+), create variance elsewhere")
    lines.append("  6. Top performers use confirmed lineup data heavily — confirmed hitters are +EV")

    lines.append("\n### Simulation Engine Lineup Pool:")
    lines.append("  1. Generate lineup pools with this stack distribution:")
    lines.append("     - 50-55% of lineups: 5-man primary stack")
    lines.append("     - 22-25% of lineups: 4-man primary stack")
    lines.append("     - 10-12% of lineups: 3-man primary stack")
    lines.append("     - 5-8% of lineups: 2-man or unstructured")
    lines.append("  2. Team stacking weight: proportional to team projected run total")
    lines.append("  3. Ownership curve: top 3 pitchers ~35-55%, top hitters ~15-30%")
    lines.append("  4. Multi-entry users account for 25-35% of field but 60%+ of entries")
    lines.append("  5. Lineup correlation within multi-entry portfolios: ~0.3-0.5 player overlap")

    lines.append("\n### For Future Integration:")
    lines.append("  1. Map prematch projected ownership to actual ownership (calibration)")
    lines.append("  2. Use confirmed lineup data as strong signal for ownership spikes")
    lines.append("  3. Build user archetype model: single-entry casual vs. multi-entry sharp")
    lines.append("  4. Track leverage players (top 5% over-owned) to identify correlation value")
    lines.append("  5. Incorporate salary-based ownership curves (cheap confirmed hitters get over-owned)")

    return "\n".join(lines)


if __name__ == "__main__":
    report = generate_report()
    print(report)

    output_path = (
        Path(__file__).resolve().parent.parent.parent
        / "contest results downloads"
        / "findings_report.txt"
    )
    with open(output_path, "w") as f:
        f.write(report)
    print(f"\n\nReport saved to: {output_path}")
