"""S1: Baseline — Single Provider, Serial Calls.

Purpose: Establish per-call overhead baseline. Measure the cost of a single
MCP tool call through Hangar vs direct.

- Provider: controlled_delay with configurable delay
- Pattern: 1 call at a time, measure N=50 calls
- Baselines: Direct call vs Hangar-proxied call
- Key metric: Per-call overhead introduced by Hangar
"""

from __future__ import annotations

from typing import Any

from src.harness import BenchmarkConfig, ToolCall
from src.providers.configs import make_provider_config
from src.scenarios.base import BaseScenario


class S1Baseline(BaseScenario):
    """Single provider serial calls with varying delay."""

    def __init__(self, delay_ms: int = 100, num_calls: int = 50) -> None:
        self.delay_ms = delay_ms
        self.num_calls = num_calls

    @property
    def name(self) -> str:
        return f"S1 Baseline ({self.delay_ms}ms delay, {self.num_calls} calls)"

    @property
    def scenario_id(self) -> str:
        return "s1_baseline"

    def get_provider_configs(self) -> list[dict[str, Any]]:
        return [
            make_provider_config(
                "baseline",
                call_delay_ms=self.delay_ms,
                num_tools=1,
                tool_prefix="baseline",
            )
        ]

    def get_calls(self) -> list[ToolCall]:
        return [
            ToolCall(
                provider="baseline",
                tool="baseline_0",
                arguments={"request_id": f"s1_{i}"},
            )
            for i in range(self.num_calls)
        ]

    def get_parameters(self) -> dict[str, Any]:
        return {
            "delay_ms": self.delay_ms,
            "num_calls": self.num_calls,
            "num_providers": 1,
        }

    def get_baselines(self) -> list[str]:
        return ["sequential", "hangar_sequential"]


def create_scenarios() -> list[S1Baseline]:
    """Create S1 scenarios for multiple delay values."""
    delays = [0, 10, 50, 100, 200]
    return [S1Baseline(delay_ms=d, num_calls=50) for d in delays]
