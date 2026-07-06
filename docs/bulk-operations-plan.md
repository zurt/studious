# Chapter Bulk Operations ("Prepare chapter")

**Status:** Shipped 2026-07-06, **beta**. Implements the Phase 5
roadmap item "Bulk operations (transcribe/breakdown all regions in a
chapter)". Beta because it has not yet been exercised on a live
chapter with real VLM calls — the runner is tested with mock providers
and verified against an isolated server (dry-run plans, per-region
failure isolation, SSE progress, terminal snapshot race). First real
"Prepare chapter" run promotes it.

## Goal

One action on the chapter view that takes a freshly marked-up chapter
to fully studyable: transcribe every untranscribed region, then
generate breakdowns for every eligible region — one queued job, live
per-region progress, per-region failure isolation. The vocab/grammar
store fills itself through the existing ingest hooks as a side effect,
which is the point: this removes the biggest friction between marking
up a chapter and studying it.

## Shape: one job, two phases (not a fan-out)

A single new job type `bulk_chapter` that loops regions in-process,
exactly like `transcribe_pages` loops pages, rather than fanning out N
single-region jobs:

- One job id → one SSE stream → the existing per-item progress UX
  (`page-started`/`page-done` has a direct analogue).
- Phase 2 eligibility (breakdowns need transcriptions) depends on
  phase 1 output. A fan-out would need an orchestrator anyway; a
  two-phase loop gets the ordering for free. Phase 2's work list is
  computed *after* phase 1 finishes.
- The queue is sequential, so a loop and a fan-out take the same wall
  time; the loop just leaves one job record instead of N.
- Per-item failures append to `errors[]` and the job finishes
  `completed_with_errors` (same contract as `transcribe_pages`); one
  bad region never aborts the chapter.

## API

`POST /api/documents/{doc_id}/chapters/{chapter_id}/bulk`

```json
{
  "transcribe": true,
  "breakdown": true,
  "overwrite_transcriptions": false,
  "overwrite_breakdowns": false,
  "dry_run": false
}
```

- Computes the work plan (rules below) and returns it:
  `{"plan": {"transcribe": [{region_id, page, tag}…],
  "breakdown": […]}, "job_id": …}`.
- `dry_run: true` → plan only, no job (drives the confirm dialog).
- Nothing to do → 200 with empty plan and `job_id: null`, not an
  error.
- Submit → 202. The runner **recomputes** the plan at execution time
  (the preview is advisory; regions may change while queued, and
  skip-if-exists keeps resubmission idempotent).

Every region the VLM touches is a billed call, so the frontend always
shows the dry-run counts in a confirm dialog before submitting —
consistent with the Phase 1.5 UX-safety stance.

## Selection rules

Mirrors what the single-region endpoints allow, so bulk can never do
something the buttons couldn't:

- **Transcribe phase** — every region in the chapter (any tag) without
  `transcription_md`, unless `overwrite_transcriptions`. Prompt by tag
  (`VOCAB_LIST_TRANSCRIBE_PROMPT` vs `REGION_TRANSCRIBE_PROMPT`),
  model from `get_active_vlm_model()` at run time. Missing page image
  → per-region error, continue.
- **Breakdown phase** — regions where tag ≠ `vocab_list`, a
  transcription exists (including ones phase 1 just produced), the
  region is **not** a continuation target (`_find_inbound_source` —
  chain heads only, the chain's combined transcription is used), and
  no breakdown exists unless `overwrite_breakdowns`.
- Order: `list_regions` order within each phase (page, then region
  order), matching how a person would work through the chapter.

## Runner changes (`jobs.py`)

Extract the per-region cores out of `_run_region_job` /
`_run_breakdown_job` so single and bulk share one implementation —
crop→transcribe→save→harvest for transcription;
chain→call_tool→validate→annotate→save→invalidate-completions→harvest
for breakdowns — including their llm_audit calls. The single-region
runners become thin lifecycle wrappers; behavior unchanged.

`_run_bulk_chapter_job` then:

- emits `region-started` / `region-done` / `region-skipped` /
  `region-error` with `{op: "transcribe"|"breakdown", region_id, page,
  tag}` on the job's SSE stream, plus a `phase-started` event per
  phase with the item count;
- keeps `current_region`/progress counts on the job record for
  pollers;
- audits each VLM call under its existing per-call `job_type`
  (`transcribe_region` / `breakdown_region`) so cost dashboards don't
  change; the shared bulk `job_id` in the audit context ties a run
  together.

## Frontend (chapter view)

- Topbar action **"Prepare chapter…"**: dry-run → confirm dialog
  (reuse `modules/confirm.ts` and existing button styles — no new
  parallel controls) reading "Transcribe N regions, break down M
  regions" (or "Nothing to do — all regions are transcribed and broken
  down"), → POST → progress.
- Progress: subscribe with the existing `watchJob` SSE helper; show a
  compact progress indicator (n/m per phase); refresh the affected
  region row's status chips on each `region-done`/`region-error`
  (region list already re-renders from region data; use
  `modules/events.ts` if a bus signal is cleaner than a direct
  callback).
- Completion toast: "Chapter ready" or "Done with K errors" (errors
  visible per-region in the list, as today).

## Testing

- **Backend** (pytest, existing fake-provider patterns from
  `test_jobs_with_mock_provider.py` / `test_chapters_regions.py`):
  - plan selection: skips transcribed regions, vocab_list excluded
    from breakdowns, continuation targets excluded, overwrite flags
    widen the plan, dry_run submits nothing;
  - runner: both phases run in order; a region newly transcribed in
    phase 1 is picked up by phase 2; a failing region →
    `completed_with_errors` and later regions still processed;
    vocab_list harvest fires from the bulk path; SSE event sequence;
  - endpoint: 404s, empty plan → `job_id: null`.
- **Frontend** (vitest): api helper + plan-count formatting where the
  existing test patterns make it cheap; the SSE/render path is covered
  by the module tests' conventions.
- `make benchmark` after implementation: the refactor touches the
  transcription pipeline in `jobs.py` (per CLAUDE.md), even though
  prompts/preprocessing are unchanged — expect no metric movement.

## Out of scope

- Bulk exercise completions (roadmap 2.3) — will reuse the same
  phase/event machinery once this lands.
- Cancelling a running bulk job — the queue has no cancellation today;
  a chapter-sized job makes this worth revisiting, noted for Phase 5
  polish.
- Parallel VLM calls — the queue is deliberately sequential; revisit
  only if chapter-prepare wall time actually hurts in practice.
