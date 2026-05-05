# Phase 2: Sentence Breakdowns — Implementation Plan

Generates structured study content (sentence-by-sentence vocab, grammar, gloss)
from already-transcribed regions via text-only VLM calls.

## Decisions

1. **Eligible tags.** Breakdowns are available on every region tag *except*
   `vocab_list` (vocab lists are already structured — a breakdown would be
   redundant). Backend allows any tag; the frontend hides the button on
   `vocab_list`.
2. **Structured output.** Use Anthropic tool-use with a JSON schema
   (`record_breakdown` tool) rather than JSON-in-text. More reliable parsing
   and free input validation.
3. **Trigger.** Explicit "Generate breakdown" button. Not auto-run after
   transcription — breakdowns cost tokens and aren't always wanted.
4. **Regenerate.** Overwrite-by-default with a confirmation dialog, mirroring
   transcription overwrite UX.
5. **Sentence segmentation.** The VLM splits sentences itself; we don't
   pre-segment. Each sentence: `{text, vocab[], grammar[], gloss}`.

## Data Model

Stored at `data/documents/{doc_id}/chapters/{chapter_id}/breakdowns/{region_id}.json`:

```json
{
  "region_id": "...",
  "model": "claude-...",
  "sentences": [
    {
      "text": "口べたで料理好きの父親を主人公にした...",
      "vocab": [
        {"word": "口べた", "reading": "くちべた", "meaning": "poor speaker"}
      ],
      "grammar": [
        {"pattern": "～を主人公に", "explanation": "with ~ as protagonist"}
      ],
      "gloss": "A manga called 'Cooking Papa'..."
    }
  ],
  "created_at": "...",
  "updated_at": "..."
}
```

Tool schema (`record_breakdown`):

```json
{
  "type": "object",
  "required": ["sentences"],
  "properties": {
    "sentences": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["text", "gloss"],
        "properties": {
          "text":    {"type": "string"},
          "gloss":   {"type": "string"},
          "vocab":   {"type": "array", "items": {
            "type": "object",
            "required": ["word", "meaning"],
            "properties": {
              "word":    {"type": "string"},
              "reading": {"type": "string"},
              "meaning": {"type": "string"}
            }
          }},
          "grammar": {"type": "array", "items": {
            "type": "object",
            "required": ["pattern", "explanation"],
            "properties": {
              "pattern":     {"type": "string"},
              "explanation": {"type": "string"}
            }
          }}
        }
      }
    }
  }
}
```

## Iterations

Each iteration is a commit-sized unit with its own tests. Verify after each
before moving on.

### Iter 1 — Text-only VLM path

Backend-only refactor; unit-testable; unblocks everything else.

- `VlmProvider.transcribe` signature: `image_bytes: bytes | None`
- Anthropic provider: when `image_bytes is None`, send a text-only message
  (no image content block)
- Audit log records `image_bytes=0` for text-only calls
- Tests:
  - Mocked SDK call with `image_bytes=None` produces no image block
  - Usage / cost extraction still works in text-only path
  - Existing image path unchanged (regression guard)

**Done when:** `make test` green; existing transcription flow unaffected.

### Iter 2 — Breakdown storage + prompt + tool schema

- `services/storage.py`: `save_breakdown`, `load_breakdown`,
  `delete_breakdown`. Path:
  `chapters/{chapter_id}/breakdowns/{region_id}.json`.
- `delete_region` and `delete_chapter` clean up associated breakdowns.
- `config.py`: `SENTENCE_BREAKDOWN_PROMPT` and `BREAKDOWN_TOOL_SCHEMA`.
- Tests: storage round-trip, cascading delete, schema is valid JSON Schema.

**Done when:** storage tests pass; no API surface yet.

### Iter 3 — Job type + API endpoints

- `jobs.py`: new `job_type="breakdown_region"`. Handler:
  1. Load region; require `transcription_md` (else fail with clear error)
  2. Text-only VLM call with breakdown prompt + tool
  3. Parse `tool_use` input → validate → save breakdown
  4. Audit-log entry tagged `job_type=breakdown_region`
- Provider/anthropic: support tool-use call path (returns parsed tool input).
- `api/regions.py`:
  - `GET .../regions/{region_id}/breakdown` → 200 with breakdown or 404
  - `POST .../regions/{region_id}/breakdown` with `{overwrite?: bool}` → 202 + job id
  - Refuses on `vocab_list` tag with 400 (defensive; UI also hides)
  - Refuses if no transcription with 409
- Tests via `TestClient`: happy path, 404, 409 (no transcription), 400
  (vocab_list), overwrite semantics, malformed tool response → job fails.

**Done when:** can `curl` POST, observe SSE progress, see breakdown file
written for a real region.

### Iter 4 — Frontend breakdown pane

- `api.ts`: `getBreakdown(...)`, `requestBreakdown(..., {overwrite})`
- `modules/breakdown-pane.ts`:
  - Renders sentences as cards: text (large), vocab table, grammar list,
    gloss (muted)
  - Loading / error / empty states
  - "Generate breakdown" button (hidden on `vocab_list` regions)
  - "Regenerate" button with confirm dialog (reuse `confirm.ts`)
  - Subscribes to job SSE for progress, refetches on completion
- Wire into `pages/chapter-view.ts` region detail panel: pane appears under
  the transcription view when transcription exists.

**Done when:** end-to-end loop on a real reading passage works in the
browser; UI states for loading/error verified.

### Iter 5 — Polish + observability + docs

- Copy-to-clipboard on individual sentences
- Verify audit-log entries carry `job_type=breakdown_region` and surface in
  `/api/costs/audit`
- Benchmark fixture: one reading passage → expected sentence count + key
  vocab terms; wired into `make benchmark`
- Docs: tick Phase 2 items in `roadmap.md`, update `plan.md` (mark Phase 2
  shipped), add a troubleshooting entry for breakdown failures (malformed
  tool input, missing transcription)

**Done when:** roadmap/plan/troubleshooting updated; benchmark passes.

## Critical Files

| File | Change |
|------|--------|
| `backend/app/providers/registry.py` | `image_bytes: bytes \| None` |
| `backend/app/providers/vlm/anthropic.py` | text-only path; tool-use path |
| `backend/app/services/storage.py` | breakdown CRUD + cascade delete |
| `backend/app/config.py` | breakdown prompt + tool schema |
| `backend/app/jobs.py` | `breakdown_region` job type |
| `backend/app/api/regions.py` | breakdown GET/POST endpoints |
| `frontend/src/api.ts` | breakdown client |
| `frontend/src/modules/breakdown-pane.ts` | new |
| `frontend/src/pages/chapter-view.ts` | wire breakdown pane |
