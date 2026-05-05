# Troubleshooting

Where to look first when something goes wrong. Triage in this order: **job JSON → backend stdout → DevTools EventStream → region JSON**.

## Where state and logs live

### Backend logs (stdout)
Configured in `backend/app/main.py` with a single `StreamHandler` — logs go to the terminal running `make dev-backend`. Nothing is written to disk by default. To capture a session:

```bash
make dev-backend 2>&1 | tee /tmp/studious-backend.log
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
`backend/data/documents/<doc_id>/chapters/<chapter_id>/regions/<region_id>.json` — disk truth for a region. Check `transcribed_at` and `transcription_md` here to verify whether the data actually changed, independent of what the UI shows.

### LLM audit log
`backend/data/llm_audit.YYYY-MM.jsonl` — append-only record of every VLM API call (one JSON object per line), rotated monthly by UTC date. Each entry has `id`, `timestamp`, `provider`, `model`, `job_type`, `status` (`success` or `error`), `duration_ms`, token counts (including `cache_read_tokens` / `cache_creation_tokens`), `correlation_id`, `request_id` (Anthropic's), `prompt_hash`, `image_bytes`, and `doc_id` / `chapter_id` / `region_id` / `job_id` / `page` context. OCR calls are not logged (no API cost). Use this to confirm a call happened, see how long it took, and look up token counts after the fact.

```bash
# tail the current month's calls
make audit-log

# all errored calls across all months
jq 'select(.status == "error")' backend/data/llm_audit.*.jsonl
```

A pre-rotation `llm_audit.jsonl` (no date suffix) is still read by `read_all()`. The summary endpoint maintains a `backend/data/llm_audit_summary.json` cache: archived months are aggregated once and read from cache; the current month is recomputed live. Delete the cache to force a rebuild.

The log is written via `app.services.llm_audit.record(...)` from `app/jobs.py` after every VLM call (success or failure).

### Cost estimates
`GET /api/costs/summary` — totals plus breakdown by model and by document, derived from `llm_audit.jsonl` and the `MODEL_PRICING` table in `backend/app/config.py`. `GET /api/costs/audit?limit=&offset=` returns paginated audit entries (newest first) annotated with `estimated_cost_usd`. Models not in the pricing table appear in `unknown_models` and contribute `null` cost — add them to `MODEL_PRICING` when you start using a new model. Estimates ignore prompt-cache discounts.


### Frontend logs
- Browser DevTools **Console** — `frontend/src/logger.ts` emits structured entries with `correlation_id` that match backend logs.
- DevTools **Network → `/api/jobs/<job_id>/events` → EventStream** — SSE-specific view of job events (`snapshot`, `job-started`, `job-done`, `job-failed`, `ping`).

## Known failure modes

### Spinner never stops on a region transcription
1. Check the job JSON — if `status: "failed"` with an `ANTHROPIC_API_KEY is not set` error, the backend process didn't see the env var. Re-export it in the shell that runs `make dev-backend` and restart.
2. If the job completed but the UI didn't update, inspect the EventStream — confirm `job-done`/`job-failed` actually streamed (not just `snapshot` + `ping`).
3. The frontend handles the SSE race where a job finishes before `EventSource` subscribes by reading terminal status from the replayed `snapshot`. If you change `openJobStream` consumers, preserve that behavior.

### `ANTHROPIC_API_KEY is not set`
The backend process can't read the key from its environment. The Keychain-based setup (see README) only injects into the shell that sources it — restart `make dev-backend` from that shell.

### Job stuck in `running`
The worker is sequential (`backend/app/jobs.py` `JobManager`). One stuck job blocks all subsequent ones. Check backend stdout for an exception traceback in the worker, then either let it finish or restart the backend (in-progress jobs do not resume on restart).

### Sentence breakdown fails immediately with "no transcription"
The breakdown job (`job_type=breakdown_region`) requires the region to have `transcription_md` set on disk before it runs. The API rejects the POST with 409 if the region has not been transcribed yet, and the job handler fails fast with the same message if a race wipes it. Transcribe the region first (or wait for the in-flight transcription to finish), then retry the breakdown.

### Sentence breakdown fails with "tool response missing non-empty `sentences`"
The VLM tool-use call returned, but the model's tool input either omitted `sentences` or sent an empty array. This is logged in `llm_audit.YYYY-MM.jsonl` with `job_type=breakdown_region`, `status=error`, and the full token usage so the call still counts toward cost. Causes seen in practice: the model refusing to break down extremely short or non-Japanese inputs, or a malformed tool schema. First inspect the audit entry's `request_id` to pull the raw call from Anthropic logs if needed; if the input is genuinely too short (one fragment), expect failure — that's not a bug. Otherwise, regenerate; the breakdown is idempotent and overwrites stale state when `overwrite=true`.

### Benchmark CER spikes or line accuracy collapses
Before assuming a model/prompt regression: check whether the **ground truth** matches the format the current prompt is producing. CER and line-accuracy are computed character- and line-exact — markdown structure (`#`, `**`, `<u>`), fullwidth vs halfwidth punctuation, paragraph wrapping, and inline annotations like `[?N]` all count as differences. If you change the default VLM prompt's output style, the existing GT will need to be regenerated (or normalized before scoring). Rule of thumb: if line accuracy is in single digits while the body text reads correctly side-by-side, it's a format mismatch, not a regression.
