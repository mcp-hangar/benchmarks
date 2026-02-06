"""Publication-quality chart generation for benchmark results.

Generates charts using matplotlib + seaborn with consistent styling.
Outputs both PNG (web/blog) and SVG (whitepaper) formats.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")  # Non-interactive backend

import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np
import pandas as pd
import seaborn as sns

from src.analysis.stats import (
    load_results,
    results_to_dataframe,
    compute_speedups,
)

# --- Style Configuration ---

COLORS = {
    "sequential": "#E74C3C",
    "direct_parallel": "#F39C12",
    "hangar_parallel": "#2ECC71",
    "hangar_sequential": "#95A5A6",
    "workflow_parallel": "#2ECC71",
    "overhead": "#3498DB",
}

BASELINE_LABELS = {
    "sequential": "Sequential",
    "direct_parallel": "Direct Parallel",
    "hangar_parallel": "Hangar Parallel",
    "hangar_sequential": "Hangar Sequential",
    "workflow_parallel": "Workflow Parallel",
}


def _setup_style() -> None:
    """Configure matplotlib/seaborn style for publication quality."""
    sns.set_theme(style="whitegrid")
    plt.rcParams.update(
        {
            "font.size": 12,
            "axes.titlesize": 14,
            "axes.labelsize": 12,
            "xtick.labelsize": 10,
            "ytick.labelsize": 10,
            "legend.fontsize": 10,
            "figure.figsize": (10, 6),
            "figure.dpi": 150,
            "savefig.dpi": 300,
            "axes.grid": True,
            "grid.alpha": 0.3,
        }
    )


def _save_chart(fig: plt.Figure, output_dir: str, name: str) -> None:
    """Save chart as both PNG and SVG."""
    os.makedirs(output_dir, exist_ok=True)
    fig.savefig(os.path.join(output_dir, f"{name}.png"))
    fig.savefig(os.path.join(output_dir, f"{name}.svg"))
    plt.close(fig)


def _get_color(baseline: str) -> str:
    return COLORS.get(baseline, "#333333")


def _get_label(baseline: str) -> str:
    return BASELINE_LABELS.get(baseline, baseline)


# --- Chart 1: The Money Chart ---


def chart_money(
    df: pd.DataFrame,
    output_dir: str = "results/charts",
) -> None:
    """Chart 1: Sequential vs Parallel wall-clock time (grouped bar).

    Shows S2 fan-out results at N=5, 10, 15, 20.
    """
    _setup_style()

    s2 = df[df["scenario"] == "s2_fanout"].copy()
    if s2.empty:
        return

    target_calls = [5, 10, 15, 20]
    s2 = s2[s2["num_calls"].isin(target_calls)]
    if s2.empty:
        return

    baselines_order = ["sequential", "direct_parallel", "hangar_parallel"]
    s2 = s2[s2["baseline"].isin(baselines_order)]

    fig, ax = plt.subplots(figsize=(12, 7))

    x_labels = [f"N={n}" for n in sorted(s2["num_calls"].unique())]
    x = np.arange(len(x_labels))
    width = 0.25

    for i, baseline in enumerate(baselines_order):
        subset = s2[s2["baseline"] == baseline].sort_values("num_calls")
        if subset.empty:
            continue
        values = subset["mean_ms"].values
        errors = (subset["ci_upper"].values - subset["ci_lower"].values) / 2
        bars = ax.bar(
            x + i * width,
            values,
            width,
            label=_get_label(baseline),
            color=_get_color(baseline),
            yerr=errors,
            capsize=4,
            edgecolor="white",
            linewidth=0.5,
        )
        # Annotate speedup on hangar bars
        if baseline == "hangar_parallel":
            seq_subset = s2[s2["baseline"] == "sequential"].sort_values("num_calls")
            if not seq_subset.empty:
                for j, (bar, seq_val) in enumerate(
                    zip(bars, seq_subset["mean_ms"].values)
                ):
                    if values[j] > 0:
                        speedup = seq_val / values[j]
                        ax.annotate(
                            f"{speedup:.0f}x",
                            xy=(bar.get_x() + bar.get_width() / 2, bar.get_height()),
                            xytext=(0, 8),
                            textcoords="offset points",
                            ha="center",
                            fontsize=10,
                            fontweight="bold",
                            color=_get_color("hangar_parallel"),
                        )

    ax.set_xlabel("Number of Parallel Calls")
    ax.set_ylabel("Wall-Clock Time (ms)")
    ax.set_title("Sequential vs Parallel Execution: Wall-Clock Time")
    ax.set_xticks(x + width)
    ax.set_xticklabels(x_labels)
    ax.legend()
    ax.set_ylim(bottom=0)

    _save_chart(fig, output_dir, "chart1_money")


# --- Chart 2: Scaling Curve ---


def chart_scaling(
    df: pd.DataFrame,
    output_dir: str = "results/charts",
) -> None:
    """Chart 2: Calls vs total time (line chart with confidence bands)."""
    _setup_style()

    s2 = df[df["scenario"] == "s2_fanout"].copy()
    if s2.empty:
        return

    fig, ax = plt.subplots(figsize=(10, 6))

    for baseline in ["sequential", "direct_parallel", "hangar_parallel"]:
        subset = s2[s2["baseline"] == baseline].sort_values("num_calls")
        if subset.empty:
            continue
        x = subset["num_calls"].values
        y = subset["mean_ms"].values
        lower = subset["ci_lower"].values
        upper = subset["ci_upper"].values

        color = _get_color(baseline)
        ax.plot(x, y, "o-", label=_get_label(baseline), color=color, linewidth=2)
        ax.fill_between(x, lower, upper, alpha=0.15, color=color)

    # Reference line: theoretical minimum (single call latency)
    if not s2.empty:
        min_latency = 100  # known configured delay
        ax.axhline(
            y=min_latency,
            color="gray",
            linestyle="--",
            alpha=0.5,
            label=f"Theoretical min ({min_latency}ms)",
        )

    ax.set_xlabel("Number of Parallel Calls")
    ax.set_ylabel("Total Wall-Clock Time (ms)")
    ax.set_title("Scaling: Calls vs Total Time")
    ax.legend()
    ax.set_ylim(bottom=0)

    _save_chart(fig, output_dir, "chart2_scaling")


# --- Chart 3: Cold Start ---


def chart_cold_start(
    df: pd.DataFrame,
    output_dir: str = "results/charts",
) -> None:
    """Chart 3: Cold start comparison (grouped bar)."""
    _setup_style()

    s4 = df[df["scenario"] == "s4_cold_start"].copy()
    if s4.empty:
        return

    fig, ax = plt.subplots(figsize=(10, 6))

    baselines = s4["baseline"].unique()
    x_labels = [f"N={int(n)}" for n in sorted(s4["num_calls"].unique())]
    x = np.arange(len(x_labels))
    width = 0.35

    for i, baseline in enumerate(sorted(baselines)):
        subset = s4[s4["baseline"] == baseline].sort_values("num_calls")
        if subset.empty:
            continue
        values = subset["mean_ms"].values
        errors = (subset["ci_upper"].values - subset["ci_lower"].values) / 2
        ax.bar(
            x + i * width,
            values,
            width,
            label=_get_label(baseline),
            color=_get_color(baseline),
            yerr=errors,
            capsize=4,
            edgecolor="white",
            linewidth=0.5,
        )

    ax.set_xlabel("Simultaneous Calls to Cold Provider")
    ax.set_ylabel("Total Time Including Cold Start (ms)")
    ax.set_title("Cold Start: Single-Flight Deduplication")
    ax.set_xticks(x + width / 2)
    ax.set_xticklabels(x_labels)
    ax.legend()
    ax.set_ylim(bottom=0)

    _save_chart(fig, output_dir, "chart3_cold_start")


# --- Chart 4: Latency Distribution ---


def chart_latency_distribution(
    results: list[dict[str, Any]],
    output_dir: str = "results/charts",
) -> None:
    """Chart 4: Latency distribution (violin/box plots)."""
    _setup_style()

    # Collect per-run wall-clock data
    rows = []
    for r in results:
        baseline = r.get("baseline", "")
        scenario = r.get("scenario", "")
        for m in r.get("measurements", []):
            if m.get("wall_clock_ns", 0) > 0:
                rows.append(
                    {
                        "scenario": scenario,
                        "baseline": baseline,
                        "wall_clock_ms": m["wall_clock_ns"] / 1_000_000,
                    }
                )

    if not rows:
        return

    plot_df = pd.DataFrame(rows)

    scenarios = sorted(plot_df["scenario"].unique())
    n_scenarios = len(scenarios)
    if n_scenarios == 0:
        return

    fig, axes = plt.subplots(1, n_scenarios, figsize=(6 * n_scenarios, 6), squeeze=False)

    for idx, scenario in enumerate(scenarios):
        ax = axes[0][idx]
        subset = plot_df[plot_df["scenario"] == scenario]

        # Create custom palette
        baselines_in_data = sorted(subset["baseline"].unique())
        palette = {b: _get_color(b) for b in baselines_in_data}

        sns.violinplot(
            data=subset,
            x="baseline",
            y="wall_clock_ms",
            hue="baseline",
            palette=palette,
            inner="box",
            ax=ax,
            cut=0,
            legend=False,
        )

        ax.set_title(scenario)
        ax.set_xlabel("Method")
        ax.set_ylabel("Wall-Clock Time (ms)")
        ax.set_xticks(range(len(baselines_in_data)))
        ax.set_xticklabels(
            [_get_label(b) for b in baselines_in_data], rotation=30, ha="right"
        )

    fig.suptitle("Latency Distribution by Scenario", fontsize=14, y=1.02)
    fig.tight_layout()
    _save_chart(fig, output_dir, "chart4_latency_distribution")


# --- Chart 5: Framework Overhead ---


def chart_overhead(
    df: pd.DataFrame,
    output_dir: str = "results/charts",
) -> None:
    """Chart 5: Framework overhead (stacked bar)."""
    _setup_style()

    # Compare sequential (direct) vs hangar_sequential for each scenario
    overheads = []
    for scenario in df["scenario"].unique():
        sdf = df[df["scenario"] == scenario]
        direct = sdf[sdf["baseline"] == "sequential"]
        hangar = sdf[sdf["baseline"] == "hangar_sequential"]
        if direct.empty or hangar.empty:
            continue
        direct_mean = direct.iloc[0]["mean_ms"]
        hangar_mean = hangar.iloc[0]["mean_ms"]
        overhead = max(0, hangar_mean - direct_mean)
        overheads.append(
            {
                "scenario": scenario,
                "direct_time": direct_mean,
                "overhead": overhead,
            }
        )

    if not overheads:
        return

    oh_df = pd.DataFrame(overheads)
    fig, ax = plt.subplots(figsize=(10, 6))

    x = np.arange(len(oh_df))
    width = 0.6

    ax.bar(
        x,
        oh_df["direct_time"],
        width,
        label="Direct Call Time",
        color=COLORS["sequential"],
        edgecolor="white",
        linewidth=0.5,
    )
    ax.bar(
        x,
        oh_df["overhead"],
        width,
        bottom=oh_df["direct_time"],
        label="Hangar Overhead",
        color=COLORS["overhead"],
        edgecolor="white",
        linewidth=0.5,
    )

    # Annotate overhead values
    for i, row in oh_df.iterrows():
        total = row["direct_time"] + row["overhead"]
        if row["direct_time"] > 0:
            pct = row["overhead"] / row["direct_time"] * 100
            ax.annotate(
                f"+{row['overhead']:.1f}ms ({pct:.1f}%)",
                xy=(i, total),
                xytext=(0, 5),
                textcoords="offset points",
                ha="center",
                fontsize=9,
                color=COLORS["overhead"],
            )

    ax.set_xlabel("Scenario")
    ax.set_ylabel("Time (ms)")
    ax.set_title("Framework Overhead: Direct vs Hangar")
    ax.set_xticks(x)
    ax.set_xticklabels(oh_df["scenario"], rotation=30, ha="right")
    ax.legend()
    ax.set_ylim(bottom=0)

    _save_chart(fig, output_dir, "chart5_overhead")


# --- Chart 6: Agent Workflow Timeline ---


def chart_workflow_timeline(
    results: list[dict[str, Any]],
    output_dir: str = "results/charts",
) -> None:
    """Chart 6: Gantt-style timeline for S6 agent workflow.

    Shows sequential (waterfall) vs parallel (concurrent) execution.
    """
    _setup_style()

    s6_results = [r for r in results if r.get("scenario") == "s6_agent_workflow"]
    if not s6_results:
        return

    fig, axes = plt.subplots(1, 2, figsize=(16, 6), sharey=False)

    # Define the workflow steps
    step_labels = [
        "Fetch repo 1", "Fetch repo 2", "Fetch repo 3",
        "Search repo 1", "Search repo 2", "Search repo 3",
        "Write summary",
    ]
    step_colors = (
        ["#3498DB"] * 3 +  # Fetch = blue
        ["#E67E22"] * 3 +  # Search = orange
        ["#27AE60"] * 1    # Write = green
    )

    for ax, baseline_name, title in [
        (axes[0], "sequential", "Sequential Execution"),
        (axes[1], "workflow_parallel", "Parallel Workflow"),
    ]:
        result = next(
            (r for r in s6_results if r.get("baseline") == baseline_name), None
        )
        if result is None:
            ax.set_title(f"{title} (no data)")
            continue

        measurements = result.get("measurements", [])
        if not measurements:
            ax.set_title(f"{title} (no data)")
            continue

        # Use the first successful measurement for the timeline
        m = next(
            (m for m in measurements if m.get("wall_clock_ns", 0) > 0), None
        )
        if m is None:
            ax.set_title(f"{title} (no data)")
            continue

        per_call = m.get("per_call_latencies_ns", [])
        total_ns = m["wall_clock_ns"]

        if baseline_name == "sequential" and len(per_call) >= len(step_labels):
            # Sequential: each call starts after the previous ends
            current = 0
            for i, label in enumerate(step_labels):
                duration = per_call[i] / 1_000_000  # to ms
                ax.barh(
                    len(step_labels) - 1 - i,
                    duration,
                    left=current,
                    height=0.6,
                    color=step_colors[i],
                    edgecolor="white",
                    linewidth=0.5,
                )
                current += duration
        elif baseline_name == "workflow_parallel" and len(per_call) >= 3:
            # Workflow: step1 parallel, step2 parallel, step3 sequential
            step1_dur = per_call[0] / 1_000_000
            step2_dur = per_call[1] / 1_000_000
            step3_dur = per_call[2] / 1_000_000 if len(per_call) > 2 else 0

            # Step 1: 3 fetches in parallel
            for i in range(3):
                ax.barh(
                    len(step_labels) - 1 - i,
                    step1_dur,
                    left=0,
                    height=0.6,
                    color=step_colors[i],
                    edgecolor="white",
                    linewidth=0.5,
                )
            # Step 2: 3 searches in parallel, after step 1
            for i in range(3, 6):
                ax.barh(
                    len(step_labels) - 1 - i,
                    step2_dur,
                    left=step1_dur,
                    height=0.6,
                    color=step_colors[i],
                    edgecolor="white",
                    linewidth=0.5,
                )
            # Step 3: write, after step 2
            ax.barh(
                0,
                step3_dur,
                left=step1_dur + step2_dur,
                height=0.6,
                color=step_colors[6],
                edgecolor="white",
                linewidth=0.5,
            )

        ax.set_yticks(range(len(step_labels)))
        ax.set_yticklabels(list(reversed(step_labels)))
        ax.set_xlabel("Time (ms)")
        ax.set_title(f"{title}\n(Total: {total_ns / 1_000_000:.0f}ms)")
        ax.set_xlim(left=0)

    fig.suptitle(
        "Agent Workflow: Sequential vs Parallel Pipeline", fontsize=14, y=1.02
    )
    fig.tight_layout()
    _save_chart(fig, output_dir, "chart6_workflow_timeline")


# --- Main entry point ---


def generate_all_charts(
    input_dir: str = "results/raw",
    output_dir: str = "results/charts",
) -> None:
    """Generate all charts from raw results."""
    results = load_results(input_dir)
    if not results:
        print("No results found. Run benchmarks first.")
        return

    df = results_to_dataframe(results)

    print(f"Loaded {len(results)} results, generating charts...")

    chart_money(df, output_dir)
    print("  Generated: chart1_money")

    chart_scaling(df, output_dir)
    print("  Generated: chart2_scaling")

    chart_cold_start(df, output_dir)
    print("  Generated: chart3_cold_start")

    chart_latency_distribution(results, output_dir)
    print("  Generated: chart4_latency_distribution")

    chart_overhead(df, output_dir)
    print("  Generated: chart5_overhead")

    chart_workflow_timeline(results, output_dir)
    print("  Generated: chart6_workflow_timeline")

    print(f"\nAll charts saved to {output_dir}/")


if __name__ == "__main__":
    generate_all_charts()
