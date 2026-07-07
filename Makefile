.PHONY: install install-backend install-frontend dev dev-backend dev-frontend test test-backend test-frontend test-e2e test-apple run-mac audit audit-log logs clean benchmark refs golden docker-build docker-up

install: install-backend install-frontend
	@echo ""
	@echo "==> System dependencies (install if not present):"
	@echo "    macOS:         brew install tesseract tesseract-lang uv"
	@echo "    Debian/Ubuntu: sudo apt install tesseract-ocr tesseract-ocr-jpn tesseract-ocr-jpn-vert"
	@echo "                   (install uv: https://docs.astral.sh/uv/)"
	@echo ""
	@echo "==> Copy .env.example to .env and fill in ANTHROPIC_API_KEY."
	@echo ""
	@echo "==> Required tools: uv, npm >= 11.10"

install-backend:
	cd backend && uv venv .venv && uv pip install -e ".[dev]"

install-frontend:
	cd frontend && npm install

dev:
	@echo "Run 'make dev-backend' and 'make dev-frontend' in two terminals."

dev-backend:
	cd backend && uv run uvicorn app.main:app --reload --port 8000

dev-frontend:
	cd frontend && npm run dev

test: test-backend test-frontend

test-backend:
	cd backend && uv run pytest \
		--cov=app \
		--cov-report=term-missing \
		--cov-fail-under=75

test-frontend:
	cd frontend && npm test

# Swift suite for the iOS companion (apple/StudiousKit): a plain
# executable rather than `swift test`, because Command Line Tools
# installs ship neither XCTest nor Swift Testing. Needs only CLT.
test-apple:
	cd apple/StudiousKit && swift run studious-tests

# Native Mac companion (docs/mac-app-plan.md): a plain SwiftPM executable
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
#   make dev-backend 2>&1 | tee /tmp/studious-backend.log
logs:
	tail -F /tmp/studious-backend.log | jq -C .

# Tail the LLM audit log (one JSON line per provider call).
audit-log:
	tail -F backend/data/llm_audit.jsonl | jq -C .

benchmark:
	uv run --project backend python -m benchmarks.run_benchmark

# Single-container deployment (frontend built in, FastAPI serves it).
# See docs/hosting.md for the droplet runbook.
docker-build:
	docker build -t studious:latest .

docker-up:
	docker compose up -d --build

clean:
	rm -rf backend/.venv backend/.pytest_cache backend/**/__pycache__ frontend/node_modules frontend/dist
