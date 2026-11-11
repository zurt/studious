# model_eval

A reproducible model-comparison evaluation framework for the Studious
transcription pipeline. It samples a frozen, versioned dataset of real
region/page crops from the store, runs the same crops through multiple
Claude models via the app's own VLM provider, has a blind LLM judge rank the
results on a rubric, and aggregates the judgments into a report.

Unlike the regression benchmark (`make benchmark`, which checks the shipping
model against reviewed references on a handful of committed fixtures), this
framework compares *models against each other* at scale. Both score with the
same LLM judge and rubric rather than relying on string similarity, because
"did this read the furigana right" is not something CER captures well. See
`benchmarks/README.md` for which to use when.

Run everything as a module from the repo root:

```
python -m benchmarks.model_eval <subcommand> [options]
```

## Subcommands

### `build-dataset` — sample a frozen dataset from the store

```
python -m benchmarks.model_eval build-dataset \
    --data-dir backend/data \
    --seed 20261111 \
    --out benchmarks/model_eval/dataset \
    --name v2 \
    --exclude 魔女
```

`--exclude TEXT` (repeatable) skips documents whose filename contains TEXT.
Use it to keep unrelated uploads out: anything that isn't a workbook is
classified as `textbook`, so a novel would otherwise land in the textbook
strata.

Enumerates every document/chapter/region in the on-disk store, classifies
each document as `textbook` or `workbook` (by filename, case-insensitive
substring match on "workbook"), and stratified-samples items with a seeded
`random.Random(seed)`. Candidates are sorted by a stable id before any
random draw, so the same seed always yields the same dataset regardless of
directory-listing order.

Default quotas (`sampling.QUOTAS_V2`, a plain dict — pass a different
quotas dict to `dataset_build.build_dataset()` to override):

| Source | Region tag | v2 quota | v1 (2026-07) |
|---|---|---|---|
| textbook | exercises | 6 | 5 |
| textbook | grammar_points | 6 | 5 |
| textbook | vocab_list | 5 | 4 |
| textbook | reading_passage | 5 | 3 |
| textbook | instructions | 2 | 1 |
| textbook | full pages | 8 | 4 |
| workbook | exercises | 10 | 7 |
| workbook | full pages | 6 | 2 |
| | **total** | **48** | **31** |

v2 more than doubles full pages (14 vs 6): whole-page transcription is where
v1 had the least evidence and the widest gap between models. Pages are
sampled from "content pages" (pages with at least one region), softly
preferring pages not already used by a sampled region (falls back to reusing
a page if there aren't enough unused ones — this never fails the build).

If a stratum has fewer candidates than its quota, `build-dataset` takes all
of them and records the shortfall in the manifest instead of failing.

For every sampled item it freezes the **exact bytes** the real pipeline
would send to the VLM — `crop_region(page_png, bbox, vlm_max_edge)` for
regions, `prepare_for_vlm(page_png, vlm_max_edge)` for pages — under
`dataset/<name>/items/<item_id>/input.png`, alongside a `meta.json`. This
means later runs never re-touch the store or re-crop; they just read frozen
PNGs, so a dataset is reproducible even after the store changes.

Item ids are human-scannable and stable: `tb-r-vocab_list-<region_id8>`,
`wb-r-exercises-<region_id8>`, `tb-p-0042`.

**Expanding the dataset later**: bump quotas in a custom quotas dict (or add
new tags/sources) and re-run `build-dataset` with a new `--name` (e.g. `v2`)
— datasets are meant to be frozen once built and referenced by name/seed in
run/judge output, not mutated in place. Rebuilding the *same* name replaces
its `items/` directory (idempotent), so treat a name+seed pair as "this
exact dataset," not "the latest dataset."

### `run` — transcribe every item with one or more models

```
python -m benchmarks.model_eval run \
    --dataset benchmarks/model_eval/dataset/v1 \
    --run-id 20261111-eval-v2 \
    --budget-usd 5
```

`--models` defaults to the current generation (`claude-sonnet-5-5`,
`claude-opus-5-5`, `claude-haiku-5-5`) plus `claude-sonnet-5` and
`claude-opus-4-8`, the two the July 2026 run found tied, as a bridge to that
run.

`--budget-usd N` stops the run once the estimated spend would pass N. It
stops *between items*, never inside one, so every item in the run has a
result from every model. Re-run with the same `--run-id` and a higher budget
to continue.

Reads each item's frozen `input.png` (never re-crops), picks the prompt by
the item's `prompt_kind` (`page` / `region` / `vocab_list` — same prompts
`app/jobs/` and `app/api/regions.py` use in production), and calls the
`anthropic` VLM provider's `transcribe()` directly — the same code path a
real transcription job takes, so results reflect production behavior
(including the temperature/adaptive-thinking/effort handling in
`app/providers/vlm/anthropic.py`).

Output: `runs/<run_id>/transcriptions/<item_id>/<model>.json` (model,
markdown, provider meta incl. usage/request_id/stop_reason, duration_ms,
estimated_cost_usd) and a `runs/<run_id>/run.json` summary.

**Resumable**: rerunning the same `--run-id` skips any (item, model) pair
whose output file already exists and parses as JSON — so an interrupted run,
or adding a model to `--models` later, only fills in the gaps. Errors are
caught per-call and recorded as `{"status": "error", "error": ...}`; they
don't stop the run.

Requires `ANTHROPIC_API_KEY` (falls back to macOS Keychain lookup like
`run_benchmark.py` does).

### `judge` — blind LLM judge, rubric + ranking

```
python -m benchmarks.model_eval judge \
    --run-id 20261111-eval-v2 \
    --budget-usd 8
```

Defaults: `--judge-model claude-fable-5-2`, `--fallback-model default`,
`--dataset .../dataset/v2`. `--budget-usd` works as it does for `run`.

For every item with >= 2 successful transcriptions, shuffles the candidate
order with `random.Random(f"{seed}:{item_id}")` and labels them A-E — the
judge never sees which model produced which candidate. The judge gets the
source image plus the shuffled candidates and scores each on:

- `character_accuracy` — kanji/kana/furigana read correctly vs. the image
- `completeness` — all visible content transcribed, nothing skipped
- `formatting` — markdown structure faithful to layout
- `hallucination_control` — 10 = nothing invented that isn't in the image
- `overall`

...plus a top-level `ranking` (best first, strict order) and `rationale`.
Judge design:

- **Blind**: the prompt only ever refers to "Candidate A/B/C"; model names
  never appear in the judge's input.
- **Structured output**: uses the Anthropic SDK's `output_config` JSON
  schema so the response reliably parses (`judging.JUDGE_SCHEMA`). The
  schema has no numeric min/max (not supported in the structured-outputs
  schema subset) — the 0-10 range is enforced by prompt text and by
  `judging.clamp_score()` afterward.
  The judge is a Fable model, so no `thinking`/`temperature`/`top_p` is
  passed (thinking is always on and counts toward `max_tokens`, hence
  16000). `stop_reason` is always checked before reading content; a
  `"refusal"` is recorded as `{"status": "refused", ...}` rather than
  treated as an error.
- **Server-side refusal fallback**: if the judge model declines an item,
  the API re-runs it on a fallback model inside the same call
  (`--fallback-model default` lets the API choose by refusal category; a
  model id pins one). Each judgment records `served_by_model`, so an item a
  different model judged is visible. The parameter is sent through
  `extra_body` because the pinned SDK (0.96) has no typed `fallbacks`
  argument — passing it as a keyword raised a `TypeError` that the old
  retry swallowed, so runs before 2026-11 never actually had a fallback. If
  the API itself rejects the fallback request, the call is retried once
  without one and says so.

Output: `runs/<run_id>/judgments/<item_id>.json` — judge model, the
label→model mapping (and its inverse), the raw per-candidate scores, the
ranking as both labels and resolved model names, rationale, usage, and
estimated cost. Resumable the same way as `run`.

### `analyze` — aggregate into league tables and a report

```
python -m benchmarks.model_eval analyze --run-id 20260706-153000
```

Reads every judgment and transcription result in the run, plus each
item's frozen `meta.json`, and computes:

- Per model: mean of each rubric dimension, mean rank, #1-rank count,
  pairwise win matrix (derived from rankings).
- Breakdowns by source (textbook/workbook), region tag, kind
  (region/page), and prompt_kind.
- A pairwise binomial sign test (`math.comb`, no scipy) on ranking-implied
  preference for every model pair that appears together in >= 1 judged item.
- Cost/latency from the run's transcription outputs: avg duration, avg/total
  estimated cost, output-length stats.
- The worst-scoring items (lowest mean `overall` across candidates), with
  the lowest-scoring candidate's judge notes as a concrete quote.

Writes `runs/<run_id>/analysis.json` (everything above, machine-readable)
and `runs/<run_id>/report.md` (markdown tables + quotes for humans).

## Design: datasets are frozen, runs are timestamped

- A dataset (`dataset/<name>/`) is built once from the live store and then
  treated as immutable — its `manifest.json` records the seed, quotas, and
  exact item ids so a run can always be traced back to what it evaluated,
  even after the store changes underneath it. `run.json` records a hash of
  the dataset's `manifest.json` for that traceability.
- A run (`runs/<run_id>/`) is a timestamped, resumable execution of a
  dataset against one or more models. Re-running the same `--run-id` only
  fills gaps (new models, retried errors) — it never overwrites completed
  work.
- To expand quotas or add a source/tag later, add entries to a quotas dict
  and build a new dataset name (`v2`, ...); don't mutate `v1` in place.
- To add a model, make sure it has a price row — in `backend/app/config.py`'s
  `MODEL_PRICING` if the app offers it, otherwise in
  `pricing.EVAL_ONLY_PRICING` — and
  pass it in `--models` / `--judge-model` / `--fallback-model` — no other
  code changes needed unless the model needs special request handling (see
  `app/providers/vlm/anthropic.py`'s capability-prefix lists).

## Metadata dictionary

**`dataset/<name>/manifest.json`**

| Field | Meaning |
|---|---|
| `seed` | seed passed to `random.Random` for sampling |
| `data_dir` | resolved path to the store this dataset was built from |
| `quotas` | the quotas dict used (see `sampling.DEFAULT_QUOTAS`) |
| `strata` | per-stratum `{stratum, candidate_count, quota, selected_count, shortfall}` |
| `shortfalls` | subset of `strata` where `shortfall > 0` |
| `item_ids` | every sampled item id, sorted |
| `git_sha` | repo commit the dataset was built at |
| `created_at` | UTC ISO timestamp |

**`dataset/<name>/items/<item_id>/meta.json`**

| Field | Meaning |
|---|---|
| `item_id` | e.g. `tb-r-vocab_list-abc12345`, `wb-p-0007` |
| `kind` | `region` \| `page` |
| `source` | `textbook` \| `workbook` (by filename substring match) |
| `doc_id`, `doc_filename` | source document |
| `chapter_id`, `chapter_title` | null for pages |
| `page` | 1-indexed page number |
| `tag` | region tag; null for pages |
| `label` | region label; null for pages |
| `bbox` | region bbox `[x1,y1,x2,y2]` (fractions); null for pages |
| `prompt_kind` | `page` \| `region` \| `vocab_list` — which prompt `run` uses |
| `image_width`, `image_height`, `image_bytes` | of the frozen `input.png` |
| `has_existing_transcription`, `existing_transcribed_model` | what's already in the store, if anything |
| `is_chained` | region has/references a `continues_to` pointer |
| `sampled_at` | UTC ISO timestamp |

**`runs/<run_id>/transcriptions/<item_id>/<model>.json`**

`status` (`ok`/`error`), `model`, `markdown`, `meta` (provider meta incl.
`usage`, `request_id`, `stop_reason`), `duration_ms`, `estimated_cost_usd`.

**`runs/<run_id>/judgments/<item_id>.json`**

`status` (`ok`/`refused`/`error`), `judge_model`, `label_to_model`,
`model_to_label`, `candidates` (per-candidate rubric scores + notes),
`ranking` (labels), `ranking_models` (resolved model names), `rationale`,
`usage`, `estimated_cost_usd`, `duration_ms`.

**`runs/<run_id>/analysis.json`** — see `analyze` above; top-level keys:
`overall`, `sign_tests`, `cost_latency`, `by_source`, `by_tag`, `by_kind`,
`by_prompt_kind`, `worst_items`.

## Module layout

Pure logic (no file I/O beyond simple reads, no network — safe to import
and unit test without an API key) is split out from the I/O/CLI layer:

| Module | Kind | Purpose |
|---|---|---|
| `items.py` | pure | source classification, item id / prompt_kind naming |
| `sampling.py` | pure | stratified sampling, quotas, shortfall handling |
| `pricing.py` | pure | `estimate_cost()` over the app's price table plus eval-only models |
| `reference_judge.py` | network | judges one transcription against image + reference (used by `make benchmark`) |
| `judging.py` | pure | label shuffling, `JUDGE_SCHEMA`, response validation/clamping |
| `analysis.py` | pure | aggregation, win matrix, binomial sign test |
| `store.py` | read-only I/O | walks the on-disk store into candidate dicts |
| `dataset_build.py` | I/O | `build-dataset`: crops/prepares images, writes dataset |
| `run_cmd.py` | I/O + network | `run`: calls the `anthropic` VLM provider |
| `judge_cmd.py` | I/O + network | `judge`: calls the Anthropic SDK directly |
| `analyze_cmd.py` | I/O | `analyze`: reads a run, writes analysis.json/report.md |
| `common.py` | I/O | Keychain API key fallback, git sha, backend sys.path setup |
| `__main__.py` | CLI | argparse subparsers dispatching to the above |

`backend/tests/test_model_eval.py` exercises the pure modules (plus
`store.py` against a fake on-disk store under `tmp_path`) — no API key or
network access required.

## Curated reports

Machine-generated per-run tables land in `runs/<run_id>/report.md`. Human-curated
writeups (findings, corrections, recommendations) live in `reports/` — the
latest is [`reports/2026-11-11-model-comparison.md`](reports/2026-11-11-model-comparison.md);
[`reports/2026-07-06-model-comparison.md`](reports/2026-07-06-model-comparison.md)
covers the first run.
