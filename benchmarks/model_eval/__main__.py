"""CLI entry point for the model-eval framework.

Usage:
    python -m benchmarks.model_eval build-dataset [--data-dir ...] [--seed N] [--out DIR] [--name NAME]
    python -m benchmarks.model_eval run [--dataset DIR] [--models a,b,c] [--run-id ID] [--max-tokens N]
    python -m benchmarks.model_eval judge [--run-id ID] [--dataset DIR] [--judge-model M] [--seed N] [--fallback-model M]
    python -m benchmarks.model_eval analyze --run-id ID [--dataset DIR]

See benchmarks/model_eval/README.md for full documentation and examples.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from .common import (
    DEFAULT_DATA_DIR,
    DEFAULT_DATASET_DIR,
    DEFAULT_JUDGE_FALLBACK_MODEL,
    DEFAULT_JUDGE_MODEL,
    DEFAULT_RUNS_DIR,
    ensure_anthropic_api_key,
    git_sha,
)

DEFAULT_SEED = 20261111
DEFAULT_DATASET_NAME = "v2"
# The current generation plus the two models the July 2026 run found tied,
# so a new run can be read against that one even though its dataset is gone.
DEFAULT_MODELS = "claude-sonnet-5-5,claude-opus-5-5,claude-haiku-5-5,claude-sonnet-5,claude-opus-4-8"


def _utc_run_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%d-%H%M%S")


def _cmd_build_dataset(args: argparse.Namespace) -> int:
    from . import dataset_build

    print("Studious model-eval: build-dataset")
    print(f"  data_dir: {args.data_dir}")
    print(f"  out:      {args.out}/{args.name}")
    print(f"  seed:     {args.seed}")
    print(f"  git:      {git_sha()}")
    print()

    manifest = dataset_build.build_dataset(
        data_dir=Path(args.data_dir),
        out_dir=Path(args.out),
        name=args.name,
        seed=args.seed,
        exclude=args.exclude,
    )
    print(f"Built {manifest['item_count']} items.")
    for stratum in manifest["strata"]:
        note = f" (SHORT by {stratum['shortfall']})" if stratum["shortfall"] else ""
        print(
            f"  {stratum['stratum']}: {stratum['selected_count']}/{stratum['quota']} "
            f"(of {stratum['candidate_count']} candidates){note}"
        )
    print(f"Manifest: {Path(args.out) / args.name / 'manifest.json'}")
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    from . import run_cmd

    ensure_anthropic_api_key()
    models = [m.strip() for m in args.models.split(",") if m.strip()]

    print("Studious model-eval: run")
    print(f"  dataset:  {args.dataset}")
    print(f"  models:   {models}")
    print(f"  run_id:   {args.run_id}")
    print(f"  git:      {git_sha()}")
    print()

    run_meta = run_cmd.run_dataset(
        dataset_dir=Path(args.dataset),
        runs_dir=Path(args.runs_dir),
        models=models,
        run_id=args.run_id,
        max_tokens=args.max_tokens,
        budget_usd=args.budget_usd,
    )
    print()
    print(f"Totals: {run_meta['totals']}")
    print(f"Estimated cost: ${run_meta['estimated_cost_usd']:.2f}")
    if run_meta["budget_stopped_before"]:
        print(
            f"Stopped at the budget before {run_meta['budget_stopped_before']}. "
            "Re-run with the same --run-id and a higher --budget-usd to continue."
        )
    print(f"Run dir: {Path(args.runs_dir) / args.run_id}")
    return 0


def _cmd_judge(args: argparse.Namespace) -> int:
    from . import judge_cmd

    ensure_anthropic_api_key()
    seed = args.seed
    if seed is None:
        manifest_path = Path(args.dataset) / "manifest.json"
        if manifest_path.exists():
            seed = json.loads(manifest_path.read_text("utf-8")).get("seed", DEFAULT_SEED)
        else:
            seed = DEFAULT_SEED

    print("Studious model-eval: judge")
    print(f"  run_id:         {args.run_id}")
    print(f"  dataset:        {args.dataset}")
    print(f"  judge_model:    {args.judge_model}")
    print(f"  fallback_model: {args.fallback_model}")
    print(f"  seed:           {seed}")
    print()

    summary = judge_cmd.judge_run(
        run_dir=Path(args.runs_dir) / args.run_id,
        dataset_dir=Path(args.dataset),
        judge_model=args.judge_model,
        seed=seed,
        fallback_model=args.fallback_model,
        budget_usd=args.budget_usd,
    )
    print()
    print(f"Totals: {summary['totals']}")
    print(f"Estimated cost: ${summary['estimated_cost_usd']:.2f}")
    if summary["budget_stopped_before"]:
        print(
            f"Stopped at the budget before {summary['budget_stopped_before']}. "
            "Re-run with the same --run-id and a higher --budget-usd to continue."
        )
    return 0


def _cmd_analyze(args: argparse.Namespace) -> int:
    from . import analyze_cmd

    print("Studious model-eval: analyze")
    print(f"  run_id:  {args.run_id}")
    print(f"  dataset: {args.dataset}")
    print()

    run_dir = Path(args.runs_dir) / args.run_id
    result = analyze_cmd.analyze_run(run_dir=run_dir, dataset_dir=Path(args.dataset))
    print(f"Items judged: {result['n_items_judged']}")
    print(f"Analysis: {run_dir / 'analysis.json'}")
    print(f"Report:   {run_dir / 'report.md'}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m benchmarks.model_eval",
        description="Model-comparison evaluation framework for Studious transcription.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_build = sub.add_parser("build-dataset", help="Sample a frozen eval dataset from the store")
    p_build.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    p_build.add_argument("--seed", type=int, default=DEFAULT_SEED)
    p_build.add_argument("--out", default=str(DEFAULT_DATASET_DIR))
    p_build.add_argument("--name", default=DEFAULT_DATASET_NAME)
    p_build.add_argument(
        "--exclude", action="append", default=[], metavar="TEXT",
        help="skip documents whose filename contains TEXT (repeatable)",
    )
    p_build.set_defaults(func=_cmd_build_dataset)

    p_run = sub.add_parser("run", help="Run dataset items through one or more models")
    p_run.add_argument("--dataset", default=str(DEFAULT_DATASET_DIR / DEFAULT_DATASET_NAME))
    p_run.add_argument("--models", default=DEFAULT_MODELS)
    p_run.add_argument("--run-id", default=None)
    p_run.add_argument("--max-tokens", type=int, default=8192)
    p_run.add_argument(
        "--budget-usd", type=float, default=None,
        help="stop between items once the estimated spend would exceed this",
    )
    p_run.add_argument("--runs-dir", default=str(DEFAULT_RUNS_DIR))
    p_run.set_defaults(func=_cmd_run)

    p_judge = sub.add_parser("judge", help="Blind-judge candidate transcriptions for a run")
    p_judge.add_argument("--run-id", required=True)
    p_judge.add_argument("--dataset", default=str(DEFAULT_DATASET_DIR / DEFAULT_DATASET_NAME))
    p_judge.add_argument("--judge-model", default=DEFAULT_JUDGE_MODEL)
    p_judge.add_argument("--seed", type=int, default=None)
    p_judge.add_argument("--fallback-model", default=DEFAULT_JUDGE_FALLBACK_MODEL)
    p_judge.add_argument(
        "--budget-usd", type=float, default=None,
        help="stop between items once the estimated spend would exceed this",
    )
    p_judge.add_argument("--runs-dir", default=str(DEFAULT_RUNS_DIR))
    p_judge.set_defaults(func=_cmd_judge)

    p_analyze = sub.add_parser("analyze", help="Aggregate judgments into a report")
    p_analyze.add_argument("--run-id", required=True)
    p_analyze.add_argument("--dataset", default=str(DEFAULT_DATASET_DIR / DEFAULT_DATASET_NAME))
    p_analyze.add_argument("--runs-dir", default=str(DEFAULT_RUNS_DIR))
    p_analyze.set_defaults(func=_cmd_analyze)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "run" and args.run_id is None:
        args.run_id = _utc_run_id()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
