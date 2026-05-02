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
without a real browser.

### 3.1 Tooling

- Add `vitest`, `@testing-library/dom`, `jsdom` as devDependencies (respect
  the 7-day cooldown in `frontend/.npmrc`).
- Add `test` and `test:coverage` scripts to `package.json`.
- Wire `make test` to run both backend and frontend suites.

### 3.2 Modules

- `modules/region-drawer.ts` — image-coords ↔ normalized-bbox math,
  `setRegions` rerender, click-vs-drag selection threshold.
- `modules/zoom-pan.ts` and `modules/pane-splitter.ts` — transform math and
  clamping; both are pure enough to test under jsdom.
- `modules/page-input.ts` — input parsing (must match backend
  `range_parser` semantics; see phase 4 contract test).
- `router.ts` — hash → page dispatch.
- `api.ts` — with `vi.fn()` mocking `fetch`: correlation header injection,
  error throw on non-2xx, `getTranscription` returns `null` on 404.
- `logger.ts` — correlation id propagation across `startTimer`.

**Exit criteria:** Vitest runs in CI; ≥70% line coverage on `frontend/src/modules/`.

---

## Phase 4 — Cross-cutting

### 4.1 Coverage reporting

- Wire `pytest --cov=app --cov-report=term-missing` into `make test`.
- Set a soft floor (start with 70% on `app/services/` and `app/jobs.py`) once a
  baseline exists. Tighten after each phase.

### 4.2 Frontend↔backend page-spec contract test

The page-range mini-language is parsed in two places (`services/range_parser.py`
and `modules/page-input.ts`). Add a shared `tests/fixtures/page_specs.json`
consumed by both pytest and vitest so divergence breaks CI.

### 4.3 Integration smoke test

With `TestClient` plus a tiny real PDF fixture and a mocked VLM provider, one
test that uploads → creates a chapter → creates a region → submits a region
transcription end-to-end catches wiring bugs unit tests miss.
