# Logging & Observability Improvements

A prioritized backlog for fixing the logging surface. Each item is sized so a
fresh contributor can pick it up cold. Items 1–4 are the highest-leverage and
should ship together; 5–8 are the next batch; 9–12 are polish.

Findings come from the review in commit-history rev a35992 (LLM audit log
landing). Read that review for context if not obvious.

---

## P0 — correctness fixes

### 1. Stop dropping `extra=` fields in `StructuredFormatter`

**Why:** `middleware.py:68` allowlists 7 fields. Every other field passed via
`extra={}` (chapter_id, region_id, engine, provider, render_ms, source_type,
page_count, error_count, src/dst_chapter_id, …) is silently discarded. Most
log call sites today produce JSON missing the context the caller intended.

**Where:** `backend/app/middleware.py` — `StructuredFormatter.format`.

**How:** replace the allowlist with a denylist of stdlib `LogRecord`
attributes. Roughly:

```python
_STDLIB_RECORD_ATTRS = frozenset(vars(logging.LogRecord("", 0, "", 0, "", (), None)).keys()) | {
    "message", "asctime",
}

def format(self, record):
    entry = {
        "ts": self.formatTime(record),
        "level": record.levelname,
        "logger": record.name,
        "msg": record.getMessage(),
        "correlation_id": correlation_id_var.get(""),
    }
    for k, v in record.__dict__.items():
        if k not in _STDLIB_RECORD_ATTRS and k not in entry:
            entry[k] = v
    if record.exc_info and record.exc_info[1]:
        entry["exception"] = self.formatException(record.exc_info)
    return json.dumps(entry, ensure_ascii=False, default=str)
```

**Tests:** `tests/test_logging.py` — log a record with arbitrary kwargs and
assert they appear in the JSON. Prevents the regression returning.

**Out of scope:** sanitising large/binary fields. Callers control what they
pass.

---

### 2. Propagate `correlation_id` into `JobManager`

**Why:** the worker runs in an `asyncio.Task` created at startup
(`jobs.py:99`). The contextvar set by `CorrelationMiddleware` is empty by then,
so every transcription log line has `"correlation_id": ""`. End-to-end tracing
is broken at the most expensive operation.

**Where:** `backend/app/jobs.py` — `JobManager.submit`, `_run_job`.
`backend/app/middleware.py` — re-export `correlation_id_var`.

**How:**

1. In `submit`, capture the current CID and store it on the job payload:
   ```python
   from .middleware import correlation_id_var
   def submit(self, payload):
       payload = {**payload, "correlation_id": correlation_id_var.get("")}
       job = storage.create_job(payload)
       ...
   ```
2. In `_run_job`, set the context var for the duration of the job:
   ```python
   async def _run_job(self, job_id):
       job = storage.load_job(job_id)
       if job is None: return
       token = correlation_id_var.set(job.get("correlation_id") or "")
       try:
           ...
       finally:
           correlation_id_var.reset(token)
   ```

**Tests:** `test_jobs_with_mock_provider.py` — submit a job from a context
where the CID is set, then assert the job record persists it and the worker's
log records carry it. Capture logs with `caplog`.

---

### 3. Log every Anthropic VLM call from the provider

**Why:** the only outbound network call in the system is invisible. No
request start, no model snapshot, no Anthropic `request-id` header (needed to
file support tickets), no error class, no retry signal. Cost diagnosis is
impossible from the audit JSONL alone — we don't know which calls were cache
hits, what response sizes were, or which calls timed out vs. errored at the
API.

**Where:** `backend/app/providers/vlm/anthropic.py`.

**How:**

```python
log = logging.getLogger("studious.providers.anthropic")

def transcribe(self, image_bytes, prompt, config):
    model = ...
    log.info("vlm_call_start", extra={
        "model": model,
        "max_tokens": max_tokens,
        "image_bytes": len(image_bytes),
        "prompt_hash": _sha256_first8(prompt),
    })
    t0 = time.monotonic()
    try:
        message = self._client.messages.create(...)
    except anthropic.APIStatusError as e:
        log.error("vlm_call_error", extra={
            "model": model,
            "status_code": e.status_code,
            "request_id": getattr(e, "request_id", None),
            "error_class": type(e).__name__,
            "duration_ms": int((time.monotonic() - t0) * 1000),
        })
        raise
    duration_ms = int((time.monotonic() - t0) * 1000)
    request_id = getattr(message, "_request_id", None) or message.id
    log.info("vlm_call_done", extra={
        "model": model,
        "request_id": request_id,
        "duration_ms": duration_ms,
        "stop_reason": message.stop_reason,
        "input_tokens": getattr(message.usage, "input_tokens", None),
        "output_tokens": getattr(message.usage, "output_tokens", None),
        "cache_read_tokens": getattr(message.usage, "cache_read_input_tokens", None),
        "cache_creation_tokens": getattr(message.usage, "cache_creation_input_tokens", None),
    })
    # surface request_id and prompt_hash via meta so jobs.py can put them in audit
    meta["request_id"] = request_id
    meta["prompt_hash"] = _sha256_first8(prompt)
    meta["image_bytes"] = len(image_bytes)
    return TranscriptionResult(...)
```

**Cache fields:** the `cache_read_input_tokens` / `cache_creation_input_tokens`
fields will be `None` until prompt caching is enabled. Logging them now means
no schema change later.

**Tests:** mock the Anthropic client to return a stub `Message`; assert the
three log events fire with the expected fields. The existing
`test_jobs_with_mock_provider.py` only mocks at the registry level, so a new
test in `tests/test_anthropic_provider.py` is appropriate.

---

### 4. Enrich the LLM audit log with the new provider fields

**Why:** prereq for prompt iteration tracking and real cost estimation.

**Where:** `backend/app/jobs.py` — `_log_llm_audit`.

**How:** thread `request_id`, `prompt_hash`, `image_bytes` from `result.meta`
(populated in #3) into the audit entry. Also accept `cache_read_tokens` and
`cache_creation_tokens` so the schema is forward-compatible.

```python
usage = (meta or {}).get("usage") or {}
entry = {
    ...,
    "input_tokens": usage.get("input_tokens"),
    "output_tokens": usage.get("output_tokens"),
    "cache_read_tokens": usage.get("cache_read_input_tokens"),
    "cache_creation_tokens": usage.get("cache_creation_input_tokens"),
    "image_bytes": (meta or {}).get("image_bytes"),
    "prompt_hash": (meta or {}).get("prompt_hash"),
    "request_id": (meta or {}).get("request_id"),
    ...,
}
```

**Schema migration:** none — JSONL is forward/backward compatible by
construction; readers should treat missing fields as `None`.

**Tests:** extend the existing audit tests in `test_jobs_with_mock_provider.py`
to check the new fields land.

---

## P1 — frontend correctness & DX

### 5. Stop using a module global for the frontend correlation ID

**Why:** `logger.ts:3` has one CID per tab. Two parallel transcribe clicks
share it; `clearCorrelationId()` is exported but never called. Debugging "why
didn't this request show in backend logs?" lands you on the *last* CID
generated, not the relevant one.

**Where:** `frontend/src/logger.ts`, `frontend/src/api.ts`, every page that
calls `generateCorrelationId()` (search for that symbol — about 6 sites).

**How:**

- Drop `_activeCorrelationId`. Make `generateCorrelationId()` return a fresh
  CID each call. Remove `clearCorrelationId`.
- Have `jget` / `jpost` / `jput` / `jdelete` accept an optional `cid` arg, and
  generate one if none was passed:
  ```ts
  async function jget<T>(url: string, cid = generateCorrelationId()): Promise<T> {
    const done = startTimer("api", `GET ${url}`, { correlation_id: cid });
    const r = await fetch(url, { headers: { "x-correlation-id": cid } });
    ...
  }
  ```
- Pages that want to bind a "session" of related calls together (e.g. the
  batch transcribe loop in `chapter-view.ts:174`) generate one CID up front
  and pass it to each `jpost`.

**Tests:** none required (no test infra on frontend); manually verify in
DevTools that two parallel transcribes produce two distinct CIDs.

---

### 6. Wire `logError` into every frontend catch block

**Why:** `chapter-view.ts:401`, `chapter-view.ts:459`, `library.ts:43` etc.
catch errors and `alert(e.message)`. The error never reaches the structured
logger, so the CID, the stack, and the originating component are lost.

**Where:** every `catch (e: any) { alert(...) }` site. Quick search:

```bash
rg -n "catch.*alert" frontend/src/
```

**How:** before each `alert(...)`, call:

```ts
logError("ChapterView", "transcribe_failed", {
  region_id: region.id,
  error: e.message,
  stack: e.stack,
});
```

Keep the alert (we have no toast component). When a toast lands later, replace
`alert` with the toast call but keep the log line.

**Tests:** none required.

---

### 7. Add `STUDIOUS_LOG_LEVEL` env var

**Why:** everything is INFO. Per-page `page_done` lines are noise for
benchmark runs (which transcribe dozens of pages); developers want DEBUG
during feature work. There's no knob.

**Where:** `backend/app/main.py`, `backend/app/config.py`, `.env.example`.

**How:**

- Add `log_level: str = "INFO"` to `Settings`.
- Read `STUDIOUS_LOG_LEVEL` in `get_settings()`.
- In `main.py` change `logging.basicConfig(level=...)` to use the setting.
- Demote `page_done` from INFO → DEBUG in `jobs.py:215`. Demote `page-skipped`
  emit (job event, not log) — leave that as is.
- Document in `.env.example` and `docs/troubleshooting.md`.

---

### 8. Add `/api/costs/summary` and `/api/costs/audit` endpoints

**Why:** the audit JSONL has the data. The next roadmap item ("Cost tracking
estimation") needs a query interface. Adding a thin reader now both proves the
audit schema is sufficient and unblocks the cost UI.

**Where:** new `backend/app/api/costs.py`, register in `main.py`.

**How:**

- `MODEL_PRICING` table in `config.py` (per the existing roadmap text).
- `GET /api/costs/audit?since=<iso>&until=<iso>&model=<...>&doc=<...>&limit=<n>`
  returns paginated entries from `read_llm_audit()` with `cost_usd` computed
  per entry.
- `GET /api/costs/summary?since=<iso>` aggregates: total cost, by model, by
  doc, request count, avg duration, success rate.
- Storage helper: `iter_llm_audit_filtered(predicate)` — keep filtering in one
  place.

**Tests:** seed `data/llm_audit.jsonl` from a fixture, hit the endpoints,
assert filters and pricing math.

**Notes on pricing math:** Anthropic folds image tokens into `input_tokens`
today, so the input rate covers them. When prompt caching lands, multiply
`cache_read_tokens` by the cache-read rate (10× cheaper than fresh input) and
`cache_creation_tokens` by the cache-write rate (1.25× input). Display
estimates with a "± estimate" caveat.

---

## P2 — polish

### 9. Add `make logs` and `make audit-log` targets

```makefile
logs:
	tail -F /tmp/studious-backend.log | jq -C .

audit-log:
	tail -F backend/data/llm_audit.jsonl | jq -C .
```

(`logs` assumes the user runs `make dev-backend 2>&1 | tee /tmp/studious-backend.log`,
which is already documented in troubleshooting.md.)

### 10. Drop `duration_ms` from the transcription file payload

`jobs.py:201` writes `duration_ms` into the per-page transcription file. With
the audit log now canonical for VLM-call timing, this is a second source of
truth that will drift. Remove it from new writes; readers should fall back
gracefully (the field becomes optional in the API type).

**Where:** `jobs.py` payload construction; `frontend/src/api.ts` `Transcription`
type → mark `duration_ms?: number`; `document-view.ts` rendering of the duration
badge → keep but make conditional.

### 11. Add `test_logging.py` to lock in formatter behaviour

Pure unit test: instantiate `StructuredFormatter`, format a `LogRecord` with
arbitrary kwargs, assert all kwargs appear in the JSON. Guards against
regression of #1.

### 12. Rotate the audit log

After ~10k calls the JSONL is large enough that summary endpoints feel slow.
Options:

- Time-based rotation: roll to `llm_audit.YYYY-MM.jsonl` monthly; readers
  glob-match.
- Size-based rotation: stdlib `RotatingFileHandler`-ish, but the audit writer
  isn't going through `logging`. Could use a tiny rotation helper in storage.
- Maintain a rolling `llm_audit_summary.json` cache that the summary endpoint
  reads first, falling back to the JSONL for the current period.

**Recommendation:** monthly rotation + summary cache. Cheap, predictable, and
the cache is small enough (one row per model per day) to rebuild on demand.

---

## Out of scope for this batch

These came up during review but aren't in the priority list:

- **Shipping frontend logs to the backend.** Adds an endpoint, a buffer, and
  privacy considerations. Worth doing only if multi-user / production use
  arrives.
- **Distributed tracing (OpenTelemetry).** Overkill for a single-process
  file-backed app.
- **Metrics endpoint (`/api/metrics`).** A handful of counters (jobs in
  flight, queue depth, total tokens today) on a Prometheus-style endpoint
  would be nice but the audit-log + summary endpoint covers 90% of the need.

---

## Review of changes against this doc

After implementing each item, update its checkbox in `docs/roadmap.md` and
note any deviations here. The checklist of items 1–12 lives in the roadmap;
this doc is the source of truth for the *how*.
