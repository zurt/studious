# Codebase Audit — mobile spike branch (2026-07-07)

Full-codebase audit of `cc/mobile-spike`, with extra attention on the
interaction between the FastAPI backend and the iOS/Mac apps (the JSONL
store + CloudKit sync path). Uncontroversial fixes were applied in the
same change as this document; everything else is recorded here as a
finding with a recommendation.

**Companion doc:** `docs/hosting.md` covers moving the backend off the
local machine (DigitalOcean droplet, container), including the security
findings below that only matter once the backend is network-exposed.

## Scope and method

- **Backend↔apps sync path** (reviewed line-by-line): `backend/app/services/store.py`,
  `srs.py`, `api/store.py`, `api/study.py`, and all of
  `apple/StudiousKit` (`StudiousCore`, `StudiousSync`, `studious-sync`
  CLI, `StudiousUI/AppModel`) plus the sync design docs.
- **Backend (non-sync)**: `main.py`, `config.py`, `middleware.py`,
  `jobs.py`, remaining `api/*` and `services/*`, `providers/*`.
- **Frontend**: all of `frontend/src`, plus a cross-check of every
  `api.ts` call against the backend routes.

Verification: `make test` (backend 390 passed incl. one new regression
test, coverage 92%; frontend 112 passed) and `tsc --noEmit`. The Swift
suite (`make test-apple`) could not be run in this audit environment
(no Swift toolchain on Linux); the Swift changes are small and
mechanical, but **run `make test-apple` on the Mac before relying on
them**.

## Fixed in this change

### Sync path (backend ↔ Apple apps)

1. **Swift JSONL append was not O_APPEND → corruption race in bridge
   mode** (`apple/.../StudiousCore/JSONLStore.swift`, `appendLine`).
   The write path did `FileHandle.seekToEnd()` then `write()`. The
   backend, the `studious-sync` CLI, and the Mac app are all documented
   as concurrent writers of the same `data/store/*.jsonl` files
   ("bridge mode"), and the backend appends with POSIX `O_APPEND`
   (`open(..., "a")`). If the backend appended between the Swift
   process's seek and write, the Swift write landed at a stale offset
   and **overwrote** the backend's bytes — a corrupt line and a lost
   record. Now opens the descriptor with `O_WRONLY|O_APPEND|O_CREAT`,
   so every writer's append lands atomically at the true end of file,
   matching the backend's semantics.

2. **LWW merge decided against a stale in-memory view**
   (`ItemStore.merge`, `ReviewLog.union`, `ReviewLog.record`). In
   bridge mode the backend can append an edit after the app's last
   load. A CloudKit/import record older than that edit would still
   "win" against the stale in-memory copy and get appended *after* the
   newer line — and since reads are latest-line-per-id, the older
   record silently shadowed the newer edit. These entry points now call
   `reloadIfChanged()` (a cheap mtime+size check) before deciding.

3. **`ItemStore.append` could mark unseen external lines as loaded.**
   After appending, the store stamped the file signature without
   reading lines other processes had appended since the last load —
   those records then stayed invisible until the next external change.
   `append` now detects pre-existing external changes and does a full
   reload instead of trusting the in-memory view.

### Backend

4. **`JobManager.submit()` pushed onto an `asyncio.Queue` from a
   worker thread** (`backend/app/jobs.py`). All job-submitting routes
   are sync `def`s, so they run on Starlette's threadpool —
   `asyncio.Queue` is not thread-safe and a cross-thread `put_nowait`
   can lose the worker's wakeup, leaving a job stuck in `"queued"`
   forever (rare, timing-dependent, near-impossible to reproduce).
   `submit()` now hands the put to the event loop via
   `call_soon_threadsafe`.

5. **Unexpected job exceptions left jobs stuck in `queued`/`running`**
   (`backend/app/jobs.py`, `_run`). The worker logged the exception but
   never marked the job failed, so its SSE stream never emitted a
   terminal event and the UI spun forever. The worker now marks
   non-terminal jobs `"failed"` with an `internal error` message.
   Regression test added
   (`tests/test_jobs_with_mock_provider.py::test_unexpected_exception_marks_job_failed`).

6. **Upload/reupload blocked the event loop for the whole PDF render**
   (`backend/app/api/documents.py`). `render_pdf_to_pages` (PyMuPDF at
   300 DPI over every page) and the upload copy ran synchronously
   inside `async def` handlers — a large upload stalled every other
   request, including running jobs' SSE streams, for tens of seconds.
   Both are now `asyncio.to_thread`-wrapped.

### Frontend

7. **Stored XSS via chapter title** (`pages/document-view.ts`, chapter
   banner + chapters popover) and **via region label**
   (`pages/chapter-view.ts`, tracker popover). Free-text fields were
   interpolated into `innerHTML` unescaped; a title like
   `<img src=x onerror=...>` executed on view. These were the only
   three unescaped sinks — every other page already escapes. Now
   escaped with the same local `escapeHtml` idiom the rest of the
   codebase uses.

8. **Job streams outlived the chapter view** (`pages/chapter-view.ts`,
   all four `openJobStream` call sites). The unsubscribe functions were
   discarded and callbacks had no unmount guard, so a grammar-guide job
   completing after the user navigated away force-navigated them to the
   guide page (and stray toasts fired on unrelated pages). Streams are
   now tracked, guarded by a `destroyed` flag, and closed at unmount —
   the same pattern `grammar-guide.ts` already used.

9. **Unhandled load rejections** (`chapter-view.ts` and
   `document-view.ts` `load()`). A deleted/missing document or chapter
   (or a network error) left the page stuck on "Loading…" with only a
   console error; the existing `if (!chapter)` branch was unreachable
   because the API helpers throw on 404. Both pages now render an error
   state.

10. **Stale transcription response could win a page-flip race**
    (`document-view.ts`). Rapid next/prev fired overlapping
    `getTranscription` calls with no sequencing; a slow older response
    could overwrite the newer page's pane. Now guarded with a monotonic
    request token. (Nearly invisible on localhost; real once the
    backend is remote.)

11. **Dead code**: unused `fmtBytes` + `void fmtBytes;`
    (`modules/settings-modal.ts`).

## How the backend and the apps actually interact (for orientation)

There is **no HTTP contract between the backend and the Apple apps**.
The integration surface is the on-disk JSONL store plus replicated
semantics:

- `data/store/{vocab,grammar}.jsonl` — append-only, latest line per
  `id` wins, deletes are tombstone lines; `reviews.jsonl` — append-only
  create-only events, merged by id-union.
- The **Mac app** (`studious-mac`) and the **sync CLI**
  (`studious-sync`) open those same files directly ("bridge mode");
  the **iOS app** keeps its own copy in Application Support and syncs
  via **CloudKit** (`CKSyncEngine`, private DB, zone `StudiousZone`) or
  manual JSONL export/import.
- Conflicts: whole-record LWW on the `updated_at` *field* (never
  transport timestamps), tombstones always win, review events are
  conflict-free by construction. FSRS state is never synced — it is
  replayed from the shared review log by two implementations
  (`services/srs.py` and `FSRS.swift`) kept bit-identical by golden
  fixtures (`make golden` / `make test-apple`).

Parity checks done in this audit (all clean): ISO-8601 format
(`+00:00`, 6-digit microseconds) round-trips both ways and Swift's
custom parser accepts every format Python emits; banker's rounding in
`intervalDays`; queue ordering including Python's stable-sort
tiebreakers; event id format (32-hex UUID both sides); JSON encoding
(non-ASCII literal both sides); `elapsed_ms: null` handling; the
LWW/tombstone truth table matches the design doc on both sides.

## Known gaps — deliberate, documented, no action taken

- **Cross-process read-modify-write is still last-writer-wins.** Two
  processes editing the *same item* concurrently (e.g. backend
  `update_item` and Mac-app `setStatus` in the same instant) still race
  at whole-record granularity: both append, last line wins, the loser's
  fields are shadowed (recoverable from the JSONL history). This is the
  documented design tradeoff for a single-user tool
  (`docs/cloudkit-sync-plan.md`, "Conflict policy"); true multi-writer
  safety would need file locking (`flock`) around read-modify-write in
  both languages. Worth doing only if concurrent editing becomes real.
- **`StudiousSyncEngine` swallows merge errors** (`try? store.merge`)
  and grows its `serverRecords` stash unboundedly within a session —
  acceptable for the data volumes involved; worth a log hook when the
  app grows one.
- **iOS StudyView doesn't re-show failed (grade 1) cards within the
  session**, unlike the web study session. Behavior gap, not a bug —
  the card comes back 10 minutes later via the queue.
- **`submit_review` on the backend 404s items deleted mid-session**;
  the iOS side records reviews for locally-known items without that
  check. Dangling events are harmless by design ("referential integrity
  is enforced by the stores").

## Deferred findings (recommend fixing before/with hosting)

These are tracked in `docs/hosting.md` because they only bite once the
backend leaves localhost:

- **No authentication on any endpoint** — includes destructive
  (`DELETE /api/documents/{id}` → `rmtree`) and costly (transcribe with
  arbitrary client-supplied `model`/`max_tokens` forwarded to the
  Anthropic API) operations. *Must* be fixed before network exposure.
- **CORS origin hardcoded** to `http://localhost:5173` in `main.py`.
- **No upload size / PDF page-count limits** (disk/memory exhaustion).
- **SSE `openJobStream` has no reconnect or polling fallback**
  (`api.ts`): `es.onerror = () => es.close()` kills progress reporting
  on the first blip. Invisible on localhost; guaranteed pain through a
  reverse proxy with idle timeouts.
- **Read-modify-write races on chapter/region/job JSON metadata**
  (`services/storage.py`) — same class as the store item race above,
  fine single-user, needs locking if the backend ever serves >1 writer.
- **Blocking harvest/enrich/jmdict work inside async job runners**
  (`jobs.py` → `services/harvest.py` etc.) — event-loop latency during
  big harvests; wrap in `asyncio.to_thread` when convenient (touching
  the pipeline means re-running `make benchmark` per project policy).

## Suggested follow-ups (not started)

1. Run `make test-apple` on the Mac to confirm the Swift changes, and
   exercise bridge mode (backend + Mac app + a `studious-sync merge`)
   against a scratch data dir.
2. Decide on the hosting recommendation in `docs/hosting.md` and do the
   auth work there before exposing anything.
3. Consider `flock`-based locking for the JSONL stores if the Mac app
   gets heavier concurrent use.
