"""Compare two benchmark result files to identify regressions and improvements.

Usage:
    python -m benchmarks.compare results/baseline.json results/current.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def load_results(path: Path) -> dict:
    return json.loads(path.read_text("utf-8"))


def compare(baseline_path: Path, current_path: Path) -> None:
    baseline = load_results(baseline_path)
    current = load_results(current_path)

    print(f"Baseline: {baseline_path.name} ({baseline.get('git_sha', '?')})")
    print(f"Current:  {current_path.name} ({current.get('git_sha', '?')})")
    print(f"Engine:   {baseline.get('engine')} -> {current.get('engine')}")
    print(f"Provider: {baseline.get('provider')} -> {current.get('provider')}")
    print()

    base_fixtures = {r["fixture"]: r for r in baseline.get("fixtures", [])}
    curr_fixtures = {r["fixture"]: r for r in current.get("fixtures", [])}

    all_names = sorted(set(base_fixtures) | set(curr_fixtures))
    if not all_names:
        print("No fixtures to compare.")
        return

    print(f"{'Fixture':<20} {'CER (base)':>12} {'CER (curr)':>12} {'Delta':>10} {'Time (base)':>12} {'Time (curr)':>12}")
    print("-" * 80)

    regressions = 0
    improvements = 0

    for name in all_names:
        b = base_fixtures.get(name, {})
        c = curr_fixtures.get(name, {})

        b_cer = b.get("cer")
        c_cer = c.get("cer")
        b_time = b.get("duration_ms")
        c_time = c.get("duration_ms")

        cer_base = f"{b_cer:.2%}" if b_cer is not None else "-"
        cer_curr = f"{c_cer:.2%}" if c_cer is not None else "-"
        time_base = f"{b_time}ms" if b_time is not None else "-"
        time_curr = f"{c_time}ms" if c_time is not None else "-"

        if b_cer is not None and c_cer is not None:
            delta = c_cer - b_cer
            delta_str = f"{delta:+.2%}"
            if delta > 0.01:
                delta_str += " REGRESSION"
                regressions += 1
            elif delta < -0.01:
                delta_str += " IMPROVED"
                improvements += 1
        else:
            delta_str = "-"

        print(f"{name:<20} {cer_base:>12} {cer_curr:>12} {delta_str:>10} {time_base:>12} {time_curr:>12}")

    print()
    bs = baseline.get("summary", {})
    cs = current.get("summary", {})
    if "avg_cer" in bs and "avg_cer" in cs:
        print(f"Avg CER: {bs['avg_cer']:.2%} -> {cs['avg_cer']:.2%}")
    if "avg_duration_ms" in bs and "avg_duration_ms" in cs:
        print(f"Avg time: {bs['avg_duration_ms']}ms -> {cs['avg_duration_ms']}ms")
    print(f"Regressions: {regressions}, Improvements: {improvements}")


def main():
    if len(sys.argv) != 3:
        print("Usage: python -m benchmarks.compare <baseline.json> <current.json>")
        sys.exit(1)
    compare(Path(sys.argv[1]), Path(sys.argv[2]))


if __name__ == "__main__":
    main()
