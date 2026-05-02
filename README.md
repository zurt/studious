# Studious

A Japanese textbook study tool. Upload a PDF, organize it into chapters,
select regions of interest on pages, and transcribe them with a Vision-LLM
(Anthropic Claude). View transcriptions side-by-side with the original page
images.

Built to replace a manual ChatGPT-based study workflow with persistent storage,
chapter organization, and region-level transcription.

## Quick start

### Prerequisites

- Python 3.11+
- Node.js 18+ with npm 11.10+
- [uv](https://docs.astral.sh/uv/) (Python package manager)

```bash
# macOS
brew install uv

# install
make install

# config
cp .env.example .env

# store your Anthropic API key in macOS Keychain (do not put it in .env)
security add-generic-password -s ANTHROPIC_API_KEY -a "$USER" -w
# then add to ~/.zshrc:
#   export ANTHROPIC_API_KEY="$(security find-generic-password -s ANTHROPIC_API_KEY -a "$USER" -w 2>/dev/null)"

# run (two terminals)
make dev-backend     # http://localhost:8000
make dev-frontend    # http://localhost:5173
```

Open <http://localhost:5173>.

## Workflow

1. **Upload** a PDF or image
2. **Create chapters** — define page ranges within a document
3. **Draw regions** — select areas of interest on pages (reading passages, vocab lists, grammar points, exercises)
4. **Transcribe** — run VLM transcription on individual regions
5. View transcriptions side-by-side with the original page

## Layout

- `backend/` — FastAPI app (Python 3.11+), file-based storage.
- `frontend/` — Vite + vanilla TypeScript (no framework).
- `data/` — uploaded documents, rasterized pages, transcriptions, chapters,
  regions, and `llm_audit.jsonl` (append-only log of VLM calls; gitignored).
  Override with `STUDIOUS_DATA_DIR`.
- `benchmarks/` — quality benchmarking tools for tracking extraction accuracy.
- `docs/` — project description, roadmap, and architecture documentation.

## Tests

```bash
make test
```

## Security

Both package managers enforce a 7-day cooldown on new package versions to
protect against supply chain attacks:

- **npm**: configured in `frontend/.npmrc` (`min-release-age=7d`)
- **uv**: configured in `backend/uv.toml` (`exclude-newer = "7 days"`)

Run `make audit` to check for known vulnerabilities.

## Observability

All API requests carry `X-Correlation-ID` headers for end-to-end tracing.
Backend logs are structured JSON with correlation IDs and timing breakdowns.
