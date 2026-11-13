.PHONY: install install-backend install-frontend dev dev-backend dev-reset run-backend dev-frontend test test-backend test-frontend test-e2e test-apple run-mac lint audit audit-log logs clean benchmark refs golden docker-build docker-run docker-smoke

install: install-backend install-frontend
	@echo ""
	@echo "==> System dependencies (install if not present):"
	@echo "    macOS:         brew install tesseract tesseract-lang uv"
	@echo "    Debian/Ubuntu: sudo apt install tesseract-ocr tesseract-ocr-jpn tesseract-ocr-jpn-vert"
	@echo "                   (install uv: https://docs.astral.sh/uv/)"
	@echo ""
	@echo "==> 'make dev-backend' needs no API key (mock VLM + sample data)."
	@echo "    For real use: copy .env.example to .env and store ANTHROPIC_API_KEY in the Keychain (see README), then 'make run-backend'."
	@echo ""
	@echo "==> Required tools: uv, npm >= 11.10"

install-backend:
	cd backend && uv venv .venv && uv pip install -e ".[dev]"

install-frontend:
	cd frontend && npm install

dev:
	@echo "Run 'make dev-backend' and 'make dev-frontend' in two terminals (sample data, mock VLM, no key)."
	@echo "To work against your real data and the real model, use 'make run-backend' instead of 'make dev-backend'."

# Backend port for dev-backend / run-backend, and the port dev-frontend proxies
# to (frontend/vite.config.ts reads STUDIOUS_BACKEND_PORT). Override it to run
# the dev stack next to the real one: make dev-backend BACKEND_PORT=8001
BACKEND_PORT ?= 8000

# API keys are read from the macOS Keychain for the one process that needs
# them, never exported from the shell rc file (where every npm script and
# Python import could read them). A key already in the environment wins;
# off macOS the lookup is empty and the app treats the key as unset.
KEYCHAIN = security find-generic-password -a "$$USER" -w -s
WITH_KEYS = ANTHROPIC_API_KEY="$${ANTHROPIC_API_KEY:-$$($(KEYCHAIN) ANTHROPIC_API_KEY 2>/dev/null)}" \
	WANIKANI_API_TOKEN="$${WANIKANI_API_TOKEN:-$$($(KEYCHAIN) WANIKANI_API_TOKEN 2>/dev/null)}"

# Development backend: the mock VLM provider (canned output, no API key, no
# network) on a throwaway data dir seeded with a sample textbook, so it never
# touches backend/data. Everything below is set on the command line, which
# wins over backend/.env (load_dotenv does not override variables already in
# the environment):
#   - ANTHROPIC_API_KEY / WANIKANI_API_TOKEN are emptied: no Keychain lookup,
#     no key for the process to use or leak;
#   - ANKI_CONNECT_URL points at a closed local port (9, "discard"), so a
#     seeded card can never be pushed into the real Anki running on :8765.
# The seeder is a no-op once .dev-data holds a document; `make dev-reset`
# starts over. Reload is on: nothing here is worth a stable process.
DEV_ENV = STUDIOUS_DATA_DIR=.dev-data STUDIOUS_VLM_PROVIDER=mock \
	ANTHROPIC_API_KEY= WANIKANI_API_TOKEN= ANKI_CONNECT_URL=http://127.0.0.1:9

dev-backend:
	cd backend && $(DEV_ENV) uv run python -m app.services.seed --link-refs
	cd backend && $(DEV_ENV) uv run uvicorn app.main:app --reload --port $(BACKEND_PORT)

# Throw away the dev data and seed it again.
dev-reset:
	rm -rf backend/.dev-data
	cd backend && $(DEV_ENV) uv run python -m app.services.seed --link-refs

# The real thing: keys from the Keychain, the real data dir, the real model.
# No --reload on purpose: a reload mid-request kills the in-process job queue,
# which has damaged real data before. Restart it by hand after code changes.
run-backend:
	cd backend && $(WITH_KEYS) uv run uvicorn app.main:app --port $(BACKEND_PORT)

dev-frontend:
	cd frontend && STUDIOUS_BACKEND_PORT=$(BACKEND_PORT) npm run dev

test: test-backend test-frontend

test-backend:
	cd backend && uv run pytest \
		--cov=app \
		--cov-report=term-missing \
		--cov-fail-under=75

test-frontend:
	cd frontend && npm test

# Ruff over backend/ + benchmarks/ (config: ruff.toml) and Biome over
# the frontend (config: frontend/biome.json). Both also run in CI.
lint:
	cd backend && uv run ruff check ..
	cd frontend && npm run lint

# Swift suite for the iOS companion (apple/StudiousKit): a plain
# executable rather than `swift test`, because Command Line Tools
# installs ship neither XCTest nor Swift Testing. Needs only CLT.
test-apple:
	cd apple/StudiousKit && swift run studious-tests

# Native Mac companion (docs/design/mac-app-plan.md): a plain SwiftPM executable
# that bridges directly to the backend's data/store/. STUDIOUS_DATA_DIR
# points it at the repo's real backend data, so this is bridge mode
# against the live store by default.
run-mac:
	cd apple/StudiousKit && STUDIOUS_DATA_DIR=$(CURDIR)/backend/data swift run studious-mac

# Regenerate the Swift FSRS/queue parity fixtures from the Python
# scheduler. Run after any change to backend/app/services/srs.py, then
# `make test-apple` and commit the updated fixtures.
golden:
	cd backend && uv run python scripts/generate_fsrs_golden.py


# Browser smoke suite: Playwright boots an isolated backend (mock VLM
# provider, fresh data dir) plus a vite dev server on dedicated ports.
# One-time setup: cd frontend && npx playwright install chromium
test-e2e:
	cd frontend && npm run test:e2e

# Fetch pinned reference datasets (JMdict, JLPT lists; see
# backend/refs.lock.json) and build data/refs/jmdict/jmdict.sqlite.
refs:
	cd backend && uv run python scripts/fetch_refs.py

audit:
	@echo "==> npm audit (fail on high+critical)"
	cd frontend && npm audit --omit=dev --audit-level=high
	@echo ""
	@echo "==> pip-audit"
	cd backend && uv run pip-audit

# Tail backend log assuming it was started with
#   make run-backend 2>&1 | tee /tmp/studious-backend.log
logs:
	tail -F /tmp/studious-backend.log | jq -C .

# Tail the LLM audit log (one JSON line per provider call).
audit-log:
	tail -F backend/data/llm_audit.jsonl | jq -C .

# Regression benchmark: runs the committed fixtures through the app's
# default model and has a judge model grade the results. Makes real API
# calls. See benchmarks/README.md (and model_eval/ for comparing models).
benchmark:
	$(WITH_KEYS) uv run --project backend python -m benchmarks.run_benchmark

# Single-container image (Dockerfile, docs/hosting.md). Needs a Docker daemon.
# docker-run starts it on the mock VLM with a throwaway named volume, so it
# never touches backend/data. Variables:
#   DOCKER_DATA      the /data volume: a volume name (default) or an absolute
#                    host path writable by UID 10001. Never backend/data
#                    unless you mean it.
#   DOCKER_VLM       mock (default) or anthropic
#   DOCKER_ENV_FILE  an env file with ANTHROPIC_API_KEY etc. (not committed)
#   DOCKER_PORT      host port, bound to 127.0.0.1 only (default 8000)
DOCKER_IMAGE ?= studious:local
DOCKER_DATA ?= studious-local-data
DOCKER_VLM ?= mock
DOCKER_PORT ?= 8000

docker-build:
	docker build -t $(DOCKER_IMAGE) .

docker-run: docker-build
	@echo "==> http://127.0.0.1:$(DOCKER_PORT)  VLM=$(DOCKER_VLM)  /data=$(DOCKER_DATA)"
	docker run --rm -it --name studious-local \
		-p 127.0.0.1:$(DOCKER_PORT):8000 \
		-v $(DOCKER_DATA):/data \
		$(if $(DOCKER_ENV_FILE),--env-file $(DOCKER_ENV_FILE)) \
		-e STUDIOUS_VLM_PROVIDER=$(DOCKER_VLM) \
		$(DOCKER_IMAGE)

# What CI runs: build the image, run it on the mock VLM, check it from outside.
docker-smoke:
	docker build -t studious:smoke .
	scripts/docker-smoke.sh studious:smoke

clean:
	rm -rf backend/.venv backend/.pytest_cache backend/**/__pycache__ frontend/node_modules frontend/dist
