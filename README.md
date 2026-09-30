# Studious

A Japanese textbook study tool. Upload a PDF, organize it into chapters,
select regions of interest on pages, and transcribe them with a Vision-LLM
(Anthropic Claude). View transcriptions side-by-side with the original page
images.

Reading-passage regions can be expanded into a **sentence breakdown** —
each sentence is split out with an English gloss and per-sentence vocab
and grammar entries. **Vocab list** regions use a dedicated prompt that
emits structured `term（reading）　gloss` entries, preserving item indices
and section headers and supplying short English glosses where the
textbook does not print them. Vocab items detected in a sentence
breakdown are linked inline back to their entry in the chapter's vocab
list, so clicking a word in a sentence opens its reading and meaning.

Built to replace a manual ChatGPT-based study workflow with persistent storage,
chapter organization, and region-level transcription.

## Quick start

### Prerequisites

- Python 3.11+
- Node.js 18+ with npm 11.10+
- [uv](https://docs.astral.sh/uv/) (Python package manager)

```bash
# macOS
brew install uv

# install
make install

# config
cp .env.example .env

# store your Anthropic API key in macOS Keychain (do not put it in .env)
security add-generic-password -s ANTHROPIC_API_KEY -a "$USER" -w
# then add to ~/.zshrc:
#   export ANTHROPIC_API_KEY="$(security find-generic-password -s ANTHROPIC_API_KEY -a "$USER" -w 2>/dev/null)"

# run (two terminals)
make dev-backend     # http://localhost:8000
make dev-frontend    # http://localhost:5173
```

Open <http://localhost:5173>.

## Workflow

1. **Upload** a PDF or image
2. **Create chapters** — define page ranges within a document
3. **Draw regions** — select areas of interest on pages (reading passages, vocab lists, grammar points, exercises)
4. **Transcribe** — run VLM transcription on individual regions. The
   prompt is selected by region tag: `vocab_list` regions use a
   vocab-specific prompt that emits `term（reading）　gloss` entries,
   preserves item indices and section headers, and supplies short
   English glosses when the textbook does not print them. Other tags
   use the generic region prompt.
5. View transcriptions side-by-side with the original page
6. **Break down sentences** — for reading-passage regions, generate a
   per-sentence breakdown with English glosses and per-sentence vocab
   and grammar. Vocab items are linked inline to the chapter's vocab
   list so clicking a word reveals its reading and meaning.
7. **Link continuation regions** — when a passage or exercise spans a
   page break, toggle Link mode (button in the chapter toolbar, or `L`),
   click the source region, navigate to a later page, then click the
   continuation. The chain is followed at sentence-breakdown and
   exercise-completion time so the VLM sees the combined text. Per-region
   transcription is unchanged. Press Esc to cancel.
8. **Cite readings from exercises** (beta) — when an exercises region
   asks about a reading printed elsewhere (comprehension questions on
   the chapter's main text, or a passage in another textbook), select
   it and use **Reading references → Add…** to pick the
   `reading_passage` regions it depends on, from any document or
   chapter, in reading order. Exercise completion then gets that text
   as context, and comprehension or discussion questions come back as a
   model answer with an explanation pointing into the reading.
9. **Prepare a whole chapter** (beta — not yet exercised on a live
   chapter) — the chapter view's **Prepare chapter…** button is a
   one-click alternative to steps 4 and 6: it
   transcribes every untranscribed region, then breaks down every
   eligible one (skipping `vocab_list` regions and continuation
   targets), as a single queued job with live per-region progress. A
   confirm dialog shows the counts before anything is billed, and one
   region failing doesn't stop the rest of the chapter.
10. **Generate a chapter grammar guide** — once a chapter's
   `grammar_points` regions are transcribed, the chapter view shows
   a button that produces a structured study guide (one entry per
   pattern, with Meaning / Form / Examples / Related sections). The
   guide opens in its own view with regenerate and copy-as-markdown
   buttons; if a source region is re-transcribed afterward, the guide
   shows a "source changed" banner until you regenerate.
11. **Review the central vocab/grammar store** — every vocab-list
   transcription and sentence breakdown automatically harvests its
   vocab and grammar into a cross-textbook store (deduped by
   headword+reading / normalized pattern, with per-occurrence
   provenance). The **Vocab** and **Grammar** topbar links open
   dashboards with an inbox for newly harvested items, status tracking
   (inbox → active → known / ignored), search and filters, manual
   add/edit with notes, checkbox selection for bulk status changes and
   merging duplicate entries, and per-item sightings that link back to
   the source chapter. A **Backfill** button harvests data that
   predates the store. Words marked **known** render de-emphasized in
   sentence breakdowns (each word's popover gets an in-store status
   toggle), and the chapter view shows a "Vocab N/M known" coverage
   chip. See `docs/vocab-store-plan.md` for the Phase 3 design.
12. **Study with built-in flashcards** — the **Study** topbar link runs a
    spaced-repetition session over everything marked **active** in the
    store. Vocab gets a word→meaning card plus a sentence-context card
    built from a real textbook sighting; grammar patterns get a
    pattern→explanation card. Reveal with space, grade with 1–4
    (Again/Hard/Good/Easy); failed cards return at the end of the
    session. Scheduling is FSRS-4.5 implemented in-repo; every review is
    appended to `data/store/reviews.jsonl` and card state is derived by
    replay, so history is never lost and the scheduler can evolve
    without migrations.

## Layout

- `backend/` — FastAPI app (Python 3.11+), file-based storage.
- `frontend/` — Vite + vanilla TypeScript (no framework).
- `data/` — uploaded documents, rasterized pages, transcriptions, chapters,
  regions, the central vocab/grammar store (`store/*.jsonl`, append-only
  with latest-entry-per-id semantics), and monthly-rotated
  `llm_audit.YYYY-MM.jsonl` (append-only log of VLM calls; gitignored).
  Override the data root with `STUDIOUS_DATA_DIR`.
- `benchmarks/` — quality benchmarking tools for tracking extraction accuracy,
  including `benchmarks/model_eval/`, a model-comparison framework (frozen
  stratified datasets sampled from the live store, multi-model transcription
  runs, blind LLM-judge scoring, per-tag/source analysis). See
  `benchmarks/model_eval/README.md`.
- `apple/` — native iOS/iPadOS study companion (SwiftUI): `StudiousKit/`
  SwiftPM package (models, same-format JSONL store, FSRS-4.5 port,
  CloudKit sync, UI, Mac-side `studious-sync` CLI) plus a thin
  `Studious.xcodeproj` app shell. The same package also ships
  `studious-mac`, a native macOS companion (`make run-mac`) that bridges
  directly to `data/store/*.jsonl` — no sync layer needed on the Mac. See
  `apple/README.md`, `docs/ios-app-plan.md`, and `docs/mac-app-plan.md`.
- `docs/` — project description, roadmap, and architecture documentation.

## Configuration

Environment variables (read at startup, `.env` supported):

- `ANTHROPIC_API_KEY` — required for the Anthropic VLM provider.
- `WANIKANI_API_TOKEN` — optional; enables the WaniKani sync (levels,
  mnemonics, your own WK notes, kanji/radical drill-down). Store it in the
  Keychain like the Anthropic key:
  `security add-generic-password -s WANIKANI_API_TOKEN -a "$USER" -w`, then
  export it in `~/.zshrc` the same way. Never put it in `.env`.
- `STUDIOUS_DATA_DIR` — data root (default `./data`).
- `STUDIOUS_PDF_RENDER_DPI` — page raster DPI (default `300`).
- `STUDIOUS_LOG_LEVEL` — backend log level (default `INFO`; set `DEBUG` for
  verbose per-page events).
- `TESSERACT_CMD` — path to the Tesseract binary if not on `$PATH`.
- `STUDIOUS_VLM_EFFORT_TRANSCRIPTION` — effort level for VLM transcription
  calls (default `high`). Maps to Anthropic's `output_config.effort`.
- `STUDIOUS_VLM_EFFORT_BREAKDOWN` — effort level for sentence-breakdown tool
  calls (default `xhigh` — these are harder reasoning tasks).

Valid effort values are `low`, `medium`, `high`, `xhigh`, `max`. Effort and
adaptive thinking only apply to models that support them (Opus 4.5+ and
Sonnet 4.6+); on Haiku 4.5 they are silently omitted. The `temperature`
config field is silently dropped on Claude Opus 4.7+ and Sonnet 5+ (which
removed it).

The default VLM model is `claude-sonnet-5-5`. **Settings → General** offers
Claude Sonnet 5.5, Opus 5.5, Sonnet 5, Opus 4.8 and Opus 4.7; the choice
persists to `data/preferences.json` and is exposed via
`GET`/`PUT /api/preferences`. Sonnet 5.5 and Opus 5.5 don't accept a forced
tool call, so their breakdowns, grammar guides and exercise completions use
structured JSON output instead, with tool-call effort set per model
(Sonnet 5.5: thinking off, effort capped at `high`; Opus 5.5: adaptive
thinking at `medium`). Requests to those two models opt into Anthropic's
server-side refusal fallback, so a safety-classifier decline is retried on
the recommended fallback model rather than failing the job.

The same panel holds the **Study profile** used by exercise completions:
your JLPT level (plus an optional note), and an answer length. Answers are
written at your level with at most one or two words or grammar points one
step above it, each named in the explanation; furigana goes on kanji above
your level. Answer length sizes only the Japanese: *brief* (default) gives
one short sentence for comprehension questions and two alternative
examples for fill-in items, *standard* one to three sentences and three
examples, *detailed* fuller native-style answers. English explanations are
the same at every setting.

**Furigana.** Readings written inline as `漢字(かな)` — the textbook's own
furigana in transcriptions, and a reading on every kanji word in exercise
completions — render as furigana in the transcription pane, sentence
breakdowns, and completions. By default each reading is veiled (a faint
bar above the word) until you tap that word, so you try the reading first;
the **Hide / Show / Off** toggle in the Transcription and Sentence
breakdown headers (or `F` in the chapter view) switches to showing every
reading or none. An example's full kana line blurs the same way. Tapping a
vocab-linked word opens its popover, which already shows the reading.

Prompt caching is placed where calls actually repeat: every tool call
caches its fixed instructions, and exercise completions also cache the
exercise block's transcription and reading references, so completing
several items of one block within five minutes re-reads that context at
the cache-read rate instead of paying for it again (visible as
`cache_read_tokens` in the audit log; the Costs view prices cache writes
and reads).

## Tests

```bash
make test            # backend (pytest + coverage) and frontend (vitest)
make test-backend    # pytest only
make test-frontend   # vitest only
make test-apple      # iOS companion Swift suite (incl. FSRS golden parity)
make test-e2e        # browser smoke suite (Playwright)
```

Backend coverage runs under pytest-cov with a 75% floor. Frontend uses
Vitest + jsdom; run `cd frontend && npm run test:coverage` for a v8
coverage report.

The E2E suite drives Chromium against the real stack on dedicated ports
(backend 8765, frontend 5273) with a mock VLM provider and an isolated,
per-run data dir (`backend/.e2e-data`) — no API key or tokens needed.
One-time setup: `cd frontend && npx playwright install chromium`. On
failure, traces and screenshots land in `frontend/test-results/`.

## Reference data

`make refs` downloads pinned reference datasets and builds a local lookup
index (`data/refs/jmdict/jmdict.sqlite`, ~70 MB) used to enrich the vocab
store with dictionary glosses, part-of-speech, common-word flags, and JLPT
levels. Everything is pinned by exact URL + SHA-256 in
`backend/refs.lock.json`; downloads that don't match are rejected. The app
runs fine without the index — enrichment is simply skipped until it exists.

Attribution:

- **JMdict** (via [jmdict-simplified](https://github.com/scriptin/jmdict-simplified))
  is the property of the [Electronic Dictionary Research and Development
  Group](https://www.edrdg.org/) and is used in conformance with the
  Group's [licence](https://www.edrdg.org/edrdg/licence.html) (CC BY-SA 4.0).
- **JLPT vocabulary lists** derive from [Jonathan Waller's JLPT
  resources](https://www.tanos.co.uk/jlpt/) (CC BY), via
  [elzup/jlpt-word-list](https://github.com/elzup/jlpt-word-list). The JLPT
  has published no official lists since 2010; levels are community
  estimates.
- **WaniKani** content (levels, mnemonics, your own notes) is synced via
  the [official API v2](https://docs.api.wanikani.com/) with your personal
  token into a gitignored local cache (`data/refs/wanikani/`) for personal
  use only. WK SRS history is shown as context (e.g. "burned 2022") but
  never changes an item's study status.

## Security

Both package managers enforce a 7-day cooldown on new package versions to
protect against supply chain attacks:

- **npm**: configured in `frontend/.npmrc` (`min-release-age=7`)
- **uv**: configured in `backend/uv.toml` (`exclude-newer = "7 days"`)

Run `make audit` to check for known vulnerabilities.

## Observability

All API requests carry `X-Correlation-ID` headers for end-to-end tracing.
Backend logs are structured JSON with correlation IDs and timing breakdowns.

Every VLM API call is recorded in `data/llm_audit.jsonl` (append-only JSONL):
provider, model, token usage, duration, status, and the originating
job/document/chapter/region. See `docs/troubleshooting.md` for the schema and
tailing tips.
