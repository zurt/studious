# Studious - Project Description

## What is Studious?

Studious is a tool for studying Japanese textbooks and books. Users upload a PDF or image, transcribe pages using either Tesseract OCR or a Vision-Language Model (Anthropic Claude by default), and read the transcription side-by-side with the original page.

## Tech Stack

### Backend (Python 3.11+)
- **Framework**: FastAPI with uvicorn
- **OCR**: Tesseract with Japanese language support (jpn + jpn_vert)
- **VLM**: Anthropic Claude API (configurable model: sonnet, opus, haiku)
- **Storage**: File-based (JSON metadata, PNG page images, JSON transcriptions)
- **Job queue**: In-process async queue with SSE progress streaming
- **Config**: Pydantic Settings with .env file support

### Frontend (TypeScript)
- **Framework**: React 18
- **Build**: Vite with TypeScript
- **Routing**: React Router
- **Markdown**: react-markdown with GitHub-flavored markdown support

### Infrastructure
- **Package management**: uv (backend), npm (frontend) with 7-day cooldown
- **Logging**: Structured JSON with correlation IDs across the full stack
- **Testing**: pytest with pytest-asyncio

## Architecture

```
┌─────────────┐         ┌─────────────────────────────────────┐
│   Browser    │◄──SSE──►│           FastAPI Backend            │
│  React SPA   │◄──API──►│                                     │
│  :5173       │         │  ┌──────────┐  ┌────────────────┐  │
└─────────────┘         │  │ Job Queue │  │   Providers    │  │
                        │  │ (async)   │──│  ├─ Tesseract  │  │
                        │  └──────────┘  │  └─ Anthropic  │  │
                        │                └────────────────┘  │
                        │  ┌─────────────────────────────┐   │
                        │  │   File Storage (data/)      │   │
                        │  │  documents/ jobs/            │   │
                        │  └─────────────────────────────┘   │
                        └─────────────────────────────────────┘
```

### Request Flow

1. User uploads PDF/image via frontend
2. Backend saves original file, renders PDF pages to PNG
3. User selects pages and provider, submits transcription job
4. Job queue processes pages sequentially, streaming progress via SSE
5. Transcription results stored as JSON, displayed as rendered markdown

### Key Directories

- `backend/app/` — FastAPI application code
  - `api/` — route handlers (documents, transcribe, jobs, providers)
  - `providers/` — OCR and VLM provider implementations
  - `services/` — business logic (storage, PDF processing, range parsing)
- `frontend/src/` — React application code
  - `pages/` — Library (document list) and DocumentView (reader)
  - `components/` — TranscribePanel, MarkdownPane
- `data/` — runtime data (gitignored)
- `benchmarks/` — quality benchmarking tools
- `docs/` — project documentation
