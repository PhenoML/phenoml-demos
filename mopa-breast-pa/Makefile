# MOPA breast-cancer prior-auth web UI — dev tasks.
#
#   make dev        run backend (:8001) + frontend (:5173) together; Ctrl+C stops both
#   make setup      one-time: create the venv + install backend and frontend deps
#   make backend    run only the FastAPI backend
#   make frontend   run only the Vite dev server
#
# Requires `uv` (https://docs.astral.sh/uv) for the Python venv and `npm` for the frontend.

SHELL := /bin/bash
.DEFAULT_GOAL := help

VENV := .venv
UVICORN := $(VENV)/bin/uvicorn
BACKEND_PORT ?= 8001

# Create the venv and install backend deps whenever requirements.txt changes.
$(VENV): requirements.txt
	uv venv --python 3.12 $(VENV)
	uv pip install --python $(VENV)/bin/python -r requirements.txt
	@touch $(VENV)

# Install frontend deps whenever package.json changes.
ui/node_modules: ui/package.json
	cd ui && npm install
	@touch ui/node_modules

.PHONY: setup
setup: $(VENV) ui/node_modules ## Create the venv + install backend and frontend deps

.PHONY: backend
backend: $(VENV) ## Run the FastAPI backend on :8001
	$(UVICORN) ui_server:app --port $(BACKEND_PORT) --reload

.PHONY: frontend
frontend: ui/node_modules ## Run the Vite dev server on :5173
	cd ui && npm run dev

.PHONY: dev
dev: setup ## Run backend + frontend together (Ctrl+C stops both)
	@echo "backend  -> http://localhost:$(BACKEND_PORT)"
	@echo "frontend -> http://localhost:5173   (open this one)"
	@echo "Ctrl+C stops both."
	@trap 'kill 0' EXIT INT TERM; \
	  $(UVICORN) ui_server:app --port $(BACKEND_PORT) --reload & \
	  ( cd ui && npm run dev ) & \
	  wait

.PHONY: help
help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'
