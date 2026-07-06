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
from datetime import datetime, timezone
from pathlib import Path

from .common import (
    DEFAULT_DATA_DIR,
    DEFAULT_DATASET_DIR,
    DEFAULT_RUNS_DIR,
    ensure_anthropic_api_key,
    git_sha,
)

DEFAULT_SEED = 20260706
DEFAULT_MODELS = "claude-haiku-4-5,claude-sonnet-5,claude-opus-4-8"


def _utc_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


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
    )
    print()
    print(f"Totals: {run_meta['totals']}")
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
    )
    print()
    print(f"Totals: {summary['totals']}")
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
    p_build.add_argument("--name", default="v1")
    p_build.set_defaults(func=_cmd_build_dataset)

    p_run = sub.add_parser("run", help="Run dataset items through one or more models")
    p_run.add_argument("--dataset", default=str(DEFAULT_DATASET_DIR / "v1"))
    p_run.add_argument("--models", default=DEFAULT_MODELS)
    p_run.add_argument("--run-id", default=None)
    p_run.add_argument("--max-tokens", type=int, default=8192)
    p_run.add_argument("--runs-dir", default=str(DEFAULT_RUNS_DIR))
    p_run.set_defaults(func=_cmd_run)

    p_judge = sub.add_parser("judge", help="Blind-judge candidate transcriptions for a run")
    p_judge.add_argument("--run-id", required=True)
    p_judge.add_argument("--dataset", default=str(DEFAULT_DATASET_DIR / "v1"))
    p_judge.add_argument("--judge-model", default="claude-fable-5")
    p_judge.add_argument("--seed", type=int, default=None)
    p_judge.add_argument("--fallback-model", default="claude-opus-4-8")
    p_judge.add_argument("--runs-dir", default=str(DEFAULT_RUNS_DIR))
    p_judge.set_defaults(func=_cmd_judge)

    p_analyze = sub.add_parser("analyze", help="Aggregate judgments into a report")
    p_analyze.add_argument("--run-id", required=True)
    p_analyze.add_argument("--dataset", default=str(DEFAULT_DATASET_DIR / "v1"))
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
