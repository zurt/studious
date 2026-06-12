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
`backend/data/llm_audit.YYYY-MM.jsonl` — append-only record of every VLM API call (one JSON object per line), rotated monthly by UTC date. Each entry has `id`, `timestamp`, `provider`, `model`, `job_type`, `status` (`success` or `error`), `duration_ms`, token counts (including `cache_read_tokens` / `cache_creation_tokens`), `correlation_id`, `request_id` (Anthropic's), `prompt_hash`, `image_bytes`, `stop_reason`, and `doc_id` / `chapter_id` / `region_id` / `job_id` / `page` context. OCR calls are not logged (no API cost). Use this to confirm a call happened, see how long it took, and look up token counts after the fact.

```bash
# tail the current month's calls
make audit-log

# all errored calls across all months
jq 'select(.status == "error")' backend/data/llm_audit.*.jsonl
```

A pre-rotation `llm_audit.jsonl` (no date suffix) is still read by `read_all()`. The summary endpoint maintains a `backend/data/llm_audit_summary.json` cache: archived months are aggregated once and read from cache; the current month is recomputed live. Delete the cache to force a rebuild.

The log is written via `app.services.llm_audit.record(...)` from `app/jobs.py` after every VLM call (success or failure).

### Prompt cache hits / misses
The Anthropic VLM provider sets `cache_control: ephemeral` on the prompt
text (and tool schema, for breakdown calls). Expect the first call with a
given prompt to show non-zero `cache_creation_tokens` (one-time write at
~1.25× cost) and subsequent calls within the 5-minute TTL to show
`cache_read_tokens` (~0.1× cost). If `cache_read_tokens` stays zero across
repeated calls, something is invalidating the prefix — most likely the
prompt text changed, the model changed, or more than 5 minutes elapsed
between calls. Effort changes (`STUDIOUS_VLM_EFFORT_*`) do not invalidate
the cache. Cache discounts are not yet reflected in `/api/costs/summary`.

### Cost estimates
`GET /api/costs/summary` — totals plus breakdown by model and by document, derived from `llm_audit.jsonl` and the `MODEL_PRICING` table in `backend/app/config.py`. `GET /api/costs/audit?limit=&offset=` returns paginated audit entries (newest first) annotated with `estimated_cost_usd`. Models not in the pricing table appear in `unknown_models` and contribute `null` cost — add them to `MODEL_PRICING` when you start using a new model. Estimates ignore prompt-cache discounts.


### Frontend logs
- Browser DevTools **Console** — `frontend/src/logger.ts` emits structured entries with `correlation_id` that match backend logs.
- DevTools **Network → `/api/jobs/<job_id>/events` → EventStream** — SSE-specific view of job events (`snapshot`, `job-started`, `job-done`, `job-failed`, `ping`).

## Known failure modes

### npm installs a package newer than 7 days despite the .npmrc cooldown
`min-release-age=7d` in `frontend/.npmrc` requires npm >= 11.10; older npm versions ignore the setting **silently** and resolve to the newest release (observed with npm 10.9.2 installing a same-day dompurify). Check `npm --version` first when adding a dependency. If npm is too old, verify the release date by hand (`npm view <pkg> time --json`) and pin the newest version that is at least 7 days old with `npm install --save-exact <pkg>@<version>`.

### Upload fails with 400 "could not render uploaded file"
The file reached the backend but PyMuPDF/Pillow could not parse it — usually a corrupt download, a password-protected PDF, or a file whose extension doesn't match its contents. The partial document directory is cleaned up automatically (nothing appears in the library), and the render error is logged as `document_render_failed` with the underlying parser message. Re-export or decrypt the source file and upload again. Note: the re-upload endpoint (`PUT /api/documents/{id}/file`) does not yet have this protection — a failed re-upload render can leave a document with stale metadata and no pages (see R6 in `docs/improvement-recommendations.md`).

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

### Sentence breakdown fails with "model returned no sentences for this region" (or legacy "tool response missing non-empty `sentences`")
The VLM tool-use call returned, but the model's tool input either omitted `sentences` or sent an empty array. This is logged in `llm_audit.YYYY-MM.jsonl` with `job_type=breakdown_region`, `status=error`, and the full token usage so the call still counts toward cost. The breakdown schema requires `sentences`, sets `minItems: 1`, and breakdown requests use `max_tokens: 8192`. If `stop_reason=max_tokens`, the response was truncated before the tool input completed (the error message says so explicitly); split the region smaller or make the prompt/output less verbose. Otherwise the model judged there was nothing to split — common on regions that are purely visual or all-blank exercise items the model declined to break down. Inspect the audit entry's `request_id` to pull the raw call from Anthropic logs, or just retry; the `<region_tag>` hint and exercise-item rules in `SENTENCE_BREAKDOWN_PROMPT` (`backend/app/config.py`) usually coax a non-empty result on `exercises`/`instructions` regions. The operation is idempotent and overwrites stale state when `overwrite=true`.

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

### "this region is a continuation of region ... generate the breakdown from there" (409)
By design. Breakdowns and exercise completions on a region that is the *target* of a `continues_to` pointer are blocked so the chain is always processed from the head — otherwise the tail-only breakdown would miss any sentence whose start lives on the prior page. The chapter view replaces the Generate-breakdown UI with a notice and a "Go to source" button for these regions. To bypass: unlink the source (✕ on the chip), or run the breakdown from the source as intended.

### Linked region's text isn't appearing in breakdown / exercise completion
The breakdown and exercise-completion jobs read the source region from disk and walk `continues_to` forward via `backend/app/services/region_chain.py` to build the combined VLM input. If the combined text doesn't reflect the continuation:
- Confirm the link is set on disk: `backend/data/documents/<doc>/chapters/<ch>/regions/<source>.json` → `continues_to` should be the target region id.
- Confirm both regions have `transcription_md` set; an empty tail contributes nothing.
- Check the job log line `breakdown_job_start` / `exercise_completion_job_start` for the correlation id, then `llm_audit.YYYY-MM.jsonl` for the call — the `prompt_hash` differs from the single-region call if the chain was built. (For deeper debugging, the prompt itself isn't logged, but you can replay locally: load the source region, call `region_chain.resolve_chain` + `combined_transcription`, and compare.)
- Per-region transcription is *not* combined — that's by design; only breakdown and exercise completion use the chain.
- The combined text is concatenated with a blank-line separator only — no `(continues on page N)` marker is injected. That marker used to be there but leaked into prompts and tool output as if it were content; the page boundary is now a frontend rendering concern.

### Benchmark CER spikes or line accuracy collapses
Before assuming a model/prompt regression: check whether the **ground truth** matches the format the current prompt is producing. CER and line-accuracy are computed character- and line-exact — markdown structure (`#`, `**`, `<u>`), fullwidth vs halfwidth punctuation, paragraph wrapping, and inline annotations like `[?N]` all count as differences. If you change the default VLM prompt's output style, the existing GT will need to be regenerated (or normalized before scoring). Rule of thumb: if line accuracy is in single digits while the body text reads correctly side-by-side, it's a format mismatch, not a regression.
