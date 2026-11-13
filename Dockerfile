# Studious: single-container image (see docs/hosting.md).
#
# Stage 1 builds the frontend. Stage 2 installs the backend from the frozen
# lockfile and serves both: FastAPI serves the built frontend itself
# (STUDIOUS_STATIC_DIR), so the browser talks to one same-origin server.
#
# Supply chain: every base image is pinned to a version tag AND the digest of
# its multi-arch index, so a rebuild cannot silently pick up a different
# image. Dependabot's `docker` ecosystem proposes updates to both. The uv
# version (0.13.7, released 2026-11-03) was at least 7 days old when pinned,
# like every other dependency in this repo.
#
# The image holds no secrets and no data. Keys arrive as environment
# variables at run time; state lives on the /data volume.

# ---- Stage 1: frontend build ----
FROM node:26.13.0-trixie-slim@sha256:5adad64f9a1fca2d51972caa65983634c8a774eb300d72b20f7f2a0f60368072 AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json frontend/.npmrc ./
# frontend/.npmrc sets min-release-age, which needs npm >= 11.10 (older npm
# ignores it silently). `npm ci` installs the lockfile verbatim, so the setting
# matters little here, but fail loudly if the base image ever ships an older npm.
RUN npm --version | awk -F. '{ if ($1 < 11 || ($1 == 11 && $2 < 10)) { print "npm " $0 " is too old for min-release-age"; exit 1 } }'
RUN npm ci
COPY frontend/index.html frontend/tsconfig.json frontend/vite.config.ts ./
COPY frontend/src ./src
RUN npm run build

# ---- Stage 2: backend runtime ----
FROM python:3.15.0-slim-trixie@sha256:f5b92f2a669a4c347044f29367f31983280b648250ca94dea66f98c53bc87e58 AS runtime
COPY --from=ghcr.io/astral-sh/uv:0.13.7@sha256:96f40d3904aad8d0bd010539001d36c8e2188b981e1334471a90c4a1d93bb490 /uv /usr/local/bin/uv

# tesseract for the OCR provider (the same packages `make install` names).
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        tesseract-ocr tesseract-ocr-jpn tesseract-ocr-jpn-vert \
    && rm -rf /var/lib/apt/lists/*

# Fixed UID so the owner of a mounted volume can be matched from the host.
RUN useradd --uid 10001 --user-group --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin studious \
    && mkdir /data \
    && chown studious:studious /data

# Use the image's Python; never let uv download another one.
ENV UV_PYTHON_DOWNLOADS=never \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app/backend

# Dependency layer first, so a code change does not re-download packages.
# --frozen installs uv.lock verbatim (no resolution; the cooldown in uv.toml
# governs resolution, which never happens here).
COPY backend/pyproject.toml backend/uv.lock backend/uv.toml ./
RUN uv sync --frozen --no-install-project --no-dev

# Only what the app reads at run time: the package, the pinned reference
# manifest and its fetch script (`docker exec ... python scripts/fetch_refs.py`
# builds the JMdict index into /data/refs). backend/seed/ is dev-only and
# stays out.
COPY backend/app ./app
COPY backend/refs.lock.json ./
COPY backend/scripts/fetch_refs.py ./scripts/fetch_refs.py
RUN uv sync --frozen --no-dev

COPY --from=frontend /build/dist /app/frontend-dist

ENV PATH="/app/backend/.venv/bin:$PATH" \
    STUDIOUS_DATA_DIR=/data \
    STUDIOUS_STATIC_DIR=/app/frontend-dist

USER studious
VOLUME /data
EXPOSE 8000

# Python is already here; no curl needed.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"]

# Bound to all interfaces INSIDE the container; compose and `make docker-run`
# publish it on the host's loopback only. No --reload: a reload mid-request
# kills the in-process job queue.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
