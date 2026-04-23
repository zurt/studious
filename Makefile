.PHONY: install install-backend install-frontend dev dev-backend dev-frontend test test-backend clean

install: install-backend install-frontend
	@echo ""
	@echo "==> System dependency reminder:"
	@echo "    sudo apt install tesseract-ocr tesseract-ocr-jpn tesseract-ocr-jpn-vert"
	@echo ""
	@echo "==> Copy .env.example to .env and fill in ANTHROPIC_API_KEY."

install-backend:
	cd backend && python3 -m venv .venv && . .venv/bin/activate && pip install -e .

install-frontend:
	cd frontend && npm install

dev:
	@echo "Run 'make dev-backend' and 'make dev-frontend' in two terminals."

dev-backend:
	cd backend && . .venv/bin/activate && uvicorn app.main:app --reload --port 8000

dev-frontend:
	cd frontend && npm run dev

test: test-backend

test-backend:
	cd backend && . .venv/bin/activate && pytest

clean:
	rm -rf backend/.venv backend/.pytest_cache backend/**/__pycache__ frontend/node_modules frontend/dist
