# CLAUDE.md

## Project Overview

Benchmark suite for [mcp-hangar](https://github.com/mcp-hangar/mcp-hangar) — measures MCP tool call performance comparing sequential vs parallel execution. Answers: "How much faster is parallel MCP tool execution through Hangar compared to sequential?"

## Commands

```bash
# Setup
make setup                        # Install all dependencies
make setup SKIP_HANGAR=1          # Install deps WITHOUT overwriting locally installed mcp-hangar

# Benchmarks
make smoke-test                   # Quick test: 5 runs, all scenarios
make smoke-test SKIP_HANGAR=1     # Same, preserving local hangar
make benchmark                    # Standard: 30 runs + charts
make full-benchmark               # Publication: 100 runs + charts

# Analysis (from existing results)
make charts                       # Generate PNG/SVG charts
make report                       # Print statistical report to console

# CLI (more granular control)
uv run python -m src.runner run --scenario s2 --runs 50
uv run python -m src.runner run --scenario s3 --baselines sequential,hangar_parallel
uv run python -m src.runner run --all-scenarios --runs 30 --warmup 5
uv run python -m src.runner charts
uv run python -m src.runner report
uv run python -m src.runner report --format markdown --output results/REPORT.md

# Cleanup
make clean                        # Remove all results and charts
```

## SKIP_HANGAR Flag

When developing against a local mcp-hangar build (e.g. installed from main via `uv pip install -e ../mcp-hangar/packages/core`), use `SKIP_HANGAR=1` on ALL make commands. This:

- `make setup`: runs `uv sync --inexact --no-install-package mcp-hangar` (installs deps without touching hangar, doesn't remove "foreign" packages)
- All other targets: runs `uv run --no-sync` (skips automatic sync that would overwrite local hangar)

Without the flag, `make setup` installs mcp-hangar from PyPI and `uv run` syncs before each command.

## Architecture

### Execution Flow

```
CLI (src/runner.py)
  → Scenario (src/scenarios/s*.py, extends BaseScenario)
    → Harness (src/harness.py: run_benchmark)
      → Baseline function (src/baselines/*.py)
        → Provider (src/providers/controlled_delay.py via stdio)
    → Statistics + JSON output
  → Analysis (src/analysis/stats.py, charts.py)
    → Console tables / PNG+SVG charts / Markdown report
```

### Key Files

| File | Role |
|------|------|
| `src/runner.py` | CLI entrypoint (Click). Three commands: `run`, `charts`, `report`. Routes to scenarios via `SCENARIO_MAP` dict. |
| `src/harness.py` | Core benchmark engine. Runs warmup + N measurement iterations, times each with `time.perf_counter_ns()`, computes stats (mean, median, p50/p95/p99, 95% CI via t-distribution, outliers at 3σ), saves JSON to `results/raw/`. |
| `src/scenarios/base.py` | `BaseScenario` ABC. Handles direct MCP client setup (`DirectMCPClient`), Hangar setup with singleton reset (`_reset_hangar_globals()`), and iterating over baselines. Each scenario overrides: `name`, `scenario_id`, `get_provider_configs()`, `get_calls()`, `get_parameters()`, `get_baselines()`. |
| `src/providers/controlled_delay.py` | Custom MCP server (JSON-RPC over stdio). Configurable via env vars. Sleeps `BENCH_CALL_DELAY_MS` per call. Handles concurrent requests via `asyncio.create_task`. Self-measures scheduling overhead. |
| `src/providers/configs.py` | Factory functions (`make_provider_config`, `s1_baseline_configs`, etc.) that build provider command + env dicts. |
| `src/baselines/direct_sequential.py` | `DirectMCPClient` (manages raw MCP stdio sessions) + `run_sequential()`. |
| `src/baselines/direct_parallel.py` | `run_parallel()` — `asyncio.gather` over `DirectMCPClient`. |
| `src/baselines/hangar_sequential.py` | `run_hangar_sequential()` — serial `hangar.invoke()` calls. |
| `src/baselines/hangar_parallel.py` | `run_hangar_parallel()` — `asyncio.gather` over `hangar.invoke()`. |
| `src/analysis/stats.py` | `load_results()`, `results_to_dataframe()`, `compute_speedups()`, `compute_overhead()`, report generators. Deduplicates results by `(scenario, baseline, num_calls, delay_ms)` keeping last. |
| `src/analysis/charts.py` | 6 chart generators: money chart, scaling curve, cold start, latency distribution, overhead, workflow timeline. Uses matplotlib + seaborn. |
| `src/utils/timing.py` | `TimingRecord`, `BatchTimingRecord` dataclasses, `now_ns()`, `ns_to_ms()`. |
| `src/utils/environment.py` | `capture_environment()` — captures OS, CPU, Python, package versions, git commit. |

### Hangar Singleton Reset

`_reset_hangar_globals()` in `base.py` resets all mcp-hangar global singletons (CQRS buses, context, security handler, saga manager, rate limiter, knowledge base, server state) between Hangar instances. This is critical — without it, Hangar baselines would share state from previous runs and produce wrong results.

### Four Baselines

| Baseline | What | Measures |
|----------|------|----------|
| `sequential` | Direct MCP `call_tool()` in a loop | Baseline: sum of latencies |
| `direct_parallel` | Direct MCP via `asyncio.gather()` | Best-case parallelism (no framework) |
| `hangar_sequential` | `hangar.invoke()` in a loop | Hangar overhead without parallelism |
| `hangar_parallel` | `hangar.invoke()` via `asyncio.gather()` | Hangar's actual parallel performance |

S6 adds a fifth baseline `workflow_parallel` — 3-step pipeline with per-step parallelism.

### Six Scenarios

| ID | Class | What | Parametrization | Baselines |
|----|-------|------|-----------------|-----------|
| S1 | `S1Baseline` | Per-call overhead | delay_ms ∈ [0, 10, 50, 100, 200], 50 calls each | sequential, hangar_sequential |
| S2 | `S2Fanout` | Parallel scaling, 1 provider | N ∈ [1, 2, 5, 10, 15, 20] tools, 100ms delay | all four |
| S3 | `S3MultiProvider` | Cross-provider parallelism | 5 providers [50,100,200,300,500]ms; also [100,100,100]ms | all four |
| S4 | `S4ColdStart` | Cold start deduplication | N ∈ [1, 5, 10, 20] concurrent calls, 500ms startup | sequential, hangar_parallel |
| S5 | `S5MixedLatency` | Head-of-line blocking | 5×10ms + 3×100ms + 1×500ms | all four |
| S6 | `S6AgentWorkflow` | Realistic 3-step pipeline | fetch(200ms)×3 → search(300ms)×3 → fs(50ms)×1 | sequential, workflow_parallel |

S6 has a custom `run()` override — it doesn't use `BaseScenario.run()` because the workflow has step dependencies (step 2 depends on step 1 completion).

### Output Formats

- **JSON results**: `results/raw/{scenario}_{baseline}_{YYYYMMDD_HHMMSS}.json` — raw measurements, stats, environment, parameters
- **Charts**: `results/charts/chart{1-6}_*.{png,svg}` — publication-quality figures
- **Console report**: Rich tables with color-coded speedups/overhead
- **Markdown report**: `results/REPORT.md` via `--format markdown`

### Data Flow in Analysis

`load_results()` reads all JSON files from `results/raw/` → `results_to_dataframe()` flattens to pandas DataFrame with deduplication (keeps last by scenario+baseline+num_calls+delay_ms) → `compute_speedups()` and `compute_overhead()` produce comparison DataFrames → `print_executive_summary()` uses `compute_overhead()` output for the summary line (overhead as percentage range, NOT ms/call).

**Important**: The executive summary's "Framework overhead" line is derived from `compute_overhead()` — the same function that powers the detailed overhead table. This ensures consistency. Overhead is reported as percentage range across all scenario/baseline pairs.

## Adding a New Scenario

1. Create `src/scenarios/s7_name.py`
2. Subclass `BaseScenario`, implement required properties/methods:
   - `name` → display name
   - `scenario_id` → `"s7_name"` (used in filenames and analysis grouping)
   - `get_provider_configs()` → list of dicts from `make_provider_config()`
   - `get_calls()` → list of `ToolCall(provider, tool, arguments)`
   - `get_parameters()` → dict saved in result JSON
   - `get_baselines()` → which of the four baselines to run (override if not all)
3. Add `create_scenarios()` factory → returns list of scenario instances (one per parametrization)
4. Register in `src/runner.py` `SCENARIO_MAP`: `"s7": s7_scenarios`
5. If the scenario needs step dependencies (like S6), override `run()` entirely
6. Optionally add a Hangar config YAML in `configs/` (these are reference configs, not used by code)

## Provider Environment Variables

The controlled delay provider (`src/providers/controlled_delay.py`) reads:

| Variable | Default | Description |
|----------|---------|-------------|
| `BENCH_CALL_DELAY_MS` | 100 | Per-call sleep in ms |
| `BENCH_STARTUP_DELAY_MS` | 0 | Startup sleep before serving |
| `BENCH_NUM_TOOLS` | 5 | Number of tools to expose |
| `BENCH_TOOL_PREFIX` | `bench_tool` | Tool naming: `{prefix}_{i}` |
| `BENCH_PAYLOAD_SIZE` | 256 | Response payload bytes |

## Known Gotchas

- **Hangar global singletons**: Creating multiple `Hangar` instances in one process requires `_reset_hangar_globals()` between them. If you see "already initialized" errors, the reset function needs updating for new Hangar internals.
- **`uv run` auto-syncs**: Without `--no-sync`, every `uv run` call syncs the environment and may overwrite a local mcp-hangar install. Always use `SKIP_HANGAR=1` when working with a local build.
- **`uv sync` removes foreign packages**: Even `--no-install-package` won't prevent uninstallation of packages not in the lockfile. The `--inexact` flag is required to keep locally installed packages.
- **S6 custom run()**: Don't assume all scenarios use `BaseScenario.run()`. S6 overrides it completely for step-dependency handling.
- **Result deduplication**: `results_to_dataframe()` deduplicates by `(scenario, baseline, num_calls, delay_ms)` keeping last. If you re-run a scenario, old results in the same directory are effectively shadowed (not deleted, just ignored in analysis).
- **Overhead summary**: The executive summary overhead line uses percentage from `compute_overhead()`, not its own calculation. This was a past bug — never reintroduce independent overhead computation in the summary.