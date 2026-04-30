# Studious - Claude Code Project Instructions

## Project Overview

Japanese study tool: upload PDFs, organize into chapters, select regions of interest, and transcribe with VLM (Anthropic Claude). View transcriptions side-by-side with originals.

- **Backend**: FastAPI (Python 3.11+), file-based storage, async job queue
- **Frontend**: Vanilla TypeScript + Vite (no framework)
- **Package managers**: uv (backend), npm (frontend) — both enforce 7-day cooldown on new package versions

### Key concepts
- **Document** — an uploaded PDF or image, rendered to page images
- **Chapter** — a named page range within a document (e.g., 第14課, pp. 45-52)
- **Region** — a bounding box on a page, tagged by type (reading_passage, vocab_list, grammar_points, exercises, instructions, other)
- **Transcription** — VLM output stored as markdown, either per-page or per-region

## Development Commands

```bash
make install          # install all deps (uv + npm)
make dev-backend      # uvicorn on :8000 with reload
make dev-frontend     # vite on :5173 with proxy to backend
make test             # run backend pytest suite
make audit            # run npm audit + pip-audit
make benchmark        # run quality benchmarks (when fixtures exist)
```

## Post-Commit Workflow

After every commit, follow these steps:

1. **Tests**: Review whether new/changed code needs tests. Add them if so.
2. **Run tests**: Run `make test` and ensure all tests pass. Fix any failures before proceeding.
3. **README**: Update `README.md` if the change affects setup, usage, or architecture.
4. **Docs**: Update relevant files in `docs/` if the change affects the project description, roadmap, or architecture.
5. **Troubleshooting**: When you discover a new failure mode, where to find logs/state for a subsystem, or fix a bug whose diagnosis was non-obvious, add or update an entry in `docs/troubleshooting.md`. Keep it organized by symptom, not by date.

## Supply Chain Security

- **npm**: `frontend/.npmrc` enforces `min-release-age=7d`. Do not bypass this.
- **uv**: `backend/uv.toml` enforces `exclude-newer = "7 days"`. Do not bypass this.
- Never install packages less than 7 days old. If a dependency is too new, wait or pin an older version.
- Run `make audit` periodically to check for known vulnerabilities.
- Never commit `.env` files or API keys.

## Quality Benchmarks

Run `make benchmark` when making significant changes to:
- Provider logic (OCR or VLM providers)
- VLM prompts or prompt configuration
- Image preprocessing (PDF rendering, VLM image preparation)
- The transcription pipeline in `jobs.py`

## Code Conventions

- Backend logging uses structured JSON with correlation IDs. Use `logging.getLogger("studious.<module>")` for new loggers.
- All API requests carry `X-Correlation-ID` headers for end-to-end tracing.
- Frontend uses `logger.ts` for structured console logging with correlation IDs.
