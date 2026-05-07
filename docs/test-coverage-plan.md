# Test Coverage Plan

A snapshot of where the test suite is thin today and a phased plan for closing
the largest gaps. Phases are ordered by risk-reduction per unit of effort: do
phase 1 before phase 2, etc.

## Current state

- Backend: ~10 tests across 5 files (`backend/tests/`). Covered: storage CRUD,
  page-range parser, `crop_region`, two `JobManager` happy-path cases.
- Frontend: **no tests, no test runner configured.** `package.json` has only
  `dev`, `build`, `preview`, `typecheck`.
- No coverage reporting on either side (no `pytest-cov`, no `vitest`).

---

## Phase 1 — API handlers, job-runner branches, middleware

Highest-leverage gaps. These cover code paths that handle untrusted input,
shape user-visible errors, or are the documented core of the system.

### 1.1 FastAPI handlers via `TestClient`

No test currently exercises a route. Add an `httpx`/`TestClient` fixture and
cover, at minimum:

- `api/documents.py`
  - `POST /api/documents`: PDF and image suffix routing; unsupported suffix → 400;
    missing filename → 400; rendered page count is written back into `meta.json`.
  - `PUT /api/documents/{id}/file`: replaces `original.*`, wipes `pages/`, re-renders.
  - `DELETE /api/documents/{id}`: 404 on unknown id; removes the directory.
  - `GET /api/documents/{id}`: includes `transcribed_pages` and `chapters`.
  - `GET .../pages/{p}/image` and `.../pages/{p}/transcription`: 404 paths.
- `api/chapters.py`: `page_start < 1`, `page_end > page_count`, empty update body → 400.
- `api/regions.py`: bbox validator (`0 <= x1 < x2 <= 1`), tag whitelist, page must
  fall inside the chapter's range, move-region with destination chapter range
  check, `transcribe_region` job submission shape.
- `api/transcribe.py`: page-spec `ValueError` → 400; VLM prompt fallback when
  `prompt` is omitted; unknown `doc_id` → 404.
- `api/jobs.py` (SSE): snapshot replay as the first event, `ping` after
  timeout, terminal close on `job-done` / `job-failed`.
- `api/providers.py`: `unavailable` branch when a provider's `info()` raises.

### 1.2 `jobs.py` paths beyond OCR happy case

Current tests cover only sequential OCR and `overwrite=False`. Add:

- VLM engine branch (`jobs.py:147-154`) — `prepare_for_vlm` is invoked; the
  saved payload records `prompt` and `model`.
- `_run_region_job` (`jobs.py:198-251`) — happy path writes
  `transcription_md`/`transcribed_model` onto the region; missing image and
  unknown provider both end as `failed`.
- Unknown engine → `failed` with error payload (`jobs.py:111-120`).
- Per-page exception → `page-error` event, terminal status
  `completed_with_errors` (`jobs.py:155-159, 186`).
- Missing page image → recorded as a page error, not a job failure.
- `overwrite=True` actually replaces an existing transcription.
- SSE `subscribe` / `unsubscribe` lifecycle — `_emit` is a no-op when there are
  no listeners.
- Two queued jobs run **sequentially** (the `JobManager` docstring's
  invariant).

### 1.3 Middleware and structured logging

Easy to test, and high-leverage because every other test relies on this
implicitly:

- `CorrelationMiddleware` echoes an incoming `x-correlation-id`, generates a
  16-char one when absent, and resets the contextvar even when the handler
  raises.
- `StructuredFormatter` emits valid JSON, includes the correlation id, merges
  the documented `extra` fields, and captures `exc_info`.

**Exit criteria:** `pytest --cov=app` reports ≥75% line coverage on
`app/api/`, `app/jobs.py`, and `app/middleware.py`.

---

## Phase 2 — Services, providers, storage edges

### 2.1 PDF service

`services/pdf.py` only has `crop_region` covered. Add:

- `render_pdf_to_pages`: multi-page rasterization, file naming `0001.png`,
  page-count return value (use a tiny generated PDF via PyMuPDF).
- `copy_image_as_page`: RGB conversion, single-page output.
- `prepare_for_vlm`: downscale path when `long_edge > max_edge`, no-op when
  smaller, RGB conversion of an RGBA input.

### 2.2 Provider registry and providers

- `providers/registry.py`: `register` / `get` / `list` happy paths; `get`
  raises on unknown name; `bootstrap_default_providers` is idempotent.
- `providers/ocr/tesseract.py`: `_to_markdown` paragraph splitting (testable
  without the tesseract binary).
- `providers/vlm/anthropic.py` with the SDK mocked:
  - `_model_deprecates_temperature` for `claude-opus-4-7` (drops `temperature`
    from the request kwargs).
  - Default-model fallback when `config["model"]` is missing.
  - Base64 envelope shape and the message structure passed to
    `client.messages.create`.
  - `usage` and `stop_reason` extraction into `meta`.

### 2.3 Storage edge cases

`storage.py` is solid for CRUD, but missing:

- `_atomic_write_text` crash safety: no leftover `.tmp` after success; a
  pre-existing `.tmp` is overwritten cleanly.
- `list_documents` ordering by `created_at` (recent-first, as the function
  promises — current test only checks the set, not order).
- Round-trip of Japanese strings in chapter titles and region labels (UTF-8 +
  `ensure_ascii=False`).
- `update_job` against a missing job id raises `KeyError`.

**Exit criteria:** `pytest --cov=app` reports ≥80% on `app/services/` and
`app/providers/`.

---

## Phase 3 — Frontend test runner and pure-logic modules

Stand up Vitest and cover the modules whose logic is reasonable to test
without a real browser. Frontend currently has zero tests and no runner —
`frontend/package.json` only has `dev`, `build`, `preview`, `typecheck`.

### 3.1 Tooling

- Add `vitest`, `@testing-library/dom`, `jsdom` as devDependencies. Respect
  the 7-day cooldown in `frontend/.npmrc` — if any version is fresher, pin
  one published before the cooldown window.
- Add `test`, `test:watch`, and `test:coverage` scripts to
  `frontend/package.json`.
- Add `frontend/vitest.config.ts` with `environment: "jsdom"` and a
  `setupFiles` entry that polyfills/seeds anything the modules depend on
  (e.g. `crypto.randomUUID` for `logger.generateCorrelationId`).
- Update the root `Makefile`: `test` should depend on `test-backend` and a
  new `test-frontend` target (`cd frontend && npm test`).

### 3.2 Modules and what to assert

Priority order — start at the top, each row is one test file:

1. `src/logger.ts` → `tests/logger.test.ts`
   - `generateCorrelationId()` returns the documented format (match the
     backend `CorrelationMiddleware` length/charset)
   - `info`/`warn`/`error` emit valid JSON with the active correlation id
   - `startTimer().end()` records monotonic duration (mock `performance.now`)

2. `src/api.ts` → `tests/api.test.ts`
   - `vi.fn()`-mock `fetch`; assert correlation header on every request
   - 4xx/5xx responses throw with body in the message
   - `getTranscription` resolves `null` on 404 (special-case)
   - `pageImageUrl(docId, page)` builds the right path

3. `src/router.ts` → `tests/router.test.ts`
   - Pattern compilation: `/doc/:id` matches `/doc/abc` with
     `params.id === "abc"`; literal segments don't match params
   - `navigate("/x")` updates `location.hash` and triggers the right route
   - `replaceQuery({k: "v"})` preserves the path

4. `src/modules/pane-splitter.ts` → `tests/pane-splitter.test.ts`
   - Ratio clamps to `[MIN_RATIO, MAX_RATIO]`
   - localStorage round-trip survives a remount (state persists)
   - Collapse/expand toggles the right CSS class

5. `src/modules/region-drawer.ts` → `tests/region-drawer.test.ts`
   - `imageToNorm`/`normToImage` round-trip within FP tolerance
   - Click below the drag threshold selects the region under the pointer
   - Drag above the threshold creates a new bbox with normalized coords in
     `[0, 1]` and `x1 < x2`, `y1 < y2`
   - `setRegions(arr)` rerenders — each region has a corresponding handle

6. `src/modules/zoom-pan.ts` → `tests/zoom-pan.test.ts`
   - Wheel + Cmd zooms about the cursor (transform math)
   - Pan clamps so the image cannot leave the viewport entirely
   - `fit()` resets transform to the documented baseline

7. `src/modules/page-input.ts` → `tests/page-input.test.ts`
   - Click swaps span → input; Enter commits with
     `Math.min(max, Math.max(min, value))`
   - Esc/blur restores prior text and does not call `onCommit`
   - Non-finite input (e.g. empty) restores without committing

### 3.3 Out of scope for Phase 3

- E2E (Playwright/Cypress) — separate phase if/when needed
- Visual regression — manual review for now
- `breakdown-pane.ts`, `region-list.ts`, `settings-modal.ts` are heavily
  DOM-bound; defer until the pure-logic modules above are green and we
  have the conventions down

**Exit criteria:** `make test` runs both suites; Vitest reports ≥70% line
coverage on `frontend/src/modules/`, `api.ts`, `logger.ts`, `router.ts`.

---

## Phase 4 — Cross-cutting

### 4.1 Coverage reporting

- Wire `pytest --cov=app --cov-report=term-missing` into `make test`.
- Set a soft floor (start with 70% on `app/services/` and `app/jobs.py`) once a
  baseline exists. Tighten after each phase.

### 4.2 Page-spec parser

The page-range mini-language is parsed in `services/range_parser.py` only —
the frontend (`modules/page-input.ts`) is a single-number input that posts
the raw string to the backend. No frontend parser exists, so no contract
test is needed. If a frontend parser is ever added, mirror the backend
fixtures so divergence breaks CI.

### 4.3 Integration smoke test

With `TestClient` plus a tiny real PDF fixture and a mocked VLM provider, one
test that uploads → creates a chapter → creates a region → submits a region
transcription end-to-end catches wiring bugs unit tests miss.
