"""S4: Cold Start Deduplication.

Purpose: Demonstrate single-flight cold start optimization.

- Providers: controlled_delay instances with 500ms startup time, 50ms call time
- Pattern: N simultaneous calls to a cold provider
- Key metric: Cold start time with N parallel calls
"""

from __future__ import annotations

from typing import Any

from src.harness import ToolCall
from src.providers.configs import make_provider_config
from src.scenarios.base import BaseScenario


class S4ColdStart(BaseScenario):
    """Cold start deduplication benchmark.

    Tests whether Hangar deduplicates cold starts when multiple
    concurrent calls hit a provider that hasn't been started yet.
    """

    def __init__(
        self,
        num_concurrent_calls: int = 10,
        startup_delay_ms: int = 500,
        call_delay_ms: int = 50,
    ) -> None:
        self.num_concurrent_calls = num_concurrent_calls
        self.startup_delay_ms = startup_delay_ms
        self.call_delay_ms = call_delay_ms

    @property
    def name(self) -> str:
        return (
            f"S4 Cold Start (N={self.num_concurrent_calls}, "
            f"startup={self.startup_delay_ms}ms)"
        )

    @property
    def scenario_id(self) -> str:
        return "s4_cold_start"

    def get_provider_configs(self) -> list[dict[str, Any]]:
        return [
            make_provider_config(
                "cold_provider",
                call_delay_ms=self.call_delay_ms,
                startup_delay_ms=self.startup_delay_ms,
                num_tools=1,
                tool_prefix="cold",
            )
        ]

    def get_calls(self) -> list[ToolCall]:
        return [
            ToolCall(
                provider="cold_provider",
                tool="cold_0",
                arguments={"request_id": f"s4_{i}"},
            )
            for i in range(self.num_concurrent_calls)
        ]

    def get_parameters(self) -> dict[str, Any]:
        return {
            "num_concurrent_calls": self.num_concurrent_calls,
            "startup_delay_ms": self.startup_delay_ms,
            "call_delay_ms": self.call_delay_ms,
            "expected_without_dedup_ms": (
                self.num_concurrent_calls * self.startup_delay_ms + self.call_delay_ms
            ),
            "expected_with_dedup_ms": self.startup_delay_ms + self.call_delay_ms,
        }

    def get_baselines(self) -> list[str]:
        # For cold start, we only compare Hangar parallel
        # (which should deduplicate) vs sequential (which starts once then reuses)
        return ["sequential", "hangar_parallel"]


def create_scenarios() -> list[S4ColdStart]:
    """Create S4 scenarios for varying concurrency levels."""
    concurrencies = [1, 5, 10, 20]
    return [S4ColdStart(num_concurrent_calls=n) for n in concurrencies]
