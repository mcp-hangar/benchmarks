.PHONY: setup benchmark smoke-test full-benchmark charts report clean help

SKIP_HANGAR ?= 0

ifeq ($(SKIP_HANGAR),1)
  UV_RUN = uv run --no-sync
else
  UV_RUN = uv run
endif

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

setup: ## Install dependencies (use SKIP_HANGAR=1 to keep locally installed mcp-hangar)
ifeq ($(SKIP_HANGAR),1)
	uv sync --inexact --no-install-package mcp-hangar
else
	uv sync
	uv pip install mcp-hangar
endif

smoke-test: ## Quick smoke test (5 runs, all scenarios)
	$(UV_RUN) python -m src.runner run --all-scenarios --runs 5 --warmup 2

benchmark: ## Standard benchmark (30 runs, all scenarios + charts)
	$(UV_RUN) python -m src.runner run --all-scenarios --runs 30 --warmup 5
	$(UV_RUN) python -m src.runner charts

full-benchmark: ## Full publication run (100 runs + charts)
	$(UV_RUN) python -m src.runner run --all-scenarios --runs 100 --warmup 10
	$(UV_RUN) python -m src.runner charts

charts: ## Generate charts from existing results
	$(UV_RUN) python -m src.runner charts

report: ## Print statistical report from existing results
	$(UV_RUN) python -m src.runner report

clean: ## Remove all results
	rm -rf results/raw/*.json results/charts/*.png results/charts/*.svg
