.DEFAULT_GOAL := help

-include .env
export

COMPOSE := docker compose
SERVICE := smartfind-api
CLIENT_SERVICE := smartfind-client

PUBLIC_HOST ?= localhost
PORT ?= 8000
CLIENT_PORT ?= 5173

ifeq ($(strip $(API_URL)),)
API_URL := http://$(PUBLIC_HOST):$(PORT)
endif
ifeq ($(strip $(CLIENT_URL)),)
CLIENT_URL := http://$(PUBLIC_HOST):$(CLIENT_PORT)
endif

WAIT_RETRIES ?= 60
WAIT_INTERVAL ?= 5

.PHONY: help setup env urls up up-d down build restart restart-api restart-client logs logs-api logs-client health wait-health rebuild rebuild-api build-index deploy shell clean clean-all ps

help: ## Show available commands
	@echo "Pelasko SmartFind AI (Docker)"
	@echo ""
	@grep -E '^[a-zA-Z0-9_-]+:.*##' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

setup: env ## Copy .env.example to .env
	@echo ""
	@echo "Next steps:"
	@echo "  1. Edit .env (set GAPGPT_API_KEY and PUBLIC_HOST)"
	@echo "  2. make up"
	@$(MAKE) urls

env: ## Create .env from .env.example if missing
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		echo "Created .env"; \
	else \
		echo ".env already exists"; \
	fi

urls: ## Show service URLs from .env
	@echo "API_URL=$(API_URL)"
	@echo "CLIENT_URL=$(CLIENT_URL)"
	@echo "WS_URL=ws://$(PUBLIC_HOST):$(CLIENT_PORT)/ws/chat"

up: ## Build and start all services (API + Client)
	$(COMPOSE) up --build

up-d: ## Start all services in background
	$(COMPOSE) up --build -d

down: ## Stop all services
	$(COMPOSE) down

build: ## Build Docker images
	$(COMPOSE) build

ps: ## Show running containers
	$(COMPOSE) ps

restart: restart-api restart-client ## Restart all services

restart-api: ## Restart API container
	$(COMPOSE) restart $(SERVICE)

restart-client: ## Restart client container
	$(COMPOSE) restart $(CLIENT_SERVICE)

logs: logs-api ## Follow API logs

logs-api: ## Follow API logs
	$(COMPOSE) logs -f $(SERVICE)

logs-client: ## Follow client logs
	$(COMPOSE) logs -f $(CLIENT_SERVICE)

health: wait-health ## Check API health
	@curl -fsS $(API_URL)/health | python3 -m json.tool

wait-health: ## Wait until API responds on /health
	@echo "Waiting for API at $(API_URL)/health ..."
	@i=0; \
	while [ $$i -lt $(WAIT_RETRIES) ]; do \
		if curl -fsS "$(API_URL)/health" >/dev/null 2>&1; then \
			echo "API is ready."; \
			exit 0; \
		fi; \
		i=$$((i + 1)); \
		printf "  attempt %s/%s - not ready yet\n" "$$i" "$(WAIT_RETRIES)"; \
		sleep $(WAIT_INTERVAL); \
	done; \
	echo "ERROR: API did not become ready. Check logs: make logs-api"; \
	exit 1

rebuild: build-index restart-api wait-health ## Rebuild FAISS index (works even if API is down)
	@echo "Index rebuilt and API restarted."

rebuild-api: wait-health ## Rebuild FAISS index via HTTP (API must already be running)
	@curl -fsS -X POST $(API_URL)/rebuild | python3 -m json.tool

build-index: ## Build FAISS index inside Docker
	$(COMPOSE) run --rm --entrypoint python $(SERVICE) -m scripts.build_index

deploy: ## Pull latest code, rebuild images, rebuild index
	git pull
	$(COMPOSE) up --build -d
	$(MAKE) rebuild

shell: ## Open shell in API container
	$(COMPOSE) exec $(SERVICE) /bin/sh

clean: ## Remove Python cache files
	find backend -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

clean-all: clean ## Stop containers and remove volumes
	$(COMPOSE) down -v
