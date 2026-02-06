# Benchmark Methodology

This document describes the measurement methodology, statistical approach, and fairness controls used in the MCP Hangar benchmark suite.

## Timing

All timing measurements use `time.perf_counter_ns()`:
- Monotonic clock (not affected by system clock adjustments)
- Nanosecond resolution
- Best available precision on each platform

For each benchmark run, we record:
- **Batch start/end timestamps** — wall-clock time for the entire operation
- **Per-call start/end timestamps** — individual tool call latency
- **ISO 8601 timestamp** — for correlation and ordering

## Statistical Approach

### Sample Size

- **Minimum 30 runs** per scenario per baseline (Central Limit Theorem)
- **5 warmup runs** discarded before measurement begins
- Publication runs use 100+ runs for tighter confidence intervals

### Reported Statistics

For each measurement, we compute and report:

| Statistic | Description |
|-----------|-------------|
| Mean | Arithmetic mean |
| Median | 50th percentile |
| P50, P95, P99 | Percentile values |
| Standard Deviation | Sample standard deviation (Bessel's correction, ddof=1) |
| 95% Confidence Interval | Via Student's t-distribution |
| Min, Max | Extremes |
| Outlier Count | Values > 3 sigma from mean |
| N | Total successful runs |

### Confidence Intervals

95% confidence intervals are computed using the Student's t-distribution:

```
CI = mean +/- t(0.975, n-1) * (stddev / sqrt(n))
```

This is appropriate for small sample sizes and when the population standard deviation is unknown.

### Outlier Handling

- An outlier is defined as any measurement more than 3 standard deviations from the mean
- Statistics are reported **both with and without outliers**
- Outliers are never silently discarded
- The raw data (every individual measurement) is saved for independent verification

## Warmup

Before measurement begins, each baseline executes a configurable number of warmup runs (default: 5). This accounts for:

- Python JIT warmup (if using PyPy)
- Connection establishment and TCP socket warmup
- Operating system I/O cache population
- MCP protocol handshake completion
- Any first-run initialization in Hangar

Warmup applies equally to all baselines in a scenario.

## Controlled Delay Provider

To ensure reproducible results independent of network conditions, all scenarios use a custom MCP server with configurable latency:

- **Deterministic delays**: Each tool call sleeps for a precisely configured duration using `asyncio.sleep()`
- **Self-measurement**: The provider measures actual vs configured delay, reporting any scheduling overhead
- **Configurable**: Delay, number of tools, payload size, and startup time are all parameterized
- **Lightweight**: Minimal implementation to avoid introducing its own overhead

The provider reports `scheduling_overhead_ms` in every response, allowing us to separate provider latency from framework latency.

## Fairness Controls

### Same Conditions

1. All baselines in a scenario run on the **same machine** in the **same process**
2. Provider configurations are **identical** across baselines — same delay, same tools
3. Warmup applies to **all baselines equally**
4. The same set of tool calls is used for every baseline

### Environment Capture

Every result file includes complete environment metadata:
- Operating system and kernel version
- CPU model and core count
- Python version and implementation
- Package versions (mcp-hangar, mcp)
- Asyncio event loop implementation
- Git commit hash
- UTC timestamp

### No Cherry-Picking

- If a baseline shows unexpected results, they are reported as-is
- Error counts and error rates are included in every result
- Failed runs are recorded (with error details) alongside successful ones
- Statistics are computed on all data, with separate clean-data stats for reference

## Scenario Design

### S1: Baseline (Per-Call Overhead)

Isolates the overhead introduced by Hangar's proxy layer. A single provider, single tool, serial calls. The difference between direct and Hangar-proxied calls reveals the framework cost per invocation.

### S2: Fan-out (Parallel Scaling)

Tests parallel speedup on a single provider. With N calls at 100ms each:
- Sequential: expected N * 100ms (linear)
- Parallel: expected ~100ms (constant)

This demonstrates Amdahl's Law applied to MCP tool calls.

### S3: Multi-Provider (Cross-Provider Parallelism)

The realistic case: tools across different providers with different latencies. Sequential execution = sum(latencies). Parallel execution = max(latencies).

### S4: Cold Start (Deduplication)

Tests Hangar's single-flight optimization. When N concurrent calls hit a cold provider, only one startup should occur. Without dedup, each call triggers its own startup.

### S5: Mixed Latency (Head-of-Line Blocking)

Demonstrates the "convoy effect" where sequential execution is bottlenecked by the slowest call, even when most calls are fast.

### S6: Agent Workflow (Realistic Pipeline)

Models a real agent workflow with dependent steps:
1. Parallel fetch (3 calls)
2. Parallel search (3 calls, depends on step 1)
3. Sequential write (1 call, depends on step 2)

This is the most representative benchmark of actual agent usage patterns.

## Limitations

- **Controlled delays vs real I/O**: Using `asyncio.sleep()` eliminates network variance but doesn't capture real I/O patterns (TCP retransmits, DNS resolution, TLS handshakes)
- **Single machine**: All benchmarks run on one machine. Real deployments involve network hops between providers
- **Python GIL**: Thread-based parallelism in Hangar is subject to GIL contention for CPU-bound operations (tool calls are I/O-bound, so this is minimal)
- **Subprocess overhead**: Each provider runs as a subprocess. Real deployments may use remote or container providers with different overhead characteristics
- **No resource contention**: Benchmark providers don't compete for shared resources (database connections, API rate limits) as real providers might

## Reproducibility

To reproduce these results:

```bash
git clone https://github.com/mcp-hangar/benchmarks.git
cd benchmarks
make setup
make benchmark
```

Expected variance:
- Absolute values will differ by machine (CPU speed, scheduler, load)
- Relative speedups (parallel/sequential ratio) should be consistent within ~10%
- CI width depends on system stability during the run

For most reliable results:
- Close other applications during benchmarking
- Disable CPU frequency scaling if possible
- Run on a machine with minimal background load
- Use `make full-benchmark` (100 runs) for publication
