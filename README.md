# Studious

A tool for studying Japanese textbooks and books. Upload a PDF or image,
transcribe pages with either Tesseract OCR or a Vision-LLM (Anthropic Claude
by default, with a custom prompt), and read the transcription side-by-side
with the original page.

This is the MVP. Future features (designed for, not built): furigana display,
vocabulary lookup, and LLM translation + grammar breakdown.

## Quick start

### Prerequisites

- Python 3.11+
- Node.js 18+ with npm 11.10+
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- Tesseract OCR with Japanese language data

```bash
# system deps (Debian/Ubuntu)
sudo apt install tesseract-ocr tesseract-ocr-jpn tesseract-ocr-jpn-vert

# macOS
brew install tesseract tesseract-lang uv

# install
make install

# config
cp .env.example .env
# edit .env, set ANTHROPIC_API_KEY

# run (two terminals)
make dev-backend     # http://localhost:8000
make dev-frontend    # http://localhost:5173
```

Open <http://localhost:5173>.

## Layout

- `backend/` — FastAPI app (Python 3.11+).
- `frontend/` — Vite + React + TypeScript.
- `data/` — uploaded documents, rasterized pages, transcriptions, and job
  state (gitignored). Override with `STUDIOUS_DATA_DIR`.
- `benchmarks/` — quality benchmarking tools for tracking extraction accuracy.
- `docs/` — project description, roadmap, and architecture documentation.

## Tests

```bash
make test
```

## Quality benchmarks

```bash
make benchmark
```

See `benchmarks/fixtures/README.md` for how to add test documents.

## Security

Both package managers enforce a 7-day cooldown on new package versions to
protect against supply chain attacks:

- **npm**: configured in `frontend/.npmrc` (`min-release-age=7d`)
- **uv**: configured in `backend/uv.toml` (`exclude-newer = "7 days"`)

Run `make audit` to check for known vulnerabilities.

## Observability

All API requests carry `X-Correlation-ID` headers for end-to-end tracing.
Backend logs are structured JSON with correlation IDs and timing breakdowns.
See `docs/project-description.md` for the full architecture.
