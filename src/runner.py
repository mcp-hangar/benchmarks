"""CLI entrypoint for the MCP Hangar benchmark suite.

Usage:
    python -m src.runner --all-scenarios --runs 30
    python -m src.runner --scenario s2 --runs 50
    python -m src.runner --scenario s3 --baselines sequential,hangar_parallel
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any

import click
from rich.console import Console
from rich.panel import Panel

from src.analysis.charts import generate_all_charts
from src.analysis.stats import generate_markdown_report, generate_report
from src.harness import BenchmarkConfig
from src.scenarios.s1_baseline import create_scenarios as s1_scenarios
from src.scenarios.s2_fanout import create_scenarios as s2_scenarios
from src.scenarios.s3_multi_provider import create_scenarios as s3_scenarios
from src.scenarios.s4_cold_start import create_scenarios as s4_scenarios
from src.scenarios.s5_mixed_latency import create_scenarios as s5_scenarios
from src.scenarios.s6_agent_workflow import create_scenarios as s6_scenarios
from src.utils.environment import capture_environment

console = Console()

SCENARIO_MAP: dict[str, Any] = {
    "s1": s1_scenarios,
    "s2": s2_scenarios,
    "s3": s3_scenarios,
    "s4": s4_scenarios,
    "s5": s5_scenarios,
    "s6": s6_scenarios,
}


def _get_scenarios(scenario_id: str | None, all_scenarios: bool) -> list[Any]:
    """Resolve which scenarios to run."""
    if all_scenarios:
        scenarios = []
        for factory in SCENARIO_MAP.values():
            scenarios.extend(factory())
        return scenarios

    if scenario_id:
        factory = SCENARIO_MAP.get(scenario_id)
        if factory is None:
            console.print(f"[red]Unknown scenario: {scenario_id}[/]")
            console.print(f"Available: {', '.join(SCENARIO_MAP.keys())}")
            sys.exit(1)
        return factory()

    console.print("[red]Specify --scenario or --all-scenarios[/]")
    sys.exit(1)


async def _run_async(
    scenarios: list[Any],
    config: BenchmarkConfig,
    baselines: list[str] | None,
    output_dir: str,
) -> list[dict[str, Any]]:
    """Run all scenarios asynchronously."""
    all_results: list[dict[str, Any]] = []

    for scenario in scenarios:
        try:
            results = await scenario.run(
                config=config,
                baselines=baselines,
                output_dir=output_dir,
            )
            all_results.extend(results)
        except Exception as e:
            console.print(f"[red]Scenario {scenario.scenario_id} failed: {e}[/]")
            import traceback
            traceback.print_exc()

    return all_results


@click.group()
def cli() -> None:
    """MCP Hangar Benchmark Suite."""
    pass


@cli.command()
@click.option("--scenario", "-s", help="Scenario to run (s1-s6)")
@click.option("--all-scenarios", "-a", is_flag=True, help="Run all scenarios")
@click.option("--runs", "-r", default=30, help="Number of measurement runs")
@click.option("--warmup", "-w", default=5, help="Number of warmup runs")
@click.option("--baselines", "-b", help="Comma-separated baselines to run")
@click.option("--output", "-o", default="results/raw", help="Output directory")
def run(
    scenario: str | None,
    all_scenarios: bool,
    runs: int,
    warmup: int,
    baselines: str | None,
    output: str,
) -> None:
    """Run benchmark scenarios."""
    scenarios = _get_scenarios(scenario, all_scenarios)
    config = BenchmarkConfig(runs=runs, warmup_runs=warmup)
    baseline_list = baselines.split(",") if baselines else None

    # Print environment
    env = capture_environment()
    console.print(
        Panel(
            f"[bold]MCP Hangar Benchmark Suite[/]\n\n"
            f"Python: {env['python_version'].split()[0]}\n"
            f"mcp-hangar: {env['mcp_hangar_version']}\n"
            f"OS: {env['os']}\n"
            f"CPU: {env['cpu']}\n"
            f"Runs: {runs}, Warmup: {warmup}\n"
            f"Scenarios: {len(scenarios)}",
            title="Configuration",
            border_style="cyan",
        )
    )

    results = asyncio.run(_run_async(scenarios, config, baseline_list, output))

    console.print(f"\n[bold green]Completed {len(results)} benchmarks.[/]")

    # Print summary report
    if results:
        generate_report(output)


@cli.command()
@click.option("--input", "-i", "input_dir", default="results/raw", help="Input dir")
@click.option("--output", "-o", "output_dir", default="results/charts", help="Output dir")
def charts(input_dir: str, output_dir: str) -> None:
    """Generate charts from existing results."""
    generate_all_charts(input_dir, output_dir)


@cli.command()
@click.option("--input", "-i", "input_dir", default="results/raw", help="Input dir")
@click.option("--format", "-f", "output_format", default="console",
              type=click.Choice(["console", "markdown"]), help="Output format")
@click.option("--output", "-o", "output_path", default=None, help="Output file (for markdown)")
def report(input_dir: str, output_format: str, output_path: str | None) -> None:
    """Print statistical report from existing results."""
    if output_format == "markdown":
        if output_path is None:
            output_path = "results/REPORT.md"
        generate_markdown_report(input_dir, output_path)
        console.print(f"[green]Markdown report saved to {output_path}[/]")
    else:
        generate_report(input_dir)


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
