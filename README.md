# MCP Hangar Benchmarks

Publication-quality benchmark suite measuring MCP tool call performance: sequential vs parallel execution through [mcp-hangar](https://github.com/mcp-hangar/mcp-hangar).

## What This Measures

This benchmark suite answers one question: **How much faster is parallel MCP tool execution compared to sequential?**

It compares four execution strategies:
1. **Sequential** — Direct MCP calls, one at a time (baseline)
2. **Direct Parallel** — `asyncio.gather` with direct MCP clients
3. **Hangar Sequential** — Through Hangar, but one at a time (overhead measurement)
4. **Hangar Parallel** — Concurrent execution through Hangar

## Scenarios

| ID | Name | What It Tests |
|----|------|---------------|
| S1 | Baseline | Per-call overhead: Hangar vs direct |
| S2 | Fan-out | Parallel speedup: N tools on 1 provider |
| S3 | Multi-Provider | Parallel calls across 5 providers |
| S4 | Cold Start | Single-flight cold start deduplication |
| S5 | Mixed Latency | Head-of-line blocking with fast/slow mix |
| S6 | Agent Workflow | Realistic 3-step pipeline with dependencies |
| S7 | Task In-Flight Ceiling | How many concurrent governed task follow-ups one process holds |

### S7 — Task In-Flight Ceiling

S1–S6 answer "how fast". S7 answers "how many at once", for the ADR-014 governed
task relay, and it is the one scenario that reports a **limit** rather than a
speedup.

The relay dispatches every follow-up — ledger reads *and* the blocking upstream
forward — through `asyncio.to_thread`. Nothing in `mcp_hangar` ever calls
`loop.set_default_executor(...)`, so those land on CPython's stock pool, sized
`min(32, os.cpu_count() + 4)`. Concurrency is therefore capped by a **CPU-derived
thread count while the thing being waited on is network latency**.

Measured, not extrapolated — the sweep was re-run at three forced pool widths:

| Pool workers | Pod size | Sustained in-flight | Throughput ceiling |
|---|---|---|---|
| 6 | 2 vCPU | **6** | ~111 ops/s |
| 8 | 4 vCPU | **8** | ~146 ops/s |
| 22 | 18-core host | **16** (nearest level below 22) | ~372 ops/s |

The knee lands exactly on the worker count. Past it nothing fails — work queues,
and p99 grows one upstream round-trip per extra wave:

```
p99(N) ~= ceil(N / workers) * upstream_latency
```

Governance is not the bottleneck: `--mode relay` (real `GovernedTaskStore`,
ownership check, digest guard, event publish) lands within ~2% of `--mode pool`
(a bare `to_thread` sleep). The ledger work is microseconds; the pool is the
whole story.

```bash
# Isolate the mechanism (no Hangar needed)
uv run python -m src.runner task-ceiling --mode pool

# Drive a real GovernedTaskStore (needs a 2.x core installed)
uv run python -m src.runner task-ceiling --mode relay

# Measure a 2 vCPU pod from any host
uv run python -m src.runner task-ceiling --mode relay --workers 6
```

`--mode relay` requires the governed relay, which ships only on the 2.x line;
against a 1.x install it fails with an explicit message rather than a stack trace.

## Quick Start

```bash
# Install dependencies
make setup

# Quick smoke test (5 runs per scenario)
make smoke-test

# Standard benchmark (30 runs per scenario + charts)
make benchmark

# Full publication run (100 runs + charts)
make full-benchmark
```

### Development with local mcp-hangar

If you're working against a local (e.g. from-main) build of `mcp-hangar`, use `SKIP_HANGAR=1` to prevent overwriting it with the PyPI version:

```bash
# Install hangar from local checkout
uv pip install -e ../mcp-hangar/packages/core

# Install remaining dependencies without touching mcp-hangar
make setup SKIP_HANGAR=1

# Run benchmarks (also respects SKIP_HANGAR to skip uv sync)
make smoke-test SKIP_HANGAR=1
make benchmark SKIP_HANGAR=1
```

## Requirements

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) package manager
- ~2GB RAM for running benchmark providers

## CLI Usage

```bash
# Run specific scenario
python -m src.runner run --scenario s2 --runs 50

# Run with specific baselines
python -m src.runner run --scenario s3 --baselines sequential,hangar_parallel

# Generate charts from existing results
python -m src.runner charts

# Print statistical report
python -m src.runner report
```

## Output

Results are saved to `results/raw/` as JSON files containing:
- Raw measurements (every individual run with nanosecond timestamps)
- Statistical summaries (mean, median, P50/P95/P99, stddev, 95% CI)
- Environment metadata (OS, CPU, Python version, package versions)
- Scenario parameters and configuration

Charts are generated in `results/charts/` as PNG (web) and SVG (print).

## Methodology

See [METHODOLOGY.md](METHODOLOGY.md) for the full methodology:

- Minimum 30 runs per measurement (configurable up to 100+)
- 5 warmup runs discarded before measurement begins
- `time.perf_counter_ns()` for nanosecond-resolution timing
- 95% confidence intervals via t-distribution
- Outlier detection at 3 sigma (reported with and without)
- Same machine, same conditions for all baselines
- No cherry-picking — all results reported including errors

## Project Structure

```
benchmarks/
├── src/
│   ├── harness.py               # Core benchmark engine
│   ├── runner.py                # CLI entrypoint
│   ├── scenarios/               # S1-S6 benchmark scenarios
│   ├── providers/               # Controlled-delay MCP server
│   ├── baselines/               # 4 execution strategies
│   ├── analysis/                # Statistics + chart generation
│   └── utils/                   # Timing + environment capture
├── results/
│   ├── raw/                     # JSON data per run
│   └── charts/                  # Generated PNG/SVG charts
├── configs/                     # Hangar YAML configs per scenario
├── Makefile                     # One-command orchestration
├── METHODOLOGY.md               # Detailed methodology
└── pyproject.toml               # Python project config
```

## Controlled Delay Provider

The benchmarks use a custom MCP server (`src/providers/controlled_delay.py`) with configurable latency. This ensures reproducible results independent of network conditions. Each tool:

1. Sleeps for a configured duration (simulating real work)
2. Returns structured data with actual vs expected timing
3. Tracks scheduling overhead for measurement accuracy

Environment variables: `BENCH_CALL_DELAY_MS`, `BENCH_STARTUP_DELAY_MS`, `BENCH_NUM_TOOLS`, `BENCH_TOOL_PREFIX`, `BENCH_PAYLOAD_SIZE`.

## Reproducing Results

```bash
git clone https://github.com/mcp-hangar/benchmarks.git
cd benchmarks
make setup
make benchmark
```

Results will vary by machine. The relative speedups (parallel vs sequential) should be consistent across hardware.

## License

MIT
