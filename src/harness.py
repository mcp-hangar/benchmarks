"""Core benchmark harness with timing, statistics, warmup, and JSON output."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Coroutine

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskID

from src.utils.environment import capture_environment
from src.utils.timing import BatchTimingRecord, now_ns, ns_to_ms

console = Console()


@dataclass
class ToolCall:
    """Represents a single MCP tool call to be made."""

    provider: str
    tool: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class CallResult:
    """Result from a single tool call."""

    tool: str
    provider: str
    success: bool
    elapsed_ns: int
    response: Any = None
    error: str | None = None


@dataclass
class RunResult:
    """Result from a single benchmark run (one execution of all calls)."""

    run_number: int
    wall_clock_ns: int
    call_results: list[CallResult] = field(default_factory=list)
    timestamp: str = ""
    error: str | None = None

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


@dataclass
class BenchmarkConfig:
    """Configuration for a benchmark execution."""

    runs: int = 30
    warmup_runs: int = 5
    outlier_threshold_sigma: float = 3.0


# Type alias for benchmark functions
BenchmarkFn = Callable[[list[ToolCall]], Coroutine[Any, Any, BatchTimingRecord]]


def compute_statistics(values: list[float], outlier_sigma: float = 3.0) -> dict[str, Any]:
    """Compute statistical summary for a list of measurements.

    Returns stats with and without outliers.
    """
    import numpy as np
    from scipy import stats as scipy_stats

    if not values:
        return {}

    arr = np.array(values)
    n = len(arr)
    mean = float(np.mean(arr))
    std = float(np.std(arr, ddof=1)) if n > 1 else 0.0

    # Identify outliers
    if std > 0:
        outlier_mask = np.abs(arr - mean) > outlier_sigma * std
    else:
        outlier_mask = np.zeros(n, dtype=bool)
    outlier_count = int(np.sum(outlier_mask))

    # Stats with all data
    sorted_arr = np.sort(arr)
    full_stats = _compute_stats_for_array(arr, sorted_arr, n)

    # Stats without outliers
    clean_arr = arr[~outlier_mask]
    if len(clean_arr) > 0:
        clean_sorted = np.sort(clean_arr)
        clean_stats = _compute_stats_for_array(
            clean_arr, clean_sorted, len(clean_arr)
        )
    else:
        clean_stats = full_stats

    return {
        **full_stats,
        "outliers_count": outlier_count,
        "n": n,
        "without_outliers": {
            **clean_stats,
            "n": n - outlier_count,
        },
    }


def _compute_stats_for_array(
    arr: Any, sorted_arr: Any, n: int
) -> dict[str, float]:
    """Compute core stats for a numpy array."""
    import numpy as np
    from scipy import stats as scipy_stats

    mean = float(np.mean(arr))
    std = float(np.std(arr, ddof=1)) if n > 1 else 0.0

    # Confidence interval using t-distribution
    if n > 1 and std > 0:
        ci = scipy_stats.t.interval(0.95, df=n - 1, loc=mean, scale=std / np.sqrt(n))
        ci_lower, ci_upper = float(ci[0]), float(ci[1])
    else:
        ci_lower, ci_upper = mean, mean

    return {
        "mean": round(mean, 3),
        "median": round(float(np.median(arr)), 3),
        "p50": round(float(np.percentile(sorted_arr, 50)), 3),
        "p95": round(float(np.percentile(sorted_arr, 95)), 3),
        "p99": round(float(np.percentile(sorted_arr, 99)), 3),
        "stddev": round(std, 3),
        "ci_95_lower": round(ci_lower, 3),
        "ci_95_upper": round(ci_upper, 3),
        "min": round(float(np.min(arr)), 3),
        "max": round(float(np.max(arr)), 3),
    }


async def run_benchmark(
    name: str,
    scenario: str,
    baseline: str,
    calls: list[ToolCall],
    benchmark_fn: BenchmarkFn,
    config: BenchmarkConfig,
    parameters: dict[str, Any] | None = None,
    output_dir: str = "results/raw",
) -> dict[str, Any]:
    """Execute a complete benchmark: warmup, measurement runs, statistics, save.

    Args:
        name: Human-readable benchmark name
        scenario: Scenario identifier (e.g., "s2_fanout")
        baseline: Baseline identifier (e.g., "hangar_parallel")
        calls: List of tool calls to execute in each run
        benchmark_fn: Async function that executes the calls and returns timing
        config: Benchmark configuration
        parameters: Scenario-specific parameters to record
        output_dir: Directory for JSON output

    Returns:
        Complete benchmark result dict with measurements and statistics.
    """
    console.print(f"\n[bold cyan]{'='*60}[/]")
    console.print(f"[bold]{name}[/] — {scenario}/{baseline}")
    console.print(f"  Calls: {len(calls)}, Runs: {config.runs}, Warmup: {config.warmup_runs}")
    console.print(f"[bold cyan]{'='*60}[/]")

    # Warmup phase
    console.print("[dim]Warming up...[/]")
    warmup_errors = 0
    for i in range(config.warmup_runs):
        try:
            await benchmark_fn(calls)
        except Exception as e:
            warmup_errors += 1
            console.print(f"  [yellow]Warmup {i+1} error: {e}[/]")

    if warmup_errors == config.warmup_runs:
        raise RuntimeError(
            f"All {config.warmup_runs} warmup runs failed. Aborting benchmark."
        )

    # Measurement phase
    measurements: list[dict[str, Any]] = []
    errors = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        console=console,
    ) as progress:
        task_id: TaskID = progress.add_task("Measuring", total=config.runs)

        for run_num in range(1, config.runs + 1):
            try:
                timing = await benchmark_fn(calls)
                measurements.append(
                    {
                        "run": run_num,
                        "wall_clock_ns": timing.wall_clock_ns,
                        "per_call_latencies_ns": timing.per_call_latencies_ns,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                )
            except Exception as e:
                errors += 1
                measurements.append(
                    {
                        "run": run_num,
                        "wall_clock_ns": -1,
                        "per_call_latencies_ns": [],
                        "error": str(e),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                )
                console.print(f"  [red]Run {run_num} error: {e}[/]")

            progress.advance(task_id)

    # Filter successful runs for statistics
    successful = [m for m in measurements if m["wall_clock_ns"] > 0]
    if not successful:
        raise RuntimeError("All benchmark runs failed. No data to analyze.")

    wall_clock_ms_values = [ns_to_ms(m["wall_clock_ns"]) for m in successful]

    # Per-call statistics: flatten all per-call latencies
    all_per_call_ns = []
    for m in successful:
        all_per_call_ns.extend(m["per_call_latencies_ns"])
    per_call_ms_values = [ns_to_ms(ns) for ns in all_per_call_ns]

    wall_clock_stats = compute_statistics(
        wall_clock_ms_values, config.outlier_threshold_sigma
    )
    per_call_stats = (
        compute_statistics(per_call_ms_values, config.outlier_threshold_sigma)
        if per_call_ms_values
        else {}
    )

    # Build result
    result: dict[str, Any] = {
        "benchmark_id": str(uuid.uuid4()),
        "scenario": scenario,
        "baseline": baseline,
        "name": name,
        "parameters": parameters or {},
        "environment": capture_environment(),
        "config": {
            "runs": config.runs,
            "warmup_runs": config.warmup_runs,
            "outlier_threshold_sigma": config.outlier_threshold_sigma,
        },
        "measurements": measurements,
        "statistics": {
            "wall_clock_ms": wall_clock_stats,
            "per_call_ms": per_call_stats,
        },
        "errors": {
            "total": errors,
            "rate": round(errors / config.runs, 4) if config.runs > 0 else 0,
        },
    }

    # Print summary
    if wall_clock_stats:
        console.print(
            f"\n  [green]Wall clock:[/] "
            f"mean={wall_clock_stats['mean']:.1f}ms, "
            f"median={wall_clock_stats['median']:.1f}ms, "
            f"p95={wall_clock_stats['p95']:.1f}ms, "
            f"stddev={wall_clock_stats['stddev']:.1f}ms"
        )
        console.print(
            f"  [green]95% CI:[/] "
            f"[{wall_clock_stats['ci_95_lower']:.1f}, "
            f"{wall_clock_stats['ci_95_upper']:.1f}]ms"
        )
    if errors > 0:
        console.print(f"  [red]Errors: {errors}/{config.runs}[/]")

    # Save to file
    os.makedirs(output_dir, exist_ok=True)
    filename = f"{scenario}_{baseline}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    filepath = os.path.join(output_dir, filename)
    with open(filepath, "w") as f:
        json.dump(result, f, indent=2)
    console.print(f"  [dim]Saved: {filepath}[/]")

    return result
