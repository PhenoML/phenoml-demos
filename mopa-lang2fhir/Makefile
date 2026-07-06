# MOPA Lang2FHIR demo tasks.
#
#   make dev       run backend (:8002) and frontend (:5174)
#   make setup     create the venv and install backend/frontend deps
#   make backend   run FastAPI only
#   make frontend  run Vite only

SHELL := /bin/bash
.DEFAULT_GOAL := help

VENV := .venv
UVICORN := $(VENV)/bin/uvicorn
BACKEND_PORT ?= 8002

$(VENV): requirements.txt
	uv venv --python 3.12 $(VENV)
	uv pip install --python $(VENV)/bin/python -r requirements.txt
	@touch $(VENV)

ui/node_modules: ui/package.json
	cd ui && npm install
	@touch ui/node_modules

.PHONY: setup
setup: $(VENV) ui/node_modules ## Create the venv and install deps

.PHONY: backend
backend: $(VENV) ## Run the FastAPI backend
	$(UVICORN) ui_server:app --port $(BACKEND_PORT) --reload

.PHONY: frontend
frontend: ui/node_modules ## Run the Vite frontend
	cd ui && npm run dev

.PHONY: dev
dev: setup ## Run backend and frontend together
	@echo "backend  -> http://localhost:$(BACKEND_PORT)"
	@echo "frontend -> http://localhost:5174"
	@trap 'kill 0' EXIT INT TERM; \
	  $(UVICORN) ui_server:app --port $(BACKEND_PORT) --reload & \
	  ( cd ui && npm run dev ) & \
	  wait

.PHONY: help
help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'
