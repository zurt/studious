# Troubleshooting

Where to look first when something goes wrong. Triage in this order: **job JSON → backend stdout → DevTools EventStream → region JSON**.

## Where state and logs live

### iOS companion (apple/)
- The app's local store is the same JSONL format as the backend's, at
  `Application Support/Studious/store/{vocab,grammar,reviews}.jsonl`
  inside the app sandbox; CloudKit sync-engine state lives next to it
  (`cksync-state.json`). Deleting the app resets both — data re-imports
  or re-syncs.
- `no such module 'XCTest'` from `swift test`: Command Line Tools
  installs ship neither XCTest nor Swift Testing, so the suite is a
  plain executable — run `make test-apple` (= `swift run studious-tests`).
- `xcodebuild ... requires Xcode` means only CLT is installed; the
  SwiftPM package still builds/tests fine, only the `.xcodeproj` app
  shell needs a real Xcode install.
- FSRS golden-parity failures after touching
  `backend/app/services/srs.py` or `StudiousCore/FSRS.swift`: regenerate
  with `make golden`, re-run `make test-apple`, commit the fixtures.
  Rounding trap: Python `round()` is half-to-even, so the Swift interval
  math uses `.rounded(.toNearestOrEven)` deliberately.
- `studious-sync sync` failing with a CloudKit permission error: the CLI
  binary must be codesigned with the iCloud entitlement
  (`com.apple.developer.icloud-services = CloudKit`) for the container;
  unsigned `swift build` output can't reach CloudKit. Use
  `studious-sync merge/export` (manual file exchange, same merge
  semantics) until signing is set up.

### macOS companion (studious-mac)
- Store location is whatever data dir the app resolved at launch
  (`--data-dir` arg > `STUDIOUS_DATA_DIR` env > Settings pick > its own
  Application Support store) + `store/`; Settings → Data directory
  shows the resolved path. `make run-mac` always points at the repo's
  `backend/data`.
- The Settings-chosen data dir and backend URL persist in the
  `studious-mac` UserDefaults domain (`defaults read studious-mac`);
  the executable is unbundled, so the domain is the process name.
- The app doesn't show a change made by the backend/web app: external
  appends are picked up by a ~2s foreground poll, and an in-progress
  study session's queue is a snapshot from when the session started —
  lists/stats refresh, the current session deliberately doesn't.
- No iCloud sync section in Settings on the Mac: intentional
  (`AppModel.syncSupported == false`) — an unsigned executable has no
  iCloud entitlement, and in bridge mode there's nothing to sync.

### Screenshots of studious-mac (or any GUI) come out as wallpaper only
`screencapture` from a terminal without Screen Recording permission
silently captures the desktop and menu bar but blanks other apps'
window contents — it looks like the app has no window when it does.
Grant Terminal the permission in System Settings → Privacy & Security →
Screen & System Audio Recording, or confirm the window exists without
pixels: `swift -e 'import CoreGraphics; print(CGWindowListCopyWindowInfo([.optionOnScreenOnly], kCGNullWindowID)!)'`
and look for the app's `kCGWindowOwnerName`/bounds. `osascript`/System
Events needs the separate Accessibility permission and will pop a
dialog if missing.

### Backend logs (stdout)
Configured in `backend/app/main.py` with a single `StreamHandler` — logs go to the terminal running `make dev-backend` (or `make run-backend`). Nothing is written to disk by default. To capture a session:

```bash
make run-backend 2>&1 | tee /tmp/studious-backend.log
make logs           # tail -F /tmp/studious-backend.log | jq -C .
```

Every HTTP request carries a `correlation_id`; jobs emit `region_job_start` / `region_job_done` (or an exception traceback). Grep by `correlation_id` to follow a single request end-to-end.

The backend log level is configurable via `STUDIOUS_LOG_LEVEL` (default `INFO`). Set it to `DEBUG` to surface per-page `page_done` lines and other verbose events during feature work.

Outbound Anthropic VLM calls are logged via `studious.providers.anthropic` as three events: `vlm_call_start` (model, image_bytes, prompt_hash), `vlm_call_done` (request_id, duration_ms, token counts), and `vlm_call_error` (status_code, error_class). The `request_id` matches the value Anthropic returns in `anthropic-request-id` and is what to quote on a support ticket.

### Job records
`backend/data/jobs/<job_id>.json` — authoritative server-side state per job.

Key fields:
- `status` — `pending` | `running` | `completed` | `failed`
- `started_at` / `finished_at` — the diff is the runtime (a sub-millisecond diff means an instant failure, usually config)
- `errors[]` — actual error message from the worker

```bash
ls -lt backend/data/jobs/ | head    # most recent jobs
```

### Region state
`backend/data/documents/<doc_id>/chapters/<chapter_id>/regions/<region_id>.json` — disk truth for a region. Check `transcribed_at` and `transcription_md` here to verify whether the data actually changed, independent of what the UI shows. `continues_to` (cross-page chain pointer) and `references` (an exercises region's cited reading passages) live here too.

### Central vocab/grammar store
`backend/data/store/vocab.jsonl` and `grammar.jsonl` — append-only, one JSON
object per line, the **latest line per `id` wins**, deletes are tombstone
lines (`"deleted": true`). Nothing ever rewrites earlier lines, so the file
is also its own history: to see how an item evolved,
`jq 'select(.id == "<id>")' backend/data/store/vocab.jsonl`. The dedup
indexes are derived in memory on read — there is no index file to rebuild or
corrupt. Harvest events log as `harvest_vocab_list` / `harvest_breakdown`
(with created/updated counts) and `harvest_backfill_done`; a failed harvest
logs `harvest_vocab_list_error` / `harvest_breakdown_error` **without
failing the parent job** — re-run `POST /api/store/backfill` (or the
dashboard's Backfill button) to converge the store; it is idempotent.

### SRS review history (built-in flashcards)
`backend/data/store/reviews.jsonl` — append-only, one JSON line per graded
review (`item_id`, `kind`, `card_type`, `grade` 1–4, `ts`, `elapsed_ms`).
There is **no stored SRS state**: a card's stability/difficulty/due date is
derived by replaying its events through the FSRS scheduler in
`backend/app/services/srs.py` (cached against the file's mtime+size).
Inspect one card's history with
`jq 'select(.item_id == "<id>" and .card_type == "word")' backend/data/store/reviews.jsonl`.
Deleting the file resets all scheduling (cards become "new") but nothing
else. Reviews log as `review_recorded` under `studious.api.study`.

### Reference data (JMdict index, WaniKani cache)
`backend/data/refs/jmdict/jmdict.sqlite` — read-only lookup index built by
`make refs` (~70 MB; sources pinned by SHA-256 in `backend/refs.lock.json`,
downloads kept in `data/refs/downloads/`). Check what's loaded with
`sqlite3 backend/data/refs/jmdict/jmdict.sqlite "SELECT * FROM meta"`.
Rebuild with `make refs` after editing the lock file (`--force` via
`uv run python scripts/fetch_refs.py --force` if the version didn't change).

`backend/data/refs/wanikani/*.jsonl` — WaniKani subjects / study_materials /
assignments cache (append-only latest-wins, personal-use content, never
commit). `sync_state.json` holds the per-resource `updated_after` cursors;
delete it (or `POST /api/refs/wanikani/sync?full=true`) to force a full
re-pull. `GET /api/refs/wanikani/status` reports configuration + counts.

Enrichment events log as `enrich_done` (attempted/linked counts) under
`studious.enrich`; WK sync as `wanikani_sync_done` / `wanikani_rate_limited`.

### LLM audit log
`backend/data/llm_audit.YYYY-MM.jsonl` — append-only record of every VLM API call (one JSON object per line), rotated monthly by UTC date. Each entry has `id`, `timestamp`, `provider`, `model`, `job_type`, `status` (`success` or `error`), `duration_ms`, token counts (including `cache_read_tokens` / `cache_creation_tokens`), `correlation_id`, `request_id` (Anthropic's), `prompt_hash`, `image_bytes`, `stop_reason`, and `doc_id` / `chapter_id` / `region_id` / `job_id` / `page` context. OCR calls are not logged (no API cost). Use this to confirm a call happened, see how long it took, and look up token counts after the fact.

```bash
# tail the current month's calls
make audit-log

# all errored calls across all months
jq 'select(.status == "error")' backend/data/llm_audit.*.jsonl
```

A pre-rotation `llm_audit.jsonl` (no date suffix) is still read by `read_all()`. The summary endpoint maintains a `backend/data/llm_audit_summary.json` cache: archived months are aggregated once and read from cache; the current month is recomputed live. Delete the cache to force a rebuild.

The log is written via `app.services.llm_audit.record(...)` from `app/jobs/` after every VLM call (success or failure).

### Prompt cache hits / misses
Tool-call jobs pass their prompt to `provider.call_tool` as a list of text
blocks, each flagged `cache: True` or not; the provider puts
`cache_control: ephemeral` on the flagged ones. Exercise completions send
three blocks — instructions + learner profile (cached), the exercise
block's `<region_transcription>` + `<reading_reference>` (cached), and the
`<target_sentence>` (uncached) — so the second and later items of one block
completed within 5 minutes show `cache_read_tokens` ≈ the whole prefix and
`cache_creation_tokens` = 0 (verified live 2026-09-29: 6.4k written, then
6.4k read). Breakdowns and grammar guides cache only their instructions,
since each region's text is new. Transcriptions still cache the prompt
after the page image, which never repeats — expect writes and no reads
there.

The signature of a misplaced breakpoint is `cache_creation_tokens` on every
call and `cache_read_tokens` never covering the shared prefix — that was
the state of every tool-call job before 2026-09-29, when the marker sat at
the end of one block that ended with per-call text. Other causes of zero
reads: the prompt text changed (a learner-profile change rewrites the cache
once), the model changed, more than 5 minutes between calls, or a prefix
below the model's minimum (1024 tokens on Sonnet 5 / Opus 4.8, 512 on the
5.5 models). A top-level effort change also invalidates it.
`/api/costs/summary` prices writes at 1.25× and reads at 0.1× input (per-
model overrides in `MODEL_PRICING`).

### Cost estimates
`GET /api/costs/summary` — totals plus breakdown by model and by document, derived from `llm_audit.jsonl` and the `MODEL_PRICING` table in `backend/app/config.py`. `GET /api/costs/audit?limit=&offset=` returns paginated audit entries (newest first) annotated with `estimated_cost_usd`. Models not in the pricing table appear in `unknown_models` and contribute `null` cost — add them to `MODEL_PRICING` when you start using a new model. Estimates include prompt-cache writes and reads (before 2026-09-29 they were ignored, which under-reported tool-call jobs several-fold because nearly all their input was logged as cache writes); the per-month summary cache carries a `_version` and is rebuilt when the formula changes.


### Frontend logs
- Browser DevTools **Console** — `frontend/src/logger.ts` emits structured entries with `correlation_id` that match backend logs.
- DevTools **Network → `/api/jobs/<job_id>/events` → EventStream** — SSE-specific view of job events (`snapshot`, `job-started`, `job-done`, `job-failed`, `ping`).

### E2E (Playwright) state and artifacts
- `frontend/test-results/` — per-failure screenshots, error context, and traces. Inspect a trace with `cd frontend && npx playwright show-trace test-results/<test-dir>/trace.zip`.
- `backend/.e2e-data/` — the isolated data dir for the E2E backend, wiped at the start of every run (the wipe happens in the backend `webServer` command in `frontend/playwright.config.ts`). Documents/jobs left here after a failed run reflect the state the failing test saw.
- The E2E backend (`app.main:app` with `STUDIOUS_VLM_PROVIDER=mock`, port 8775) logs at `WARNING` to Playwright's server output; transcriptions come from the mock VLM provider, so real-API failure modes (auth, rate limits) cannot occur in this suite. If an E2E run reports a port already in use, something is squatting on 8775 or 5273 (`lsof -i :8775`); the suite never reuses an existing server by design.

### Model-eval runs (benchmarks/model_eval)
State lives entirely on disk under `benchmarks/model_eval/`:

- `dataset/<name>/manifest.json` — seed, quotas, per-stratum counts, item ids.
  The dataset itself (`items/*/input.png`) is **gitignored** but rebuilds
  byte-identically: `python -m benchmarks.model_eval build-dataset --data-dir
  backend/data --seed <manifest seed> --name <name>`.
- `runs/<run_id>/transcriptions/<item>/<model>.json` — one file per call, with
  `status`, provider `meta` (usage, `request_id` for Anthropic support),
  `duration_ms`, `estimated_cost_usd`. A failed call is written with
  `status: "error"` and the exception text.
- `runs/<run_id>/judgments/<item>.json` — judge output incl. the blind
  `label_to_model` mapping; `status` is `ok` / `refused` / `error`.

Both `run` and `judge` are resumable: re-running the same `--run-id` skips
any (item, model) / item whose output file already exists and parses, so a
partially failed run is fixed by deleting the bad files and re-running.
Progress prints to stdout only (no backend logger).

Symptom: a single transcription call takes ~10 minutes but succeeds — the
Anthropic SDK auto-retries 5xx/429/timeouts with backoff (seen once on a
full workbook page with opus-4-8, run 20260706-eval-v1). Not a hang; only
investigate if calls exceed the SDK's retry budget and return errors.

## Known failure modes

### A long request (e.g. `POST /api/store/backfill`) 500s; store/dashboard left partial

A uvicorn started with `--reload` (`make dev-backend` does; `make run-backend` deliberately does not, so the real data is never exposed to this) watches every
`.py` under `backend/` — including `tests/`. Any concurrent edit to a
backend Python file (an agent implementing a feature, a stray save)
restarts the server and kills in-flight requests and the in-process
job queue: a running backfill dies mid-harvest (partial store, no
enrichment pass), and queued transcription/breakdown jobs vanish
silently. The store itself stays consistent (append-only) — just
incomplete.

Remedy: stop whatever is editing backend files (do feature work in a
git worktree while the dev server runs), then re-run the backfill —
it's idempotent and converges. Re-trigger any jobs that disappeared.

(Historical note: the 2026-07-05 backfill 500 was first blamed on this
mechanism but was actually the LogRecord collision below — check the
traceback before assuming a reload kill.)

### An endpoint 500s with `KeyError: "Attempt to overwrite 'created' in LogRecord"`
Structured-logging trap: `log.info(..., extra={...})` raises KeyError
if any extra key collides with a reserved `LogRecord` attribute
(`created`, `module`, `name`, `filename`, `message`, `args`, …), and it
only fires where a handler is active — the server runs at INFO, but a
bare script or default-level pytest suppresses the call entirely, so
the crash reproduces *only* in server context (a false-negative trap
for sandbox repros; enable INFO via `caplog.at_level` in tests). This
500'd `POST /api/store/backfill`: harvest spread
`**replace_region_sightings(...)` (which returns a `created` count)
into `extra`. Never spread result dicts into `extra` — name each key.
Data written before the log line survives; the backfill is idempotent,
so re-running after the fix converges.

### `make test` fails with "Failed to spawn: pytest" after touching backend deps
Running plain `uv sync` uninstalls the dev tools: this project declares
them as a `[project.optional-dependencies]` **extra** (`.[dev]`), which
`uv sync` does not include by default, so it removes pytest/pip-audit
from the venv. Reinstall with `cd backend && uv pip install -e ".[dev]"`
(what `make install-backend` runs). After changing locked versions
(`uv lock --upgrade-package …`), use that instead of `uv sync`.

### `uv lock` / `uv sync` fails locally with "failed to parse: `uv.toml`" (TOML error on `exclude-newer = "7 days"`)
The CI version of uv (installed by `astral-sh/setup-uv`) supports relative duration syntax (`"7 days"`) in `exclude-newer`. Older local builds (observed at 0.8.17) treat the value as a date string and reject it at parse time, so every uv command fails before touching the network.

Workaround when you need to run `uv lock` locally (e.g., to upgrade a package):
1. Temporarily replace `exclude-newer = "7 days"` in `backend/uv.toml` with the equivalent absolute cutoff (`exclude-newer = "YYYY-MM-DDT23:59:59Z"`, where the date is today minus 7 days).
2. Run `uv lock --upgrade-package <pkg>` (or `uv sync`) as normal.
3. Restore `exclude-newer = "7 days"` before committing — the `--frozen` installs in CI don't re-resolve and don't validate the cutoff format at install time.

Note: changing the global cutoff causes uv to "Ignore existing lockfile due to change in timestamp cutoff" and re-resolves the full graph. Only packages whose upload timestamps fall inside the new window get updated, so all resolved versions still honour the 7-day rule, but more packages may bump than the single `--upgrade-package` target. Verify with `uv run pip-audit` and the test suite before committing the broader lock.

### `make test-backend` fails only in tests/test_wanikani.py (2 failures)
`test_sync_without_token_raises` and `test_sync_endpoint_409_without_token`
assert the no-token error path, but the recommended shell setup exports
`WANIKANI_API_TOKEN` from the Keychain in `~/.zshrc`, so any shell that
sourced it leaked a real token into pytest and both tests failed. Fixed
2026-07-03: the tests scrub the variable themselves. Gotcha for any
future test asserting a missing-env-var path: `app.config.get_settings()`
is `@lru_cache`d, so `monkeypatch.delenv` alone is not enough — also call
`config.get_settings.cache_clear()` (the same pattern the `wk_env`
fixture uses for `setenv`).

### No label suggestion, or the References pane says "Not checked yet", after transcribing
The region check (label and reading-reference questions, run on the helper
model after each transcription) fails silently by design, so a transcription
is never lost to it. Look for `region_check_error` in the backend log and for
`job_type: "region_check"` entries with `status: "error"` in the LLM audit log
(`backend/data/llm_audit.YYYY-MM.jsonl`; `jq 'select(.job_type=="region_check" and .status=="error")' backend/data/llm_audit.*.jsonl`).
Common causes: a missing `ANTHROPIC_API_KEY`, a helper model the account
cannot use, or a malformed tool response (the error says which field). The
**Check** button in the References pane (exercises regions only; for other
tags use `POST .../regions/{id}/check` or re-transcribe) retries and shows
the error as a toast (502). A suggestion also stays hidden
when the model is not highly confident, after Dismiss, and once the region is
re-transcribed or relabelled after the check (the stored check is then stale).
The helper model is set separately in Settings > General, and its calls are
costed under that model in the Usage summary.

### The Study page says "No cards to study yet" despite a full vocab store
The queue only serves items with curation status **active** — that's the
point of the curation lifecycle (see the status-vs-SRS-state distinction
in `docs/design/vocab-store-plan.md`). Freshly harvested items are `unreviewed`
and `known`/`ignored` items never appear. Accept items into study on the
Vocab/Grammar dashboards (inbox → Active, or the per-row status toggle),
then reload `/study`. Check what the server sees with
`curl 'localhost:8000/api/study/queue?limit=5' | jq .counts` —
`active_items: 0` means it's a status problem, not a scheduling one.

### Furigana shows as raw 漢字(かな), or a word has no reading to reveal
`frontend/src/modules/furigana.ts` converts a *reading unit* — a run of kanji immediately followed by a **hiragana** reading in half- or full-width parentheses — into `<ruby>`. Anything else stays plain text by design: katakana in parentheses (answer labels like 文(ア)), a reading after kana or a space, or a unit split across markdown formatting (`**漢字**(かな)`). If a reading renders as raw text, check the source text against that pattern. If a word has no veil to tap, the text simply has no reading for it: textbook transcriptions only carry the furigana the book prints, and completions generated before 2026-09-29 only annotated "uncommon" kanji (the prompt now asks for every kanji word — regenerate the completion). A reading that sits over the wrong kanji (e.g. over 健康第一 when it reads only 第一) means the model annotated just the tail of a kanji run; the prompt's `<readings>` section forbids that, so regenerate. Tapping a vocab-linked word opens its popover instead of revealing, because the link handler stops the click — the popover shows the reading. The mode is stored in `localStorage` (`studious.furigana.mode`) and mirrored on `<html data-furigana>`.

### Arrow keys (or `L`) typed into a field flip the page / toggle link mode
The document and chapter views register their single-key shortcuts on `document`, so they also receive keystrokes aimed at an input, select or dialog. Every such handler must return early when `pageShortcutsSuppressed(e)` (`frontend/src/modules/shortcuts-help.ts`) is true — the user is typing in a field (`isTypingTarget`) or any modal is open (a `.modal-bg` overlay exists). Don't fix an instance with `stopPropagation` on the one field that surfaced it: the next input or modal would regress. If a new page-level shortcut misbehaves this way, it's missing that guard. Covered by the "arrow keys typed into a field" E2E journey.

### An element with the `hidden` attribute is still visible
Any CSS rule that sets `display` on the element's class (e.g.
`.srs-back { display: flex; }`) overrides the UA stylesheet's
`[hidden] { display: none; }` because a class selector outweighs an
attribute selector. The pages toggle visibility with `el.hidden` a lot, so
when adding a `display:` rule to a toggled element, also add
`.the-class[hidden] { display: none; }` (see `.srs-back` in `styles.css`).

### Vocab items show no JLPT/common badges (or the wrong meaning) after harvest
Enrichment only runs when a source exists: the JMdict index (`make refs`)
and/or a synced WaniKani cache. Items harvested *before* the index was
built carry `enriched_at: null` and get picked up by the next harvest's
enrichment pass, or immediately via `POST /api/store/enrich`. After
rebuilding the index or syncing WK, run `POST /api/store/enrich?force=true`
to re-link everything (WK sync does this automatically). Two policy notes:
a meaning you edited by hand (`meaning_source: "user"`) is never replaced
by the JMdict gloss, and a JMdict miss still stamps `enriched_at` — force
is the only way to retry those.

### WaniKani sync returns 409/502 or seems to hang
409 = `WANIKANI_API_TOKEN` not exported (store it in the Keychain like the
Anthropic key; see README). 502 wraps the upstream error — check backend
logs for `wanikani_sync_failed`. A first full sync makes ~30 requests
against a 60/min rate limit and can take ~30s; on 429 the client honors
`Retry-After` once (logged as `wanikani_rate_limited`). WK SRS state is
display-only by design: a burned item still lands in the Inbox, because
burned-years-ago knowledge is exactly what the store is re-learning.

### Sync Anki fails
The button toasts the backend's 503 message: "Anki is not reachable at
<url>". Anki must be open on this Mac with the AnkiConnect add-on (code
2055492159) installed; check with `curl -s localhost:8765 -d
'{"action":"version","version":6}'`. If AnkiConnect listens on another
port, set `ANKI_CONNECT_URL` and restart the backend. A message starting
"AnkiConnect error" means Anki answered but rejected a call (read the
text; an Anki profile may be mid-load). A failed sync leaves the previous
snapshot (`backend/data/refs/anki/snapshot.json`) untouched; logs are
`anki_unreachable` / `anki_sync_done` under `studious.anki`.

### Send to Anki says the note type is missing
409 `Anki has no note type named 'Kaishi 1.5k'` or `Note type ... is missing
field(s): ...`. Studious fills the Kaishi fields (Word, Word Reading, Word
Meaning, Word Furigana, Sentence, Sentence Meaning, Sentence Furigana, Notes,
Frequency). Either the note type was renamed or its fields changed, or
`ANKI_PUSH_NOTE_TYPE` points at another type; fix the name, set the
variable and restart the backend. A 503 means Anki is closed (see "Sync Anki
fails"). Logs: `anki_push_start` / `anki_push_done` under `studious.anki`.

### Send to Anki skipped words
The dialog and result count words Anki would not add, with the reason on
each preview item (`POST /api/anki/push/preview`). The usual one is a
duplicate: a note with the same Word exists anywhere in the collection, even
in another deck or with a different reading (duplicates are never added). Two
candidates with the same spelling in one send also collide; the second is
skipped. A word reported as failed was accepted by the preview but refused by
`addNotes`; it stays in the inbox and can be retried.

### Cards sent to Anki have no example sentence
Cards always use a generated sentence (stored on the item as `example`);
textbook sentences are never put on a card because they are above the
learner's level. A word has none until you press **Generate** in the Send to
Anki dialog (or **Generate example** on its row), or when generation failed
for it (see "Some words still have no sentence after generating" below).
Words already sent are skipped as duplicates, so fix an existing note in
Anki by hand.

### Generate sentences fails
The dialog or the row button shows the backend's message. 503 with
"ANTHROPIC_API_KEY is not set" means the provider is not configured: put the
key in `.env` and restart the backend. 502 "Example sentence generation
failed" means every model call errored (rate limit, overload, bad model
name); the error is in the `llm_audit` log with `job_type`
`example_sentences` and in `studious.examples` as `example_batch_failed`.
Retry later; sentences already stored are kept.

### Some words still have no sentence after generating
The model's answer is checked before it is stored (6 to 40 characters,
ends with 。, the word's stem in the surface form, readings on every kanji
and only there, no Japanese in the translation) and retried once with the
reason. Words that fail twice are left without one. The reasons are logged
as `example_validation_dropped` under `studious.examples` (and listed per
word as `reason` in the `POST /api/vocab/examples` response). Open the row's
detail and press Generate example to try again; a new call often passes.

### A generated sentence uses the noun, not the verb
A する headword must be used as a verb (した, します, している…) and a な
headword as an adjective; sentences that do not are rejected and retried
with that reason. Sentences stored before this rule are not regenerated:
press Regenerate on the row.

### A generated sentence is wrong
Open the vocab row's detail: **Regenerate** asks the model for a new one,
**Remove** deletes it (the card then goes out without a sentence). Cards
already sent to Anki are not updated; fix the note in Anki by hand. The
stored `example` records the model that wrote it.

### A word shows a wrong meaning / wrong dictionary entry
Symptom: 成功する linked to 性交, 管理する to 官吏, 買える to 帰る, with
that entry's gloss, JLPT level and Anki entry match. Cause: until
`ENRICH_VERSION` 3 the dictionary lookup fell back to the reading alone and
took the lowest-numbered homophone. Now the surface is tried first, then
without a list marker (①, ＊, `a.`), without a pattern tilde and particle
(〜に及ぶ), without する/な, and a reading-only hit is accepted only for a
kana-only headword or when every kanji of the headword occurs in one of the
entry's written forms. Restarting the backend after this update re-links
every vocab item once (in the background, `startup_enrich_*` under
`studious.main`); the summary is one `enrich_done` line under
`studious.enrich` with `relinked`, `unlinked`, `unchanged`. A word whose
link is dropped gets its textbook meaning back (`meaning_context`). Cards
use `meaning_context` when present, so they are right even before the
re-link finishes. To re-run it by hand: `POST /api/store/enrich?force=true`.
Not fixed by this: an inflected form such as 受けて can still resolve to a
homophone whose kanji include its own (受け手); edit the item's reading or
headword, or its meaning (an edited meaning is never overwritten).

### Cards have no audio / Play answers 503 on the server
When the server is not on the Mac, speech uses the `say_remote` engine
(`STUDIOUS_TTS_ENGINE=say_remote`) and the Mac speech helper. The 503 message
names the cause; `GET /api/tts/status` shows `available`, `reason`, `pending`
(vocab items waiting for clips) and `helper_url`.
- **Check the helper.** On the Mac, `curl http://127.0.0.1:8766/health` should
  answer `{"ok": true, "service": "studious-say-helper", ...}`. If not, start
  it with `make say-helper` (it is not a LaunchAgent yet), and check the Mac is
  awake. From the server, try the same URL as `STUDIOUS_SAY_HELPER_URL`; the
  tailnet route (`tailscale serve --tcp 8766 tcp://127.0.0.1:8766`) must exist.
- **The helper answers 502 "The format 'aac' is unknown"** when it was
  started inside Claude Code's sandbox: `say` cannot reach the system's AAC
  encoder there (a bare `say --data-format=aac` fails the same way). Start
  the helper from an ordinary terminal.
- **Clips that exist still play** with the Mac away; only missing ones answer
  503.
- **Where state lives.** `data/audio/pending.json`: the vocab item ids still
  waiting for clips, in order. `data/audio/say-voices.txt`: the last voice
  listing the helper returned, used to work out cache keys while the Mac is
  unreachable (delete it and the pool is empty until the helper answers).
  Clips are `data/audio/<hash>.m4a`.
- **Log events** (`studious.speech_queue`): `speech_queue_drained` (counts made,
  cached, failed, remaining), `speech_queue_unavailable` (the Mac did not
  answer, nothing touched), `speech_queue_clip_failed` (one clip failed for
  another reason: text too long, `say` failed; it is dropped from the list and
  retried on play), `speech_queue_enqueue_error` (a harvest hook failed; the
  job itself did not). `studious.say_remote`: `say_remote_unreachable`,
  `say_remote_timeout`. `studious.tts`: `tts_voice_failed`. On the Mac,
  `studious.say_helper`: `say_helper_request` (status, duration, characters,
  bytes; never the text).
- **Force a catch-up.** `POST /api/tts/catch-up` (the button in Settings >
  Speech) starts a drain now. `{"all": true}` queues every vocab item first, for
  example after moving the data to a new server. Background generation is off
  with `STUDIOUS_TTS_PREGENERATE=0`; the endpoint still works.
- **Send to Anki gives some cards no audio** while the Mac is away: the result
  says how many clips were left off (`audio.missing`); they are not added to
  those cards later.

### Cards have no audio (server on the Mac)
The send result says how many clips were added. None means: not macOS or
no `say` on PATH; the voice is not installed (`say -v '?'` lists them;
`GET /api/tts/status` shows `available`, the `voices` in use and a `reason`;
the default `auto` needs an installed Japanese voice, set another with
`STUDIOUS_TTS_VOICE` or Settings > Speech); the dialog's "Add audio" box was off or
`ANKI_PUSH_AUDIO=false`. "N failed" means `say` errored for some clips (log
`anki_push_audio_failed` under `studious.tts` / `studious.anki`); those
notes were still sent. With the VOICEVOX engine, `GET /api/tts/status` gives
the `reason` (engine app not running, wrong URL, no speaker chosen). Cached
clips are in `backend/data/audio/`; delete one to regenerate it.

### No speakers listed (Settings > Speech)
The picker is filled from the engine's `GET /speakers`. "No speakers listed"
means the engine app (VOICEVOX or AivisSpeech) is not running or the URL is
wrong: VOICEVOX listens on `http://127.0.0.1:50021`, AivisSpeech on
`http://127.0.0.1:10101`. Start the app, check the URL in Settings, and
open `<url>/version` in a browser. The app must also be running whenever you
send words to Anki or play a clip.

### The audio sounds the same after changing the voice
Cards already in Anki keep their old clips: Studious never edits existing
notes. Only words sent afterwards get clips from the new voice (clips are
cached per engine, speaker and text, so old ones are not reused). Row Play
buttons use the current voice at once.

### All cards use the same voice
The `say` engine rotates among the voices in its pool. Only one voice in the
pool means only one is used: either just one Enhanced/Premium Japanese voice
is installed (or none, so plain Kyoko is used), or Settings > Speech > Voice
list names a single voice. `GET /api/tts/status` shows `voices`. Install
more in System Settings > Accessibility > Spoken Content > Manage Voices, or
clear the voice list.

### The voice changed after installing a new voice
The automatic pool is every installed Enhanced/Premium Japanese voice, so a
new one changes the pool and cards sent from now on may pick a different
voice (the choice is a stable hash of the card's Word over the pool). Cards
already in Anki are never edited; set an explicit voice list to pin it.

### The audio reads a word wrongly
The built-in voice picks the reading from the kanji itself and can choose a
different one than the card shows (the card's reading field is not given to
it). Try another voice in `STUDIOUS_TTS_VOICE`, or fix the clip in Anki.

### A word I expected was skipped as a duplicate
Words that differ only by a trailing する or な (管理 / 管理する, 重要 /
重要な) are treated as the same word: in the shortlist an existing card hides
the other form (badge "matched the same word with or without する/な"), and
in the send only the first of the pair goes; the skip reason names the other
word. Hiragana-only words are not affected. Anki's own duplicate check
(exact Word field) is also asked about the other spelling.

### New cards do not appear on my phone
Studious adds the notes to Anki desktop only. Sync Anki desktop with
AnkiWeb, then sync the phone. Also check the `Studious` deck's new cards per
day limit in Anki's deck options (Studious never changes deck options); a
limit of 0 shows nothing.

### An item I study in Anki shows no Anki badge
Matching uses the note type's word field, picked by name (Word,
Expression, Vocabulary, Vocab, Kanji, Front, else the first field). See
what was used with `GET /api/refs/anki/status` (`note_types`); a wrong
`word_field` means that note type's name is not recognised — add it to
`WORD_FIELD_CANDIDATES` in `backend/app/services/anki.py`. Cards whose
cleaned word is empty or over 30 characters are skipped. If the word
matches but the reading differs (e.g. Anki holds kanji-with-furigana or a
different reading), the badge still appears by headword only (`~`, "matched
on spelling only, reading differs"). Variant spellings (うれしい in the store,
嬉しい in Anki) match through the JMdict entry (`~`, "matched by dictionary
entry"): that needs the JMdict index (`make refs`) and an Anki card with a
reading that the entry confirms; a card without a reading is matched only
exactly or by headword. Both indexes are rebuilt automatically when the
snapshot or the JMdict file changes. No badge at all means none of the three
tiers (exact, entry, headword) hit: the headword itself differs (okurigana,
食べる vs 食べ) or the item has no `jmdict_seq` yet (run
`POST /api/store/enrich`). Re-run Sync Anki after changing cards; state is
read from the snapshot.

### A word I expected is missing from the shortlist
The shortlist hides a word for exactly one reason (first match wins):
known, ignored, already in Anki (exact or same-entry match, any state,
including new and suspended), grammar-like (a `〜`/`～`/`~`/`…` headword, or a
kana-only particle/conjunction/expression/suffix/auxiliary), no JMdict entry,
or JLPT N5/N4. The summary line lists the non-zero counts; click one to see
those words (`GET /api/vocab?excluded=<reason>` does the same, and each item
carries `shortlist_excluded`). Wrongly hidden: a missing `jmdict_seq` means
the word was never enriched (`POST /api/store/enrich`); a wrong "in Anki" is
usually a stale snapshot (Sync Anki again); known/ignored words have a
Restore button. Also check the textbook/chapter, search, source, status and
Anki filters: the shortlist composes with them.

### A word I know keeps appearing in the shortlist
Nothing marks a word known automatically, not even WaniKani burned ones
(they only get a `WK burned` badge). Tap **Know it** on the row (or Skip to
ignore it); it moves to the hidden "known" group and stays out of every
future shortlist. Words you study in Anki disappear once Sync Anki has
imported their cards.

### No frequency ranks (`#1.2k` badges) shown, or "By frequency" does nothing
Ranks need the frequency index: `ls backend/data/refs/freq/jpdb-freq.sqlite`
(built by `make refs`; `sqlite3 ... "SELECT * FROM meta"` shows the list
revision and row count). If it exists but items have no rank, they have not
been re-enriched yet: restart the backend (it runs a pending-enrichment pass
at startup) or `POST /api/store/enrich`; items are re-checked once per list
revision and lookup-logic version (`freq_checked`, e.g. `rev-A+l2`; bump
`LOOKUP_VERSION` in `freq.py` when the matching changes), no `force` needed.
Items stay unranked when the list does not contain their spelling (terms
jpdb never saw are dropped by design); those sort last. A headword with no
row of its own is retried without one trailing `する` / `(する)` / `な` /
`(な)` (企画する uses 企画's rank); hiragana-only words are never stemmed,
and a stem that is itself missing (決定的な needs a 決定的 row) stays
unranked. If `make refs` fails on the frequency step, a
checksum mismatch means the pinned release changed (re-pin
`backend/refs.lock.json` deliberately), and "unsafe zip member" / "too
large" / "unexpected frequency list format" mean the archive was rejected by
the build's safety checks and nothing was written.

### A vocab-list entry didn't show up in the vocab store
The harvest parser (`backend/app/services/harvest.py`) only ingests lines it
can positively identify as entries; everything else is treated as a section
header and skipped. Known miss modes:
- **Reading not pure kana** — `term（reading）gloss` is only an entry when
  the parenthesized text is kana (that's what separates it from headers like
  `（p. 28）`). A transcription typo inside the reading drops the line.
- **Kana-only entry with a non-English gloss** — `term　gloss` lines are
  required to contain an ASCII letter in the gloss (rejects Japanese-only
  headers containing an ideographic space). A gloss like `？` is skipped.
- **Item deleted from the store** — deletes are tombstones and deliberately
  block re-harvest of the same headword+reading; re-create manually if the
  delete was a mistake.
Check what the parser saw with the region's `transcription_md`, fix the
transcription (or add the item manually via the dashboard), then Backfill.

### After merging duplicates, a spelling seems to vanish (or you expect it back and it isn't)
Merge (dashboard checkboxes → Merge…, or `POST /api/vocab/{id}/merge`)
tombstones the losing entry with `merged_into: <canonical id>` — distinct
from a plain delete. Consequences: re-harvesting the merged-away spelling
adds its sightings to the *canonical* item (a plain delete blocks
re-harvest entirely); the old spelling stays findable via search and the
breakdown-pane lookup because it's recorded in the canonical item's
`surface_variants` (shown as "also: …" in the row detail). To split a bad
merge there is no unmerge — edit the canonical item, or delete it and
re-create both entries by hand. Inspect the chain with
`jq 'select(.merged_into != null)' backend/data/store/vocab.jsonl`.

### A job-progress wait hangs even though the job completed (batch transcribe stuck at "N pending")
`GET /api/jobs/{id}/events` replays the job's current state as a `snapshot`
event and only then streams live events. If the job reached a terminal state
*before* the EventSource connected — routine for fast jobs (mock provider in
E2E, small crops) — **no `job-done`/`job-failed` event will ever arrive**;
the snapshot is the only signal. Every `openJobStream` consumer must treat a
snapshot whose `status` is `completed` / `completed_with_errors` / `failed`
as terminal. The chapter-view batch-transcribe waiter missed this until
2026-07-01, which made the E2E linking journey fail deterministically
(tracker stuck at "1 pending" while all jobs on disk showed `completed`).
Diagnosis tip: if the UI says pending but `data/jobs/*.json` say completed,
it's the subscriber, not the queue.

### E2E test drawing a region times out waiting for `#tag-select` (or a card click shows an empty breakdown pane)
Two chapter-view behaviors trip up new journey tests (both bit on 2026-06-12):
1. **Region drags must stay inside the visible viewport.** At fit-width zoom the page canvas is taller than the 720px viewport; `canvas.boundingBox()` reports the full (partially clipped) height, so a drag endpoint at a large height fraction lands below the viewport, the canvas never sees `mouseup`, and the tag popover never opens. The failure screenshot shows a small stranded dashed box at the last in-viewport mousemove. Keep drag coordinates in the upper ~half of the canvas box. Also remember a `mousedown` inside an existing region's bbox *selects* that region instead of starting a draw — draw beside existing regions, not over or under them.
2. **The chapter view auto-selects the page's first region on load** (falling back from the remembered selection). Clicking that region's card therefore *toggles it off* and unmounts the breakdown pane. Assert against the auto-selected state instead of re-clicking the card.

### Every E2E test fails with "Executable doesn't exist ... chromium_headless_shell-NNNN"
A Playwright version bump (Dependabot) needs a newer browser build than the
one in `~/Library/Caches/ms-playwright`. Run `cd frontend && npx playwright install chromium`.

### Playwright cannot download browsers (403 from cdn.playwright.dev)
Sandboxed/CI-like environments may block the browser CDN. If a Playwright-managed chromium is preinstalled (this remote env ships one under `/opt/pw-browsers/`), point the suite at it with a local-only config that extends `playwright.config.ts` and sets `use.launchOptions.executablePath` — don't commit it (machine-specific path). If the local `uv` is too old to parse `exclude-newer = "7 days"` in `backend/uv.toml`, run the suite with `UV_NO_CONFIG=1` (harmless here: the E2E backend installs nothing; `uv run` only uses the existing lockfile environment).

### npm installs a package newer than 7 days despite the .npmrc cooldown (or errors with "Invalid time value")
Two distinct causes, both observed 2026-06-12:
1. **Wrong value format.** `min-release-age` takes a plain number of days (`min-release-age=7`). The old `7d` suffix form is invalid: npm >= 11.10 fails every install with `npm error Invalid time value`, while older npm ignores the unknown-typed key entirely.
2. **npm too old.** Enforcement requires npm >= 11.10; older versions skip the setting **silently** and resolve to the newest release (npm 10.9.2 installed a same-day dompurify). This machine's nvm node v22 was upgraded to npm 11.16.0 on 2026-06-12.

To verify enforcement is live: `npm install --dry-run <pkg>@<version-published-this-week>` from `frontend/` must fail with `notarget No matching version found ... with a date before <cutoff>`. On a machine with old npm, check release dates by hand (`npm view <pkg> time --json`) and pin the newest version at least 7 days old with `npm install --save-exact <pkg>@<version>`. Note the cooldown only matters where dependency resolution happens (adding/updating packages locally); CI runs `npm ci`, which installs the lockfile verbatim.

npm 11 also emits `npm warn allow-scripts` for esbuild/fsevents install scripts — npm now blocks install scripts by default. Tests and builds pass with those scripts skipped, so leave them unapproved.

### CI fails with `npm ci ... Missing: esbuild@X from lock file` even though the lockfile was just regenerated
npm 10 (bundled with node 22, used by CI) and npm 11 disagree about peer dependencies: vitest 4 ships a nested vite 8 whose *optional* peer dep on `esbuild ^0.27 || ^0.28` is materialized into the install tree by npm 10 but not npm 11. A lockfile written by npm 11 therefore fails `npm ci` under npm 10. Worse, regenerating the lock with an npm that ignores `min-release-age` (see above) resolves that peer to the newest esbuild, which can violate the 7-day cooldown (0.28.1 was 1 day old when this bit on 2026-06-12). Fix: pin the peer with a scoped override in `frontend/package.json` (`"overrides": { "vitest": { "vite": { "esbuild": "<7-day-old version>" } } }`), regenerate the lock, and verify with **both** `npm ci --dry-run` (npm 10) and `npx npm@11 ci --dry-run`.

### CI `audit` job suddenly fails (pip-audit / npm audit) with no code change — often right after a merge to `main`
`pip-audit` and `npm audit` query the **live** advisory database on every run; there is no pinned snapshot. A PR that passed audit can fail the post-merge run on `main` (or any later run) the moment a new advisory is published against an already-installed version. The failure is therefore not caused by the merge — the lockfile is unchanged, the advisory is new. Confirm with `gh run view <id> --log-failed`: look for `Found N known vulnerabilities` naming a CVE with a recent `CVE-20YY-` id.

Fixing collides with the 7-day install cooldown (`backend/uv.toml` `exclude-newer`, `frontend/.npmrc` `min-release-age`): a fix version published in the last 7 days **cannot** be installed under our own policy, so there is an unavoidable window where `main` audit stays red. Options, in order of preference: (1) if a fix version is already >7 days old, bump it — `uv lock --upgrade-package <pkg>` (uv honors `exclude-newer` and picks the newest eligible version automatically) or the npm equivalent; (2) wait for the newest fix to age past 7 days, then bump; (3) bump to an older fix version that clears the cooldown if it covers the advisory; (4) as a last resort, defer a specific advisory with a tracked `pip-audit --ignore-vuln <ID>` / `npm audit` exclusion and a comment. Note transitive-only deps (e.g. `starlette`, `python-multipart` via `fastapi`) won't be touched by Dependabot **version** updates — only Dependabot **security** updates (a repo setting) reach them, and those also respect the cooldown.

### A merged Dependabot PR silently downgrades a backend package (uv.lock out of sync with pyproject, but CI was green)
`uv sync --frozen` installs `uv.lock` **verbatim and does not validate it against `pyproject.toml`** — a lock that pins a version *below* a `pyproject` floor still syncs with exit 0. So CI's backend job stays green even when the two have drifted apart. This bit on 2026-06-16: a Dependabot frontend PR was rebased onto a `main` that had bumped `PyMuPDF>=1.27.2.3` and `pytest-asyncio>=1.4.0`; the rebase took main's new `pyproject` constraints but kept the branch's older `uv.lock` (pymupdf 1.27.2.2, pytest-asyncio 1.3.0, both below their floors). Merging it would have regressed both packages on `main`.

How to catch it: after a Dependabot rebase that touches `pyproject` (or any time the lock's age looks off), run `uv lock` in `backend/` — if it reports `Updated <pkg> vX -> vY`, the committed lock was stale; commit the reconciled lock. To detect drift without changing anything, `uv lock --check` (or `uv lock --locked`) fails when the lock doesn't match `pyproject`. Consider adding `uv lock --check` to the backend CI job so `--frozen`'s blind spot can't merge a desynced lock. `uv lock` honors `exclude-newer` in `backend/uv.toml`, so it won't pull anything inside the 7-day cooldown.

### My documents are gone, or I see a "Studious サンプル教科書" after `make dev-backend`
`make dev-backend` is the development setup: it runs the mock VLM provider against `backend/.dev-data`, a throwaway data dir it seeds with a sample textbook, not against `backend/data`. Your real documents are untouched; they appear when the backend runs against `backend/data`: start it with `make run-backend` (real Keychain keys, real model, no `--reload`). The web UI shows an amber "Mock VLM · seed data" pill in the top bar whenever the mock is active, and `GET /api/providers` reports `"mock": true` for the VLM. Related checks:

- Transcriptions say "Mock transcription" and breakdowns always describe 勉強: that is the canned mock output (`backend/app/providers/vlm/mock.py`), not a broken model call.
- To run both at once, give the dev stack another port: `make dev-backend BACKEND_PORT=8001` and `make dev-frontend BACKEND_PORT=8001` (the second vite takes port 5174 if 5173 is busy).
- Dev data looks wrong or half-edited: `make dev-reset` deletes `backend/.dev-data` and seeds it again. The seeder does nothing when the dir already holds a document, and refuses to run against `backend/data`.
- Vocab items in the dev app have no JLPT/common badges: reference data is linked into `.dev-data/refs` from `backend/data/refs` only when that exists (the seeder prints which case it hit). Build it into the dev dir with `cd backend && STUDIOUS_DATA_DIR=.dev-data uv run python scripts/fetch_refs.py`.
- `STUDIOUS_VLM_PROVIDER` accepts only `anthropic` or `mock`; anything else stops the backend at startup with a `ValueError` naming the variable.
- The sample page images come from `backend/seed/sample_textbook.pdf`; after editing `backend/seed/textbook.json`, run `cd backend && uv run python scripts/build_seed.py` on a Mac (it needs the Hiragino fonts) to rebuild the PDF and the region boxes, then `make dev-reset`.

### Upload fails with 400 "could not render uploaded file"
The file reached the backend but PyMuPDF/Pillow could not parse it — usually a corrupt download, a password-protected PDF, or a file whose extension doesn't match its contents. The partial document directory is cleaned up automatically (nothing appears in the library), and the render error is logged as `document_render_failed` with the underlying parser message. Re-export or decrypt the source file and upload again. Note: the re-upload endpoint (`PUT /api/documents/{id}/file`) does not yet have this protection — a failed re-upload render can leave a document with stale metadata and no pages (see R6 in `docs/archive/improvement-recommendations.md`).

### Spinner never stops on a region transcription
1. Check the job JSON — if `status: "failed"` with an `ANTHROPIC_API_KEY is not set` error, the backend process didn't see the env var. You are probably on the real provider without a key: use `make run-backend` (reads the Keychain), or `make dev-backend` for the mock. Restart it.
2. If the job completed but the UI didn't update, inspect the EventStream — confirm `job-done`/`job-failed` actually streamed (not just `snapshot` + `ping`).
3. The frontend handles the SSE race where a job finishes before `EventSource` subscribes by reading terminal status from the replayed `snapshot`. If you change `openJobStream` consumers, preserve that behavior.

### `ANTHROPIC_API_KEY is not set`
The backend process can't read the key from its environment. `make run-backend` reads `ANTHROPIC_API_KEY` (and `WANIKANI_API_TOKEN`) from the macOS Keychain when it starts; the keys are deliberately not exported from `~/.zshrc`. Check that the Keychain item exists (`security find-generic-password -s ANTHROPIC_API_KEY -a "$USER"` prints its attributes, not the secret), then restart `make run-backend`. Starting uvicorn by hand skips the lookup. `make dev-backend` never reads the Keychain: it runs the mock provider, which needs no key. Inside Claude Code's sandbox the Keychain lookup may be blocked, which is intended: an agent's shell should not get the real key by default.

### In a Claude Code session, `gh` fails with `~/.config/gh/config.yml: operation not permitted`, or git fails with `Host key verification failed`
The sandbox denies reads of `~/.config/gh` and `~/.ssh`. The owner's user settings exclude `gh *`, `git push *`, `git fetch *` and `git pull *` from the sandbox, but an exclusion matches only when the command is run on its own. Chained after other commands (`git log && gh pr list`), the whole line runs sandboxed and the credential read is refused. The same happens when the command contains a substitution, such as `gh pr create --body "$(cat <<'EOF' ...)"`; pass `--body-file` instead. Run `gh` and the git network commands as separate, plain commands. Git commands that reach the remote but are not on the list (`git ls-remote`, `git clone`) fail the same way; use `git fetch` instead. Verified 2026-11-13: `gh pr list` and `git push --dry-run origin main` both work when run alone.

### `docker build` fails in `uv sync` with "Failed to build `uvloop`" / "no acceptable C compiler found in $PATH"
The Python base image is newer than the wheels a dependency publishes, so uv falls back to compiling from source and the slim image has no compiler. Seen 2026-11 when Dependabot moved the base from 3.13 to 3.15 (`uvloop` 0.22.1 had no 3.15 wheel); the PR auto-merged because the `docker` job was not a required check. Fix: put the previous `FROM python:...` tag and digest back in `Dockerfile`. Dependabot now ignores Python minor and major bumps for the image (`.github/dependabot.yml`); move the minor by hand once `make docker-smoke` passes on it.

### Transcription fails after about 90 seconds with `vlm_call_error` / `APIConnectionError`
The log shows two `Retrying request to /v1/messages` lines about 30 seconds apart, then `error_class: APIConnectionError` with no `status_code`. This is the network, not the key: a rejected key is an instant 401 logged with a status code, and the SDK's own timeout (10 minutes by default) logs as `APITimeoutError`. Something between the backend and the API is closing connections that stay quiet for 30 seconds. Transcription is one non-streaming request, and the model can think for longer than that before sending its first byte. Seen 2026-11-13 on a guest Wi-Fi network (through a VPN); the same request succeeded on a phone hotspot. Switch networks. Sentence breakdowns stream their response, so they can keep working on a network where transcription fails; that difference confirms the diagnosis. The handler logs only the exception class, so the underlying network error is not in the log.

### Job stuck in `running`
The worker is sequential (`backend/app/jobs/` `JobManager`). One stuck job blocks all subsequent ones. Check backend stdout for an exception traceback in the worker, then either let it finish or restart the backend (in-progress jobs do not resume on restart).

### Job stuck in `queued` forever (worker idle, later jobs may unstick it)
Two historical causes, both fixed 2026-07-07 (see `docs/archive/audit-2026-07-mobile-spike.md`):
1. `JobManager.submit()` used to `put_nowait` onto the worker's `asyncio.Queue` from a Starlette threadpool thread (submitting routes are sync `def`s). `asyncio.Queue` is not thread-safe — the cross-thread wakeup could be lost, leaving the job `queued` until some later submission happened to wake the worker. Fixed with `loop.call_soon_threadsafe`. If a stuck-in-`queued` job reappears, check whether a new code path calls `submit()`/`put_nowait` from outside the event loop.
2. An exception escaping a job runner used to be logged but never marked the job failed, so its status (and SSE stream) never reached a terminal state. `_run` now marks non-terminal jobs `failed` with an `internal error: …` message — so a job showing that error means the runner raised outside its own handling; the traceback is in backend stdout under the same correlation id.

### Sentence breakdown fails immediately with "no transcription"
The breakdown job (`job_type=breakdown_region`) requires the region to have `transcription_md` set on disk before it runs. The API rejects the POST with 409 if the region has not been transcribed yet, and the job handler fails fast with the same message if a race wipes it. Transcribe the region first (or wait for the in-flight transcription to finish), then retry the breakdown.

### Sentence breakdown fails with "model returned no sentences for this region" (or legacy "tool response missing non-empty `sentences`")
The VLM tool-use call returned, but the model's tool input either omitted `sentences` or sent an empty array. This is logged in `llm_audit.YYYY-MM.jsonl` with `job_type=breakdown_region`, `status=error`, and the full token usage so the call still counts toward cost. The breakdown schema requires `sentences`, sets `minItems: 1`, and breakdown requests use `max_tokens: 8192`. If `stop_reason=max_tokens`, the response was truncated before the tool input completed (the error message says so explicitly); split the region smaller or make the prompt/output less verbose. Otherwise the model judged there was nothing to split — common on regions that are purely visual or all-blank exercise items the model declined to break down. Inspect the audit entry's `request_id` to pull the raw call from Anthropic logs, or just retry; the `<region_tag>` hint and exercise-item rules in `SENTENCE_BREAKDOWN_PROMPT` (`backend/app/config.py`) usually coax a non-empty result on `exercises`/`instructions` regions. The operation is idempotent and overwrites stale state when `overwrite=true`.

### Exercise completion fails with "tool response missing `answer` or `examples`" (or the truncated variant)
The `record_exercise_completion` tool call returned but the model's tool input was missing `answer`, or sent an empty/invalid `examples` list on an item that needed one. Logged in `llm_audit.YYYY-MM.jsonl` with `job_type=exercise_completion`, `status=error`. There are **two distinct causes** — check `stop_reason` in the audit entry to tell them apart:

- **`stop_reason=max_tokens` → truncation.** This is a large forced tool call (answer + answer_english + explanation + three fully-glossed Japanese examples, each with japanese/reading/english/explanation) run at `xhigh` effort, and the output ran past `max_tokens` before `examples` finished serializing — the SDK then hands back a partial tool input. The budget is `max_tokens: 8192` (`backend/app/api/regions.py`), matching breakdown; the error message says "truncated at max_tokens" explicitly. If it recurs, the item is unusually long — split/simplify it. Truncation is *not* retried (a resend with the same budget can't help).
- **`stop_reason=tool_use` → intermittent malformed response.** The model finished cleanly but still omitted `answer`, despite producing a normal-sized output (often a few hundred tokens, well under budget). It's low-rate and not tied to length — the same item usually succeeds on resend. A forced tool call isn't strict-validated, so the schema can't prevent it. `_run_exercise_completion_job` now **retries once** on this case; the generic "missing `answer` or `examples`" error only surfaces if both attempts come back malformed. Each attempt is a billed call and is audited separately, so a recovered completion leaves one `error` then one `success` entry. Just retry from the UI if it still fails.

An empty `examples` list is only treated as malformed when `exercise_type` is `"open"` (or missing/unrecognized, for older responses). `EXERCISE_COMPLETION_PROMPT` (`backend/app/config.py`) has the model classify each item as `open` (free completion — must return two or three alternative `examples`, per the Study profile's answer length), `question` (comprehension/discussion question — model answer, `examples: []`) or `constrained` (a word-bank or inline `（A／B）`-style choice item — must return `examples: []`, since the textbook already limits the answer to a closed set and inventing "alternatives" would mislead the learner). `_run_exercise_completion_job` only requires non-empty `examples` when `exercise_type` is neither `"constrained"` nor `"question"`.

If instead the model set `no_exercise: true`, the job fails with a `no_exercise:` message (that's the model correctly reporting the target line isn't a drill item, audited as success). The operation is idempotent and overwrites stale state when `overwrite=true`.

### Exercise completion answer isn't highlighting the filled-in word
The completion pane bolds/highlights the filled-in span of `answer` (`.exercise-completion-fill` in `breakdown-pane.ts`, `**bold**` in the markdown export) by doing a plain `indexOf` substring search for `entry.filled_text` inside `entry.answer` — there's no character-offset math, since offsets are unreliable for a model to produce but exact substrings are not (same reasoning as the vocab/grammar link highlighting in `breakdown_links.py`). This is a purely cosmetic feature: if it doesn't fire, the answer still renders correctly, just unhighlighted.

It won't highlight when `filled_text` is empty. `_run_exercise_completion_job` (`backend/app/jobs/`) only keeps the model's `filled_text` if it's a non-empty, exact, verbatim substring of `answer` — anything else (hallucinated text, a value missing the furigana annotation the model added to `answer`, mismatched punctuation) is silently dropped to `""` rather than stored, since a non-substring value would just fail the frontend's `indexOf` lookup anyway. Older stored completions (from before this field existed) also have no `filled_text` and won't highlight until regenerated. This isn't retried or audited as an error — check the stored entry (`storage.load_exercise_completion`) to see whether `filled_text` came back empty.

### Tool-call job fails with `tool_choice: type "tool" and "any" are not supported for this model` (400)
Claude Sonnet 5.5, Opus 5.5 and Fable 5.1 reject a forced `tool_choice`. The provider routes those models (`_STRUCTURED_OUTPUT_PREFIXES` in `backend/app/providers/vlm/anthropic.py`) through structured outputs instead: no `tools`, `output_config.format` carrying the tool schema (made strict — `additionalProperties: false`, length/count keywords stripped by `_strict_json_schema`), and the JSON text parsed back into the same `tool_input` the jobs expect. The `vlm_tool_call_start` log line shows `mode: "structured_output"` or `"forced_tool"`. If this 400 appears, a new model ID isn't in that list. Related 400s on these models: `thinking.type.disabled` (never send it; Sonnet 5.5 uses `between_tools`, only at effort `high` or below — the provider clamps), and a schema keyword structured outputs don't support (add it to `_UNSUPPORTED_SCHEMA_KEYS`). A structured-output response cut off at `max_tokens` becomes `{}`, which the jobs report as truncation; Opus 5.5 gets 16k tokens of extra `max_tokens` headroom because its thinking counts toward the limit.

### Job fails with "model declined the request (refusal, category=…)"
A safety classifier declined the call (HTTP 200, `stop_reason: "refusal"`). The provider raises instead of reading the empty or partial content. Requests to Sonnet 5.5 / Opus 5.5 carry `fallbacks: "default"` (beta `server-side-fallback-2026-07-01`), so declines in categories Anthropic retries (e.g. `cyber`, `frontier_llm`) are re-run on a fallback model automatically; the result then carries `meta.served_model`. Categories that aren't retried (`bio`, `general_harms`, `reasoning_extraction`) surface as this error. Textbook content should essentially never trigger it; if it does, retry once, then switch models in Settings for that item.

### Tool-call job fails with "Thinking may not be enabled when tool_choice forces tool use"
Affects any job that uses `provider.call_tool` (sentence breakdown, chapter grammar guide). Anthropic rejects the request when `tool_choice` pins a specific tool *and* `thinking` is also set. The provider strips `thinking` for forced-tool calls (see `backend/app/providers/vlm/anthropic.py::call_tool`); if this error reappears, a new code path is sending `thinking` alongside `tool_choice={"type": "tool", ...}`. Reasoning budget on these calls is controlled via `output_config.effort` (`vlm_effort_breakdown`) instead — `thinking` is redundant.

### Vocab term in the breakdown table doesn't underline in the sentence
The sentence-link computer (`backend/app/services/breakdown_links.py`) tries three strategies in order: exact-substring of `word`, exact-substring of `reading`, then a "drop trailing hiragana" stem. All three can miss legitimately:
- Pure-hiragana inflected adjectives (e.g., `おいしい` vs `おいしかった`) — the stem is too short to risk and is rejected.
- Stems that would land inside a longer kanji run (e.g., `行` inside `銀行` when vocab is `行く`) — rejected on purpose to avoid false positives.
- Compound vocab the model split into pieces — usually still links each piece, but adjacent splits can lose one if their stems collide.

To confirm what happened, look up the region's breakdown JSON on disk (`backend/data/documents/<doc>/chapters/<chapter>/regions/<region>.json` → `breakdown.sentences[i].links`); a missing link for a vocab index means none of the three strategies matched. The vocab row still renders in the table — the linker only suppresses the *inline* underline. The `breakdown_links_annotated` log line gives per-region totals by match strategy if you want to track drift over time.

### Grammar pattern doesn't underline in the sentence
Grammar links come from `surfaces` in the model's tool response — literal substrings of the sentence text that anchor each pattern (we tried offsets first; the model couldn't count CJK code-points reliably). If a pattern doesn't link, either:
- The model omitted `surfaces` for that entry. Inspect the breakdown JSON (`grammar[i].surfaces`); regenerating the breakdown often produces a complete set on the next call.
- The surface string isn't actually a substring of `text` (model paraphrased rather than copying). Same fix — regenerate.

Multiple identical surfaces (e.g., two ます in one sentence) are linked to *different* occurrences automatically. Surfaces shared across patterns (e.g., `的` inside `社会文化的な`) are allowed to overlap — the popover stacks both entries.

### Grammar guide comes back mostly in Japanese instead of English explanations
`GRAMMAR_GUIDE_PROMPT` (`backend/app/config.py`) used to ask for "a concise
study guide in a mix of Japanese and English" — vague enough that different
models resolved it differently. Guides generated under `claude-opus-4-7`
wrote English explanatory prose with Japanese limited to patterns/examples;
after the default VLM switched to `claude-sonnet-5` (2026-07-06), the same
prompt produced guides where `intro` and most section `body_md` are written
in Japanese prose, with English only in translation lines. No grammar-guide
code changed between the two — it was purely the model swap plus prompt
ambiguity. Confirmed by comparing the `model` field stored in each
chapter's `grammar_guide.json` against how Japanese-heavy its `body_md`
reads.

Fixed by making the prompt's language rule explicit (English for all
explanatory prose; Japanese only for the pattern itself, quoted Japanese
terms/forms, and example sentences) rather than leaving "a mix" to
interpretation. If this drifts again on a future model swap, regenerate
via `POST /api/documents/{doc}/chapters/{chapter}/grammar-guide` with
`{"overwrite": true}` after checking the guide reads the way you expect —
there's no automated check for output language, since this is a stylistic
property of free-text generation, not something the tool schema validates.

### "this region is a continuation of region ... generate the breakdown from there" (409)
By design. Breakdowns and exercise completions on a region that is the *target* of a `continues_to` pointer are blocked so the chain is always processed from the head — otherwise the tail-only breakdown would miss any sentence whose start lives on the prior page. The chapter view replaces the Generate-breakdown UI with a notice and a "Go to source" button for these regions. To bypass: unlink the source (✕ on the chip), or run the breakdown from the source as intended.

### Linked region's text isn't appearing in breakdown / exercise completion
The breakdown and exercise-completion jobs read the source region from disk and walk `continues_to` forward via `backend/app/services/region_chain.py` to build the combined VLM input. If the combined text doesn't reflect the continuation:
- Confirm the link is set on disk: `backend/data/documents/<doc>/chapters/<ch>/regions/<source>.json` → `continues_to` should be the target region id.
- Confirm both regions have `transcription_md` set; an empty tail contributes nothing.
- Check the job log line `breakdown_job_start` / `exercise_completion_job_start` for the correlation id, then `llm_audit.YYYY-MM.jsonl` for the call — the `prompt_hash` differs from the single-region call if the chain was built. (For deeper debugging, the prompt itself isn't logged, but you can replay locally: load the source region, call `region_chain.resolve_chain` + `combined_transcription`, and compare.)
- Per-region transcription is *not* combined — that's by design; only breakdown and exercise completion use the chain.
- The combined text is concatenated with a blank-line separator only — no `(continues on page N)` marker is injected. That marker used to be there but leaked into prompts and tool output as if it were content; the page boundary is now a frontend rendering concern.

### Exercise completion ignores the reading (explanation says "The reading was not provided")
Comprehension questions only see a reading printed elsewhere if the exercises region cites it via **Reading references** (Phase 2.5, `docs/design/exercise-references-plan.md`). The `question` shape's explanation starts with "The reading was not provided" when the prompt had no reading to draw on. Check, in order:
- The references are on the **chain head**: `backend/data/documents/<doc>/chapters/<ch>/regions/<head>.json` → `references` should list `{doc_id, chapter_id, region_id}` entries. Completions run from the head, and the PUT endpoint refuses a continuation region (409), so references on a tail can't happen through the API.
- The job saw them: the `exercise_completion_job_start` log line carries `reference_count`. A count lower than the stored list means some targets were skipped — look for `reference_missing` (target doc/chapter/region gone, e.g. the reading region was deleted or moved to another chapter) or `reference_untranscribed` (target has no `transcription_md` yet) warnings from `studious.services.region_reference` with the same correlation id. Neither fails the job; references are supplementary context.
- The chapter view marks the same conditions: a red "Missing" entry or a "not transcribed" badge in the Reading references list. Transcribe the reading, or reopen the picker and Save (which drops missing entries), then regenerate the completion.
- To see the exact text the model got, replay locally: `region_reference.combined_reference_text(region_reference.resolve_references(doc, ch, head))`.

### Sentence breakdown pane stuck on "Loading…" forever, reload doesn't help
The breakdown job and the API both completed fine — check `data/jobs/<id>.json`
(`status: "completed"`) and the region's `breakdowns/<region_id>.json` on
disk to confirm. This is a **frontend render crash**, not a stuck job: a
forced tool-use call isn't strict-validated (same caveat as the exercise-
completion malformed-response note above), so a vocab/grammar field can come
back with a garbled key name instead of the expected one — observed once as
`"meaング"` instead of `"meaning"` on a single vocab entry. `render()` in
`breakdown-pane.ts` builds every sentence's HTML in one pass; before this was
fixed, `escapeHtml(v.meaning)` threw on the `undefined` value, which aborted
the whole render before it replaced the "Loading…" spinner — so the pane
looked stuck even though the underlying data was intact, and reloading just
re-ran the same crash. `escapeHtml` (now exported from `breakdown-pane.ts`,
tested in `tests/breakdown-completions.test.ts`) is nullish-safe, so a single
malformed field now renders blank instead of blanking the whole pane.
Diagnosis: an "Unhandled Promise Rejection" in the browser console pointing
into `breakdown-pane.ts`'s `render`/`escapeHtml` (not a fetch/network error)
means the data loaded but rendering blew up — inspect the region's
breakdown JSON on disk for the offending field rather than re-triggering the
job. If a *different* field/function crashes the same way, hand-editing the
bad key on disk (as done here) is a safe, free, deterministic fix — no
backend restart, no re-billed VLM call — versus regenerating the breakdown
via `overwrite: true`, which costs a new call and isn't guaranteed to avoid
the same glitch.

### Benchmark CER spikes or line accuracy collapses
Before assuming a model/prompt regression: check whether the **ground truth** matches the format the current prompt is producing. CER and line-accuracy are computed character- and line-exact — markdown structure (`#`, `**`, `<u>`), fullwidth vs halfwidth punctuation, paragraph wrapping, and inline annotations like `[?N]` all count as differences. If you change the default VLM prompt's output style, the existing GT will need to be regenerated (or normalized before scoring). Rule of thumb: if line accuracy is in single digits while the body text reads correctly side-by-side, it's a format mismatch, not a regression.

### Fill-in blanks show as `\_\_\_\_\_`, vanish, or vary wildly in length
Symptoms: a breakdown sentence displays literal backslashes
(`\_\_\_\_`); an exercise transcription has runs of spaces where the
page has printed underlines; blank length differs between regions.

Cause: blanks are printed rules, and the VLM rendered them in whatever
style it liked — `＿＿＿`, ASCII `______`, markdown-escaped `\_\_\_`
(Sonnet 5.5 did this because it knows `_` is markdown), or full-width
spaces (underline treated as "decorative" and dropped). The breakdown
model copies input verbatim, so it inherited the escapes. The breakdown
pane does not render markdown, so the backslashes show literally.

Fix in place: transcription prompts define the canonical blank
(`＿＿＿＿＿`, see `BLANK_TRANSCRIBE_RULES` in `app/config.py`), and
`services/blanks.normalize_blanks` canonicalizes on write and before
breakdown/completion prompts. Pre-existing data: run
`uv run python scripts/normalize_blanks.py` (dry run) then `--apply`
with the dev server stopped. Legacy blanks transcribed as full-width
spaces can't be recovered without re-transcribing the region.

### Callout labels (boxed ①②… joined to a dialogue line by a leader line) come out as a list after the dialogue, or attached to the wrong line
Textbook dialogues sometimes carry boxed margin labels (e.g. ①はじめの挨拶)
joined to one line by a leader line or speech-bubble tail. Region
transcriptions made before the `<callouts>` rule existed dump them as a
bullet list after the dialogue, losing which line each one labels. Fix:
re-transcribe the region. The `<callouts>` block
(`CALLOUT_TRANSCRIBE_RULES` in `backend/app/config.py`) is part of
`REGION_TRANSCRIBE_PROMPT` and places each callout as a `> ` blockquote
right after the turn its leader line touches. The page-level prompt
(`DEFAULT_VLM_PROMPT`) does not have the rule yet, so use regions for such
pages.
