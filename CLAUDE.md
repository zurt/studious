# Studious - Claude Code Project Instructions

## Project Overview

Japanese study tool: upload PDFs, organize into chapters, select regions of interest, and transcribe with VLM (Anthropic Claude). View transcriptions side-by-side with originals. On top of transcription: sentence breakdowns, chapter grammar guides, exercise completions, a central vocab/grammar store (JMdict/JLPT enrichment, WaniKani sync) and built-in FSRS flashcards.

- **Backend**: FastAPI (Python 3.11+), file-based storage, async job queue
- **Frontend**: Vanilla TypeScript + Vite (no framework)
- **Apple** (`apple/`): SwiftPM package with an iOS companion and a native Mac app that read the same vocab/grammar store. Built in CI on macOS; not yet run on a device.
- **Package managers**: uv (backend), npm (frontend) — both enforce 7-day cooldown on new package versions
- **Docs**: `docs/README.md` indexes what is current, what is a shipped design (`docs/design/`), and what is historical (`docs/archive/`)
- **Open work**: read `docs/next-steps.md` at the start of a session — decisions made, open items, and where the next sessions pick up

### Key concepts
- **Document** — an uploaded PDF or image, rendered to page images
- **Chapter** — a named page range within a document (e.g., 第14課, pp. 45-52)
- **Region** — a bounding box on a page, tagged by type (reading_passage, vocab_list, grammar_points, exercises, instructions, other)
- **Transcription** — VLM output stored as markdown, either per-page or per-region
- **Breakdown** — per-sentence gloss, vocab and grammar for a reading passage
- **Store** — append-only JSONL of vocab/grammar items and review events under `data/store/`, harvested from breakdowns and vocab lists; shared with the Apple apps

## Development Commands

```bash
make install          # install all deps (uv + npm)
make dev-backend      # mock VLM + seeded backend/.dev-data, no key; :8000 (BACKEND_PORT=) with reload
make dev-reset        # delete backend/.dev-data and reseed it
make run-backend      # real data dir + real model (Keychain keys), no reload; :8000 (BACKEND_PORT=)
make dev-frontend     # vite on :5173 with proxy to the backend (BACKEND_PORT=)
make test             # run backend pytest + frontend vitest
make lint             # ruff (backend, benchmarks) + Biome (frontend)
make test-e2e         # Playwright smoke suite (STUDIOUS_VLM_PROVIDER=mock, isolated data dir)
make test-apple       # Swift suite (needs a Mac)
make audit            # run npm audit + pip-audit
make benchmark        # regression benchmark: fixtures vs. the default model, judged (real API calls)
```

## Post-Commit Workflow

After every commit, follow these steps:

1. **Tests**: Review whether new/changed code needs tests. Add them if so.
2. **Run tests**: Run `make test` and `make lint` and ensure both pass. Fix any failures before proceeding.
3. **README**: Update `README.md` if the change affects setup, usage, or architecture.
4. **Docs**: Update relevant files in `docs/` if the change affects the project description, roadmap, or architecture.
5. **Troubleshooting**: When you discover a new failure mode, where to find logs/state for a subsystem, or fix a bug whose diagnosis was non-obvious, add or update an entry in `docs/troubleshooting.md`. Keep it organized by symptom, not by date.

## Supply Chain Security

- **npm**: `frontend/.npmrc` enforces `min-release-age=7`. Do not bypass this.
- **uv**: `backend/uv.toml` enforces `exclude-newer = "7 days"`. Do not bypass this.
- Never install packages less than 7 days old. If a dependency is too new, wait or pin an older version.
- Run `make audit` periodically to check for known vulnerabilities.
- Never commit `.env` files or API keys.

## Quality Benchmarks

Two tools; `benchmarks/README.md` says which answers which question. Both
make real API calls.

- **Regression** (`make benchmark`): did a change make the shipping setup
  worse? Run it before and after, then
  `uv run --project backend python -m benchmarks.compare <before> <after>`.
  Act on the judge score; CER is only a fallback.
- **Model comparison**
  (`uv run --project backend python -m benchmarks.model_eval <build-dataset|run|judge|analyze>`):
  which model should ship? Run it before changing the default model — see
  `benchmarks/model_eval/README.md`.

Run `make benchmark` when making significant changes to:
- Provider logic (OCR or VLM providers)
- VLM prompts or prompt configuration
- Image preprocessing (PDF rendering, VLM image preparation)
- The transcription pipeline in `backend/app/jobs/`

## Code Conventions

- Backend logging uses structured JSON with correlation IDs. Use `logging.getLogger("studious.<module>")` for new loggers.
- All API requests carry `X-Correlation-ID` headers for end-to-end tracing.
- Frontend uses `logger.ts` for structured console logging with correlation IDs.
