# Studious — single-container deployment (see docs/hosting.md).
# Stage 1 builds the frontend; stage 2 installs the backend from the
# frozen lockfile and serves both (FastAPI serves frontend/dist via
# STUDIOUS_STATIC_DIR, so the browser talks to one same-origin server).

# ---- Stage 1: frontend build ----
FROM node:22-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json frontend/.npmrc ./
# npm ci installs the lockfile verbatim (the 7-day cooldown in .npmrc
# governs resolution, which never happens here).
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- Stage 2: backend runtime ----
FROM python:3.11-slim AS runtime
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# tesseract for the OCR provider (same packages `make install` names).
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr tesseract-ocr-jpn tesseract-ocr-jpn-vert curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/backend

# Dependency layer first so code edits don't re-download packages.
# --frozen installs uv.lock verbatim (no resolution, cooldown not consulted).
COPY backend/pyproject.toml backend/uv.lock backend/uv.toml ./
RUN uv sync --frozen --no-install-project --no-dev

COPY backend/app ./app
RUN uv sync --frozen --no-dev

COPY --from=frontend /build/dist /app/frontend-dist

ENV STUDIOUS_DATA_DIR=/data \
    STUDIOUS_STATIC_DIR=/app/frontend-dist \
    PYTHONUNBUFFERED=1
VOLUME /data
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

CMD ["uv", "run", "--no-sync", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
