"""Statistical analysis for benchmark results.

Aggregates raw JSON results, computes comparative statistics,
and generates summary tables.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from rich.console import Console
from rich.table import Table

console = Console()


def load_results(results_dir: str = "results/raw") -> list[dict[str, Any]]:
    """Load all JSON result files from a directory."""
    results: list[dict[str, Any]] = []
    path = Path(results_dir)
    if not path.exists():
        return results

    for f in sorted(path.glob("*.json")):
        with open(f) as fh:
            data = json.load(fh)
            data["_source_file"] = str(f)
            results.append(data)
    return results


def results_to_dataframe(results: list[dict[str, Any]]) -> pd.DataFrame:
    """Convert result list to a pandas DataFrame for analysis.

    When multiple results exist for the same scenario/baseline/num_calls,
    keeps only the latest one (by source file timestamp in name).
    """
    rows = []
    for r in results:
        stats = r.get("statistics", {}).get("wall_clock_ms", {})
        params = r.get("parameters", {})
        row = {
            "scenario": r.get("scenario", ""),
            "baseline": r.get("baseline", ""),
            "name": r.get("name", ""),
            "num_calls": params.get("num_calls", params.get("num_concurrent_calls", 0)),
            "mean_ms": stats.get("mean", 0),
            "median_ms": stats.get("median", 0),
            "p50_ms": stats.get("p50", 0),
            "p95_ms": stats.get("p95", 0),
            "p99_ms": stats.get("p99", 0),
            "stddev_ms": stats.get("stddev", 0),
            "ci_lower": stats.get("ci_95_lower", 0),
            "ci_upper": stats.get("ci_95_upper", 0),
            "min_ms": stats.get("min", 0),
            "max_ms": stats.get("max", 0),
            "outliers": stats.get("outliers_count", 0),
            "n": stats.get("n", 0),
            "errors": r.get("errors", {}).get("total", 0),
            "error_rate": r.get("errors", {}).get("rate", 0),
            "source_file": r.get("_source_file", ""),
        }
        rows.append(row)

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    # Deduplicate: keep last (most recent) result per unique key
    key_cols = ["scenario", "baseline", "num_calls"]
    df = df.drop_duplicates(subset=key_cols, keep="last").reset_index(drop=True)
    return df


def compute_speedups(df: pd.DataFrame) -> pd.DataFrame:
    """Compute speedup ratios relative to sequential baseline.

    For each scenario, divides sequential mean by each baseline's mean.
    """
    speedups = []
    for scenario in df["scenario"].unique():
        scenario_df = df[df["scenario"] == scenario]
        sequential = scenario_df[scenario_df["baseline"] == "sequential"]
        if sequential.empty:
            continue
        seq_mean = sequential.iloc[0]["mean_ms"]

        for _, row in scenario_df.iterrows():
            if row["mean_ms"] > 0:
                speedup = seq_mean / row["mean_ms"]
            else:
                speedup = 0
            speedups.append(
                {
                    "scenario": scenario,
                    "baseline": row["baseline"],
                    "name": row["name"],
                    "sequential_ms": seq_mean,
                    "baseline_ms": row["mean_ms"],
                    "speedup": round(speedup, 2),
                }
            )
    return pd.DataFrame(speedups)


def compute_overhead(df: pd.DataFrame) -> pd.DataFrame:
    """Compute Hangar overhead vs direct calls.

    Compares hangar_sequential vs sequential (same pattern, different path).
    """
    overheads = []
    for scenario in df["scenario"].unique():
        scenario_df = df[df["scenario"] == scenario]
        direct = scenario_df[scenario_df["baseline"] == "sequential"]
        hangar = scenario_df[scenario_df["baseline"] == "hangar_sequential"]

        if direct.empty or hangar.empty:
            continue

        direct_mean = direct.iloc[0]["mean_ms"]
        hangar_mean = hangar.iloc[0]["mean_ms"]
        overhead = hangar_mean - direct_mean
        overhead_pct = (overhead / direct_mean * 100) if direct_mean > 0 else 0

        overheads.append(
            {
                "scenario": scenario,
                "direct_ms": round(direct_mean, 2),
                "hangar_ms": round(hangar_mean, 2),
                "overhead_ms": round(overhead, 2),
                "overhead_pct": round(overhead_pct, 2),
            }
        )
    return pd.DataFrame(overheads)


def print_summary_table(df: pd.DataFrame) -> None:
    """Print a rich summary table of all results."""
    table = Table(title="Benchmark Results Summary")
    table.add_column("Scenario", style="cyan")
    table.add_column("Baseline", style="green")
    table.add_column("Mean (ms)", justify="right")
    table.add_column("Median (ms)", justify="right")
    table.add_column("P95 (ms)", justify="right")
    table.add_column("StdDev", justify="right")
    table.add_column("95% CI", justify="right")
    table.add_column("N", justify="right")
    table.add_column("Errors", justify="right")

    for _, row in df.iterrows():
        ci_str = f"[{row['ci_lower']:.1f}, {row['ci_upper']:.1f}]"
        err_style = "red" if row["errors"] > 0 else "dim"
        table.add_row(
            row["scenario"],
            row["baseline"],
            f"{row['mean_ms']:.1f}",
            f"{row['median_ms']:.1f}",
            f"{row['p95_ms']:.1f}",
            f"{row['stddev_ms']:.1f}",
            ci_str,
            str(row["n"]),
            f"[{err_style}]{row['errors']}[/]",
        )

    console.print(table)


def print_speedup_table(speedups: pd.DataFrame) -> None:
    """Print speedup comparison table."""
    table = Table(title="Speedup vs Sequential")
    table.add_column("Scenario", style="cyan")
    table.add_column("Baseline", style="green")
    table.add_column("Sequential (ms)", justify="right")
    table.add_column("Actual (ms)", justify="right")
    table.add_column("Speedup", justify="right", style="bold")

    for _, row in speedups.iterrows():
        speedup_style = "green" if row["speedup"] > 1.5 else "yellow"
        table.add_row(
            row["scenario"],
            row["baseline"],
            f"{row['sequential_ms']:.1f}",
            f"{row['baseline_ms']:.1f}",
            f"[{speedup_style}]{row['speedup']:.1f}x[/]",
        )

    console.print(table)


def print_overhead_table(overheads: pd.DataFrame) -> None:
    """Print Hangar overhead analysis table."""
    table = Table(title="Hangar Framework Overhead")
    table.add_column("Scenario", style="cyan")
    table.add_column("Direct (ms)", justify="right")
    table.add_column("Hangar (ms)", justify="right")
    table.add_column("Overhead (ms)", justify="right")
    table.add_column("Overhead %", justify="right")

    for _, row in overheads.iterrows():
        oh_style = "green" if abs(row["overhead_pct"]) < 10 else "yellow"
        table.add_row(
            row["scenario"],
            f"{row['direct_ms']:.1f}",
            f"{row['hangar_ms']:.1f}",
            f"[{oh_style}]{row['overhead_ms']:.1f}[/]",
            f"[{oh_style}]{row['overhead_pct']:.1f}%[/]",
        )

    console.print(table)


def generate_report(results_dir: str = "results/raw") -> None:
    """Generate and print a full statistical report from raw results."""
    results = load_results(results_dir)
    if not results:
        console.print("[red]No results found.[/]")
        return

    df = results_to_dataframe(results)

    console.print(f"\n[bold]Loaded {len(results)} result files[/]\n")

    print_summary_table(df)

    speedups = compute_speedups(df)
    if not speedups.empty:
        console.print()
        print_speedup_table(speedups)

    overheads = compute_overhead(df)
    if not overheads.empty:
        console.print()
        print_overhead_table(overheads)
