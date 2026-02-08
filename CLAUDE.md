# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MCP Hangar Benchmarks is a publication-quality benchmark suite measuring MCP tool call performance, comparing sequential vs parallel execution through mcp-hangar. It answers: "How much faster is parallel MCP tool execution compared to sequential?"

## Commands

```bash
# Install dependencies
make setup

# Install dependencies but keep locally installed mcp-hangar (e.g. from main branch)
make setup SKIP_HANGAR=1

# Run benchmarks
make smoke-test           # Quick test (5 runs per scenario)
make benchmark            # Standard (30 runs + charts)
make full-benchmark       # Publication (100 runs + charts)

# Run specific scenario
python -m src.runner run --scenario s2 --runs 50

# Run with specific baselines
python -m src.runner run --scenario s3 --baselines sequential,hangar_parallel

# Generate charts/reports from existing results
python -m src.runner charts
python -m src.runner report

# Clean results
make clean
```

## Architecture

### Execution Flow

1. `src/runner.py` (CLI via Click) → loads scenarios
2. `src/scenarios/base.py` (`BaseScenario`) → orchestrates setup/teardown
3. `src/harness.py` (`run_benchmark`) → executes warmup + measurement runs, computes statistics, saves JSON
4. `src/baselines/` → 4 execution strategies (sequential, direct_parallel, hangar_sequential, hangar_parallel)
5. `src/analysis/` → generates statistics and charts from results

### Key Components

**BaseScenario** (`src/scenarios/base.py`): Abstract class all scenarios inherit. Handles:
- Direct MCP client setup via `setup_direct_client()`
- Hangar instance setup via `setup_hangar()` with global singleton reset (`_reset_hangar_globals()`)
- Running each baseline through the harness

**Harness** (`src/harness.py`): Core benchmark engine. Executes warmup runs, measurement runs with nanosecond-precision timing, computes statistics (mean, median, percentiles, 95% CI), and saves JSON results.

**Controlled Delay Provider** (`src/providers/controlled_delay.py`): Custom MCP server with configurable latency via `asyncio.sleep()`. Ensures reproducible results. Configured via env vars: `BENCH_CALL_DELAY_MS`, `BENCH_STARTUP_DELAY_MS`, `BENCH_NUM_TOOLS`, `BENCH_TOOL_PREFIX`, `BENCH_PAYLOAD_SIZE`.

### Four Baselines

| Baseline | Description |
|----------|-------------|
| `sequential` | Direct MCP calls, one at a time |
| `direct_parallel` | Direct MCP via `asyncio.gather()` |
| `hangar_sequential` | Through Hangar, one at a time |
| `hangar_parallel` | Through Hangar with `asyncio.gather()` |

### Six Scenarios (S1-S6)

Each scenario isolates a specific performance question:
- **S1**: Per-call overhead (Hangar vs direct)
- **S2**: Parallel scaling on single provider (1-20 tools)
- **S3**: Cross-provider parallelism (5 providers)
- **S4**: Cold start deduplication
- **S5**: Head-of-line blocking (convoy effect)
- **S6**: Realistic 3-step agent workflow pipeline

### Adding a New Scenario

1. Create `src/scenarios/s7_yourname.py`
2. Subclass `BaseScenario` and implement:
   - `name`, `scenario_id` properties
   - `get_provider_configs()` → list of provider dicts
   - `get_calls()` → list of `ToolCall` objects
   - `get_parameters()` → optional scenario metadata
3. Create `create_scenarios()` factory function
4. Register in `src/runner.py` `SCENARIO_MAP`
5. Add Hangar config in `configs/` if needed

### Output

- **JSON results**: `results/raw/{scenario}_{baseline}_{timestamp}.json`
- **Charts**: `results/charts/*.{png,svg}`

Results include raw measurements, statistical summaries, and environment metadata for reproducibility.
