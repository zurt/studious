.PHONY: install install-backend install-frontend dev dev-backend dev-frontend test test-backend test-frontend audit audit-log logs clean benchmark

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

audit:
	@echo "==> npm audit"
	cd frontend && npm audit --omit=dev || true
	@echo ""
	@echo "==> pip-audit"
	cd backend && uv run pip-audit || true

# Tail backend log assuming it was started with
#   make dev-backend 2>&1 | tee /tmp/studious-backend.log
logs:
	tail -F /tmp/studious-backend.log | jq -C .

# Tail the LLM audit log (one JSON line per provider call).
audit-log:
	tail -F backend/data/llm_audit.jsonl | jq -C .

benchmark:
	uv run --project backend python -m benchmarks.run_benchmark

clean:
	rm -rf backend/.venv backend/.pytest_cache backend/**/__pycache__ frontend/node_modules frontend/dist
