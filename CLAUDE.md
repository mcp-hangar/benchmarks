# CLAUDE.md

## Project Overview

Benchmark suite for [mcp-hangar](https://github.com/mcp-hangar/mcp-hangar) — measures MCP tool call performance comparing sequential vs parallel execution.

**Core question:** "How much faster is parallel MCP tool execution through Hangar compared to sequential?"

**Answer (N=100, publication run):** Up to **19.6× faster** for fan-out workloads, **18.5×** for cold-start deduplication, with **~0% framework overhead** (-3.2% to +2.2%, within noise floor).

## Commands

```bash
# Setup
make setup                        # Install all dependencies
make setup SKIP_HANGAR=1          # Install deps WITHOUT overwriting locally installed mcp-hangar

# Benchmarks
make smoke-test                   # Quick validation: 5 runs, all scenarios
make benchmark                    # Standard: 30 runs + charts
make full-benchmark               # Publication: 100 runs + charts

# Analysis (from existing results)
make charts                       # Generate PNG/SVG charts
make report                       # Print statistical report to console

# CLI (granular control)
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

When developing against a local mcp-hangar build (e.g., `uv pip install -e ../mcp-hangar/packages/core`), add `SKIP_HANGAR=1` to **all** make commands:

- `make setup SKIP_HANGAR=1` → `uv sync --inexact --no-install-package mcp-hangar` (installs deps, keeps local hangar)
- All other targets → `uv run --no-sync` (skips auto-sync that would overwrite local hangar)

Without the flag, `make setup` installs mcp-hangar from PyPI and `uv run` syncs before each command.

## Architecture

### Execution Flow

```
CLI (src/runner.py)
  → Scenario (src/scenarios/s*.py extends BaseScenario)
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
| `src/runner.py` | CLI entrypoint (Click). Commands: `run`, `charts`, `report`. Routes to scenarios via `SCENARIO_MAP`. |
| `src/harness.py` | Benchmark engine. Warmup + N measurement iterations, `time.perf_counter_ns()`, stats (mean, median, p50/p95/p99, 95% CI via t-distribution, 3σ outlier detection), JSON output. |
| `src/scenarios/base.py` | `BaseScenario` ABC. Manages direct MCP client setup, Hangar setup with singleton reset (`_reset_hangar_globals()`), baseline iteration. |
| `src/providers/controlled_delay.py` | Custom MCP server (JSON-RPC/stdio). Configurable delay, startup latency, tool count. Handles concurrency via `asyncio.create_task`. |
| `src/providers/configs.py` | Factory functions for provider command + env dicts. |
| `src/baselines/` | Four baseline implementations (see below). |
| `src/analysis/stats.py` | Result loading, deduplication, speedup/overhead computation, report generation. |
| `src/analysis/charts.py` | Chart generators: money chart, scaling curve, cold start, latency distribution, overhead, workflow timeline. |
| `src/utils/timing.py` | `TimingRecord`, `BatchTimingRecord` dataclasses, `now_ns()`, `ns_to_ms()`. |
| `src/utils/environment.py` | `capture_environment()` — OS, CPU, Python, package versions, git commit. |

### Four Baselines

| Baseline | Implementation | What It Measures |
|----------|---------------|------------------|
| `sequential` | Direct MCP `call_tool()` in a loop | Sum of latencies (worst case) |
| `direct_parallel` | Direct MCP via `asyncio.gather()` | Best-case parallelism (no framework overhead) |
| `hangar_sequential` | `hangar.invoke()` in a loop | Hangar overhead without parallelism |
| `hangar_parallel` | `hangar.invoke()` via `asyncio.gather()` | Hangar's actual parallel performance |

S6 adds `workflow_parallel` — 3-step pipeline with per-step parallelism.

### Six Scenarios

| ID | What | Parametrization | Baselines |
|----|------|-----------------|-----------|
| **S1** | Per-call overhead | delay ∈ [0, 10, 50, 100, 200]ms, 50 calls | sequential, hangar_sequential |
| **S2** | Parallel fan-out scaling | N ∈ [1, 2, 5, 10, 15, 20] tools, 100ms delay | all four |
| **S3** | Cross-provider parallelism | 5 providers [50,100,200,300,500]ms; 3 providers × 100ms | all four |
| **S4** | Cold start deduplication | N ∈ [1, 5, 10, 20] concurrent, 500ms startup | sequential, hangar_parallel |
| **S5** | Mixed latency / head-of-line | 5×10ms + 3×100ms + 1×500ms | all four |
| **S6** | Agent workflow (3-step pipeline) | fetch(200ms)×3 → search(300ms)×3 → fs(50ms)×1 | sequential, workflow_parallel |

### Output Formats

- **JSON**: `results/raw/{scenario}_{baseline}_{YYYYMMDD_HHMMSS}.json`
- **Charts**: `results/charts/chart{1-6}_*.{png,svg}` (300 DPI PNG + SVG)
- **Console**: Rich tables with color-coded speedups/overhead
- **Markdown**: `results/REPORT.md` via `--format markdown`

## Adding a New Scenario

1. Create `src/scenarios/s7_name.py`, subclass `BaseScenario`
2. Implement: `name`, `scenario_id` (`"s7_name"`), `get_provider_configs()`, `get_calls()`, `get_parameters()`, `get_baselines()`
3. Add `create_scenarios()` factory → returns list of instances (one per parametrization)
4. Register in `src/runner.py` `SCENARIO_MAP`: `"s7": s7_scenarios`
5. For step dependencies (like S6): override `run()` entirely

## Provider Environment Variables

`src/providers/controlled_delay.py` configuration:

| Variable | Default | Description |
|----------|---------|-------------|
| `BENCH_CALL_DELAY_MS` | `100` | Per-call sleep (ms) |
| `BENCH_STARTUP_DELAY_MS` | `0` | Startup sleep before serving (ms) |
| `BENCH_NUM_TOOLS` | `5` | Number of tools to register |
| `BENCH_TOOL_PREFIX` | `bench_tool` | Tool naming: `{prefix}_{i}` |
| `BENCH_PAYLOAD_SIZE` | `256` | Response payload (bytes) |

## Data Flow in Analysis

```
load_results()          → reads all JSON from results/raw/
results_to_dataframe()  → flattens to pandas DataFrame, deduplicates (keeps last by scenario+baseline+params)
compute_speedups()      → comparison DataFrame: hangar vs sequential
compute_overhead()      → comparison DataFrame: hangar vs direct (percentage)
print_executive_summary() → uses compute_overhead() output for summary line
```

## Known Gotchas

**Hangar global singletons.** Creating multiple `Hangar` instances in one process requires `_reset_hangar_globals()` between them. "Already initialized" errors mean the reset function needs updating for new Hangar internals.

**`uv run` auto-syncs.** Without `--no-sync`, every `uv run` syncs the environment and may overwrite a local mcp-hangar install. Always use `SKIP_HANGAR=1` with local builds.

**`uv sync` removes foreign packages.** Even `--no-install-package` won't prevent uninstallation of packages not in the lockfile. The `--inexact` flag is required to preserve locally installed packages.

**S6 custom `run()`.** Don't assume all scenarios use `BaseScenario.run()`. S6 overrides it completely for step-dependency handling.

**Result deduplication.** `results_to_dataframe()` deduplicates by `(scenario, baseline, num_calls, delay_ms)` keeping last. Re-running a scenario shadows (not deletes) old results.

**Overhead summary consistency.** The executive summary overhead line uses percentage from `compute_overhead()` — the same function that powers the detailed overhead table. Never reintroduce independent overhead computation in the summary; this was a past bug.
