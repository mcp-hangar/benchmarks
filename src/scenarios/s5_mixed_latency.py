"""S5: Mixed Latency — Head-of-Line Blocking.

Purpose: Show that sequential execution is bottlenecked by the slowest call.

- Providers: 1 fast (10ms), 1 medium (100ms), 1 slow (500ms)
- Pattern: 5 calls to fast, 3 to medium, 1 to slow — all at once
- Key metric: Head-of-line blocking time saved
"""

from __future__ import annotations

from typing import Any

from src.harness import ToolCall
from src.providers.configs import make_provider_config
from src.scenarios.base import BaseScenario


class S5MixedLatency(BaseScenario):
    """Mixed latency scenario demonstrating head-of-line blocking."""

    def __init__(self) -> None:
        self.fast_delay = 10
        self.fast_count = 5
        self.medium_delay = 100
        self.medium_count = 3
        self.slow_delay = 500
        self.slow_count = 1

    @property
    def name(self) -> str:
        return "S5 Mixed Latency (Head-of-Line Blocking)"

    @property
    def scenario_id(self) -> str:
        return "s5_mixed_latency"

    def get_provider_configs(self) -> list[dict[str, Any]]:
        return [
            make_provider_config(
                "fast",
                call_delay_ms=self.fast_delay,
                num_tools=self.fast_count,
                tool_prefix="fast",
            ),
            make_provider_config(
                "medium",
                call_delay_ms=self.medium_delay,
                num_tools=self.medium_count,
                tool_prefix="medium",
            ),
            make_provider_config(
                "slow",
                call_delay_ms=self.slow_delay,
                num_tools=self.slow_count,
                tool_prefix="slow",
            ),
        ]

    def get_calls(self) -> list[ToolCall]:
        calls: list[ToolCall] = []
        # 5 fast calls
        for i in range(self.fast_count):
            calls.append(
                ToolCall(
                    provider="fast",
                    tool=f"fast_{i}",
                    arguments={"request_id": f"s5_fast_{i}"},
                )
            )
        # 3 medium calls
        for i in range(self.medium_count):
            calls.append(
                ToolCall(
                    provider="medium",
                    tool=f"medium_{i}",
                    arguments={"request_id": f"s5_medium_{i}"},
                )
            )
        # 1 slow call
        calls.append(
            ToolCall(
                provider="slow",
                tool="slow_0",
                arguments={"request_id": "s5_slow_0"},
            )
        )
        return calls

    def get_parameters(self) -> dict[str, Any]:
        sequential_total = (
            self.fast_count * self.fast_delay
            + self.medium_count * self.medium_delay
            + self.slow_count * self.slow_delay
        )
        parallel_expected = max(self.fast_delay, self.medium_delay, self.slow_delay)
        return {
            "fast_delay_ms": self.fast_delay,
            "fast_count": self.fast_count,
            "medium_delay_ms": self.medium_delay,
            "medium_count": self.medium_count,
            "slow_delay_ms": self.slow_delay,
            "slow_count": self.slow_count,
            "expected_sequential_ms": sequential_total,
            "expected_parallel_ms": parallel_expected,
            "expected_speedup": round(sequential_total / parallel_expected, 1),
        }

    def get_baselines(self) -> list[str]:
        return ["sequential", "direct_parallel", "hangar_sequential", "hangar_parallel"]


def create_scenarios() -> list[S5MixedLatency]:
    """Create S5 scenarios."""
    return [S5MixedLatency()]
