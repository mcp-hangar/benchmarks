"""S2: Fan-out — Single Provider, N Parallel Tools.

Purpose: Show parallel speedup on a single provider with multiple tools.

- Provider: controlled_delay with 100ms delay, exposes up to 20 distinct tools
- Pattern: Call N tools simultaneously (N = 1, 2, 5, 10, 15, 20)
- Baselines: Sequential, Direct parallel, Hangar parallel
- Key metric: Wall-clock time as N increases
"""

from __future__ import annotations

from typing import Any

from src.harness import ToolCall
from src.providers.configs import make_provider_config
from src.scenarios.base import BaseScenario


class S2Fanout(BaseScenario):
    """Fan-out: single provider, N parallel tool calls."""

    def __init__(self, num_calls: int = 10, delay_ms: int = 100) -> None:
        self.num_calls = num_calls
        self.delay_ms = delay_ms

    @property
    def name(self) -> str:
        return f"S2 Fan-out (N={self.num_calls}, {self.delay_ms}ms delay)"

    @property
    def scenario_id(self) -> str:
        return "s2_fanout"

    def get_provider_configs(self) -> list[dict[str, Any]]:
        return [
            make_provider_config(
                "fanout",
                call_delay_ms=self.delay_ms,
                num_tools=max(self.num_calls, 20),
                tool_prefix="fanout",
            )
        ]

    def get_calls(self) -> list[ToolCall]:
        return [
            ToolCall(
                provider="fanout",
                tool=f"fanout_{i}",
                arguments={"request_id": f"s2_{i}"},
            )
            for i in range(self.num_calls)
        ]

    def get_parameters(self) -> dict[str, Any]:
        return {
            "num_calls": self.num_calls,
            "provider_delay_ms": self.delay_ms,
            "num_providers": 1,
        }

    def get_baselines(self) -> list[str]:
        return ["sequential", "direct_parallel", "hangar_sequential", "hangar_parallel"]


def create_scenarios() -> list[S2Fanout]:
    """Create S2 scenarios for multiple fan-out widths."""
    widths = [1, 2, 5, 10, 15, 20]
    return [S2Fanout(num_calls=n) for n in widths]
