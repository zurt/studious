# Studious: Chapter-Based Study Workflow Tool

## Context

The user is an intermediate-to-advanced Japanese learner who previously used ChatGPT with page screenshots to study from multiple textbooks (生きた素材で学ぶ, Quartet, Tobira). That workflow was painful: re-entering prompts each session, losing context, no persistent vocab/grammar store, manual screenshot management.

Tesseract OCR proved too low-quality for Japanese textbook pages (~22% CER). The tool is pivoting from a generic OCR/VLM transcription viewer to a structured study workflow powered by VLM (Claude) that solves these pain points.

## Platform Strategy

**Web MVP now, native later.** The web app is the fastest way to iterate on the VLM prompts, data model, and study workflow — the hard parts of this project. Once the workflow stabilizes, build SwiftUI apps (macOS/iOS/iPad) that call the same backend API. Don't invest in web-specific polish (animations, offline, PWA); the web app is a usable prototype.

**Frontend: vanilla TypeScript + Vite.** Dropping React. The app's needs (routes, fetch JSON, render HTML, canvas drawing) don't require a framework. Vite stays for HMR and build tooling. If reactive data binding is needed later (Phase 3 vocab status syncing), add Vue or a small reactive library then.

## Existing Foundation

The backend (FastAPI + file-based storage) provides: PDF rendering, VLM provider (Anthropic Claude), async job queue with SSE, structured logging. The frontend will be rewritten in vanilla TS but the backend is reusable as-is.

---

## Phase 1: Chapters + Regions + Targeted Transcription

**Goal:** Replace the "upload screenshot, re-enter prompt" loop. User marks up a PDF into chapters, selects regions of interest, gets persistent VLM transcriptions.

### Data Model

Extend the on-disk structure:

```
data/documents/{doc_id}/
  meta.json                              # (unchanged)
  original.{ext}                         # (unchanged)
  pages/{nnnn}.png                       # (unchanged)
  transcriptions/{nnnn}.json             # (unchanged — full-page transcription)
  chapters/{chapter_id}/
    meta.json                            # id, doc_id, title, page_start, page_end, order, created_at
    regions/{region_id}.json             # id, chapter_id, page, bbox, tag, label, transcription_md, created_at
```

**Chapter meta.json:**
```json
{
  "id": "a1b2c3d4e5f6",
  "doc_id": "348ce521fca7",
  "title": "第14課 男の料理と市民権",
  "page_start": 45,
  "page_end": 52,
  "order": 14,
  "created_at": "..."
}
```

**Region {region_id}.json:**
```json
{
  "id": "f6e5d4c3b2a1",
  "chapter_id": "a1b2c3d4e5f6",
  "page": 47,
  "bbox": [0.05, 0.12, 0.95, 0.65],
  "tag": "reading_passage",
  "label": "本文",
  "transcription_md": null,
  "created_at": "..."
}
```

- `bbox`: normalized [x1, y1, x2, y2] as fractions (0.0–1.0), resolution-independent
- `tag`: one of `vocab_list`, `grammar_points`, `reading_passage`, `exercises`, `instructions`, `other`

### Backend

**New storage functions** in `backend/app/services/storage.py`:
- Chapter CRUD: `create_chapter`, `list_chapters`, `load_chapter`, `update_chapter`, `delete_chapter`
- Region CRUD: `create_region`, `list_regions`, `load_region`, `update_region`, `delete_region`

**New image function** in `backend/app/services/pdf.py`:
- `crop_region(image_path, bbox, max_edge) -> bytes` — crop page image to normalized bbox, prepare for VLM

**New API routers:**

`backend/app/api/chapters.py`:
- `POST /api/documents/{doc_id}/chapters` — create chapter (title, page_start, page_end, order)
- `GET /api/documents/{doc_id}/chapters` — list chapters
- `GET /api/documents/{doc_id}/chapters/{chapter_id}` — get chapter with regions
- `PUT /api/documents/{doc_id}/chapters/{chapter_id}` — update chapter
- `DELETE /api/documents/{doc_id}/chapters/{chapter_id}` — delete chapter + regions

`backend/app/api/regions.py`:
- `POST /api/documents/{doc_id}/chapters/{chapter_id}/regions` — create region
- `GET /api/documents/{doc_id}/chapters/{chapter_id}/regions` — list regions
- `PUT .../{region_id}` — update region
- `DELETE .../{region_id}` — delete region
- `POST .../{region_id}/transcribe` — queue VLM transcription for cropped region

**Job queue changes** in `backend/app/jobs.py`:
- Add `job_type` field to job payload: `"transcribe_pages"` (existing), `"transcribe_region"` (new)
- Dispatch in `_run_job` based on `job_type`
- Region transcription: crop image → VLM call → save transcription_md back to region file

**New prompt** in `backend/app/config.py`:
```python
REGION_TRANSCRIBE_PROMPT = (
    "You are transcribing a selected region from a Japanese textbook page. "
    "Output GitHub-flavored Markdown preserving the content exactly as written. "
    "When furigana is present, write it inline as 漢字(かんじ). "
    "Output only the Markdown, with no preamble or commentary."
)
```

**Modify existing:**
- `GET /api/documents/{doc_id}` — include `chapters` summary in response
- Register new routers in `backend/app/main.py`

### Frontend (vanilla TS rewrite)

Replace the React frontend with vanilla TypeScript + Vite. Keep the same Vite config (HMR, API proxy to :8000). No framework, no JSX.

**Architecture:**
- Simple hash router or `pushState` router (~50 lines)
- Pages as functions that return DOM elements or render into a container
- Shared `api.ts` module (port existing fetch logic, drop React-specific parts)
- CSS stays as a single file with CSS variables

**Pages:**

`library.ts` — document grid + upload (port from existing Library.tsx)

`document-view.ts` — page viewer + chapter sidebar
- Left sidebar: chapter list, "New Chapter" button → modal (title, page_start, page_end)
- Main area: page image with navigation, existing transcription display
- Show colored page indicators for pages belonging to chapters

`chapter-view.ts` — core study page (new, route: `/doc/:id/chapter/:chapterId`)
- Top bar: chapter title, page range, back link
- Left pane: page image with canvas overlay for region drawing + display
- Right pane: region list for current page

**Modules:**

`region-drawer.ts` — canvas overlay for bbox interaction
- `<canvas>` positioned over page `<img>`
- mousedown/mousemove/mouseup to draw rectangles
- Convert pixel coords to normalized bbox (÷ natural image dimensions)
- Render existing regions as semi-transparent colored overlays (color per tag)
- Returns bbox on completion; caller handles the create-region API call

`region-list.ts` — renders region list for a page
- Each region: tag badge, label, transcription preview
- Transcribe button (POST .../{region_id}/transcribe)
- Delete button

`router.ts` — minimal client-side router
- Match patterns: `/`, `/doc/:id`, `/doc/:id/chapter/:chapterId`
- Mount/unmount page functions on navigation

### Tests

- Storage: chapter + region CRUD round-trips
- pdf.py: `crop_region` produces valid PNG bytes, respects bbox normalization
- API: chapter + region endpoints (happy path + 404s)
- Job queue: region transcription job type dispatches correctly

### Verification

1. Upload a PDF, create a chapter with page range
2. Navigate to chapter view, draw regions on a page
3. Tag regions as vocab_list, reading_passage, etc.
4. Trigger transcription on a region, verify VLM output is stored and displayed
5. Navigate between pages within the chapter, see region overlays persist
6. Run `make test`

---

## Phase 2: Sentence Breakdowns + Vocab/Grammar Extraction

**Status:** ✅ Shipped (2026-05-05). See `docs/sentence-breakdowns-plan.md` for the iteration log.

**Goal:** Generate structured study content from transcribed regions — sentence-by-sentence breakdowns with vocab, grammar, and gloss.

### Backend

**New storage** in `storage.py`:
- `save_breakdown(doc_id, chapter_id, region_id, data)`, `load_breakdown(...)`
- Stored at `chapters/{chapter_id}/breakdowns/{region_id}.json`

**Breakdown schema:**
```json
{
  "region_id": "...",
  "sentences": [
    {
      "text": "口べたで料理好きの父親を...",
      "vocab": [{"word": "口べた", "reading": "くちべた", "meaning": "poor speaker"}],
      "grammar": [{"pattern": "～を主人公に", "explanation": "with ~ as protagonist"}],
      "gloss": "A manga called 'Cooking Papa'..."
    }
  ],
  "created_at": "..."
}
```

**Provider change:** Make `VlmProvider.transcribe` accept `image_bytes: bytes | None`. When `None`, Anthropic provider sends text-only message (no image tokens — cheaper and faster for analysis prompts).

**New prompts** in `config.py`:
- `SENTENCE_BREAKDOWN_PROMPT` — break down text sentence by sentence (vocab + grammar + gloss), output JSON
- `VOCAB_EXTRACT_PROMPT` — extract intermediate+ vocab as JSON array
- `GRAMMAR_EXTRACT_PROMPT` — extract grammar points as JSON array

**New job type:** `"breakdown_region"` — loads region transcription_md, sends text-only VLM call with breakdown prompt, parses JSON response, saves breakdown file.

**New endpoints** in `backend/app/api/regions.py`:
- `GET .../{region_id}/breakdown` — get breakdown
- `POST .../{region_id}/breakdown` — queue breakdown generation

### Frontend

**New module: `breakdown-pane.ts`**
- Renders sentence breakdown as cards/accordions (plain DOM)
- Each sentence: text (large), vocab table, grammar points, gloss (muted)
- Generate button triggers POST if no breakdown exists yet

**Wire into chapter-view:** region detail panel shows breakdown when it exists, or a generate button when not.

---

## Phase 1.5: UX Safety + LLM Observability

**Goal:** Add confirmation dialogs for destructive actions, audit logging for all LLM API calls, and cost tracking based on token usage.

### Confirmation Dialogs

- Confirmation modal before delete operations (regions, chapters, documents)
- Reusable `confirm(title, message) -> Promise<boolean>` utility
- Wire into all existing delete handlers in chapter-view, document-view, library

### LLM Audit Log

**On-disk structure:**
```
data/
  llm_audit.jsonl    # append-only, one JSON object per LLM API call
```

**Schema (one JSONL line):**
```json
{
  "id": "req_abc123",
  "timestamp": "2026-04-26T12:00:00Z",
  "provider": "anthropic",
  "model": "claude-sonnet-4-20250514",
  "job_type": "transcribe_region",
  "doc_id": "...",
  "chapter_id": "...",
  "region_id": "...",
  "input_tokens": 1500,
  "output_tokens": 800,
  "image_tokens": 2400,
  "duration_ms": 3200,
  "status": "success",
  "error": null
}
```

- Log every LLM API call in the VLM provider layer (after response or on error)
- Include enough context to trace back to the document/chapter/region
- Append-only JSONL — same pattern as vocab store

### Cost Tracking

**Per-model token pricing table** in `backend/app/config.py`:
```python
MODEL_PRICING = {
    "claude-sonnet-4-20250514": {"input": 3.0, "output": 15.0, "image": 3.0},  # per 1M tokens
    # ... add models as needed
}
```

- Calculate estimated cost per request from audit log entry (input_tokens × rate + output_tokens × rate + image_tokens × rate)
- `GET /api/costs` — aggregate cost summary (total, by model, by doc, by time range)
- `GET /api/costs/audit` — paginated audit log with cost per entry
- Frontend: cost summary widget (total spend, recent requests) — location TBD

### Implementation Notes

- Anthropic API response includes `usage.input_tokens` and `usage.output_tokens` — extract these in the provider
- Image token count: Anthropic counts image tokens based on image dimensions; the API response includes them in `input_tokens`. Track image bytes sent so we can estimate the image token portion separately if needed.
- Cost estimates are just that — estimates. Display with appropriate caveat.

**Pricing-table maintenance.** `MODEL_PRICING` is a hand-maintained constant.
Anthropic has no pricing API (the Models API returns capabilities/context
windows but no per-token cost), so there's no clean way to refresh it without
either a third-party structured feed (e.g. LiteLLM's
`model_prices_and_context_window.json`) or scraping the official pricing page.
A self-service "update pricing" feature in the settings usage view is deferred
(roadmap Phase 1.5) pending a decision on that source vs. the project's
supply-chain rules. **Interim process: review and update `MODEL_PRICING` by
hand roughly every two weeks during development** (cross-check against
platform.claude.com pricing). Keep Opus 4.5–4.8 at $5/$25, Sonnet at $3/$15,
Haiku at $1/$5 until Anthropic changes published rates.

---

## Phase 3: Central Vocab/Grammar Store

**Goal:** Vocab and grammar harvested from textbooks accumulate into a single
cross-textbook store — dictionary-linked, graded, editable — that becomes the
long-term core study artifact and eventually powers built-in SRS and an iOS
companion app.

**Design agreed 2026-07-01; all milestones (3.1–3.5) shipped 2026-07-01**
(see roadmap for the item-level record; the 3.5 CloudKit design doc is
`docs/cloudkit-sync-plan.md`). Full schemas, milestone breakdown (3.1–3.5),
licensing notes, and open questions live in `docs/vocab-store-plan.md`. Key
decisions:

- **Canonical identity via JMdict.** Items link to a JMdict entry id
  (`jmdict_seq`); headword+reading is only the fallback key for unlinked
  items. Textbook occurrences are *sightings* (with provenance and the full
  example sentence) on one canonical entry, so surface variants (口下手 vs
  口べた, conjugated forms) don't fragment the store.
- **Local dictionary enrichment.** Bundle JMdict (jmdict-simplified JSON,
  pinned + checksummed download; CC BY-SA attribution) for glosses, POS,
  common-word flags. jisho.org is an outbound link, not a data source.
- **WaniKani via official API** (personal token in Keychain, cache
  gitignored): subjects (levels, mnemonics, vocab→kanji→radical component
  graph), the user's own study notes, and SRS history. WK history is a
  display signal only — the user completed all 60 levels years ago and the
  knowledge has atrophied, so "burned on WK" must never auto-mark an item
  known. A vocab→kanji→radical drill-down view surfaces WK mnemonics and
  personal notes for recall.
- **Multiple classification signals, derived priority.** JLPT level
  (community lists), frequency rank, JMdict common flags, WK level, and
  textbook order are stored independently; a derived `priority_group`
  (pure function, recomputable) orders study queues.
- **Curation status ≠ SRS state.** `unreviewed → active → known/ignored` is
  a curation lifecycle with an inbox for auto-ingested items; SRS state
  derives from an append-only review-event log (`reviews.jsonl`) consumed by
  an in-repo FSRS scheduler (milestone 3.4).
- **CloudKit-ready schema now, sync later.** UUID ids, `updated_at`,
  tombstones, append-only logs, flat records. The iOS/CloudKit topology is
  documented in milestone 3.5 but not built until Phase 5.

### Milestones

1. **3.1 Foundation + harvest** — stores under `data/store/`, ingest hooks
   (breakdown generation + vocab_list transcription parse), idempotent
   backfill over existing data, dedup, status lifecycle, `/api/vocab` +
   `/api/grammar`, dashboard with inbox.
2. **3.2 Enrichment + classification** — JMdict bundling and linking, JLPT +
   frequency datasets, WaniKani sync + drill-down, outbound links, priority
   grouping.
3. **3.3 Curation** — manual add/edit, merge duplicates, bulk actions,
   known-word de-emphasis in breakdowns, chapter coverage stats.
4. **3.4 Built-in SRS (web)** — review event log, in-repo FSRS-4.5, queue
   API, flashcard UI at `/study` (word-first + sentence-context cards from
   sightings, graded per card).
5. **3.5 Sync groundwork** — CloudKit record-mapping design doc only
   (`docs/cloudkit-sync-plan.md`).

**State syncing:** status changes need to reflect across dashboard/breakdown
views — add a simple pub/sub event bus (evaluate a reactive lib only if that
gets painful).

**Topbar:** Add "Study", "Vocab", and "Grammar" links.

## Phase 4: Export + Exercises

- Anki TSV export endpoint (`GET /api/export/anki`)
- Export button on VocabDashboard
- Exercise-specific prompt and walkthrough UI
- Grammar dashboard (parallel to vocab)

## Phase 5: Polish

- Bulk operations (transcribe/breakdown all regions in a chapter)
- Region editing (resize, move, reorder)
- Reading progress tracking
- Mobile-responsive layout

---

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Keep full-page transcription alongside regions | Full-page is a quick first pass; regions scope down for targeted study. Both coexist. |
| One region per page (for now) | Simpler to implement; revisit linked/multi-page regions if it feels clunky in practice |
| Normalized bbox (0.0–1.0) | Resolution-independent; works at any DPI or display size |
| Breakdowns stored per-region | Matches job queue model (one VLM call = one file); regions are the unit of work |
| Global vocab/grammar store | User studies across multiple textbooks; needs cross-reference |
| JSONL + derived index | Human-readable, append-safe, no database dependency; rebuilds trivially at this scale |
| Text-only VLM for analysis | Cheaper (no image tokens), faster; analysis operates on already-transcribed markdown |
| Single job queue with job_type dispatch | Simple, prevents API rate limiting, reuses SSE broadcast pattern |
| JSONL audit log for LLM calls | Same append-only pattern as vocab store; human-readable, no DB dependency; enables cost tracking without external services |
| JMdict entry id as canonical vocab identity | headword+reading alone fragments across surface variants; JMdict linkage also gives free glosses/POS/common flags and stable jisho links |
| Dictionary-first enrichment (no LLM, no scraping) | Bundled JMdict is instant, free, offline, deterministic; LLM glosses only fill gaps; jisho.org unofficial API avoided entirely |
| WaniKani SRS history is display-only | User finished WK long ago and knowledge atrophied; auto-marking burned items "known" would poison the study queue |
| Curation status separate from SRS state | Status (`unreviewed/active/known/ignored`) is human judgment; SRS state is derived from an append-only review log — mixing them breaks both |
| FSRS-4.5 in-repo, SRS state derived by event replay | Small, well-specified algorithm — no dependency; replaying `reviews.jsonl` per card means formula changes need no data migration and history is never lost |
| CloudKit-ready schema from day one | UUIDs, `updated_at`, tombstones, append-only event logs cost nothing now and avoid a migration when the iOS companion arrives |
| Cost estimation from API response tokens | Anthropic includes token counts in responses; combine with a pricing table for estimates. Not billing-accurate, but good enough for awareness |

## Critical Files

| File | Changes |
|------|---------|
| `backend/app/services/storage.py` | Chapter, region, breakdown, vocab/grammar CRUD |
| `backend/app/services/pdf.py` | `crop_region` function |
| `backend/app/jobs.py` | Job type dispatch, region transcription + breakdown handlers |
| `backend/app/config.py` | New VLM prompt templates, model pricing table (Phase 1.5) |
| `backend/app/providers/vlm/anthropic.py` | Text-only VLM call path (Phase 2), audit log writes (Phase 1.5) |
| `backend/app/api/costs.py` | Cost summary + audit log endpoints (Phase 1.5) |
| `data/llm_audit.jsonl` | Append-only LLM request audit log (Phase 1.5) |
| `backend/app/providers/registry.py` | Update VlmProvider protocol signature (Phase 2) |
| `backend/app/main.py` | Register new routers |
| `frontend/src/` | Full rewrite: vanilla TS replacing React |
| `frontend/src/pages/chapter-view.ts` | New — core study page with region drawing |
| `frontend/src/modules/region-drawer.ts` | New — canvas bbox overlay |
| `frontend/src/modules/router.ts` | New — minimal client-side router |
| `frontend/src/api.ts` | Port from React version, add chapter/region endpoints |
| `frontend/package.json` | Remove react, react-dom, react-router-dom, react-markdown, remark-gfm; add marked or similar for markdown |
