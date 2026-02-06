.PHONY: setup benchmark smoke-test full-benchmark charts report clean help

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

setup: ## Install dependencies
	uv sync
	uv pip install mcp-hangar

smoke-test: ## Quick smoke test (5 runs, all scenarios)
	python -m src.runner run --all-scenarios --runs 5 --warmup 2

benchmark: ## Standard benchmark (30 runs, all scenarios + charts)
	python -m src.runner run --all-scenarios --runs 30 --warmup 5
	python -m src.runner charts

full-benchmark: ## Full publication run (100 runs + charts)
	python -m src.runner run --all-scenarios --runs 100 --warmup 10
	python -m src.runner charts

charts: ## Generate charts from existing results
	python -m src.runner charts

report: ## Print statistical report from existing results
	python -m src.runner report

clean: ## Remove all results
	rm -rf results/raw/*.json results/charts/*.png results/charts/*.svg
