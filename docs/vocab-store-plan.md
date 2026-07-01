# Phase 3: Central Vocab/Grammar Store — Design & Plan

**Status:** Design agreed 2026-07-01. Milestones 3.1 (store foundation +
harvest + dashboards) and 3.2 (enrichment + classification) shipped
2026-07-01 — see roadmap for the item-level record. Implementation notes:

- Dedup indexes are derived in memory from the JSONL (cached against file
  mtime+size) rather than written to `*.index.json` files — one less
  artifact to drift.
- Frequency-rank classification is deferred: jmdict-simplified reduces
  JMdict's nf priority bands to a boolean `common` flag, so a finer rank
  would need a separate corpus dataset. Current signals: JLPT, common,
  WaniKani level (open question 2 below stays open).
- WK enrichment stores only `wanikani_level` in classifications; SRS
  history appears in the drill-down payload only, keeping the
  display-signal-only rule structural.

## Objective

Vocab and grammar harvested from textbooks accumulate into a single
cross-textbook store that becomes the long-term core study artifact of
the tool — graded, dictionary-linked, editable, and eventually
studyable via built-in SRS on web and a companion iOS app.

## Decisions (agreed 2026-07-01)

| Decision | Choice | Notes |
|----------|--------|-------|
| Canonical identity | Link items to **JMdict entry IDs** (`jmdict_seq`); headword+reading is the fallback key for unlinked items | Prevents fragmentation across surface variants (口下手 vs 口べた, kana vs kanji forms, conjugated sightings) |
| Dictionary enrichment | **Bundle JMdict locally** (jmdict-simplified JSON); jisho.org becomes an outbound link only | Instant, free, offline; no dependence on jisho's unofficial API. CC BY-SA attribution required |
| WaniKani | **API sync of subjects + study materials** (personal token), levels as classification, links out. **Never auto-mark WK-burned items as known** | User completed all 60 levels but knowledge has atrophied; WK history is a display signal, not a status. User has significant personal notes on WK worth surfacing |
| Kanji/radical drill-down | Vocab → component kanji → component radicals, each with WK mnemonics + the user's own WK notes | This is a primary reference workflow, driven by mnemonic recall |
| Flashcards | **Built-in SRS** (FSRS-style), web first, iOS later; Anki TSV export (Phase 4) stays as escape hatch | Review history recorded from day one so the scheduler has full data |
| iOS sync | **iCloud/CloudKit-native** eventually; Phase 3 only locks in a CloudKit-friendly schema | Flat records, UUID ids, `updated_at`, tombstones, append-only event logs |
| Storage engine | Keep **JSONL + derived index** for user data (project pattern; append-only oplog is sync-friendly). Read-only SQLite cache is acceptable for the bundled JMdict lookup index | Revisit only if dashboard queries get slow (>10k items is still fine in memory) |

## Data model

New on-disk structure (all user data append-only JSONL, latest-per-id
wins, derived indexes rebuilt on demand):

```
data/
  store/
    vocab.jsonl        # one JSON object per line, latest per id wins
    grammar.jsonl      # (dedup indexes are derived in memory on read)
    reviews.jsonl      # append-only SRS review events (Milestone 3.4)
  refs/
    jmdict/            # bundled dictionary (gitignored, pinned download)
    jlpt/              # pinned community JLPT lists
    frequency/         # pinned frequency dataset
    wanikani/          # WK subjects + study_materials cache (gitignored;
                       # WK content is personal-use licensed — never commit)
```

### Vocab item

```json
{
  "id": "uuid4",
  "headword": "関わる",
  "reading": "かかわる",
  "kana_variants": ["かかわる"],
  "surface_variants": ["関わっ", "かかわる"],
  "meaning": "to be affected; to be influenced; to be concerned with",
  "meaning_source": "jmdict",
  "pos": ["v5r", "vi"],
  "jmdict_seq": 1198890,
  "status": "unreviewed",
  "classifications": {
    "jlpt": "N2",
    "frequency_rank": 3021,
    "jmdict_common": true,
    "wanikani_level": 21,
    "wanikani_srs": {"stage": "burned", "burned_at": "2022-11-03"}
  },
  "priority_group": 2,
  "sightings": [
    {
      "doc_id": "...", "chapter_id": "...", "region_id": "...",
      "sentence_index": 3,
      "surface": "関わっ",
      "sentence_text": "…",
      "source": "breakdown",
      "seen_at": "2026-07-01T…"
    }
  ],
  "links": {"jisho": "https://jisho.org/word/関わる", "wanikani": "https://www.wanikani.com/vocabulary/関わる"},
  "notes": "",
  "created_at": "…", "updated_at": "…", "deleted": false
}
```

Key semantics:

- **`status`** is a *curation* lifecycle: `unreviewed` (auto-ingested,
  inbox) → `active` (studying) → `known` / `ignored`. It is **not** SRS
  state — SRS state derives from `reviews.jsonl` (3.4). WK "burned" never
  sets `known` automatically.
- **`sightings`** carry full provenance plus the example sentence text —
  the raw material for sentence-based flashcards. `source` is
  `vocab_list` (textbook-curated, higher trust) or `breakdown`.
- **`meaning`** prefers the JMdict gloss; LLM gloss is kept when JMdict
  has no entry (`meaning_source: "llm"`).
- Tombstones: delete = append a line with `deleted: true`. Never remove
  lines. Every write bumps `updated_at`. This is the CloudKit-ready
  shape (flat fields, UUID record names, per-record modification time).

### Grammar item

```json
{
  "id": "uuid4",
  "pattern": "〜に関わらず",
  "pattern_normalized": "にかかわらず",
  "explanation": "regardless of ~",
  "classifications": {"jlpt": "N2"},
  "status": "unreviewed",
  "sightings": [{"doc_id": "…", "chapter_id": "…", "region_id": "…", "sentence_index": 1, "surface": "…にかかわらず", "sentence_text": "…", "source": "breakdown", "seen_at": "…"}],
  "links": {"reference": null},
  "notes": "",
  "created_at": "…", "updated_at": "…", "deleted": false
}
```

Grammar has no JMdict equivalent; dedup is by `pattern_normalized`
(strip leading 〜/～, kana-normalize). Classification comes from a
pinned community JLPT grammar list; reference links are best-effort
(open question below).

### WaniKani cache (`data/refs/wanikani/`)

Synced via API v2 (`Authorization: Bearer <token>`, 60 req/min,
incremental via `updated_after`):

- `subjects.jsonl` — radicals, kanji, vocabulary: characters, level,
  meanings, readings, `meaning_mnemonic`, `reading_mnemonic`,
  `component_subject_ids` (vocab → kanji → radicals graph)
- `study_materials.jsonl` — the user's own meaning/reading notes and
  synonyms
- `assignments.jsonl` — SRS stage per subject (display signal only)

Token stored in macOS Keychain like `ANTHROPIC_API_KEY`
(`WANIKANI_API_TOKEN` env var at runtime; never in `.env` or git).
WK content is licensed for personal use — the cache is gitignored.

## Harvest pipeline

1. **At breakdown generation** (hook in `jobs.py` after
   `save_breakdown`): for each sentence vocab/grammar item, normalize →
   look up JMdict → dedup against the store → append (new item) or
   append updated item with the new sighting.
2. **At vocab_list transcription save**: parse the structured
   `term（reading）　gloss` markdown (indices + section headers are
   preserved by the prompt) and ingest with `source: "vocab_list"`.
3. **Backfill job** (one-time, idempotent): walk all existing
   breakdowns and vocab_list transcriptions and run the same ingest.
4. **Normalization**: try JMdict lookup by surface, then by
   kanji-stripped/kana reading. Misses stay as unlinked items flagged in
   the inbox — no LLM normalization pass in v1 (dictionary-first; cheap
   and deterministic).

Ingest must be idempotent (re-running a breakdown adds no duplicate
sightings — key sightings by region_id + sentence_index + source).

## Classification & priority

Store every signal independently; derive a priority grouping for study
ordering:

| Signal | Source | Notes |
|--------|--------|-------|
| JLPT level | Pinned community dataset (official lists ceased 2010) | vocab + grammar |
| Frequency rank | Pinned corpus-derived list (BCCWJ short-unit; decide exact dataset at implementation, checksum-pinned) | |
| Common flag | JMdict priority tags (news/ichi/spec/nf) | |
| WaniKani level | WK subjects cache | 1–60 |
| WK SRS history | WK assignments | display only ("burned 2022") |
| Textbook order | first sighting's chapter | ties study to the book being worked |

`priority_group` = derived bucket (e.g. 1: common + JLPT-listed + seen
in current textbook … down to 5: rare, no signals). Exact formula is an
implementation detail — keep it a pure function of `classifications` so
it can be recomputed when the formula changes.

## API

New router `backend/app/api/store.py`:

- `GET /api/vocab` — list; filters: status, jlpt, priority_group,
  doc/chapter, jmdict_common, search (headword/reading/meaning);
  sort: priority, frequency, recency; pagination
- `POST /api/vocab` — manual create
- `PATCH /api/vocab/{id}` — status, notes, field edits
- `POST /api/vocab/{id}/merge` — merge duplicate into canonical (3.3)
- `GET /api/vocab/{id}/wanikani` — drill-down payload: WK vocab subject
  → component kanji (with mnemonics + user notes) → component radicals
- Parallel `GET/POST/PATCH /api/grammar…`
- `GET /api/documents/{doc_id}/chapters/{chapter_id}/vocab` —
  chapter-scoped view + coverage stats
- `POST /api/store/backfill` — run the backfill job (job-queue based)
- `POST /api/refs/wanikani/sync` — incremental WK sync job
- SRS (3.4): `GET /api/study/queue`, `POST /api/study/reviews`

## Frontend

- **`/vocab` dashboard** (`pages/vocab-dashboard.ts`): filterable,
  searchable table; status controls; stats header; **Inbox** tab for
  `unreviewed` with bulk accept/ignore. Reuse existing controls/styles
  (see shared-UI note in project feedback) — no parallel components.
- **Vocab detail pane**: JMdict senses, classifications, sightings with
  sentence context (links back to chapter/region), notes editor,
  jisho/WK links, and the **kanji drill-down**: component kanji cards
  with WK mnemonic + user's WK note, expanding to radicals with the
  same.
- **`breakdown-pane.ts`**: vocab popovers gain "in store" indicator +
  status toggle; known items render de-emphasized (3.3).
- **Topbar**: "Vocab" and "Grammar" links.
- State syncing across views: simple pub/sub event bus (per plan.md,
  evaluate a reactive lib only if this gets painful).

## Milestones

### 3.1 Store foundation + harvest (must-have core)
Stores, schemas, ingest hooks, backfill, dedup, status lifecycle,
`/api/vocab` + `/api/grammar`, dashboard with inbox. LLM glosses only
(no JMdict yet) — but `jmdict_seq` field and lookup interface stubbed so
3.2 slots in without migration.

### 3.2 Enrichment + classification
JMdict bundling (pinned + checksummed download via `make refs`,
attribution in README + settings), JMdict linking/re-linking pass, JLPT
+ frequency datasets, WK sync + drill-down view, outbound links,
priority grouping.

### 3.3 Curation & editing
Manual add/edit, merge duplicates, bulk inbox actions, known-word
de-emphasis in breakdowns, chapter coverage stats ("N of M chapter
vocab known").

### 3.4 Built-in SRS (web)
`reviews.jsonl` event log (id, item_id, ts, grade, elapsed), FSRS
scheduler implemented in-repo (small, well-specified algorithm — avoids
a dependency), review queue API, flashcard UI (word→meaning and
sentence-context cards from sightings). Anki export remains Phase 4.

### 3.5 Sync groundwork (design doc only)
Document the CloudKit record mapping (items + review events as CKRecord
types, tombstone handling, conflict policy: reviews append-only merge
trivially; item fields last-writer-wins per `updated_at`). No code
until the iOS app starts (Phase 5).

## Licensing & supply chain

- **JMdict / JMdictFurigana**: EDRDG license (CC BY-SA 4.0) —
  attribution in README and the app's settings/about. Bundled data is
  downloaded by a make target from pinned release URLs with SHA-256
  checksums recorded in-repo (consistent with supply-chain rules; no
  auto-updating feeds).
- **WaniKani content** (mnemonics, user notes): personal use only;
  cache gitignored; token in Keychain.
- **JLPT lists**: unofficial community data; pin an exact snapshot.
- No new runtime package dependencies expected in 3.1–3.3; FSRS in 3.4
  is implemented in-repo. Any dataset download respects checksum
  pinning rather than "latest".

## Open questions (revisit before the relevant milestone)

1. **Grammar reference links** (3.2): Bunpro has JLPT-graded grammar
   pages but no stable public API; options are curated slug mapping,
   search URLs, or skip links for grammar. Decide when 3.2 starts.
2. **Frequency dataset choice** (3.2): BCCWJ short-unit list vs
   wordfreq-derived. Compare coverage on real store contents.
3. **Card design** (3.4): word-first vs sentence-first as the default
   flashcard front; probably both card types per item with FSRS
   scheduling per card.
4. **Sense granularity**: v1 tracks at word level (one item per JMdict
   entry), not per-sense. Revisit if polysemous words (かける…) become
   noisy in study.
