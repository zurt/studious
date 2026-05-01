"""Quality benchmark runner for Studious transcription pipeline.

Processes fixture documents through OCR/VLM providers and compares output
against ground-truth transcriptions. Results are saved as timestamped JSON
for tracking quality over time.

Usage:
    python -m benchmarks.run_benchmark [--provider anthropic] [--engine vlm]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


def ensure_anthropic_api_key() -> None:
    """Populate ANTHROPIC_API_KEY from macOS Keychain if not already set.

    The README's recommended setup stores the key in Keychain and exports it
    from interactive shell rc files. `make` spawns a non-interactive subshell
    that does not source those files, so fall back to a direct Keychain lookup.
    """
    if os.environ.get("ANTHROPIC_API_KEY"):
        return
    user = os.environ.get("USER")
    if not user or sys.platform != "darwin":
        return
    try:
        value = subprocess.check_output(
            ["security", "find-generic-password", "-s", "ANTHROPIC_API_KEY", "-a", user, "-w"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return
    if value:
        os.environ["ANTHROPIC_API_KEY"] = value

BENCHMARKS_DIR = Path(__file__).parent
FIXTURES_DIR = BENCHMARKS_DIR / "fixtures"
GROUND_TRUTH_DIR = BENCHMARKS_DIR / "ground-truth"
RESULTS_DIR = BENCHMARKS_DIR / "results"

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp"}
PDF_SUFFIXES = {".pdf"}


def character_error_rate(reference: str, hypothesis: str) -> float:
    """Compute Character Error Rate using Levenshtein distance.

    CER = edit_distance(ref, hyp) / len(ref)
    Returns 0.0 for perfect match, >1.0 if hypothesis is much longer/different.
    """
    ref = reference.strip()
    hyp = hypothesis.strip()
    if not ref:
        return 0.0 if not hyp else 1.0

    # Standard DP Levenshtein
    n, m = len(ref), len(hyp)
    prev = list(range(m + 1))
    for i in range(1, n + 1):
        curr = [i] + [0] * m
        for j in range(1, m + 1):
            cost = 0 if ref[i - 1] == hyp[j - 1] else 1
            curr[j] = min(curr[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost)
        prev = curr
    return prev[m] / n


def line_accuracy(reference: str, hypothesis: str) -> float:
    """Fraction of reference lines that appear exactly in the hypothesis."""
    ref_lines = [l.strip() for l in reference.strip().splitlines() if l.strip()]
    if not ref_lines:
        return 1.0
    hyp_lines = set(l.strip() for l in hypothesis.strip().splitlines())
    matches = sum(1 for l in ref_lines if l in hyp_lines)
    return matches / len(ref_lines)


def find_input_file(fixture_dir: Path) -> Path | None:
    """Find the input document in a fixture directory."""
    for child in sorted(fixture_dir.iterdir()):
        if child.suffix.lower() in IMAGE_SUFFIXES | PDF_SUFFIXES:
            if child.stem.lower().startswith("input"):
                return child
    # Fallback: any image or PDF
    for child in sorted(fixture_dir.iterdir()):
        if child.suffix.lower() in IMAGE_SUFFIXES | PDF_SUFFIXES:
            return child
    return None


def git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return "unknown"


def run_transcription(image_path: Path, engine: str, provider: str) -> dict:
    """Run transcription through the Studious pipeline and return results."""
    # Import here to allow running from project root
    sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
    from app.config import get_settings
    from app.providers import registry
    from app.services import pdf

    registry.bootstrap_default_providers()
    settings = get_settings()

    t0 = time.monotonic()
    if engine == "ocr":
        prov = registry.get_ocr(provider)
        result = prov.transcribe(image_path, {})
    elif engine == "vlm":
        prov = registry.get_vlm(provider)
        image_bytes = pdf.prepare_for_vlm(image_path, settings.vlm_max_edge)
        result = prov.transcribe(image_bytes, settings.default_vlm_prompt, {})
    else:
        raise ValueError(f"unknown engine: {engine}")
    duration_ms = int((time.monotonic() - t0) * 1000)

    return {
        "markdown": result.markdown,
        "meta": result.meta,
        "duration_ms": duration_ms,
    }


def run_benchmark(engine: str, provider: str) -> dict:
    """Run the full benchmark suite and return results."""
    fixtures = sorted(
        d for d in FIXTURES_DIR.iterdir() if d.is_dir() and not d.name.startswith(".")
    )

    if not fixtures:
        print("No fixtures found. Add test documents to benchmarks/fixtures/")
        print("See benchmarks/fixtures/README.md for instructions.")
        return {"fixtures": [], "summary": {"total": 0}}

    results = []
    for fixture_dir in fixtures:
        name = fixture_dir.name
        input_file = find_input_file(fixture_dir)
        if input_file is None:
            print(f"  SKIP {name}: no input file found")
            results.append({"fixture": name, "status": "skipped", "reason": "no input file"})
            continue

        ground_truth_path = GROUND_TRUTH_DIR / f"{name}.md"
        has_ground_truth = ground_truth_path.exists()

        print(f"  RUN  {name} ({engine}/{provider})...", end=" ", flush=True)
        try:
            output = run_transcription(input_file, engine, provider)
        except Exception as e:
            print(f"ERROR: {e}")
            results.append({"fixture": name, "status": "error", "error": str(e)})
            continue

        entry: dict = {
            "fixture": name,
            "status": "ok",
            "duration_ms": output["duration_ms"],
            "output_chars": len(output["markdown"]),
            "meta": output.get("meta", {}),
        }

        if has_ground_truth:
            ref = ground_truth_path.read_text("utf-8")
            cer = character_error_rate(ref, output["markdown"])
            line_acc = line_accuracy(ref, output["markdown"])
            entry["cer"] = round(cer, 4)
            entry["line_accuracy"] = round(line_acc, 4)
            print(f"CER={cer:.2%} line_acc={line_acc:.2%} ({output['duration_ms']}ms)")
        else:
            print(f"no ground truth ({output['duration_ms']}ms)")

        results.append(entry)

    # Summary
    ok_results = [r for r in results if r["status"] == "ok"]
    with_cer = [r for r in ok_results if "cer" in r]
    summary = {
        "total": len(results),
        "ok": len(ok_results),
        "errors": sum(1 for r in results if r["status"] == "error"),
        "skipped": sum(1 for r in results if r["status"] == "skipped"),
    }
    if with_cer:
        summary["avg_cer"] = round(sum(r["cer"] for r in with_cer) / len(with_cer), 4)
        summary["avg_line_accuracy"] = round(
            sum(r["line_accuracy"] for r in with_cer) / len(with_cer), 4
        )
    if ok_results:
        summary["avg_duration_ms"] = round(
            sum(r["duration_ms"] for r in ok_results) / len(ok_results)
        )

    return {"fixtures": results, "summary": summary}


def main():
    parser = argparse.ArgumentParser(description="Run Studious quality benchmarks")
    parser.add_argument("--engine", default="vlm", choices=["ocr", "vlm"])
    parser.add_argument("--provider", default=None, help="Provider name (default: tesseract for ocr, anthropic for vlm)")
    args = parser.parse_args()

    provider = args.provider or ("tesseract" if args.engine == "ocr" else "anthropic")

    if provider == "anthropic":
        ensure_anthropic_api_key()

    print(f"Studious Quality Benchmark")
    print(f"  engine:   {args.engine}")
    print(f"  provider: {provider}")
    print(f"  git:      {git_sha()}")
    print()

    result = run_benchmark(args.engine, provider)

    if not result["fixtures"]:
        sys.exit(0)

    # Save results
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    result_file = RESULTS_DIR / f"{timestamp}_{args.engine}_{provider}.json"
    output = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "git_sha": git_sha(),
        "engine": args.engine,
        "provider": provider,
        **result,
    }
    result_file.write_text(json.dumps(output, indent=2, ensure_ascii=False), "utf-8")

    print()
    print(f"Summary: {result['summary']}")
    print(f"Results saved to: {result_file}")


if __name__ == "__main__":
    main()
