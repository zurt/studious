"""Compare two regression-benchmark result files.

Usage:
    python -m benchmarks.compare <baseline.json> <current.json>

A fixture counts as a regression when its judge `overall` score drops by a
point or more, or — when either run has no judge score for it — when its
character error rate rises by more than one percentage point. Exits 1 if
anything regressed, so it can gate a script.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

JUDGE_DELTA = 1  # points of `overall` (0-10)
CER_DELTA = 0.01


def load_results(path: Path) -> dict:
    return json.loads(path.read_text("utf-8"))


def _judge_overall(fixture: dict) -> int | None:
    judge = fixture.get("judge") or {}
    return judge.get("overall") if judge.get("status") == "ok" else None


def classify(base: dict, curr: dict) -> str:
    """"regression", "improved" or "" for one fixture's pair of results."""
    b_judge, c_judge = _judge_overall(base), _judge_overall(curr)
    if b_judge is not None and c_judge is not None:
        if c_judge <= b_judge - JUDGE_DELTA:
            return "regression"
        if c_judge >= b_judge + JUDGE_DELTA:
            return "improved"
        return ""
    b_cer, c_cer = base.get("cer"), curr.get("cer")
    if b_cer is not None and c_cer is not None:
        if c_cer - b_cer > CER_DELTA:
            return "regression"
        if c_cer - b_cer < -CER_DELTA:
            return "improved"
    return ""


def _fmt(value, pattern: str) -> str:
    return pattern.format(value) if value is not None else "-"


def compare(baseline_path: Path, current_path: Path) -> int:
    """Print the comparison; return the number of regressed fixtures."""
    baseline = load_results(baseline_path)
    current = load_results(current_path)

    print(f"Baseline: {baseline_path.name} ({baseline.get('git_sha', '?')})")
    print(f"Current:  {current_path.name} ({current.get('git_sha', '?')})")
    print(f"Engine:   {baseline.get('engine')} -> {current.get('engine')}")
    print(f"Provider: {baseline.get('provider')} -> {current.get('provider')}")
    print(f"Judge:    {baseline.get('judge_model')} -> {current.get('judge_model')}")
    if baseline.get("judge_model") != current.get("judge_model"):
        print("  (different judges: judge scores are not directly comparable)")
    print()

    base_fixtures = {r["fixture"]: r for r in baseline.get("fixtures", [])}
    curr_fixtures = {r["fixture"]: r for r in current.get("fixtures", [])}

    all_names = sorted(set(base_fixtures) | set(curr_fixtures))
    if not all_names:
        print("No fixtures to compare.")
        return 0

    width = max(len(n) for n in all_names)
    print(f"{'Fixture':<{width}} {'Judge':>9} {'CER':>17} {'Time':>19}  Verdict")
    print("-" * (width + 58))

    regressions = 0
    improvements = 0
    for name in all_names:
        b = base_fixtures.get(name, {})
        c = curr_fixtures.get(name, {})
        verdict = classify(b, c)
        regressions += verdict == "regression"
        improvements += verdict == "improved"

        judge = f"{_fmt(_judge_overall(b), '{}')} -> {_fmt(_judge_overall(c), '{}')}"
        cer = f"{_fmt(b.get('cer'), '{:.2%}')} -> {_fmt(c.get('cer'), '{:.2%}')}"
        time = f"{_fmt(b.get('duration_ms'), '{}ms')} -> {_fmt(c.get('duration_ms'), '{}ms')}"
        print(f"{name:<{width}} {judge:>9} {cer:>17} {time:>19}  {verdict.upper()}")

    print()
    bs = baseline.get("summary", {})
    cs = current.get("summary", {})
    if "avg_judge_overall" in bs and "avg_judge_overall" in cs:
        print(f"Avg judge overall: {bs['avg_judge_overall']} -> {cs['avg_judge_overall']}")
    if "avg_cer" in bs and "avg_cer" in cs:
        print(f"Avg CER: {bs['avg_cer']:.2%} -> {cs['avg_cer']:.2%}")
    if "avg_duration_ms" in bs and "avg_duration_ms" in cs:
        print(f"Avg time: {bs['avg_duration_ms']}ms -> {cs['avg_duration_ms']}ms")
    print(f"Regressions: {regressions}, Improvements: {improvements}")
    return regressions


def main():
    if len(sys.argv) != 3:
        print("Usage: python -m benchmarks.compare <baseline.json> <current.json>")
        sys.exit(1)
    regressions = compare(Path(sys.argv[1]), Path(sys.argv[2]))
    sys.exit(1 if regressions else 0)


if __name__ == "__main__":
    main()
