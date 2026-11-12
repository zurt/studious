# Studious: Chapter-Based Study Workflow Tool

## Context

The user is an intermediate-to-advanced Japanese learner who previously used ChatGPT with page screenshots to study from multiple textbooks (生きた素材で学ぶ, Quartet, Tobira). That workflow was painful: re-entering prompts each session, losing context, no persistent vocab/grammar store, manual screenshot management.

Tesseract OCR proved too low-quality for Japanese textbook pages (~22% CER). The tool is pivoting from a generic OCR/VLM transcription viewer to a structured study workflow powered by VLM (Claude) that solves these pain points.

## Platform Strategy

**Web MVP now, native later.** The web app is the fastest way to iterate on the VLM prompts, data model, and study workflow — the hard parts of this project. Once the workflow stabilizes, build SwiftUI apps (macOS/iOS/iPad) that call the same backend API. Don't invest in web-specific polish (animations, offline, PWA); the web app is a usable prototype.

*Update 2026-07-02:* the first native piece shipped — an iOS/iPadOS study companion under `apple/` (SwiftPM package + Xcode shell) that syncs the vocab/grammar stores and review log through CloudKit rather than calling the backend API; see `docs/design/ios-app-plan.md`. The Mac web app remains the harvest/curation surface.

*Update 2026-07-05:* next native piece planned — a macOS app (`docs/design/mac-app-plan.md`) reusing the same SwiftUI package for study/browse/curation, operating directly on the backend's canonical `data/store/` JSONL so it doubles as the bridge to the local FastAPI server. The web app still owns the harvest workflow (documents, transcription, regions).

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

**Job queue changes** in `backend/app/jobs/`:
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

**Status:** ✅ Shipped (2026-05-05). See `docs/design/sentence-breakdowns-plan.md` for the iteration log.

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
`docs/design/cloudkit-sync-plan.md`). Full schemas, milestone breakdown (3.1–3.5),
licensing notes, and open questions live in `docs/design/vocab-store-plan.md`. Key
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
- **Anki push**: `POST /api/anki/push/preview` (read-only dry run) and
  `POST /api/anki/push` (`confirm: true`; the only writes to Anki, limited to
  `createDeck` and `addNotes`) send a chapter's first `limit` shortlist
  candidates into the `ANKI_PUSH_DECK` deck as `ANKI_PUSH_NOTE_TYPE` notes
  (`services/anki_push.py`). A note's sentence is always the item's stored
  generated `example` (`source: "generated"`), else empty: authentic textbook
  sentences are above the learner's level and are never put on a card. The
  preview reports `sentence_source` (`generated` or null) per row and
  `counts.needs_example` / `needs_example_ids` (every will-add row without a
  stored generated example).
- **Speech engines** (`services/tts.py`, `services/voicevox.py`): `say`
  (default; `tts_voice` = `auto`, i.e. every installed ja_JP `(Enhanced)` /
  `(Premium)` voice sorted by name, else plain Kyoko, or an explicit
  comma-separated list; the voice is picked per card from the pool by a
  sha256 of the Word, with next-voice then plain-Kyoko fallback per clip;
  `GET /api/tts/status` returns `voices`, `setting`, `installed`;
  `POST /api/tts/test {voice}` is limited to installed ja_JP voices) or a VOICEVOX-compatible engine (`GET /version`, `GET /speakers`,
  `POST /audio_query`, `POST /synthesis`; all assumptions in `voicevox.py`).
  Settings `tts_engine` / `tts_url` / `tts_speaker` (env `STUDIOUS_TTS_*`) are
  overridden by `preferences.json` keys of the same names (PUT
  `/api/preferences`; `""` clears). WAV is converted with `afconvert -f m4af -d aac`
  else kept `.wav`; clips cached under `data/audio/` by hash of engine,
  voice/speaker, text and expected reading. `synthesize(text, reading)` compares
  the engine's kana with the card's reading (long vowels and は/へ/を
  normalised) and re-queries with the reading on a mismatch
  (`reading_corrected` in the push result). Endpoints: `GET /api/tts/status`
  (engine, voice, reason), `GET /api/tts/speakers`, `POST /api/tts/test`.
- **Dictionary links and `meaning_context`**: `jmdict.lookup` tries the
  surface, then without list markers (`store.strip_list_marker`), without a
  pattern tilde + particle, without する/な (`store.stem_parts`), and only
  then the reading, accepted for kana-only headwords or when every kanji
  (digits equal kanji numerals) of the headword is in one of the entry's
  kanji forms; the hit carries `match` (surface | marker | pattern | stem |
  reading). `enrich.ENRICH_VERSION` (stamped as `enrich_version`) re-links
  every item once when bumped, clears `jmdict_seq`/`pos`/JLPT/common when a
  link is dropped, skips no-op writes and logs `enrich_done` with relinked /
  unlinked / unchanged. Vocab items carry `meaning_context`: the textbook's
  own meaning (source llm or user), set at creation and on PATCH, backfilled
  once from `store.meaning_history()` (latest llm/user record per item), never
  replaced by enrichment, restored into `meaning` when a link is dropped.
  The card meaning and the example-sentence prompt prefer it. Harvest does
  not strip list markers from headwords (only the vocab-list parser strips
  numeric indices and `-*•` bullets); existing headwords are not rewritten.
- **Card quality** (`services/anki_push.py`): `Word Meaning` is shortened
  (`card_meaning`: first 3 glosses, 40 chars) only when
  `meaning_source == "jmdict"` (values: `llm` default, `jmdict`, `user`).
  `store.stem_parts` / `store.stem_variants` are the one する/な stem rule
  (`freq._stem` delegates); `anki.lookup` has a `stem` tier between `exact`
  and `entry`, treated like them by the shortlist, badge and push (in-batch
  duplicates compare stems; variants are checked in the same
  `canAddNotesWithErrorDetail` call). Audio: `services/tts.py` (`say -v
  <voice> --file-format=m4af --data-format=aac -o tmp -f textfile`, cached
  `data/audio/<hash>.m4a`), settings `tts_voice` / `anki_push_audio`; the
  push attaches per-note `audio` media (`anki_push.attach_audio`, the only
  place that knows the shape; confirmed against a real Anki: both
  `[sound:…]` tags land in the fields), never in the
  can-add notes; preview reports `audio {enabled, available, voice}`, the
  result `audio {enabled, attached, failed}`; `GET /api/tts/status`,
  `GET /api/vocab/{id}/audio?part=word|sentence`.
- **Example sentences**: a vocab item may carry `example` =
  `{sentence, surface, furigana, gloss, source: "generated", model,
  created_at}` (plain text; furigana in Anki `漢字[よみ]` syntax; the `<b>`
  is added when a note is built). Written with `store.update_item`; Swift
  readers keep unknown item keys (raw `[String: JSONValue]`).
  `services/examples.py` generates them in batches of 20 through the VLM
  provider's `call_tool` (tool `record_examples`, `EXAMPLE_SENTENCES_PROMPT`
  and `EXAMPLE_SENTENCES_TOOL_SCHEMA` in `config.py`, instructions cached,
  effort `vlm_effort_examples`, the active model), validates every entry,
  retries failures once with the reason, and audits each call as
  `job_type: "example_sentences"`. `POST /api/vocab/examples`
  `{item_ids (1..40), force}` returns per item `generated | kept | failed`
  plus token/cost totals (503 without an API key, 502 when every call
  failed); `DELETE /api/vocab/{id}/example` clears it.
- **Anki import (read-only)**: AnkiConnect on `127.0.0.1:8765`
  (`ANKI_CONNECT_URL`), snapshot at `data/refs/anki/snapshot.json`
  (`GET /api/refs/anki/status`, `POST /api/refs/anki/sync`). Card state is
  joined onto `/api/vocab` items at read time and never stored in the
  append-only JSONL.
- **Frequency rank.** `classifications.freq_rank` (1 = most frequent) comes
  from the JPDB-derived Yomitan frequency list, built by `make refs` into
  `data/refs/freq/jpdb-freq.sqlite` (git-ignored local download; kanji
  spelling and kana spelling are ranked separately, the item's own spelling
  wins). It does not feed `priority_group`.
- **Chapter shortlist.** `GET /api/vocab` takes `shortlist=true` (candidates
  only, own ordering, adds a `shortlist` summary of hidden counts) or
  `excluded=<reason>` (the hidden items; reasons `status_known`,
  `status_ignored`, `in_anki`, `grammar_like`, `not_dictionary`, `basic`);
  the two are mutually exclusive. Items carry `shortlist_excluded` and
  `wk_burned`, joined at read time like `anki`, never stored.
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
  documented in milestone 3.5 and implemented by the Phase 5 iOS
  companion under `apple/` (see `docs/design/ios-app-plan.md`).

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
   (`docs/design/cloudkit-sync-plan.md`).

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
| Blind LLM-judge model eval (image-grounded rubric + ranking) | No verified ground truth exists for most regions; judging against the source image with anonymized, order-shuffled candidates avoids anchoring on any one model's style. Frozen seeded datasets keep runs reproducible/expandable |

## Critical Files

| File | Changes |
|------|---------|
| `backend/app/services/storage.py` | Chapter, region, breakdown, vocab/grammar CRUD |
| `backend/app/services/pdf.py` | `crop_region` function |
| `backend/app/jobs/` | Job queue (`manager.py`) and one module per job type |
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
