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


def _get_num_calls(params: dict[str, Any]) -> int:
    """Extract num_calls from parameters, handling different naming conventions."""
    return params.get("num_calls", params.get("num_concurrent_calls", 0))


def _get_param_label(row: pd.Series) -> str:
    """Generate a human-readable parameter label for a result row."""
    scenario = row["scenario"]
    num_calls = row["num_calls"]
    delay_ms = row.get("delay_ms", 0)

    if scenario == "s1_baseline":
        return f"{delay_ms}ms"
    elif scenario in ("s2_fanout", "s4_cold_start"):
        return f"N={num_calls}"
    elif scenario == "s3_multi_provider":
        num_providers = row.get("num_providers", 0)
        return f"{num_providers}p" if num_providers else ""
    else:
        return ""


def results_to_dataframe(results: list[dict[str, Any]]) -> pd.DataFrame:
    """Convert result list to a pandas DataFrame for analysis.

    When multiple results exist for the same scenario/baseline/num_calls,
    keeps only the latest one (by source file timestamp in name).
    """
    rows = []
    for r in results:
        stats = r.get("statistics", {}).get("wall_clock_ms", {})
        per_call_stats = r.get("statistics", {}).get("per_call_ms", {})
        params = r.get("parameters", {})
        row = {
            "scenario": r.get("scenario", ""),
            "baseline": r.get("baseline", ""),
            "name": r.get("name", ""),
            "num_calls": _get_num_calls(params),
            "delay_ms": params.get("delay_ms", params.get("provider_delay_ms", 0)),
            "num_providers": params.get("num_providers", 0),
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
            "per_call_mean_ms": per_call_stats.get("mean", 0),
            "errors": r.get("errors", {}).get("total", 0),
            "error_rate": r.get("errors", {}).get("rate", 0),
            "source_file": r.get("_source_file", ""),
        }
        rows.append(row)

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    # Deduplicate: keep last (most recent) result per unique key
    key_cols = ["scenario", "baseline", "num_calls", "delay_ms"]
    df = df.drop_duplicates(subset=key_cols, keep="last").reset_index(drop=True)

    # Sort logically: scenario -> num_calls/delay -> baseline
    df = df.sort_values(
        by=["scenario", "num_calls", "delay_ms", "baseline"],
        ascending=[True, True, True, True]
    ).reset_index(drop=True)

    return df


def compute_speedups(df: pd.DataFrame) -> pd.DataFrame:
    """Compute speedup ratios relative to sequential baseline.

    Groups by (scenario, num_calls) so that each N-value is compared
    against its own sequential baseline.
    """
    speedups = []

    # Group by scenario AND num_calls to compare apples to apples
    group_cols = ["scenario", "num_calls", "delay_ms"]
    for group_key, group_df in df.groupby(group_cols, dropna=False):
        scenario, num_calls, delay_ms = group_key

        # Find sequential baseline for this specific group
        sequential = group_df[group_df["baseline"] == "sequential"]
        if sequential.empty:
            continue
        seq_mean = sequential.iloc[0]["mean_ms"]

        for _, row in group_df.iterrows():
            if row["mean_ms"] > 0:
                speedup = seq_mean / row["mean_ms"]
            else:
                speedup = 0

            # Build param label
            if scenario == "s1_baseline":
                param_label = f"{int(delay_ms)}ms"
            elif scenario in ("s2_fanout", "s4_cold_start"):
                param_label = f"N={int(num_calls)}"
            else:
                param_label = ""

            speedups.append({
                "scenario": scenario,
                "params": param_label,
                "baseline": row["baseline"],
                "sequential_ms": round(seq_mean, 1),
                "baseline_ms": round(row["mean_ms"], 1),
                "speedup": round(speedup, 2),
            })

    result = pd.DataFrame(speedups)
    if not result.empty:
        result = result.sort_values(
            by=["scenario", "params", "baseline"]
        ).reset_index(drop=True)
    return result


def compute_overhead(df: pd.DataFrame) -> pd.DataFrame:
    """Compute Hangar overhead vs direct calls.

    Compares:
    - Sequential: hangar_sequential vs sequential (direct)
    - Parallel: hangar_parallel vs direct_parallel

    Groups by (scenario, num_calls) to compare matching configurations.
    """
    overheads = []

    group_cols = ["scenario", "num_calls", "delay_ms"]
    for group_key, group_df in df.groupby(group_cols, dropna=False):
        scenario, num_calls, delay_ms = group_key

        # Build param label
        if scenario == "s1_baseline":
            param_label = f"{int(delay_ms)}ms"
        elif scenario in ("s2_fanout", "s4_cold_start"):
            param_label = f"N={int(num_calls)}"
        else:
            param_label = ""

        # Sequential overhead
        direct_seq = group_df[group_df["baseline"] == "sequential"]
        hangar_seq = group_df[group_df["baseline"] == "hangar_sequential"]

        if not direct_seq.empty and not hangar_seq.empty:
            direct_mean = direct_seq.iloc[0]["mean_ms"]
            hangar_mean = hangar_seq.iloc[0]["mean_ms"]
            overhead = hangar_mean - direct_mean
            overhead_pct = (overhead / direct_mean * 100) if direct_mean > 0 else 0

            # For S1, compute per-call overhead
            if scenario == "s1_baseline" and num_calls > 0:
                per_call_overhead = overhead / num_calls
                overhead_note = f"({per_call_overhead:.2f}ms/call)"
            else:
                overhead_note = ""

            overheads.append({
                "scenario": scenario,
                "params": param_label,
                "mode": "Sequential",
                "direct_ms": round(direct_mean, 1),
                "hangar_ms": round(hangar_mean, 1),
                "overhead_ms": round(overhead, 1),
                "overhead_pct": round(overhead_pct, 1),
                "note": overhead_note,
            })

        # Parallel overhead
        direct_par = group_df[group_df["baseline"] == "direct_parallel"]
        hangar_par = group_df[group_df["baseline"] == "hangar_parallel"]

        if not direct_par.empty and not hangar_par.empty:
            direct_mean = direct_par.iloc[0]["mean_ms"]
            hangar_mean = hangar_par.iloc[0]["mean_ms"]
            overhead = hangar_mean - direct_mean
            overhead_pct = (overhead / direct_mean * 100) if direct_mean > 0 else 0

            overheads.append({
                "scenario": scenario,
                "params": param_label,
                "mode": "Parallel",
                "direct_ms": round(direct_mean, 1),
                "hangar_ms": round(hangar_mean, 1),
                "overhead_ms": round(overhead, 1),
                "overhead_pct": round(overhead_pct, 1),
                "note": "",
            })

    result = pd.DataFrame(overheads)
    if not result.empty:
        result = result.sort_values(
            by=["scenario", "params", "mode"]
        ).reset_index(drop=True)
    return result


def print_summary_table(df: pd.DataFrame) -> None:
    """Print a rich summary table of all results."""
    table = Table(title="Benchmark Results Summary")
    table.add_column("Scenario", style="cyan")
    table.add_column("Params", style="dim")
    table.add_column("Baseline", style="green")
    table.add_column("Mean (ms)", justify="right")
    table.add_column("Median (ms)", justify="right")
    table.add_column("P95 (ms)", justify="right")
    table.add_column("StdDev", justify="right")
    table.add_column("95% CI", justify="right")
    table.add_column("N", justify="right")
    table.add_column("Errors", justify="right")

    for _, row in df.iterrows():
        param_label = _get_param_label(row)
        ci_str = f"[{row['ci_lower']:.1f}, {row['ci_upper']:.1f}]"
        err_style = "red" if row["errors"] > 0 else "dim"
        table.add_row(
            row["scenario"],
            param_label,
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
    table.add_column("Params", style="dim")
    table.add_column("Baseline", style="green")
    table.add_column("Sequential (ms)", justify="right")
    table.add_column("Actual (ms)", justify="right")
    table.add_column("Speedup", justify="right", style="bold")

    for _, row in speedups.iterrows():
        if row["speedup"] >= 2.0:
            speedup_style = "green bold"
        elif row["speedup"] >= 1.5:
            speedup_style = "green"
        elif row["speedup"] >= 1.0:
            speedup_style = "yellow"
        else:
            speedup_style = "red"

        table.add_row(
            row["scenario"],
            row["params"],
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
    table.add_column("Params", style="dim")
    table.add_column("Mode", style="blue")
    table.add_column("Direct (ms)", justify="right")
    table.add_column("Hangar (ms)", justify="right")
    table.add_column("Overhead (ms)", justify="right")
    table.add_column("Overhead %", justify="right")

    for _, row in overheads.iterrows():
        if abs(row["overhead_pct"]) < 5:
            oh_style = "green"
        elif abs(row["overhead_pct"]) < 10:
            oh_style = "yellow"
        else:
            oh_style = "red"

        overhead_str = f"{row['overhead_ms']:.1f}"
        if row.get("note"):
            overhead_str += f" {row['note']}"

        table.add_row(
            row["scenario"],
            row["params"],
            row["mode"],
            f"{row['direct_ms']:.1f}",
            f"{row['hangar_ms']:.1f}",
            f"[{oh_style}]{overhead_str}[/]",
            f"[{oh_style}]{row['overhead_pct']:.1f}%[/]",
        )

    console.print(table)


def print_executive_summary(df: pd.DataFrame) -> None:
    """Print a high-level executive summary table for the blog post."""
    table = Table(title="MCP Tool Call Performance Summary", box=None)
    table.add_column("Scenario", style="bold")
    table.add_column("Sequential", justify="right")
    table.add_column("Hangar Parallel", justify="right")
    table.add_column("Speedup", justify="right", style="green bold")

    summary_rows = []

    # S2: Fan-out at various N
    for n in [5, 10, 20]:
        s2 = df[(df["scenario"] == "s2_fanout") & (df["num_calls"] == n)]
        seq = s2[s2["baseline"] == "sequential"]
        par = s2[s2["baseline"] == "hangar_parallel"]
        if not seq.empty and not par.empty:
            seq_ms = seq.iloc[0]["mean_ms"]
            par_ms = par.iloc[0]["mean_ms"]
            speedup = seq_ms / par_ms if par_ms > 0 else 0
            summary_rows.append((
                f"{n} tools, 1 provider",
                f"{seq_ms:,.0f}ms",
                f"{par_ms:,.0f}ms",
                f"{speedup:.1f}x"
            ))

    # S3: Multi-provider
    s3 = df[df["scenario"] == "s3_multi_provider"]
    seq = s3[s3["baseline"] == "sequential"]
    par = s3[s3["baseline"] == "hangar_parallel"]
    if not seq.empty and not par.empty:
        seq_ms = seq.iloc[0]["mean_ms"]
        par_ms = par.iloc[0]["mean_ms"]
        speedup = seq_ms / par_ms if par_ms > 0 else 0
        num_p = s3.iloc[0].get("num_providers", 5)
        summary_rows.append((
            f"{num_p} providers, parallel",
            f"{seq_ms:,.0f}ms",
            f"{par_ms:,.0f}ms",
            f"{speedup:.1f}x"
        ))

    # S5: Mixed latency
    s5 = df[df["scenario"] == "s5_mixed_latency"]
    seq = s5[s5["baseline"] == "sequential"]
    par = s5[s5["baseline"] == "hangar_parallel"]
    if not seq.empty and not par.empty:
        seq_ms = seq.iloc[0]["mean_ms"]
        par_ms = par.iloc[0]["mean_ms"]
        speedup = seq_ms / par_ms if par_ms > 0 else 0
        summary_rows.append((
            "Mixed latency (9 calls)",
            f"{seq_ms:,.0f}ms",
            f"{par_ms:,.0f}ms",
            f"{speedup:.1f}x"
        ))

    # S6: Agent workflow
    s6 = df[df["scenario"] == "s6_agent_workflow"]
    seq = s6[s6["baseline"] == "sequential"]
    par = s6[s6["baseline"] == "workflow_parallel"]
    if not seq.empty and not par.empty:
        seq_ms = seq.iloc[0]["mean_ms"]
        par_ms = par.iloc[0]["mean_ms"]
        speedup = seq_ms / par_ms if par_ms > 0 else 0
        summary_rows.append((
            "Agent workflow (7 steps)",
            f"{seq_ms:,.0f}ms",
            f"{par_ms:,.0f}ms",
            f"{speedup:.1f}x"
        ))

    # S4: Cold start at N=20
    s4 = df[(df["scenario"] == "s4_cold_start") & (df["num_calls"] == 20)]
    seq = s4[s4["baseline"] == "sequential"]
    par = s4[s4["baseline"] == "hangar_parallel"]
    if not seq.empty and not par.empty:
        seq_ms = seq.iloc[0]["mean_ms"]
        par_ms = par.iloc[0]["mean_ms"]
        speedup = seq_ms / par_ms if par_ms > 0 else 0
        summary_rows.append((
            "Cold start (20 calls)",
            f"{seq_ms:,.0f}ms",
            f"{par_ms:,.0f}ms",
            f"{speedup:.1f}x"
        ))

    for row in summary_rows:
        table.add_row(*row)

    # Framework overhead summary
    s1 = df[df["scenario"] == "s1_baseline"]
    seq = s1[s1["baseline"] == "sequential"]
    hangar = s1[s1["baseline"] == "hangar_sequential"]
    if not seq.empty and not hangar.empty:
        # Average per-call overhead across all delay configurations
        seq_total = seq["mean_ms"].mean()
        hangar_total = hangar["mean_ms"].mean()
        overhead = hangar_total - seq_total
        num_calls = seq.iloc[0]["num_calls"] if "num_calls" in seq.columns else 50
        per_call = overhead / num_calls if num_calls > 0 else overhead

        table.add_row("", "", "", "")
        table.add_row(
            "Framework overhead",
            "",
            f"~{abs(per_call):.1f}ms/call",
            "~0%" if abs(per_call) < 1 else f"+{per_call:.0f}%"
        )

    console.print()
    console.print(table)


def generate_report(results_dir: str = "results/raw") -> None:
    """Generate and print a full statistical report from raw results."""
    results = load_results(results_dir)
    if not results:
        console.print("[red]No results found.[/]")
        return

    df = results_to_dataframe(results)

    console.print(f"\n[bold]Loaded {len(results)} result files[/]\n")

    # Executive summary first
    print_executive_summary(df)

    console.print()
    print_summary_table(df)

    speedups = compute_speedups(df)
    if not speedups.empty:
        console.print()
        print_speedup_table(speedups)

    overheads = compute_overhead(df)
    if not overheads.empty:
        console.print()
        print_overhead_table(overheads)


def generate_markdown_report(results_dir: str = "results/raw", output_path: str | None = None) -> str:
    """Generate a markdown report suitable for blog posts."""
    results = load_results(results_dir)
    if not results:
        return "No results found."

    df = results_to_dataframe(results)

    lines = [
        "# MCP Hangar Benchmark Results",
        "",
        "## Executive Summary",
        "",
        "| Scenario | Sequential | Hangar Parallel | Speedup |",
        "|----------|------------|-----------------|---------|",
    ]

    # S2 N=10, N=20
    for n in [10, 20]:
        s2 = df[(df["scenario"] == "s2_fanout") & (df["num_calls"] == n)]
        seq = s2[s2["baseline"] == "sequential"]
        par = s2[s2["baseline"] == "hangar_parallel"]
        if not seq.empty and not par.empty:
            seq_ms = seq.iloc[0]["mean_ms"]
            par_ms = par.iloc[0]["mean_ms"]
            speedup = seq_ms / par_ms if par_ms > 0 else 0
            lines.append(f"| {n} parallel tools | {seq_ms:,.0f}ms | {par_ms:,.0f}ms | **{speedup:.1f}x** |")

    # S6
    s6 = df[df["scenario"] == "s6_agent_workflow"]
    seq = s6[s6["baseline"] == "sequential"]
    par = s6[s6["baseline"] == "workflow_parallel"]
    if not seq.empty and not par.empty:
        seq_ms = seq.iloc[0]["mean_ms"]
        par_ms = par.iloc[0]["mean_ms"]
        speedup = seq_ms / par_ms if par_ms > 0 else 0
        lines.append(f"| Agent workflow | {seq_ms:,.0f}ms | {par_ms:,.0f}ms | **{speedup:.1f}x** |")

    lines.extend([
        "",
        "## Charts",
        "",
        "![Sequential vs Parallel](charts/chart1_money.png)",
        "",
        "![Scaling Curve](charts/chart2_scaling.png)",
        "",
        "![Agent Workflow Timeline](charts/chart6_workflow_timeline.png)",
        "",
        "## Methodology",
        "",
        "See [METHODOLOGY.md](../METHODOLOGY.md) for full details.",
        "",
        f"- Runs per measurement: {results[0].get('config', {}).get('runs', 30)}",
        f"- Warmup runs: {results[0].get('config', {}).get('warmup_runs', 5)}",
        f"- Statistical confidence: 95% CI",
        "",
    ])

    # Environment
    env = results[0].get("environment", {})
    lines.extend([
        "## Environment",
        "",
        f"- OS: {env.get('os', 'N/A')}",
        f"- CPU: {env.get('cpu', 'N/A')}",
        f"- Python: {env.get('python_version', 'N/A').split()[0]}",
        f"- mcp-hangar: {env.get('mcp_hangar_version', 'N/A')}",
        "",
    ])

    report = "\n".join(lines)

    if output_path:
        with open(output_path, "w") as f:
            f.write(report)

    return report
