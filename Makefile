# VASPTrace — developer tasks
# Every target is safe to run repeatedly.

PY := backend/.venv/bin/python
PIP := backend/.venv/bin/pip
VENV_PYTHON := /Library/Frameworks/Python.framework/Versions/3.11/bin/python3.11

.DEFAULT_GOAL := help
MANIFEST := ../data/labels/manifest.yaml

.PHONY: help install install-backend install-frontend backend frontend \
        lint lint-backend lint-frontend format typecheck typecheck-backend \
        typecheck-frontend test test-backend check clean \
        migrate migrate-down migration demo-fixtures seed seed-demo seed-check

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: install-backend install-frontend ## Install backend + frontend dependencies

install-backend: ## Create the Python 3.11 venv and install backend dependencies
	test -d backend/.venv || $(VENV_PYTHON) -m venv backend/.venv
	$(PIP) install --quiet --upgrade pip
	$(PIP) install --quiet -r backend/requirements-dev.txt

install-frontend: ## Install frontend dependencies
	cd frontend && npm install

backend: ## Run the API on http://127.0.0.1:8000
	cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000

frontend: ## Run the dashboard on http://localhost:3000
	cd frontend && npm run dev

migrate: ## Apply all database migrations
	cd backend && .venv/bin/alembic upgrade head

migrate-down: ## Roll back the most recent migration
	cd backend && .venv/bin/alembic downgrade -1

migration: ## Generate a migration from model changes: make migration m="add x"
	cd backend && .venv/bin/alembic revision --autogenerate -m "$(m)"

demo-fixtures: ## Regenerate the synthetic demo label files
	cd backend && .venv/bin/python -m app.database.seeds.demo_fixtures

seed-check: ## Validate label sources and run the integrity scan, writing nothing
	cd backend && .venv/bin/python -m app.database.seeds.import_labels \
		--manifest $(MANIFEST) --dry-run

seed: ## Import real label sources (skips demo_unverified sources)
	cd backend && .venv/bin/python -m app.database.seeds.import_labels --manifest $(MANIFEST)

seed-demo: ## Import labels including the synthetic demo fixture (never in production)
	cd backend && .venv/bin/python -m app.database.seeds.import_labels \
		--manifest $(MANIFEST) --allow-demo

lint: lint-backend lint-frontend ## Lint everything

lint-backend:
	cd backend && .venv/bin/ruff check .
	cd backend && .venv/bin/ruff format --check .

lint-frontend:
	cd frontend && npm run lint

format: ## Auto-fix formatting and import order (backend)
	cd backend && .venv/bin/ruff check --fix .
	cd backend && .venv/bin/ruff format .

typecheck: typecheck-backend typecheck-frontend ## Type-check everything

typecheck-backend:
	cd backend && .venv/bin/mypy app tests

typecheck-frontend:
	cd frontend && npm run typecheck

test: test-backend ## Run the test suites

test-backend:
	cd backend && .venv/bin/pytest

check: lint typecheck test ## The full gate — run this before every commit

clean: ## Remove caches and build output
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf backend/.pytest_cache backend/.mypy_cache backend/.ruff_cache frontend/.next
