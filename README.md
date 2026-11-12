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
   chip. See `docs/design/vocab-store-plan.md` for the Phase 3 design.
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
- `benchmarks/` — two tools, both scored by an LLM judge: the regression
  benchmark (`make benchmark`: committed fixtures vs. the default model,
  run before and after a pipeline change) and `benchmarks/model_eval/`, a
  model-comparison framework (frozen stratified datasets sampled from the
  live store, multi-model runs, blind ranking, per-tag/source analysis).
  See `benchmarks/README.md`.
- `apple/` — native iOS/iPadOS study companion (SwiftUI): `StudiousKit/`
  SwiftPM package (models, same-format JSONL store, FSRS-4.5 port,
  CloudKit sync, UI, Mac-side `studious-sync` CLI) plus a thin
  `Studious.xcodeproj` app shell. The same package also ships
  `studious-mac`, a native macOS companion (`make run-mac`) that bridges
  directly to `data/store/*.jsonl` — no sync layer needed on the Mac. See
  `apple/README.md`, `docs/design/ios-app-plan.md`, and `docs/design/mac-app-plan.md`.
- `docs/` — project description, roadmap, and architecture documentation;
  `docs/README.md` indexes what is current, shipped design, or archived.

## Configuration

Environment variables (read at startup, `.env` supported):

- `ANTHROPIC_API_KEY` — required for the Anthropic VLM provider.
- `WANIKANI_API_TOKEN` — optional; enables the WaniKani sync (levels,
  mnemonics, your own WK notes, kanji/radical drill-down). Store it in the
  Keychain like the Anthropic key:
  `security add-generic-password -s WANIKANI_API_TOKEN -a "$USER" -w`, then
  export it in `~/.zshrc` the same way. Never put it in `.env`.
- `ANKI_CONNECT_URL` — AnkiConnect endpoint for the Anki import (default
  `http://127.0.0.1:8765`).
- `STUDIOUS_TTS_VOICE` — macOS `say` voice for card audio (default
  `Kyoko`); `ANKI_PUSH_AUDIO` — attach audio on send (default true).
- `ANKI_PUSH_DECK` / `ANKI_PUSH_NOTE_TYPE` — where "Send to Anki" puts new
  cards (defaults `Studious` and `Kaishi 1.5k`).
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

The default VLM model is `claude-opus-5-5` (chosen on the November 2026
model comparison: `benchmarks/model_eval/reports/2026-11-11-model-comparison.md`).
**Settings → General** offers
Claude Opus 5.5, Sonnet 5.5, Sonnet 5, Opus 4.8 and Opus 4.7; the choice
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
make lint            # ruff (backend, benchmarks) + Biome (frontend)
```

CI runs all of the above on every pull request (the Swift suite on a
macOS runner), plus `npm audit` and `pip-audit`, and re-runs weekly so
new advisories surface while the repo is idle.

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

`make refs` also fetches a **word-frequency list** (the JPDB-derived Yomitan
frequency dictionary from the releases of
[MarvNC/jpdb-freq-list](https://github.com/MarvNC/jpdb-freq-list), ~6 MB zip)
into the git-ignored `data/refs/downloads/` and builds
`data/refs/freq/jpdb-freq.sqlite` from it. It gives vocab items a
`freq_rank` (1 = most frequent), shown as a `#1.2k` badge and sortable with
"By frequency" on the vocab dashboard. It is a local download only: the
repository has no licence file and the data derives from jpdb.io, so it is
never committed or redistributed. After `make refs`, the backend gives
existing items their rank on its next start or harvest, or immediately via
`POST /api/store/enrich`.

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

## Anki bridge

If you study flashcards in Anki, **Sync Anki** on the vocab dashboard pulls
the state of every card (new / learning / young / mature / suspended) and
shows an `Anki · mature` badge on matching store items, plus an Anki filter.
It needs the Anki desktop app open with the
[AnkiConnect](https://ankiweb.net/shared/info/2055492159) add-on installed,
and the import only ever reads: nothing is written to Anki or to the vocab
store by Sync Anki. The
snapshot lives in `data/refs/anki/snapshot.json` (replaced atomically; a
failed sync keeps the previous one) and is matched to store items at read
time. The word and reading fields are picked per note type by name
(`GET /api/refs/anki/status` shows which).

### Sending a chapter's words to Anki

With the shortlist on and a textbook and chapter selected, **Send to Anki…**
(next to the summary line) previews the first 125 candidates: how many will
be added, the deck, the first ten words, how many are skipped (already in
Anki anywhere in the collection), how many have no example sentence, and
how many match an existing card by spelling only. You can change the count,
then **Send N words**. Nothing is written until you press that button.

Cards go into a separate deck (`ANKI_PUSH_DECK`, default `Studious`, created
if missing) using your existing note type (`ANKI_PUSH_NOTE_TYPE`, default
`Kaishi 1.5k`) so they look like your other cards. Word, reading, meaning,
furigana and frequency are filled in (`Notes` holds only your own note on
the word; the source is in the tags); the example sentence and its translation are chosen as
described below; audio, pitch accent and
picture stay empty. Cards are tagged `studious` and
`studious::<doc>::<chapter>`, and added in shortlist order, which is the
order Anki introduces new cards. Words that were sent become `active` in the
store, and the Anki snapshot is re-synced so they leave the shortlist.

#### Card quality

- **Short meanings.** A meaning that came from the dictionary
  (`meaning_source: "jmdict"`) goes on the card as its first three glosses,
  cut earlier if the next would pass 40 characters (`to obtain, to get, to
  procure`). A meaning you edited (`user`) or the model wrote for the
  textbook context (`llm`) is sent as is. The store keeps the full meaning.
- **A word and its する / な form are one word.** 管理 and 管理する (or 重要
  and 重要な) count as the same word: a card for either one in Anki hides the
  other from the shortlist (badge `Anki · … ~`, "matched the same word with
  or without する/な"), the preview also asks Anki about the other spelling,
  and of two such words in one send only the first is sent. Hiragana-only
  words (する, きれいな) are never stemmed.
- **Audio.** On a Mac the send attaches two clips from the built-in voice
  (`STUDIOUS_TTS_VOICE`, default `Kyoko`): the word (as written on the card)
  to `Word Audio` and the example sentence to `Sentence Audio`. Clips are
  made with `say` as real AAC .m4a files, cached under `data/audio/`
  (named by a hash of voice and text) and sent inside `addNotes`, so no new
  AnkiConnect action is used. The dialog shows an "Add audio" checkbox when
  the voice is available; `ANKI_PUSH_AUDIO=false` turns it off by default.
  A clip that fails to generate is left off and counted in the result. In a
  vocab row's detail, **Play word** / **Play sentence** play the same clips.
  Better voices can be downloaded in macOS System Settings > Accessibility >
  Spoken Content > System Voice > Manage Voices; set `STUDIOUS_TTS_VOICE` to
  the voice's name and restart. The per-note `audio` shape follows
  AnkiConnect's documented `addNote` media format but has not been checked
  against a real Anki yet.

#### Example sentences

Each card gets one example sentence, chosen in this order:

1. A short sentence (60 characters or fewer) from a breakdown of a reading
   passage where the word was seen, with its translation. Textbook
   sentences keep their text as printed, with no readings added.
2. Otherwise a generated sentence stored on the vocab item (a する word
   gets a sentence that uses it as a verb, a な word as an adjective): one natural
   sentence in the style of the Kaishi 1.5k deck, using the word in its
   meaning with everything else at about N5-N4 level, plus real furigana
   and an English translation.
3. Otherwise the sentence fields stay empty.

When some of the words about to be sent have no sentence, the dialog says
so and offers **Generate N sentences**. This asks the configured model
(Settings > model) for the sentences in batches of 20, shows progress, and
can be cancelled between batches; **Send without** skips it. It costs API
tokens, audited under the `example_sentences` job type in the cost summary.
Every generated sentence is checked (length, ending, the word and its
readings are really in it, no Japanese in the translation) and retried once
if it fails; words that still fail are left without a sentence. Generated
sentences are stored on the item (`example`) and reused, so a word is
generated once and the send itself never calls the model. In the expanded
detail of a vocab row you can **Generate example**, **Regenerate** or
**Remove** one. Endpoints: `POST /api/vocab/examples` (1 to 40 ids,
`force` to regenerate) and `DELETE /api/vocab/{id}/example`.

Studious writes to Anki with exactly two AnkiConnect actions, `createDeck`
and `addNotes` (enforced in `backend/app/services/anki_push.py`); it never
updates or deletes existing notes, cards, decks or deck options. Set the
`Studious` deck's **new cards per day** limit in Anki's deck options
yourself; Studious does not change deck options. Endpoints:
`POST /api/anki/push/preview` (read-only) and `POST /api/anki/push`
(needs `"confirm": true`).

## Chapter shortlist

The **Shortlist** toggle on the vocab dashboard proposes what to put in Anki
for a chapter (pick a textbook and chapter first) so you only strike words
out. It shows candidates in study order (frequency rank, words from a vocab
list counted twice as important) and hides, with the reason:

- **in Anki** — a card already exists (exact or same dictionary entry, any
  state, including new and suspended; a spelling-only match does not hide)
- **basic** — JLPT N5 or N4
- **grammar-like** — a `〜`/`～`/`~`/`…` pattern, or a kana-only particle,
  conjunction, set phrase, suffix, prefix or auxiliary
- **not in dictionary** — no JMdict entry (headings, phrases, names)
- **known** / **ignored** — your own status

The summary line (`142 candidates · hidden: 310 in Anki · …`) is clickable:
each count lists those hidden words (known and ignored ones have a
**Restore** button), and **Back to shortlist** returns. A divider after the
125th row marks the chapter's budget. **Know it** and **Skip** on each
candidate mark it known or ignored in one tap. Words burned in WaniKani get a
`WK burned` badge everywhere but are not hidden. The shortlist is computed at
read time (`GET /api/vocab?shortlist=true`, `?excluded=<reason>`) and never
stored.

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
