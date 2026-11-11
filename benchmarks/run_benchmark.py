"""Regression benchmark for the Studious transcription pipeline.

Answers one question: "did my change to a prompt, the provider or the
pipeline make the shipping configuration worse?" It runs the committed
fixtures through the app's own provider with the app's default model and
scores each transcription two ways:

- a judge model grades it against the source image and the reviewed
  reference transcription, on the same 0-10 rubric model_eval uses. This is
  the score to act on.
- character error rate and line accuracy against the reference. Free and
  deterministic, but blind to what matters most (a wrong furigana reading
  costs one character); treat it as a tripwire, not a verdict.

Results are saved as timestamped JSON under benchmarks/results/; compare two
with `python -m benchmarks.compare`. To compare *models* against each other,
use `python -m benchmarks.model_eval` instead.

Usage:
    python -m benchmarks.run_benchmark [--engine vlm] [--provider anthropic]
                                       [--no-judge] [--judge-model M]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from benchmarks.model_eval.common import (
    DEFAULT_JUDGE_FALLBACK_MODEL,
    DEFAULT_JUDGE_MODEL,
    ensure_anthropic_api_key,
    ensure_backend_on_path,
    git_sha,
)

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
        if child.suffix.lower() in IMAGE_SUFFIXES | PDF_SUFFIXES and child.stem.lower().startswith("input"):
            return child
    # Fallback: any image or PDF
    for child in sorted(fixture_dir.iterdir()):
        if child.suffix.lower() in IMAGE_SUFFIXES | PDF_SUFFIXES:
            return child
    return None


def find_text_input(fixture_dir: Path) -> Path | None:
    """Find a text input file (input.md / input.txt) for non-image fixtures."""
    for ext in (".md", ".txt"):
        candidate = fixture_dir / f"input{ext}"
        if candidate.exists():
            return candidate
    return None


def run_breakdown(text: str, provider: str) -> dict:
    """Run a sentence breakdown via the configured VLM tool-use path."""
    ensure_backend_on_path()
    from app.config import (
        BREAKDOWN_TOOL_SCHEMA,
        SENTENCE_BREAKDOWN_PROMPT,
        get_settings,
    )
    from app.providers import registry

    registry.bootstrap_default_providers()
    settings = get_settings()
    prov = registry.get_vlm(provider)

    full_prompt = f"{SENTENCE_BREAKDOWN_PROMPT}\n\n---\n\n{text}"
    config = {"model": settings.default_vlm_model}

    t0 = time.monotonic()
    result = prov.call_tool(full_prompt, "record_breakdown", BREAKDOWN_TOOL_SCHEMA, config)
    duration_ms = int((time.monotonic() - t0) * 1000)

    return {
        "tool_input": result.tool_input,
        "meta": result.meta,
        "duration_ms": duration_ms,
    }


def evaluate_breakdown(tool_input: dict, expected: dict) -> dict:
    """Compare breakdown output against expected sentence count + vocab terms."""
    sentences = tool_input.get("sentences") or []
    actual_count = len(sentences)
    expected_count = int(expected.get("expected_sentence_count", 0))
    expected_vocab = list(expected.get("expected_vocab", []))

    # Collect every vocab word and sentence text — match against either,
    # since the model may surface a term in the sentence text without listing
    # it as a vocab entry.
    vocab_words: set[str] = set()
    all_text_parts: list[str] = []
    for s in sentences:
        all_text_parts.append(str(s.get("text", "")))
        all_text_parts.append(str(s.get("gloss", "")))
        for v in s.get("vocab") or []:
            w = v.get("word")
            if isinstance(w, str):
                vocab_words.add(w)
                all_text_parts.append(w)
    haystack = "\n".join(all_text_parts)

    found = [t for t in expected_vocab if t in haystack]
    missing = [t for t in expected_vocab if t not in haystack]

    return {
        "actual_sentence_count": actual_count,
        "expected_sentence_count": expected_count,
        "sentence_count_match": actual_count == expected_count,
        "vocab_found": found,
        "vocab_missing": missing,
        "vocab_recall": round(len(found) / len(expected_vocab), 4) if expected_vocab else 1.0,
    }


def summarize_judgments(results: list[dict]) -> dict:
    """Average each rubric dimension over the fixtures the judge scored."""
    judged = [r["judge"] for r in results if r.get("judge", {}).get("status") == "ok"]
    attempted = [r for r in results if "judge" in r]
    if not attempted:
        return {}
    out: dict = {"judged": len(judged), "judge_failures": len(attempted) - len(judged)}
    if judged:
        from benchmarks.model_eval.judging import RUBRIC_DIMENSIONS

        for dim in RUBRIC_DIMENSIONS:
            out[f"avg_judge_{dim}"] = round(sum(j[dim] for j in judged) / len(judged), 2)
        out["min_judge_overall"] = min(j["overall"] for j in judged)
        costs = [j.get("estimated_cost_usd") for j in judged]
        if all(c is not None for c in costs):
            out["judge_cost_usd"] = round(sum(costs), 4)
    return out


def make_judge(judge_model: str, fallback_model: str) -> Any:
    """Bind an Anthropic client and models into the callable run_benchmark takes."""
    import anthropic

    from benchmarks.model_eval.reference_judge import judge_against_reference

    ensure_backend_on_path()
    from app.config import get_settings
    from app.services import pdf

    client = anthropic.Anthropic()
    max_edge = get_settings().vlm_max_edge

    def judge(image_path: Path, prompt_kind: str, reference_md: str, candidate_md: str) -> dict:
        # The same bytes the transcriber is sent, so both see one image.
        image_png = pdf.prepare_for_vlm(image_path, max_edge)
        return judge_against_reference(
            client, image_png, prompt_kind, reference_md, candidate_md,
            judge_model, fallback_model,
        )

    return judge


def run_transcription(
    image_path: Path, engine: str, provider: str, prompt_kind: str = "page"
) -> dict:
    """Run transcription through the Studious pipeline and return results."""
    ensure_backend_on_path()
    from app.config import (
        REGION_TRANSCRIBE_PROMPT,
        VOCAB_LIST_TRANSCRIBE_PROMPT,
        get_settings,
    )
    from app.providers import registry
    from app.services import pdf

    registry.bootstrap_default_providers()
    settings = get_settings()

    prompts = {
        "page": settings.default_vlm_prompt,
        "region": REGION_TRANSCRIBE_PROMPT,
        "vocab_list": VOCAB_LIST_TRANSCRIBE_PROMPT,
    }
    if prompt_kind not in prompts:
        raise ValueError(f"unknown prompt_kind: {prompt_kind}")

    t0 = time.monotonic()
    if engine == "ocr":
        prov = registry.get_ocr(provider)
        result = prov.transcribe(image_path, {})
    elif engine == "vlm":
        prov = registry.get_vlm(provider)
        image_bytes = pdf.prepare_for_vlm(image_path, settings.vlm_max_edge)
        result = prov.transcribe(image_bytes, prompts[prompt_kind], {})
    else:
        raise ValueError(f"unknown engine: {engine}")
    duration_ms = int((time.monotonic() - t0) * 1000)

    return {
        "markdown": result.markdown,
        "meta": result.meta,
        "duration_ms": duration_ms,
        "model": settings.default_vlm_model if engine == "vlm" else None,
    }


def run_benchmark(engine: str, provider: str, judge: Any = None) -> dict:
    """Run the full benchmark suite and return results.

    `judge`, when given, is called as `judge(image_path, prompt_kind,
    reference_md, candidate_md)` for every image fixture that has a
    reference, and its result dict is stored under the fixture's "judge" key.
    """
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

        meta_path = fixture_dir / "meta.json"
        meta_data: dict = {}
        if meta_path.exists():
            try:
                meta_data = json.loads(meta_path.read_text("utf-8"))
            except (OSError, json.JSONDecodeError):
                meta_data = {}

        kind = meta_data.get("kind", "transcription")

        if kind == "breakdown":
            if engine != "vlm":
                print(f"  SKIP {name}: breakdowns need the vlm engine")
                results.append({"fixture": name, "status": "skipped", "reason": "not a vlm run"})
                continue
            text_input = find_text_input(fixture_dir)
            if text_input is None:
                print(f"  SKIP {name}: no text input (input.md/input.txt) for breakdown fixture")
                results.append({"fixture": name, "status": "skipped", "reason": "no text input"})
                continue
            print(f"  RUN  {name} (breakdown/{provider})...", end=" ", flush=True)
            try:
                output = run_breakdown(text_input.read_text("utf-8"), provider)
            except Exception as e:
                print(f"ERROR: {e}")
                results.append({"fixture": name, "status": "error", "error": str(e)})
                continue
            evaluation = evaluate_breakdown(output["tool_input"], meta_data)
            entry: dict = {
                "fixture": name,
                "kind": "breakdown",
                "status": "ok",
                "duration_ms": output["duration_ms"],
                "meta": output.get("meta", {}),
                **evaluation,
            }
            ok_mark = "✓" if evaluation["sentence_count_match"] else "✗"
            print(
                f"sentences={evaluation['actual_sentence_count']}/"
                f"{evaluation['expected_sentence_count']} {ok_mark} "
                f"vocab_recall={evaluation['vocab_recall']:.0%} "
                f"({output['duration_ms']}ms)"
            )
            results.append(entry)
            continue

        input_file = find_input_file(fixture_dir)
        if input_file is None:
            print(f"  SKIP {name}: no input file found")
            results.append({"fixture": name, "status": "skipped", "reason": "no input file"})
            continue

        ground_truth_path = GROUND_TRUTH_DIR / f"{name}.md"
        has_ground_truth = ground_truth_path.exists()

        prompt_kind = meta_data.get("prompt_kind", "page")

        print(f"  RUN  {name} ({engine}/{provider}/{prompt_kind})...", end=" ", flush=True)
        try:
            output = run_transcription(input_file, engine, provider, prompt_kind)
        except Exception as e:
            print(f"ERROR: {e}")
            results.append({"fixture": name, "status": "error", "error": str(e)})
            continue

        entry = {
            "fixture": name,
            "status": "ok",
            "duration_ms": output["duration_ms"],
            "output_chars": len(output["markdown"]),
            "meta": output.get("meta", {}),
        }
        if output.get("model"):
            entry["model"] = output["model"]

        if has_ground_truth:
            ref = ground_truth_path.read_text("utf-8")
            cer = character_error_rate(ref, output["markdown"])
            line_acc = line_accuracy(ref, output["markdown"])
            entry["cer"] = round(cer, 4)
            entry["line_accuracy"] = round(line_acc, 4)
            line = f"CER={cer:.2%} line_acc={line_acc:.2%}"
            if judge is not None:
                judgment = judge(input_file, prompt_kind, ref, output["markdown"])
                entry["judge"] = judgment
                if judgment.get("status") == "ok":
                    line += f" judge={judgment['overall']}/10"
                else:
                    line += f" judge={judgment.get('status')}"
            print(f"{line} ({output['duration_ms']}ms)")
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
    summary.update(summarize_judgments(ok_results))
    if ok_results:
        summary["avg_duration_ms"] = round(
            sum(r["duration_ms"] for r in ok_results) / len(ok_results)
        )

    breakdown_results = [r for r in ok_results if r.get("kind") == "breakdown"]
    if breakdown_results:
        summary["breakdown_count"] = len(breakdown_results)
        summary["breakdown_sentence_count_match"] = sum(
            1 for r in breakdown_results if r.get("sentence_count_match")
        )
        summary["breakdown_avg_vocab_recall"] = round(
            sum(r["vocab_recall"] for r in breakdown_results) / len(breakdown_results), 4
        )

    return {"fixtures": results, "summary": summary}


def main():
    parser = argparse.ArgumentParser(description="Run Studious quality benchmarks")
    parser.add_argument("--engine", default="vlm", choices=["ocr", "vlm"])
    parser.add_argument("--provider", default=None, help="Provider name (default: tesseract for ocr, anthropic for vlm)")
    parser.add_argument("--no-judge", action="store_true", help="Skip the judge; report CER/line accuracy only")
    parser.add_argument("--judge-model", default=DEFAULT_JUDGE_MODEL)
    parser.add_argument("--fallback-model", default=DEFAULT_JUDGE_FALLBACK_MODEL)
    args = parser.parse_args()

    provider = args.provider or ("tesseract" if args.engine == "ocr" else "anthropic")

    use_judge = not args.no_judge
    if provider == "anthropic" or use_judge:
        ensure_anthropic_api_key()

    print("Studious Quality Benchmark")
    print(f"  engine:   {args.engine}")
    print(f"  provider: {provider}")
    print(f"  judge:    {args.judge_model if use_judge else 'off'}")
    print(f"  git:      {git_sha()}")
    print()

    judge = make_judge(args.judge_model, args.fallback_model) if use_judge else None
    result = run_benchmark(args.engine, provider, judge=judge)

    if not result["fixtures"]:
        sys.exit(0)

    # Save results
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    result_file = RESULTS_DIR / f"{timestamp}_{args.engine}_{provider}.json"
    output = {
        "timestamp": datetime.now(UTC).isoformat(),
        "git_sha": git_sha(),
        "engine": args.engine,
        "provider": provider,
        "judge_model": args.judge_model if use_judge else None,
        **result,
    }
    result_file.write_text(json.dumps(output, indent=2, ensure_ascii=False), "utf-8")

    print()
    print(f"Summary: {result['summary']}")
    print(f"Results saved to: {result_file}")
    if result["summary"].get("errors"):
        # A run where calls failed is not a clean baseline; say so to scripts.
        sys.exit(1)


if __name__ == "__main__":
    main()
