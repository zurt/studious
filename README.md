# Studious

A tool for studying Japanese textbooks and books. Upload a PDF or image,
transcribe pages with either Tesseract OCR or a Vision-LLM (Anthropic Claude
by default, with a custom prompt), and read the transcription side-by-side
with the original page.

This is the MVP. Future features (designed for, not built): furigana display,
vocabulary lookup, and LLM translation + grammar breakdown.

## Quick start

```bash
# system deps (Debian/Ubuntu)
sudo apt install tesseract-ocr tesseract-ocr-jpn tesseract-ocr-jpn-vert

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

## Tests

```bash
make test
```
