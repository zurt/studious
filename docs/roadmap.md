# Studious - Roadmap

**Where things stand (2026-11):** Phases 1–3 are shipped. Exercise
reading references (2.5) and chapter bulk operations are shipped as
beta, pending real use. The Apple apps (Phase 5) are built and compiled
in CI but have not been run on a device. Open work: Phase 4 (exercise walkthroughs), region editing, mobile-responsive web
layout, and the hosting/auth findings in
`docs/archive/audit-2026-07-mobile-spike.md`.

## Phase 1: Chapters + Regions + Targeted Transcription (Shipped)

- [x] PDF and image upload with page rendering
- [x] Anthropic Claude VLM integration with custom prompt
- [x] Side-by-side page image + transcription viewer
- [x] Async job queue with SSE progress streaming
- [x] Structured logging with correlation IDs
- [x] Supply chain security (package manager cooldown)
- [x] Chapter management (create, list, update, delete)
- [x] Region drawing on page images (canvas overlay with bbox)
- [x] Region tagging (reading_passage, vocab_list, grammar_points, exercises, etc.)
- [x] Tag-specific VLM prompt for `vocab_list` (full-width furigana, glosses,
      preserves item indices and section headers)
- [x] Region-level VLM transcription (crop to bbox, send to Claude)
- [x] Vanilla TypeScript frontend (no framework)
- [x] Map-like zoom/pan page viewer (pinch zoom, two-finger scroll, Cmd+/-, Cmd+0, fit button)
- [x] Full screen mode
- [x] Chapter popover panel (closed by default) with drag-to-reorder
- [x] Current chapter indicator banner in document view
- [x] Region transcription tracker widget in chapter view (pending count, batch transcribe)
- [x] Resizable split panes with collapse affordance (drag splitter, collapse left/right, persists in localStorage)
- [x] Copy-to-clipboard buttons on region cards and transcription detail view
- [x] Text size toggle (100/150/200%) in transcription detail view
- [x] Auto-select region on page navigation, remembering last selection per page
- [x] Region hover highlight with fade-out (replaces persistent shading)

## Phase 1.5: UX Safety + LLM Observability

- [x] Confirmation dialog utility + wired into region, chapter, and document delete
- [x] LLM audit log (append-only JSONL with provider, model, tokens, duration, context)
- [x] Cost tracking estimation (per-model token pricing, cost-per-request, summary API)
- [x] Settings modal (general + usage sections) with floating gear/fullscreen controls and cost summary UI
- [ ] Self-service pricing-table update from the settings usage view. Anthropic
      exposes no pricing API (the Models API returns capabilities/context only),
      so a non-LLM source would be either a third-party structured feed
      (e.g. LiteLLM's `model_prices_and_context_window.json`) or a scrape of the
      official pricing page — both carry trade-offs (supply-chain surface vs.
      fragile parsing) to weigh against the project's supply-chain rules.
      Interim: `MODEL_PRICING` in `backend/app/config.py` is updated by hand
      during development on a ~2-week cadence. See plan.md → Cost Tracking.

## Phase 1.6: Logging & Observability Improvements

Detailed implementation notes for each item in `docs/archive/logging-improvements.md`.
Items 1–4 are the highest-leverage and should ship together; 5–8 are the next
batch; 9–12 are polish.

P0 — correctness fixes:
- [x] 1. Stop dropping `extra=` fields in `StructuredFormatter` (allowlist → denylist)
- [x] 2. Propagate `correlation_id` from request middleware into `JobManager` workers
- [x] 3. Log every Anthropic VLM call from the provider (start/done/error, request_id, cache fields)
- [x] 4. Enrich audit-log entries with `request_id`, `prompt_hash`, `image_bytes`, cache tokens

P1 — frontend correctness & DX:
- [x] 5. Replace frontend `_activeCorrelationId` module global with per-request CIDs
- [x] 6. Wire `logError` into every frontend `catch` block (currently `alert()` only)
- [x] 7. Add `STUDIOUS_LOG_LEVEL` env var; demote `page_done` to DEBUG
- [x] 8. Add `/api/costs/summary` and `/api/costs/audit` endpoints (foundation for cost UI)

P2 — polish:
- [x] 9. `make logs` / `make audit-log` targets (`tail -F | jq -C .`)
- [x] 10. Drop `duration_ms` from transcription file payload (audit log is canonical)
- [x] 11. `tests/test_logging.py` to lock in formatter behaviour (regression guard for #1)
- [x] 12. Rotate `llm_audit.jsonl` monthly + maintain summary cache

## Phase 1.7: Test Coverage

See `docs/archive/test-coverage-plan.md` for the full phased plan.

Done since the phase was opened:
- [x] `CorrelationMiddleware` + `StructuredFormatter` regression tests
      (`tests/test_logging.py`)
- [x] `JobManager` VLM engine path, region jobs, per-page errors →
      `completed_with_errors`, `overwrite=True/False`, sequential ordering
      (`tests/test_jobs_with_mock_provider.py`)
- [x] Anthropic VLM with mocked SDK — temperature deprecation for
      `claude-opus-4-7`, default-model fallback, message envelope, usage
      extraction, start/done logging (`tests/test_anthropic_provider.py`)
- [x] Chapter + region API handlers, cost endpoints, breakdown endpoints
      (`tests/test_chapters_regions.py`, `tests/test_costs.py`,
      `tests/test_breakdown_links.py`)
- [x] Storage: `list_documents` recent-first, Japanese-string round-trip
      (`tests/test_storage.py`, `tests/test_logging.py`)

Outstanding:
- [x] FastAPI handler tests for documents (POST/PUT/DELETE/GET),
      `/api/transcribe`, `/api/jobs/{id}/events` (SSE), `/api/providers`
      (`tests/test_api_documents.py`, `tests/test_api_transcribe.py`,
      `tests/test_api_jobs_sse.py`, `tests/test_api_providers.py`)
- [x] `JobManager`: unknown engine → `failed`, missing page image → page
      error (not job failure), SSE `subscribe`/`unsubscribe` lifecycle,
      sequential ordering (`tests/test_jobs_lifecycle.py`)
- [x] `services/pdf.py`: `render_pdf_to_pages`, `copy_image_as_page`,
      `prepare_for_vlm` (`tests/test_pdf_service.py`)
- [x] Provider registry: `register`/`get`/`list`, unknown name raises,
      `bootstrap_default_providers` idempotent; OCR `_to_markdown` paragraph
      splitting (`tests/test_provider_registry.py`)
- [x] Storage edges: `_atomic_write_text` crash safety, `update_job` missing
      id raises `KeyError` (`tests/test_storage_edges.py`)
- [x] `pytest --cov=app --cov-fail-under=75` wired into `make test`;
      coverage on `app/api/`, `app/jobs.py`, `app/middleware.py` all ≥75%
      (current total: 89%)

## Phase 1.8: Frontend Test Coverage

Vitest + jsdom now run as part of `make test`. See the frontend section of
`docs/archive/test-coverage-plan.md` for the original plan.

- [x] Stand up Vitest + jsdom (respect 7-day cooldown in `frontend/.npmrc`);
      add `test` and `test:coverage` scripts; wire `make test` to run both
      suites
- [x] `api.ts` — fetch wrapper tests with mocked `fetch` (correlation header
      injection, non-2xx throws, `getTranscription` 404 → `null`)
- [x] `logger.ts` — correlation id generation/format, `startTimer` duration
- [x] `router.ts` — pattern compile, parameter extraction, route dispatch
- [x] `modules/region-drawer.ts` — image-coords ↔ normalized-bbox math,
      click-vs-drag selection threshold
- [x] `modules/zoom-pan.ts` — transform math, clamping
- [x] `modules/pane-splitter.ts` — ratio clamping, localStorage round-trip
- [x] `modules/page-input.ts` — Enter/Esc/blur behaviour, min/max clamping
- [x] Coverage target: ≥70% line on `frontend/src/modules/` plus
      `api.ts`/`logger.ts`/`router.ts` (achieved: 90.6% line overall;
      api.ts 97%, router.ts 100%, modules dir 87.7%)

## Phase 1.8.1: Browser E2E Smoke Suite (Playwright)

Thin browser-level smoke suite over the real stack (vite + FastAPI) with a
mock VLM provider — deterministic, no API key, no tokens. Deliberately small:
one test per core journey, no visual regression (the web app is a prototype;
see "Web MVP now, native later" in `docs/plan.md`). Also serves as executable
UI documentation and a seeded environment for agent-driven browser
verification. See the E2E section of `docs/archive/test-coverage-plan.md`.

- [x] Playwright scaffold: `frontend/playwright.config.ts`, `make test-e2e`,
      dedicated ports (backend 8765 / frontend 5273) so runs never touch a
      real dev stack or data dir
- [x] `backend/e2e_server.py` — ASGI entrypoint that registers a canned mock
      VLM under the "anthropic" name before app startup; isolated
      `backend/.e2e-data` wiped per run
- [x] Committed fixture PDF (`frontend/e2e/fixtures/sample.pdf`, 2 pages,
      generated with pymupdf)
- [x] Journey: fresh library shows empty state
- [x] Journey: upload PDF → document view renders page image, paging works
- [x] Journey: create chapter → chapter view opens; banner links back
- [x] Journey: draw region in chapter view → tag type → transcribe with mock
      provider → markdown renders in right pane
- [x] Journey: sentence breakdown on a transcribed region → cards render,
      vocab/grammar popover opens
- [x] Journey: grammar guide generation from grammar_points regions
- [x] Journey: exercise completion on an exercises-region breakdown →
      answer, explanation, and example sentences render
- [x] Journey: link a continuation region across pages (continuation
      transcribed via the tracker's "Transcribe all") → continuation's
      breakdown pane defers to the source; source shows the combined
      transcription
- [x] Journey: document lifecycle — upload a second document, delete it
      from the library card menu behind the confirm dialog
- [x] Journey: vocab dashboard lists breakdown-harvested items; status
      change persists across reload; stat-chip filters; grammar
      dashboard shows the harvested pattern
- [ ] Wire `make test-e2e` into CI (after journeys above stabilize)

## Phase 1.9: Supply Chain Hardening

See `docs/supply-chain-plan.md` for full details.

Priority 1:
- [x] Frozen installs in CI (`uv sync --frozen`, `npm ci`)
- [x] `make audit` runs on every PR; fails on high/critical
- [x] Dependabot config with 7-day cooldown (pip + npm + actions)

Priority 2 (second pass, bundled):
- [x] Pin GitHub Actions by SHA
- [ ] Enable GitHub secret scanning + push protection
- [ ] Prune unused deps (`depcheck`, `deptry`)
- [ ] SBOM on release tags
- [ ] Document API key rotation; sandbox PDF rendering

## Phase 1.10: Transcription Model Evaluation

- [x] `benchmarks/model_eval/` framework: frozen stratified datasets sampled
      from the live store (regions by tag + full pages, textbook + workbook),
      multi-model transcription runs through the production pipeline, blind
      Fable-judged rubric scoring + ranking, per-tag/source/kind analysis
      with pairwise sign tests, cost/latency tracking
- [x] `claude-sonnet-5` registered in the Anthropic VLM provider
- [x] First run (`20260706-eval-v1`, 31 items × haiku-4-5/sonnet-5/opus-4-8,
      Fable judge): Opus 4.8 and Sonnet 5 statistically tied on quality
      (p=0.47); Sonnet 5 wins on low-quality workbook scans and costs ~2.3×
      less at lower latency (median 8.1s vs 10.5s; Opus mean skewed by one
      10-min SDK-retry call); Haiku 4.5 far behind (p<0.0001)
- [x] Vocab-gloss follow-up: investigation showed supplied glosses are
      *intended* (`VOCAB_LIST_TRANSCRIBE_PROMPT` explicitly asks for a
      dictionary gloss when none is printed) — the eval judge, not the
      prompt, was fixed to score gloss accuracy instead of gloss presence.
      Re-judge (`20260706-eval-v1-judge2`): Opus/Sonnet vocab 6.5/6.75 →
      9.25 both; Haiku stays low (6.5) because its glosses are wrong.
      Corrected league: Opus 8.81, Sonnet 8.71 (still tied, p=0.28),
      Haiku 5.81 (0 first-place finishes)
- [x] Default VLM switched to `claude-sonnet-5` (tied quality, ~2.3× cheaper,
      wins workbook scans); Opus 4.8/4.7 remain selectable in settings
- [x] `claude-sonnet-5-5` and `claude-opus-5-5` registered (2026-09-29).
      Neither accepts a forced `tool_choice`, so their tool calls use
      structured outputs (`output_config.format`); refusals raise a clear
      error and opt into server-side fallback (`fallbacks: "default"`)
- [x] Default VLM switched to `claude-sonnet-5-5` (2026-09-29). Same-code
      `make benchmark` single runs: avg CER 32.6% vs 40.4% on Sonnet 5, line
      accuracy 16.5% vs 12.3%, better on 4/5 vocab-list fixtures, slightly
      worse on the full-page fixture (10.1% vs 7.3%); breakdown 3/3, recall
      100% on both
- [x] Curated report: `benchmarks/model_eval/reports/2026-07-06-model-comparison.md`
- [ ] Re-run the 31-item benchmark when a new model tier ships or
      transcription prompts / image preprocessing change (~$4.50/run);
      expand a stratum only when a decision hinges on it — due for the
      5.5 models (the Sonnet 5.5 default switch rests on `make benchmark`
      only)
- [x] Benchmark cleanup (2026-11): `make benchmark` is now the
      *regression* check and scores each fixture with the same judge and
      rubric as `model_eval`, against the image plus the reviewed reference;
      CER stays as a fallback (the 30-40% CERs above are mostly gloss
      wording on vocab lists, not misreadings). `benchmarks.compare` gates
      on a one-point judge drop. One price table for the app and both
      tools. `benchmarks/README.md` says which tool answers which question.
      First live run 2026-11-11: 6/6 fixtures judged, avg overall 9.67; all
      five vocab lists scored 10/10 at 19-45% CER
- [x] New-models run prepared (2026-11): judge is `claude-fable-5-2` with a
      refusal fallback that now actually engages; candidates default to
      Sonnet 5.5, Opus 5.5, Haiku 5.5 plus Sonnet 5 and Opus 4.8 as a bridge
      to July; dataset `v2` quotas total 48 items with 14 full pages (v1:
      31 and 6); `run` and `judge` take `--budget-usd`; the provider sends
      Haiku 5.5 the same effort as the other models
- [x] Run `20261111-eval-v2` (47 items, 5 models, $8.71): Opus 5.5 leads
      clearly (9.02, never below 8, beats every other model head-to-head);
      the current default Sonnet 5.5 is last (7.70) because it invents
      unprinted furigana, worst on workbook pages; Haiku 5.5 ties both
      Sonnets at a tenth of the cost but misreads. Report:
      `benchmarks/model_eval/reports/2026-11-11-model-comparison.md`. The
      July `v1` dataset no longer exists, so July's numbers are history only
- [x] Default VLM switched to `claude-opus-5-5` (2026-11-11) on that run.
      About 2.6x Sonnet 5.5 per transcription ($0.031 vs $0.012) and twice
      the latency; negligible at one user's volume. A model saved in
      Settings (`data/preferences.json`) still overrides the default
- [ ] **Sonnet 5.5 prompt fix — only if scale makes the cost gap matter.**
      Its weakness is one habit: adding furigana the page does not print.
      If a transcription-prompt change stops that, Sonnet 5.5 becomes a
      2.6x cheaper, 2x faster default. Test by re-running that one model on
      `dataset/v2` and re-judging (about $1.10). Not worth doing at
      single-user volume
- [ ] **Benchmarks for breakdowns, exercise completions and grammar
      guides.** The model setting drives every job type, but both
      benchmark tools measure transcription only (plus one structural
      breakdown fixture). The Opus 5.5 switch is therefore unevaluated for
      most of what the app does with the model, including cost: those jobs
      run at higher effort with longer outputs. Needs a frozen dataset of
      transcribed regions, a rubric per job type (gloss accuracy, vocab and
      grammar coverage, answer correctness, level-appropriateness), and
      the same blind-judge flow

## Phase 2: Sentence Breakdowns

- [x] Sentence-by-sentence breakdown (vocab, grammar, gloss) per region
- [x] Text-only VLM calls for analysis (no image tokens, cheaper)
- [x] Breakdown storage per-region
- [x] Breakdown display UI (cards/accordions)

### Phase 2.1: Inline vocab/grammar links

See `docs/design/breakdown-vocab-links-plan.md`.

- [x] Iter 1 — Backend vocab linker (exact/reading/stem) + lazy migration on read
- [x] Iter 2 — Frontend renders linked spans with click-to-open popover (vocab)
- [x] Iter 3 — Grammar links via LLM-emitted surface strings; overlapping
      vocab + grammar merge into a single popover
- [x] Iter 4 — Polish: hide-by-default vocab/grammar answers behind a
      per-card eye toggle (gray-bar overlay, no layout shift),
      `breakdown_links_annotated` INFO log with per-region match-strategy
      counts, troubleshooting entries for linker miss modes

### Phase 2.2: Chapter Grammar Guide

- [x] Per-chapter "grammar guide" generated from concatenated
      `grammar_points` transcriptions via VLM tool-call (structured
      JSON: title / subtitle / sections of markdown).
- [x] Standalone view with Regenerate, Copy-markdown, and Open-in-window
      buttons; source-changed warning when any underlying grammar
      region is re-transcribed since the guide was generated.

### Phase 2.3: Exercise Completions

- [x] Per-sentence "Complete exercise" button on breakdown cards for
      `exercises` regions (gated on an existing breakdown). VLM tool-call
      returns `answer`, `explanation`, and three example sentences (the
      first as the simplest illustration, two more as appropriate
      variations); each example carries `japanese`, `reading`, `english`,
      and a brief `explanation`.
- [x] Region transcription sent as `<region_transcription>` context
      alongside the `<target_sentence>` so the model can read the
      exercise instruction header, sibling items, and choice banks.
- [x] Tool reports `no_exercise: true` with a `reason` when the target
      line isn't actually a drill item; UI shows a muted notice with a
      "Try again" button instead of treating it as an error.
- [x] Completions saved per-region keyed by `sentence_index`; cascaded
      delete with the region; cleared automatically when a region's
      breakdown is regenerated (sentence indices would otherwise become
      stale).
- [x] Study profile (Settings → General, 2026-09-29): JLPT level + note and
      answer length (brief / standard / detailed) render into the prompt.
      Answers sit at the level with at most one or two named "stretch"
      items one step above; brief = one short sentence for questions and
      two examples for `open` items (English explanations unaffected).
      Each saved entry records the `profile` it was generated with.
- [x] Tap-to-reveal furigana (2026-09-29): completions now carry a
      reading on every kanji word (the old "uncommon kanji" rule was
      unreliable), and `漢字(かな)` renders as ruby in completions,
      transcriptions and breakdown sentences. Global mode on
      `<html data-furigana>`: hidden (default, tap a word to reveal),
      shown, off — toggles in the pane headers and `F` in the chapter view.
      Breakdown link spans are widened to keep a word with its reading.
- [x] Prompt caching fixed (2026-09-29): the whole prompt used to be one
      cached block ending in the per-item target line, so every call wrote
      a fresh ~3.8k-token cache entry that was never read (109 writes /
      1 read in the audit log). Now the instructions and the exercise
      block's context are separate cached blocks and only the target line
      is uncached; breakdowns/grammar guides cache just their instructions.

Beyond MVP (deferred):
- [ ] Bulk "Complete all exercises in this region" action that fans out
      one job per sentence, with per-item progress in the UI.
- [ ] Completion-count badge on exercises regions in the region list
      and chapter-view tracker widget.
- [ ] Include the chapter's grammar guide (when present) as additional
      context so completions stay grounded in patterns the chapter has
      actually taught.
- [x] Markdown / clipboard export of completions per region (per-card
      copy button + region-level "copy all completions", mirroring the
      breakdown copy-all affordance). Per-chapter export still deferred.
- [ ] Fallback: when transcription quality is poor, optionally include
      the region image crop in the VLM call (toggle, not default — image
      tokens are expensive).
- [ ] Regenerate-completion-on-stale: if the source breakdown is
      regenerated, surface the prior completions in a "review and
      reapply" UI rather than silently dropping them.

### Phase 2.4: Cross-Page Region Linking

- [x] Region schema gains an optional `continues_to` pointer (one-way,
      same chapter, target page must be later, cycles rejected).
- [x] `POST /api/documents/{doc_id}/chapters/{chapter_id}/regions/{region_id}/link`
      endpoint. Cross-chapter `move` clears the link; deleting a region
      clears any inbound pointers.
- [x] `region_chain.resolve_chain` + `combined_transcription` helpers
      consumed by the breakdown and exercise-completion jobs so they
      receive the joined transcription of the chain head + tails.
      Per-region transcription itself is unchanged (visual task; doesn't
      need cross-page context).
- [x] Chapter view's click-to-link UI (toolbar button, `L` shortcut,
      Esc to cancel): pick source, navigate, pick target. Tag-colored
      arrow glyph on canvas (→ on source, ← on target) and matching
      "Continues on p.N →" / "← Continued from p.N" chips on the
      region cards with unlink action.
- [x] Source region's detail pane renders the combined chain
      transcription with a dashed "continues on page N" separator;
      copy button emits combined markdown matching the VLM input.
- [x] Continuation regions reject `breakdown` and `exercise-completion`
      requests with a 409 pointing at the source. When a continuation
      region is selected, the breakdown pane shows an explanatory
      notice plus a "Go to source on p.N →" jump button instead of the
      Generate-breakdown UI.

### Phase 2.5: Exercise Reading References

Shipped 2026-09-29 as **beta** — see `docs/design/exercise-references-plan.md`.
Covered by unit + E2E tests against the mock provider, but not yet run
against real VLM completions; promote out of beta after the first live
chapter (the 生きた素材で学ぶ 第5課 comprehension questions are the
motivating case).

- [x] Region schema gains an ordered `references` list (many, cross-
      document, target must be `reading_passage`). Distinct from Phase
      2.4's `continues_to`: that's a single same-chapter continuation
      pointer; this is a citation of separate background material,
      possibly from another textbook.
- [x] `PUT .../regions/{region_id}/references` endpoint (replace-whole-
      list semantics, duplicates dropped); validates source is
      `exercises`-tagged and a chain head (409 on a continuation), and
      every target is `reading_passage`-tagged.
- [x] `region_reference.resolve_references` +
      `combined_reference_text` helpers, consumed by the exercise-
      completion job as a new `<reading_reference>` prompt block.
      Consecutive same-chapter references share one `[Source: …]` label
      (a reading split across regions stays one passage); missing or
      untranscribed targets are skipped with a warning log.
- [x] Completion prompt gains a `question` exercise shape (comprehension
      / discussion questions → a model answer + explanation citing the
      reading, `examples: []`) and a multiple-choice case under
      `constrained` — comprehension questions previously had no shape
      and risked `no_exercise`.
- [x] Reference picker modal (Document → Chapter browse of
      `reading_passage` regions with per-page "Add all", ordered
      selection tray with ↑/↓/✕) and a "Reading references" section in
      the chapter view, shown for any region of an exercises chain and
      editing the chain head's list.

## Phase 3: Central Vocab/Grammar Store

The long-term core study workflow: vocab and grammar accumulate across
textbooks into a single graded, dictionary-linked, editable store that
eventually powers built-in SRS and an iOS companion. Design agreed
2026-07-01 — see `docs/design/vocab-store-plan.md` for schemas, decisions, and
rationale.

### 3.1 Store foundation + harvest

Shipped 2026-07-01.

- [x] Sync-ready JSONL stores (`data/store/{vocab,grammar}.jsonl`):
      UUID ids, `updated_at`, tombstones, append-only
      latest-per-id-wins; dedup index derived in memory (no index file
      to drift)
- [x] Ingest hook: breakdown generation appends deduped vocab/grammar
      items with sighting provenance (doc/chapter/region/sentence +
      sentence text); harvest failures log but never fail the parent job
- [x] Ingest hook: `vocab_list` transcription save parses the
      `term（reading）gloss` format (item indices, section headers,
      kana-only entries; tolerates stray bullet markers)
- [x] Idempotent backfill over existing breakdowns and vocab_list
      transcriptions (`POST /api/store/backfill` + dashboard button)
- [x] Curation status lifecycle: unreviewed (inbox) → active → known /
      ignored — distinct from SRS state; deletes are tombstones and
      block re-harvest
- [x] `/api/vocab` + `/api/grammar` routers (filters, search, sorts,
      pagination, PATCH, manual create with 409-on-duplicate, DELETE)
      plus `/api/store/stats`
- [x] Vocab + grammar dashboards at `/vocab` and `/grammar`: stat-chip
      filters, search, textbook/source filters, inbox with bulk
      accept/ignore, expandable sightings linking back to chapters,
      manual add

### 3.2 Enrichment + classification

Shipped 2026-07-01 (except frequency-rank tagging, deferred — see note).

- [x] Bundle JMdict locally (jmdict-simplified 3.6.2 JSON; URL + SHA-256
      pinned in `backend/refs.lock.json`, fetched/built via `make refs`
      into a read-only SQLite index; EDRDG CC BY-SA attribution in README)
- [x] JMdict linking (`jmdict_seq`, glosses, POS, common flags) with
      reading-disambiguated homographs and variant-spelling matching;
      enrichment runs after every harvest and `POST /api/store/enrich`
      re-links everything. User-edited meanings (`meaning_source:
      "user"`) are never overwritten
- [x] JLPT level tagging (tanos.co.uk-derived lists pinned to an
      immutable commit; kana-listed and variant-spelling fallbacks)
- [ ] ~~Frequency rank tagging~~ deferred: jmdict-simplified folds
      JMdict's nf frequency bands into a boolean `common` flag, so a
      finer rank needs a separate corpus dataset (BCCWJ/wordfreq).
      Revisit if JLPT + common + WK level prove too coarse for queue
      ordering
- [x] WaniKani sync: subjects + study_materials + assignments via
      personal API token (Keychain, `WANIKANI_API_TOKEN`); incremental
      `updated_after` cursors; gitignored personal-use cache; WK SRS
      history is a display signal only — never auto-marks items known
- [x] Vocab → kanji → radical drill-down (dashboard row detail +
      `GET /api/vocab/{id}/wanikani`) with WK mnemonics, the user's own
      WK notes, and SRS chips ("burned 2022")
- [x] Outbound reference links (jisho.org search, WaniKani subject pages)
- [x] Anki import, step one of an Anki bridge (read-only): `POST
      /api/refs/anki/sync` reads every card through AnkiConnect
      (`findCards`/`cardsInfo` only) into an atomic snapshot under
      `data/refs/anki/`; `GET /api/vocab` joins card state onto items at
      read time (exact word+reading, else the same JMdict entry so variant
      spellings like うれしい/嬉しい match, else headword; non-exact matches
      show a `~` on the badge) with an `anki` filter,
      and the dashboard has a "Sync Anki" button and `Anki · state`
      badges. Never written to the store
- [x] Anki bridge, step two (push): the dashboard's "Send to Anki…" previews
      then sends a chapter's shortlist candidates (default 125) into a
      separate `Studious` deck with the `Kaishi 1.5k` note type
      (`POST /api/anki/push/preview`, `POST /api/anki/push`). The bridge now
      goes both ways; writes are limited to `createDeck` and `addNotes`,
      duplicates anywhere in the collection are skipped, sent items become
      `active`, and an example sentence (with its translation when the
      breakdown has it) is attached when a breakdown sighting is usable.
      Deck options (new cards per day) stay the owner's to set in Anki
- [x] Generated example sentences for Anki cards: words with no short
      textbook sentence get a Kaishi-style sentence (with furigana and an
      English translation) from the configured model, stored on the vocab
      item as `example` so it is generated once. The Send to Anki dialog
      offers "Generate N sentences" (batches of 20, cancellable) before the
      send; a vocab row's detail has Generate / Regenerate / Remove.
      Textbook sentences over 60 characters are no longer used
      (`POST /api/vocab/examples`, `DELETE /api/vocab/{id}/example`)
- [x] Anki card quality: short dictionary meanings on the card; a word
      and its する/な form are one word (Anki lookup `stem` match, in-batch and
      in-Anki duplicate checks); generated sentences use する words as verbs
      and な words as adjectives; Mac-voice audio (`say`, cached AAC) for
      `Word Audio` and `Sentence Audio`, with Play buttons on vocab rows
- [x] Frequency rank: `make refs` also builds `data/refs/freq/jpdb-freq.sqlite`
      from the pinned JPDB frequency list (local download, not committed);
      enrichment writes `classifications.freq_rank` (and `freq_checked`, so
      existing items are revisited once per list revision), `GET /api/vocab`
      has `sort=frequency`, and the dashboard shows a `#1.2k` badge and a
      "By frequency" sort. `priority_group` is unchanged
- [x] Dashboard shortlist aids: "N items" count and a chapter filter beside
      the textbook filter (vocab and grammar)
- [x] Chapter shortlist: `GET /api/vocab?shortlist=true` returns only
      candidates in shortlist order (frequency rank, halved for vocab-list
      sightings) and hides words already in Anki, N5/N4, grammar-like,
      without a JMdict entry, known or ignored (`?excluded=<reason>` lists the
      hidden ones); items also carry `wk_burned`. Dashboard: Shortlist toggle,
      clickable hidden counts, 125-word budget divider, Know it / Skip /
      Restore, `WK burned` badge. Read-time only, nothing stored
- [x] Derived priority grouping (pure function of jlpt/common/WK-level
      signals, 1–5) + "By study priority" sort on the vocab dashboard

### 3.3 Curation + editing

Shipped 2026-07-01.

- [x] Manual add (3.1) + inline edit of any entry's fields and notes in
      the dashboard row detail; hand-edited meanings keep
      `meaning_source: "user"` so enrichment never overwrites them
- [x] Merge-duplicates: `POST /api/{vocab,grammar}/{id}/merge` unions
      sightings, keeps the canonical entry's curated fields (an
      unreviewed target adopts the source's status), records the losing
      spelling in `surface_variants` (searchable), and tombstones the
      source with `merged_into` — re-harvests of the merged-away
      spelling redirect to the canonical item
- [x] Bulk status operations via row checkboxes on both dashboards
      (set any status on the selection; Merge needs 2+ selected and asks
      which entry to keep); the inbox "accept/ignore all shown" from 3.1
      stays
- [x] Known-vocab de-emphasis in breakdowns: sentence vocab is
      batch-resolved against the store (`POST /api/vocab/lookup`,
      surface variants included); known words render dimmed in the vocab
      table and inline links, and the word popover gains an in-store
      status toggle
- [x] Chapter vocab coverage: "Vocab N/M known" chip in the chapter
      topbar (`GET /api/store/coverage?chapter_id=…`) linking to the
      chapter-filtered vocab dashboard; updates live as statuses change
      in the breakdown popover (new `modules/events.ts` pub/sub bus, per
      the plan's state-syncing note)

### 3.4 Built-in SRS (web)

Shipped 2026-07-01.

- [x] Append-only review event log (`data/store/reviews.jsonl`): one
      JSON line per graded review (item, card type, grade 1–4, ts,
      elapsed_ms); SRS state is always derived by replaying a card's
      events, so the log stays the single source of truth and the
      scheduling formula can change without a data migration
- [x] FSRS-4.5 scheduler implemented in-repo (`services/srs.py`, default
      reference weights, no new dependency): retention target 0.9 (next
      interval = stability), whole-day intervals with a 10-minute
      same-day relearn step after "Again"
- [x] Cards per (item, card type), each scheduled independently: vocab
      gets a word card (headword → reading/meaning) plus a
      sentence-context card when a sighting carries the sentence;
      grammar gets a pattern card — resolves the plan's open question 3
      as "both card types"
- [x] Queue API: `GET /api/study/queue` (due cards most-overdue first,
      then new cards capped by `new_limit`, new vocab in dashboard
      priority order; only curation-status `active` items enter) and
      `POST /api/study/reviews` (appends an event, returns the new
      derived state)
- [x] Flashcard UI at `/study` (topbar "Study" link): reveal with
      space/enter, grade Again/Hard/Good/Easy with 1–4 keys, elapsed-ms
      capture, failed cards re-queued at the end of the session,
      session-done summary with "Keep studying"

### 3.5 Sync groundwork (design only)

Shipped 2026-07-01.

- [x] CloudKit record mapping documented in `docs/design/cloudkit-sync-plan.md`:
      `VocabItem`/`GrammarItem`/`ReviewEvent` record types in one custom
      zone (private DB), items last-writer-wins on `updated_at` with
      tombstone-wins, review events create-only (union merge, FSRS state
      re-derived per device), JSONL stays canonical on the Mac; no code
      until Phase 5

## Phase 4: Export + Exercises

- [ ] Anki TSV export for vocab/grammar items
- [ ] Exercise-specific prompts and walkthrough UI
- [ ] Grammar dashboard

## Phase 5: Polish + Native

- [x] Bulk operations (transcribe/breakdown all regions in a chapter):
      one-click "Prepare chapter" — see `docs/design/bulk-operations-plan.md`.
      Shipped 2026-07-06 as **beta**: covered by tests and verified
      against an isolated server (dry-run plan, failure isolation,
      SSE progress), but not yet exercised on a live chapter with real
      VLM calls — promote out of beta after first real use
- [ ] Region editing (resize, move, reorder)
- [x] iOS/iPadOS study companion (see `docs/design/ios-app-plan.md`): SwiftPM
      package `apple/StudiousKit` with the FSRS-4.5 Swift port
      (golden-file parity against `services/srs.py`), same-format JSONL
      store, study/browse/curation SwiftUI app, CloudKit sync engine
      (`CKSyncEngine`, per `docs/design/cloudkit-sync-plan.md`), Mac-side
      `studious-sync` CLI (CloudKit push/pull + manual JSONL
      merge/export fallback), and an Xcode app shell at
      `apple/Studious.xcodeproj`. Needs a machine with Xcode + an Apple
      Developer team to run on device — shipped 2026-07-02, source
      checked into the repo 2026-07-04
- [ ] Run the companion on a device end-to-end and deploy the CloudKit
      schema to the production environment
- [x] Native macOS app (see `docs/design/mac-app-plan.md`; shipped 2026-07-05):
      `studious-mac` executable target in `apple/StudiousKit` reusing
      the iOS companion's SwiftUI (study/browse/curation), pointed
      directly at the backend's canonical `data/store/` JSONL — the
      Mac app doubles as the bridge to the local FastAPI server, no
      CloudKit or developer account needed. Builds/runs with CLT only
      (`make run-mac`). Still open: signed .app bundle + in-app
      CloudKit once an Xcode machine is available (replaces the
      `studious-sync sync` CLI)
- [ ] Mobile-responsive web layout
