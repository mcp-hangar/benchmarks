"""S6: Agent Workflow — Realistic Pipeline.

Purpose: Simulate what an actual AI agent does — multi-step,
multi-provider, with dependencies.

Workflow: "Research and summarize 3 GitHub repos"
  Step 1 (parallel): Fetch README from 3 repos (3 x fetch tool)
  Step 2 (parallel): Search issues in each repo (3 x search tool)
  Step 3 (sequential): Write summary to filesystem (1 x filesystem tool)

Uses controlled_delay providers with realistic latencies.
"""

from __future__ import annotations

import asyncio
from typing import Any

from src.baselines.direct_sequential import DirectMCPClient, run_sequential
from src.baselines.direct_parallel import run_parallel
from src.baselines.hangar_sequential import run_hangar_sequential
from src.baselines.hangar_parallel import run_hangar_parallel
from src.harness import BenchmarkConfig, ToolCall, run_benchmark
from src.providers.configs import make_provider_config
from src.scenarios.base import BaseScenario, console
from src.utils.timing import BatchTimingRecord, TimingRecord, now_ns

from mcp_hangar import Hangar, HangarConfig


class S6AgentWorkflow(BaseScenario):
    """Realistic agent workflow with dependent steps."""

    def __init__(self) -> None:
        self.fetch_delay_ms = 200
        self.search_delay_ms = 300
        self.fs_delay_ms = 50
        self.num_repos = 3

    @property
    def name(self) -> str:
        return "S6 Agent Workflow (3-step pipeline)"

    @property
    def scenario_id(self) -> str:
        return "s6_agent_workflow"

    def get_provider_configs(self) -> list[dict[str, Any]]:
        return [
            make_provider_config(
                "fetch",
                call_delay_ms=self.fetch_delay_ms,
                num_tools=1,
                tool_prefix="fetch",
                payload_size=1024,
            ),
            make_provider_config(
                "search",
                call_delay_ms=self.search_delay_ms,
                num_tools=1,
                tool_prefix="search",
                payload_size=512,
            ),
            make_provider_config(
                "filesystem",
                call_delay_ms=self.fs_delay_ms,
                num_tools=1,
                tool_prefix="fs",
                payload_size=128,
            ),
        ]

    def _step1_calls(self) -> list[ToolCall]:
        """Step 1: Fetch README from N repos (parallel)."""
        return [
            ToolCall(
                provider="fetch",
                tool="fetch_0",
                arguments={"request_id": f"fetch_repo_{i}"},
            )
            for i in range(self.num_repos)
        ]

    def _step2_calls(self) -> list[ToolCall]:
        """Step 2: Search issues in each repo (parallel)."""
        return [
            ToolCall(
                provider="search",
                tool="search_0",
                arguments={"request_id": f"search_repo_{i}"},
            )
            for i in range(self.num_repos)
        ]

    def _step3_calls(self) -> list[ToolCall]:
        """Step 3: Write summary (sequential)."""
        return [
            ToolCall(
                provider="filesystem",
                tool="fs_0",
                arguments={"request_id": "write_summary"},
            )
        ]

    def get_calls(self) -> list[ToolCall]:
        """Return all calls flattened (for baselines that don't respect steps)."""
        return self._step1_calls() + self._step2_calls() + self._step3_calls()

    def get_parameters(self) -> dict[str, Any]:
        sequential_total = (
            self.num_repos * self.fetch_delay_ms
            + self.num_repos * self.search_delay_ms
            + self.fs_delay_ms
        )
        # Parallel: max(fetch) + max(search) + fs = 200 + 300 + 50 = 550
        parallel_expected = self.fetch_delay_ms + self.search_delay_ms + self.fs_delay_ms
        return {
            "num_repos": self.num_repos,
            "fetch_delay_ms": self.fetch_delay_ms,
            "search_delay_ms": self.search_delay_ms,
            "fs_delay_ms": self.fs_delay_ms,
            "expected_sequential_ms": sequential_total,
            "expected_parallel_ms": parallel_expected,
        }

    def get_baselines(self) -> list[str]:
        return ["sequential", "workflow_parallel"]

    async def run(
        self,
        config: BenchmarkConfig,
        baselines: list[str] | None = None,
        output_dir: str = "results/raw",
    ) -> list[dict[str, Any]]:
        """Custom run that handles the multi-step workflow.

        The workflow has dependencies between steps, so we can't just
        run all calls in parallel. Instead:
        - Sequential: all 7 calls one at a time
        - Workflow parallel: step1 parallel, step2 parallel, step3 sequential
        """
        active_baselines = baselines or self.get_baselines()
        all_calls = self.get_calls()
        results: list[dict[str, Any]] = []

        console.print(f"\n[bold magenta]Scenario: {self.name}[/]")

        # --- Sequential baseline ---
        if "sequential" in active_baselines:
            console.print("[dim]Setting up direct MCP clients...[/]")
            client = await self.setup_direct_client()
            try:
                result = await run_benchmark(
                    name=f"{self.name} — All Sequential",
                    scenario=self.scenario_id,
                    baseline="sequential",
                    calls=all_calls,
                    benchmark_fn=lambda c: run_sequential(c, client),
                    config=config,
                    parameters=self.get_parameters(),
                    output_dir=output_dir,
                )
                results.append(result)
            finally:
                await client.close()

        # --- Workflow parallel baseline ---
        if "workflow_parallel" in active_baselines:
            console.print("[dim]Setting up Hangar for workflow...[/]")
            hangar = await self.setup_hangar()
            try:

                async def workflow_parallel_fn(
                    _calls: list[ToolCall],
                ) -> BatchTimingRecord:
                    """Execute the 3-step workflow with parallel steps."""
                    timing = BatchTimingRecord()
                    timing.batch_start_ns = now_ns()

                    # Step 1: Fetch (parallel)
                    step1 = self._step1_calls()
                    step1_tasks = []
                    for call in step1:
                        step1_tasks.append(
                            hangar.invoke(call.provider, call.tool, call.arguments)
                        )
                    step1_start = now_ns()
                    await asyncio.gather(*step1_tasks)
                    step1_end = now_ns()
                    timing.call_records.append(
                        TimingRecord(start_ns=step1_start, end_ns=step1_end)
                    )

                    # Step 2: Search (parallel)
                    step2 = self._step2_calls()
                    step2_tasks = []
                    for call in step2:
                        step2_tasks.append(
                            hangar.invoke(call.provider, call.tool, call.arguments)
                        )
                    step2_start = now_ns()
                    await asyncio.gather(*step2_tasks)
                    step2_end = now_ns()
                    timing.call_records.append(
                        TimingRecord(start_ns=step2_start, end_ns=step2_end)
                    )

                    # Step 3: Write (sequential)
                    step3 = self._step3_calls()
                    for call in step3:
                        step3_start = now_ns()
                        await hangar.invoke(
                            call.provider, call.tool, call.arguments
                        )
                        step3_end = now_ns()
                        timing.call_records.append(
                            TimingRecord(start_ns=step3_start, end_ns=step3_end)
                        )

                    timing.batch_end_ns = now_ns()
                    return timing

                result = await run_benchmark(
                    name=f"{self.name} — Workflow Parallel",
                    scenario=self.scenario_id,
                    baseline="workflow_parallel",
                    calls=all_calls,
                    benchmark_fn=workflow_parallel_fn,
                    config=config,
                    parameters=self.get_parameters(),
                    output_dir=output_dir,
                )
                results.append(result)
            finally:
                await hangar.stop()

        return results


def create_scenarios() -> list[S6AgentWorkflow]:
    """Create S6 scenarios."""
    return [S6AgentWorkflow()]
