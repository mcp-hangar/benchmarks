"""S3: Multi-Provider Fan-out.

Purpose: Parallel calls across different providers (the realistic case).

- Providers: 3-5 controlled_delay instances with different latencies
- Pattern: 1 call to each provider, all in parallel
- Baselines: Sequential (sum of latencies), Direct parallel, Hangar parallel
- Key metric: Total time should equal max(latencies), not sum(latencies)
"""

from __future__ import annotations

from typing import Any

from src.harness import ToolCall
from src.providers.configs import make_provider_config
from src.scenarios.base import BaseScenario


class S3MultiProvider(BaseScenario):
    """Multi-provider fan-out with varying latencies."""

    def __init__(
        self,
        latencies: list[int] | None = None,
    ) -> None:
        self.latencies = latencies or [50, 100, 200, 300, 500]

    @property
    def name(self) -> str:
        lat_str = ", ".join(f"{lat}ms" for lat in self.latencies)
        return f"S3 Multi-Provider ({lat_str})"

    @property
    def scenario_id(self) -> str:
        return "s3_multi_provider"

    def get_provider_configs(self) -> list[dict[str, Any]]:
        return [
            make_provider_config(
                f"provider_{latency}ms",
                call_delay_ms=latency,
                num_tools=1,
                tool_prefix=f"p{latency}",
            )
            for latency in self.latencies
        ]

    def get_calls(self) -> list[ToolCall]:
        return [
            ToolCall(
                provider=f"provider_{latency}ms",
                tool=f"p{latency}_0",
                arguments={"request_id": f"s3_{latency}ms"},
            )
            for latency in self.latencies
        ]

    def get_parameters(self) -> dict[str, Any]:
        return {
            "latencies_ms": self.latencies,
            "num_providers": len(self.latencies),
            "expected_sequential_ms": sum(self.latencies),
            "expected_parallel_ms": max(self.latencies),
        }

    def get_baselines(self) -> list[str]:
        return ["sequential", "direct_parallel", "hangar_sequential", "hangar_parallel"]


def create_scenarios() -> list[S3MultiProvider]:
    """Create S3 scenarios."""
    return [
        S3MultiProvider(latencies=[50, 100, 200, 300, 500]),
        S3MultiProvider(latencies=[100, 100, 100]),
    ]
