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
import matplotlib.patches as mpatches
import numpy as np
import pandas as pd
import seaborn as sns

from src.analysis.stats import (
    load_results,
    results_to_dataframe,
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
    "workflow_parallel": "Parallel Workflow",
}

# Figure sizes
FIGSIZE_WIDE = (12, 6)
FIGSIZE_GANTT = (14, 8)
FIGSIZE_SQUARE = (10, 8)


def _setup_style() -> None:
    """Configure matplotlib/seaborn style for publication quality."""
    sns.set_theme(style="whitegrid")
    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": ["Inter", "Helvetica Neue", "Arial", "DejaVu Sans"],
        "font.size": 11,
        "axes.titlesize": 14,
        "axes.titleweight": "bold",
        "axes.labelsize": 12,
        "xtick.labelsize": 10,
        "ytick.labelsize": 10,
        "legend.fontsize": 10,
        "figure.dpi": 150,
        "savefig.dpi": 300,
        "savefig.bbox_inches": "tight",
        "axes.grid": True,
        "grid.alpha": 0.3,
    })


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

    Shows S2 fan-out results grouped by N value.
    X-axis: N (1, 2, 5, 10, 15, 20)
    Y-axis: Wall-clock time (ms)
    """
    _setup_style()

    s2 = df[df["scenario"] == "s2_fanout"].copy()
    if s2.empty:
        return

    # Get all N values, sorted
    n_values = sorted(s2["num_calls"].unique())
    if not n_values:
        return

    baselines_order = ["sequential", "direct_parallel", "hangar_parallel"]
    s2 = s2[s2["baseline"].isin(baselines_order)]

    fig, ax = plt.subplots(figsize=FIGSIZE_WIDE)

    x_labels = [f"N={n}" for n in n_values]
    x = np.arange(len(x_labels))
    width = 0.25
    offsets = [-width, 0, width]

    for i, baseline in enumerate(baselines_order):
        subset = s2[s2["baseline"] == baseline].sort_values("num_calls")
        if subset.empty:
            continue

        # Match values to n_values order
        values = []
        errors = []
        for n in n_values:
            row = subset[subset["num_calls"] == n]
            if not row.empty:
                values.append(row.iloc[0]["mean_ms"])
                ci_range = (row.iloc[0]["ci_upper"] - row.iloc[0]["ci_lower"]) / 2
                errors.append(ci_range)
            else:
                values.append(0)
                errors.append(0)

        bars = ax.bar(
            x + offsets[i],
            values,
            width,
            label=_get_label(baseline),
            color=_get_color(baseline),
            yerr=errors,
            capsize=3,
            edgecolor="white",
            linewidth=0.5,
        )

        # Annotate speedup on hangar_parallel bars
        if baseline == "hangar_parallel":
            seq_subset = s2[s2["baseline"] == "sequential"].sort_values("num_calls")
            for j, n in enumerate(n_values):
                seq_row = seq_subset[seq_subset["num_calls"] == n]
                if not seq_row.empty and values[j] > 0:
                    seq_val = seq_row.iloc[0]["mean_ms"]
                    speedup = seq_val / values[j]
                    if speedup >= 1.5:  # Only annotate significant speedups
                        ax.annotate(
                            f"{speedup:.1f}x",
                            xy=(x[j] + offsets[i], values[j]),
                            xytext=(0, 8),
                            textcoords="offset points",
                            ha="center",
                            fontsize=9,
                            fontweight="bold",
                            color=_get_color("hangar_parallel"),
                        )

    ax.set_xlabel("Number of Parallel Tool Calls")
    ax.set_ylabel("Wall-Clock Time (ms)")
    ax.set_title("Sequential vs Parallel Execution: The Money Chart")
    ax.set_xticks(x)
    ax.set_xticklabels(x_labels)
    ax.legend(loc="upper left")
    ax.set_ylim(bottom=0)

    # Add annotation about what we're seeing
    ax.text(
        0.98, 0.95,
        "Lower is better",
        transform=ax.transAxes,
        ha="right", va="top",
        fontsize=9, style="italic", color="gray"
    )

    fig.tight_layout()
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

    fig, ax = plt.subplots(figsize=FIGSIZE_WIDE)

    baselines_order = ["sequential", "direct_parallel", "hangar_parallel"]

    for baseline in baselines_order:
        subset = s2[s2["baseline"] == baseline].sort_values("num_calls")
        if subset.empty:
            continue

        x = subset["num_calls"].values
        y = subset["mean_ms"].values
        lower = subset["ci_lower"].values
        upper = subset["ci_upper"].values

        color = _get_color(baseline)
        ax.plot(x, y, "o-", label=_get_label(baseline), color=color, linewidth=2, markersize=6)
        ax.fill_between(x, lower, upper, alpha=0.15, color=color)

    # Reference line: theoretical minimum (single call latency ~100ms)
    ax.axhline(
        y=100,
        color="gray",
        linestyle="--",
        alpha=0.7,
        linewidth=1.5,
        label="Theoretical minimum (100ms)",
    )

    # Add annotation for the concurrency pattern
    max_n = s2["num_calls"].max()
    hangar_at_max = s2[(s2["baseline"] == "hangar_parallel") & (s2["num_calls"] == max_n)]
    if not hangar_at_max.empty:
        hangar_val = hangar_at_max.iloc[0]["mean_ms"]
        direct_at_max = s2[(s2["baseline"] == "direct_parallel") & (s2["num_calls"] == max_n)]
        if not direct_at_max.empty:
            direct_val = direct_at_max.iloc[0]["mean_ms"]
            if hangar_val > direct_val * 1.5:
                ax.annotate(
                    "Concurrency\nlimit visible",
                    xy=(max_n, hangar_val),
                    xytext=(max_n - 3, hangar_val + 100),
                    fontsize=9,
                    ha="center",
                    arrowprops=dict(arrowstyle="->", color="gray", alpha=0.7),
                )

    ax.set_xlabel("Number of Parallel Calls")
    ax.set_ylabel("Total Wall-Clock Time (ms)")
    ax.set_title("Scaling: How Time Grows with Parallel Calls")
    ax.legend(loc="upper left")
    ax.set_ylim(bottom=0)
    ax.set_xlim(left=0)

    fig.tight_layout()
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

    n_values = sorted(s4["num_calls"].unique())
    if not n_values:
        return

    fig, ax = plt.subplots(figsize=(10, 6))

    baselines_in_data = sorted(s4["baseline"].unique())
    x_labels = [f"N={int(n)}" for n in n_values]
    x = np.arange(len(x_labels))
    width = 0.35
    offsets = np.linspace(-width/2, width/2, len(baselines_in_data))

    for i, baseline in enumerate(baselines_in_data):
        subset = s4[s4["baseline"] == baseline].sort_values("num_calls")
        if subset.empty:
            continue

        values = []
        errors = []
        for n in n_values:
            row = subset[subset["num_calls"] == n]
            if not row.empty:
                values.append(row.iloc[0]["mean_ms"])
                ci_range = (row.iloc[0]["ci_upper"] - row.iloc[0]["ci_lower"]) / 2
                errors.append(ci_range)
            else:
                values.append(0)
                errors.append(0)

        bars = ax.bar(
            x + offsets[i],
            values,
            width * 0.9,
            label=_get_label(baseline),
            color=_get_color(baseline),
            yerr=errors,
            capsize=3,
            edgecolor="white",
            linewidth=0.5,
        )

        # Annotate speedup for parallel
        if baseline == "hangar_parallel":
            seq_subset = s4[s4["baseline"] == "sequential"].sort_values("num_calls")
            for j, n in enumerate(n_values):
                seq_row = seq_subset[seq_subset["num_calls"] == n]
                if not seq_row.empty and values[j] > 0:
                    seq_val = seq_row.iloc[0]["mean_ms"]
                    speedup = seq_val / values[j]
                    if speedup >= 1.2:
                        ax.annotate(
                            f"{speedup:.1f}x",
                            xy=(x[j] + offsets[i], values[j]),
                            xytext=(0, 5),
                            textcoords="offset points",
                            ha="center",
                            fontsize=9,
                            fontweight="bold",
                            color=_get_color("hangar_parallel"),
                        )

    ax.set_xlabel("Simultaneous Calls to Provider")
    ax.set_ylabel("Total Time (ms)")
    ax.set_title("Cold Start: Parallel vs Sequential Scaling")
    ax.set_xticks(x)
    ax.set_xticklabels(x_labels)
    ax.legend()
    ax.set_ylim(bottom=0)

    fig.tight_layout()
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
                rows.append({
                    "scenario": scenario,
                    "baseline": baseline,
                    "wall_clock_ms": m["wall_clock_ns"] / 1_000_000,
                })

    if not rows:
        return

    plot_df = pd.DataFrame(rows)

    # Focus on key scenarios
    key_scenarios = ["s2_fanout", "s5_mixed_latency", "s6_agent_workflow"]
    plot_df = plot_df[plot_df["scenario"].isin(key_scenarios)]

    scenarios = sorted(plot_df["scenario"].unique())
    n_scenarios = len(scenarios)
    if n_scenarios == 0:
        return

    fig, axes = plt.subplots(1, n_scenarios, figsize=(5 * n_scenarios, 6), squeeze=False)

    for idx, scenario in enumerate(scenarios):
        ax = axes[0][idx]
        subset = plot_df[plot_df["scenario"] == scenario]

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

        ax.set_title(scenario.replace("_", " ").title())
        ax.set_xlabel("")
        ax.set_ylabel("Wall-Clock Time (ms)" if idx == 0 else "")
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

    # Use S1 baseline data for clearest overhead picture
    s1 = df[df["scenario"] == "s1_baseline"].copy()

    overheads = []
    for delay in sorted(s1["delay_ms"].unique()):
        delay_df = s1[s1["delay_ms"] == delay]
        direct = delay_df[delay_df["baseline"] == "sequential"]
        hangar = delay_df[delay_df["baseline"] == "hangar_sequential"]

        if direct.empty or hangar.empty:
            continue

        direct_mean = direct.iloc[0]["mean_ms"]
        hangar_mean = hangar.iloc[0]["mean_ms"]
        overhead = max(0, hangar_mean - direct_mean)
        num_calls = direct.iloc[0]["num_calls"]

        overheads.append({
            "label": f"{int(delay)}ms delay",
            "direct_time": direct_mean,
            "overhead": overhead,
            "per_call_overhead": overhead / num_calls if num_calls > 0 else 0,
            "num_calls": num_calls,
        })

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

    # Annotate per-call overhead
    for i, row in oh_df.iterrows():
        total = row["direct_time"] + row["overhead"]
        per_call = row["per_call_overhead"]
        ax.annotate(
            f"+{per_call:.2f}ms/call",
            xy=(i, total),
            xytext=(0, 5),
            textcoords="offset points",
            ha="center",
            fontsize=9,
            color=COLORS["overhead"],
        )

    ax.set_xlabel("Provider Latency Configuration")
    ax.set_ylabel("Total Time for 50 Calls (ms)")
    ax.set_title("Framework Overhead: Direct vs Hangar (S1 Baseline)")
    ax.set_xticks(x)
    ax.set_xticklabels(oh_df["label"])
    ax.legend()
    ax.set_ylim(bottom=0)

    fig.tight_layout()
    _save_chart(fig, output_dir, "chart5_overhead")


# --- Chart 6: Agent Workflow Timeline (Gantt) ---


def chart_workflow_timeline(
    results: list[dict[str, Any]],
    output_dir: str = "results/charts",
) -> None:
    """Chart 6: Gantt-style timeline for S6 agent workflow.

    Shows sequential (waterfall) vs parallel (concurrent) execution.
    This is the most visually compelling chart.
    """
    _setup_style()

    s6_results = [r for r in results if r.get("scenario") == "s6_agent_workflow"]
    if not s6_results:
        return

    fig, axes = plt.subplots(1, 2, figsize=FIGSIZE_GANTT, gridspec_kw={"wspace": 0.3})

    # Define the workflow steps with colors by phase
    step_info = [
        ("Fetch repo 1", "#3498DB"),   # Blue - fetch
        ("Fetch repo 2", "#3498DB"),
        ("Fetch repo 3", "#3498DB"),
        ("Search repo 1", "#E67E22"),  # Orange - search
        ("Search repo 2", "#E67E22"),
        ("Search repo 3", "#E67E22"),
        ("Write summary", "#27AE60"),  # Green - write
    ]
    step_labels = [s[0] for s in step_info]
    step_colors = [s[1] for s in step_info]

    baseline_configs = [
        ("sequential", "Sequential Execution", axes[0]),
        ("workflow_parallel", "Parallel Workflow", axes[1]),
    ]

    for baseline_name, title, ax in baseline_configs:
        result = next(
            (r for r in s6_results if r.get("baseline") == baseline_name), None
        )
        if result is None:
            ax.set_title(f"{title}\n(no data)")
            ax.set_yticks(range(len(step_labels)))
            ax.set_yticklabels(list(reversed(step_labels)))
            continue

        measurements = result.get("measurements", [])
        if not measurements:
            ax.set_title(f"{title}\n(no data)")
            continue

        # Use the first successful measurement
        m = next(
            (m for m in measurements if m.get("wall_clock_ns", 0) > 0), None
        )
        if m is None:
            ax.set_title(f"{title}\n(no data)")
            continue

        per_call = m.get("per_call_latencies_ns", [])
        total_ms = m["wall_clock_ns"] / 1_000_000

        if baseline_name == "sequential" and len(per_call) >= len(step_labels):
            # Sequential: each call starts after the previous ends
            current = 0
            for i, (label, color) in enumerate(step_info):
                duration = per_call[i] / 1_000_000
                ax.barh(
                    len(step_labels) - 1 - i,
                    duration,
                    left=current,
                    height=0.6,
                    color=color,
                    edgecolor="white",
                    linewidth=1,
                )
                # Label inside bar if wide enough
                if duration > total_ms * 0.08:
                    ax.text(
                        current + duration / 2,
                        len(step_labels) - 1 - i,
                        f"{duration:.0f}ms",
                        ha="center", va="center",
                        fontsize=8, color="white", fontweight="bold"
                    )
                current += duration

        elif baseline_name == "workflow_parallel" and len(per_call) >= 3:
            # Workflow: step1 parallel, step2 parallel, step3 sequential
            # The per_call latencies are for each step, not individual calls
            step1_dur = per_call[0] / 1_000_000  # Max of 3 parallel fetches
            step2_dur = per_call[1] / 1_000_000  # Max of 3 parallel searches
            step3_dur = per_call[2] / 1_000_000 if len(per_call) > 2 else 0

            # Step 1: 3 fetches in parallel (same start, same duration)
            for i in range(3):
                ax.barh(
                    len(step_labels) - 1 - i,
                    step1_dur,
                    left=0,
                    height=0.6,
                    color=step_colors[i],
                    edgecolor="white",
                    linewidth=1,
                )
            # Label for step 1
            ax.text(
                step1_dur / 2, len(step_labels) - 2,
                f"{step1_dur:.0f}ms",
                ha="center", va="center",
                fontsize=8, color="white", fontweight="bold"
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
                    linewidth=1,
                )
            # Label for step 2
            ax.text(
                step1_dur + step2_dur / 2, len(step_labels) - 5,
                f"{step2_dur:.0f}ms",
                ha="center", va="center",
                fontsize=8, color="white", fontweight="bold"
            )

            # Step 3: write, after step 2
            ax.barh(
                0,
                step3_dur,
                left=step1_dur + step2_dur,
                height=0.6,
                color=step_colors[6],
                edgecolor="white",
                linewidth=1,
            )
            if step3_dur > 30:
                ax.text(
                    step1_dur + step2_dur + step3_dur / 2, 0,
                    f"{step3_dur:.0f}ms",
                    ha="center", va="center",
                    fontsize=8, color="white", fontweight="bold"
                )

        # Add vertical line at total time
        ax.axvline(x=total_ms, color="red", linestyle="--", linewidth=2, alpha=0.7)
        ax.text(
            total_ms, -0.7,
            f"Total: {total_ms:.0f}ms",
            ha="center", va="top",
            fontsize=10, fontweight="bold", color="red"
        )

        ax.set_yticks(range(len(step_labels)))
        ax.set_yticklabels(list(reversed(step_labels)))
        ax.set_xlabel("Time (ms)")
        ax.set_title(title, fontsize=12, fontweight="bold")
        ax.set_xlim(left=0)
        ax.set_ylim(-1, len(step_labels))

    # Calculate and display time saved
    seq_result = next((r for r in s6_results if r.get("baseline") == "sequential"), None)
    par_result = next((r for r in s6_results if r.get("baseline") == "workflow_parallel"), None)

    if seq_result and par_result:
        seq_stats = seq_result.get("statistics", {}).get("wall_clock_ms", {})
        par_stats = par_result.get("statistics", {}).get("wall_clock_ms", {})
        seq_mean = seq_stats.get("mean", 0)
        par_mean = par_stats.get("mean", 0)

        if seq_mean > 0 and par_mean > 0:
            saved = seq_mean - par_mean
            pct = (saved / seq_mean) * 100
            fig.text(
                0.5, 0.02,
                f"Time saved: {saved:.0f}ms ({pct:.0f}%) — Speedup: {seq_mean/par_mean:.1f}x",
                ha="center", fontsize=12, fontweight="bold",
                color=COLORS["hangar_parallel"]
            )

    # Legend for phases
    legend_elements = [
        mpatches.Patch(color="#3498DB", label="Fetch"),
        mpatches.Patch(color="#E67E22", label="Search"),
        mpatches.Patch(color="#27AE60", label="Write"),
    ]
    fig.legend(
        handles=legend_elements,
        loc="upper center",
        ncol=3,
        bbox_to_anchor=(0.5, 0.98),
        frameon=False
    )

    fig.suptitle(
        "Agent Workflow: Sequential vs Parallel Pipeline",
        fontsize=14, fontweight="bold", y=1.02
    )

    fig.tight_layout(rect=[0, 0.05, 1, 0.95])
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
