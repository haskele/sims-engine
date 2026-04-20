"""Ownership prediction model — calibrate projected ownership against actual results.

Uses contest results to build a mapping from prematch signals to actual ownership:
- Projected ownership → actual ownership (calibration curve)
- Salary → ownership baseline
- Confirmed lineup status → ownership multiplier
- Team implied total → stacking probability

This feeds directly into the simulation engine for generating realistic opponent fields.
"""
from __future__ import annotations

import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

ROOT = Path(__file__).resolve().parent.parent.parent


def build_ownership_calibration(results_path: str = None) -> Dict[str, Any]:
    """Build ownership calibration model from contest results + projection data.

    Compares prematch projected ownership to actual contest ownership to
    identify systematic biases and build a calibration function.
    """
    if results_path is None:
        results_path = str(ROOT / "contest results downloads" / "analysis_results.json")

    with open(results_path) as f:
        data = json.load(f)

    # Collect (projected_own, actual_own, salary, is_confirmed, position) tuples
    calibration_data = []
    salary_ownership = []
    confirmed_multipliers = []

    for cid, contest in data.items():
        if cid == "cross_contest":
            continue
        if "ownership" not in contest:
            continue

        for player in contest.get("ownership", []):
            actual_own = player.get("ownership_pct", 0)
            proj_own = player.get("projection", 0)  # This is median pts, not ownership
            salary = player.get("salary", 0)
            is_confirmed = player.get("is_confirmed", False)
            position = player.get("position", "")

            if salary > 0:
                salary_ownership.append({
                    "salary": salary,
                    "actual_own": actual_own,
                    "is_confirmed": is_confirmed,
                    "position": position,
                    "is_pitcher": position in ("P", "SP", "RP"),
                })

    # --- Salary-based ownership curve ---
    # Group by salary bucket
    salary_buckets: Dict[int, List[float]] = defaultdict(list)
    for item in salary_ownership:
        bucket = (item["salary"] // 500) * 500  # $500 increments
        salary_buckets[bucket].append(item["actual_own"])

    salary_curve = {}
    for bucket, ownerships in sorted(salary_buckets.items()):
        if len(ownerships) >= 3:
            salary_curve[bucket] = {
                "avg_ownership": round(statistics.mean(ownerships), 2),
                "median_ownership": round(statistics.median(ownerships), 2),
                "std": round(statistics.stdev(ownerships), 2) if len(ownerships) > 1 else 0,
                "count": len(ownerships),
            }

    # --- Confirmed vs unconfirmed ownership ---
    confirmed_owns = [s["actual_own"] for s in salary_ownership if s["is_confirmed"]]
    unconfirmed_owns = [s["actual_own"] for s in salary_ownership if not s["is_confirmed"]]

    confirmed_effect = {
        "confirmed_avg_own": round(statistics.mean(confirmed_owns), 2) if confirmed_owns else 0,
        "unconfirmed_avg_own": round(statistics.mean(unconfirmed_owns), 2) if unconfirmed_owns else 0,
        "multiplier": round(
            statistics.mean(confirmed_owns) / max(statistics.mean(unconfirmed_owns), 0.1), 2
        ) if confirmed_owns and unconfirmed_owns else 1.0,
    }

    # --- Position-based ownership patterns ---
    pos_ownership: Dict[str, List[float]] = defaultdict(list)
    for item in salary_ownership:
        pos = "P" if item["is_pitcher"] else item["position"]
        if not pos:
            pos = "UTIL"
        pos_ownership[pos].append(item["actual_own"])

    position_norms = {}
    for pos, owns in pos_ownership.items():
        if len(owns) >= 5:
            position_norms[pos] = {
                "avg": round(statistics.mean(owns), 2),
                "top_3_avg": round(statistics.mean(sorted(owns, reverse=True)[:3]), 2),
                "concentration": round(sum(sorted(owns, reverse=True)[:3]) / sum(owns) * 100, 1) if owns else 0,
            }

    # --- Ownership distribution shape ---
    # How ownership distributes across the player pool
    all_ownerships = [s["actual_own"] for s in salary_ownership]
    all_ownerships_sorted = sorted(all_ownerships, reverse=True)

    ownership_shape = {
        "top_5_avg": round(statistics.mean(all_ownerships_sorted[:5]), 1),
        "top_10_avg": round(statistics.mean(all_ownerships_sorted[:10]), 1),
        "top_20_avg": round(statistics.mean(all_ownerships_sorted[:20]), 1),
        "median": round(statistics.median(all_ownerships), 1),
        "bottom_50pct_avg": round(
            statistics.mean(all_ownerships_sorted[len(all_ownerships_sorted) // 2:]), 1
        ),
    }

    return {
        "salary_curve": salary_curve,
        "confirmed_effect": confirmed_effect,
        "position_norms": position_norms,
        "ownership_shape": ownership_shape,
        "total_observations": len(salary_ownership),
    }


def build_stacking_model(results_path: str = None) -> Dict[str, Any]:
    """Build empirical stacking probability model from contest results.

    Determines:
    - What % of lineups stack each team (by implied total / projection)
    - Stack size distribution by contest size
    - Correlation between team stacking and ownership
    """
    if results_path is None:
        results_path = str(ROOT / "contest results downloads" / "analysis_results.json")

    with open(results_path) as f:
        data = json.load(f)

    # Collect stacking data
    stack_by_field_size: Dict[str, List[Dict]] = defaultdict(list)

    for cid, contest in data.items():
        if cid == "cross_contest":
            continue

        meta = contest.get("meta", {})
        stacking = contest.get("stacking", {})
        entry_count = meta.get("entry_count", 0)

        # Classify field size
        if entry_count < 500:
            size_class = "small"
        elif entry_count < 5000:
            size_class = "medium"
        else:
            size_class = "large"

        primary_dist = stacking.get("primary_stack_distribution", {})
        stack_by_field_size[size_class].append(primary_dist)

    # Average stack distribution by field size
    stack_norms_by_size = {}
    for size_class, dists in stack_by_field_size.items():
        agg: Dict[int, List[float]] = defaultdict(list)
        for dist in dists:
            for size, info in dist.items():
                agg[int(size)].append(info["pct_of_field"])

        stack_norms_by_size[size_class] = {
            size: {
                "avg_pct": round(statistics.mean(pcts), 1),
                "std": round(statistics.stdev(pcts), 1) if len(pcts) > 1 else 0,
            }
            for size, pcts in sorted(agg.items(), reverse=True)
        }

    return {
        "stack_norms_by_field_size": stack_norms_by_size,
    }


def generate_ownership_predictions(
    projections: List[Dict[str, Any]],
    calibration: Dict[str, Any],
    contest_size: int = 10000,
) -> List[Dict[str, Any]]:
    """Given projections and calibration model, predict actual ownership for a slate.

    This is the key function for the sim engine — takes our projected player pool
    and estimates what the real DFS field will look like in terms of ownership.
    """
    salary_curve = calibration.get("salary_curve", {})
    confirmed_effect = calibration.get("confirmed_effect", {})
    confirmed_multiplier = confirmed_effect.get("multiplier", 2.0)

    results = []
    for p in projections:
        salary = p.get("salary", 0)
        is_confirmed = p.get("is_confirmed", False)
        proj_pts = p.get("median_pts", 0) or p.get("projection", 0)
        position = p.get("position", "")

        # Base ownership from salary bucket
        bucket = (salary // 500) * 500
        bucket_data = salary_curve.get(str(bucket), {})
        base_own = bucket_data.get("avg_ownership", 3.0)

        # Adjust for projection quality (higher proj = higher ownership)
        # Simple linear scaling: each point above 7.0 median adds ~2% ownership
        proj_bonus = max(0, (proj_pts - 7.0)) * 2.5

        # Confirmed lineup bonus
        if is_confirmed:
            conf_bonus = base_own * (confirmed_multiplier - 1)
        else:
            conf_bonus = 0

        predicted_own = base_own + proj_bonus + conf_bonus

        # Pitchers have much higher concentration — scale up for P
        if position in ("P", "SP", "RP"):
            predicted_own *= 1.5

        # Cap at reasonable max
        predicted_own = min(predicted_own, 65.0)

        results.append({
            **p,
            "predicted_ownership": round(predicted_own, 1),
            "base_ownership": round(base_own, 1),
            "proj_bonus": round(proj_bonus, 1),
            "confirmed_bonus": round(conf_bonus, 1),
        })

    # Normalize so total ownership sums to ~1000% (10 roster spots * 100%)
    total_own = sum(r["predicted_ownership"] for r in results)
    target_total = 1000.0
    if total_own > 0:
        scale = target_total / total_own
        for r in results:
            r["predicted_ownership"] = round(r["predicted_ownership"] * scale, 1)

    return sorted(results, key=lambda x: x["predicted_ownership"], reverse=True)


if __name__ == "__main__":
    print("Building ownership calibration model...")
    calibration = build_ownership_calibration()

    print("\n=== SALARY → OWNERSHIP CURVE ===")
    print(f"{'Salary':>8} {'Avg Own%':>8} {'Med Own%':>8} {'Std':>6} {'N':>4}")
    for bucket, data in sorted(calibration["salary_curve"].items(), key=lambda x: int(x[0])):
        print(f"${int(bucket):>6} {data['avg_ownership']:>7.1f}% {data['median_ownership']:>7.1f}% {data['std']:>5.1f} {data['count']:>4}")

    print(f"\n=== CONFIRMED LINEUP EFFECT ===")
    ce = calibration["confirmed_effect"]
    print(f"  Confirmed avg ownership: {ce['confirmed_avg_own']:.1f}%")
    print(f"  Unconfirmed avg ownership: {ce['unconfirmed_avg_own']:.1f}%")
    print(f"  Multiplier: {ce['multiplier']:.2f}x")

    print(f"\n=== POSITION OWNERSHIP NORMS ===")
    for pos, data in sorted(calibration["position_norms"].items()):
        print(f"  {pos:>4}: avg={data['avg']:.1f}%, top-3 avg={data['top_3_avg']:.1f}%, concentration={data['concentration']:.0f}%")

    print(f"\n=== OWNERSHIP SHAPE ===")
    shape = calibration["ownership_shape"]
    print(f"  Top 5 players avg: {shape['top_5_avg']:.1f}%")
    print(f"  Top 10 players avg: {shape['top_10_avg']:.1f}%")
    print(f"  Top 20 players avg: {shape['top_20_avg']:.1f}%")
    print(f"  Median player: {shape['median']:.1f}%")
    print(f"  Bottom 50% avg: {shape['bottom_50pct_avg']:.1f}%")

    print(f"\n=== STACKING MODEL ===")
    stacking = build_stacking_model()
    for size_class, norms in stacking["stack_norms_by_field_size"].items():
        print(f"\n  {size_class.upper()} fields:")
        for size, data in sorted(norms.items(), reverse=True):
            print(f"    {size}-man: {data['avg_pct']:.1f}% ± {data['std']:.1f}")

    # Save model
    output = {
        "calibration": calibration,
        "stacking": stacking,
    }
    output_path = ROOT / "contest results downloads" / "ownership_model.json"
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\n\nModel saved to: {output_path}")
