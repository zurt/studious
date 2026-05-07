# Studious - Project Description

## What is Studious?

Studious is a Japanese textbook study tool. Users upload a PDF, organize it into chapters, select regions of interest on pages (reading passages, vocab lists, grammar points, exercises), and transcribe them with a Vision-Language Model (Anthropic Claude). Transcriptions are displayed side-by-side with the original page images.

The tool replaces a manual ChatGPT-based study workflow with persistent storage, chapter organization, and region-level transcription.

## Tech Stack

### Backend (Python 3.11+)
- **Framework**: FastAPI with uvicorn
- **VLM**: Anthropic Claude API (configurable model: sonnet, opus, haiku;
  default `claude-opus-4-7`). Adaptive thinking and per-stage `effort` (default
  `high` for transcription, `xhigh` for sentence breakdowns) are applied where
  supported; ephemeral prompt caching is enabled on text/tool-schema blocks.
- **Storage**: File-based (JSON metadata, PNG page images, JSON transcriptions)
- **Job queue**: In-process async queue with SSE progress streaming
- **Config**: Pydantic Settings with .env file support

### Frontend (TypeScript)
- **No framework**: Vanilla TypeScript
- **Build**: Vite
- **Routing**: Custom minimal router
- **Markdown**: marked (GitHub-flavored markdown)

### Infrastructure
- **Package management**: uv (backend), npm (frontend) with 7-day cooldown
- **Logging**: Structured JSON with correlation IDs across the full stack
- **Testing**: pytest with pytest-asyncio

## Architecture

```
┌─────────────┐         ┌─────────────────────────────────────┐
│   Browser    │◄──SSE──►│           FastAPI Backend            │
│  Vanilla TS  │◄──API──►│                                     │
│  :5173       │         │  ┌──────────┐  ┌────────────────┐  │
└─────────────┘         │  │ Job Queue │  │   Providers    │  │
                        │  │ (async)   │──│  └─ Anthropic  │  │
                        │  └──────────┘  └────────────────┘  │
                        │  ┌─────────────────────────────┐   │
                        │  │   File Storage (data/)      │   │
                        │  │  documents/ jobs/            │   │
                        │  └─────────────────────────────┘   │
                        └─────────────────────────────────────┘
```

### Data Model

```
data/documents/{doc_id}/
  meta.json                    # document metadata
  original.{ext}               # uploaded file
  pages/{nnnn}.png             # rendered page images
  transcriptions/{nnnn}.json   # full-page transcriptions
  chapters/{chapter_id}/
    meta.json                  # chapter: title, page range, order
    regions/{region_id}.json   # region: page, bbox, tag, transcription
```

### Request Flow

1. User uploads PDF/image via frontend
2. Backend saves original file, renders PDF pages to PNG
3. User creates chapters (named page ranges) and draws regions on pages
4. User triggers transcription on regions — image is cropped to bbox, sent to VLM
5. Transcription results stored as markdown in region file, displayed alongside original

### Key Directories

- `backend/app/` — FastAPI application code
  - `api/` — route handlers (documents, chapters, regions, transcribe, jobs, providers)
  - `providers/` — VLM provider implementations
  - `services/` — business logic (storage, PDF processing, range parsing)
- `frontend/src/` — Vanilla TypeScript application
  - `pages/` — library, document-view, chapter-view
  - `modules/` — region-drawer (canvas overlay), region-list
- `data/` — runtime data (gitignored)
- `benchmarks/` — quality benchmarking tools
- `docs/` — project documentation
