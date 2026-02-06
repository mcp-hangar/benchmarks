"""Provider configurations for each benchmark scenario."""

from __future__ import annotations

import sys
from typing import Any


def _provider_command(
    *,
    call_delay_ms: int = 100,
    startup_delay_ms: int = 0,
    num_tools: int = 5,
    tool_prefix: str = "bench_tool",
    payload_size: int = 256,
) -> list[str]:
    """Build the command to run a controlled delay provider."""
    return [
        sys.executable,
        "-m",
        "src.providers.controlled_delay",
    ]


def _provider_env(
    *,
    call_delay_ms: int = 100,
    startup_delay_ms: int = 0,
    num_tools: int = 5,
    tool_prefix: str = "bench_tool",
    payload_size: int = 256,
) -> dict[str, str]:
    """Build environment variables for a controlled delay provider."""
    return {
        "BENCH_CALL_DELAY_MS": str(call_delay_ms),
        "BENCH_STARTUP_DELAY_MS": str(startup_delay_ms),
        "BENCH_NUM_TOOLS": str(num_tools),
        "BENCH_TOOL_PREFIX": str(tool_prefix),
        "BENCH_PAYLOAD_SIZE": str(payload_size),
    }


def make_provider_config(
    name: str,
    *,
    call_delay_ms: int = 100,
    startup_delay_ms: int = 0,
    num_tools: int = 5,
    tool_prefix: str = "bench_tool",
    payload_size: int = 256,
) -> dict[str, Any]:
    """Create a provider configuration dict for Hangar."""
    return {
        "name": name,
        "command": _provider_command(
            call_delay_ms=call_delay_ms,
            startup_delay_ms=startup_delay_ms,
            num_tools=num_tools,
            tool_prefix=tool_prefix,
            payload_size=payload_size,
        ),
        "env": _provider_env(
            call_delay_ms=call_delay_ms,
            startup_delay_ms=startup_delay_ms,
            num_tools=num_tools,
            tool_prefix=tool_prefix,
            payload_size=payload_size,
        ),
    }


# --- Scenario-specific configurations ---


def s1_baseline_configs(delay_ms: int = 100) -> list[dict[str, Any]]:
    """S1: Single provider, varying delays."""
    return [
        make_provider_config(
            f"delay_{delay_ms}ms",
            call_delay_ms=delay_ms,
            num_tools=1,
            tool_prefix="baseline",
        )
    ]


def s2_fanout_configs(num_tools: int = 10) -> list[dict[str, Any]]:
    """S2: Single provider with N tools for fan-out."""
    return [
        make_provider_config(
            "fanout",
            call_delay_ms=100,
            num_tools=num_tools,
            tool_prefix="fanout",
        )
    ]


def s3_multi_provider_configs() -> list[dict[str, Any]]:
    """S3: Multiple providers with different latencies."""
    latencies = [50, 100, 200, 300, 500]
    configs = []
    for latency in latencies:
        configs.append(
            make_provider_config(
                f"provider_{latency}ms",
                call_delay_ms=latency,
                num_tools=1,
                tool_prefix=f"p{latency}",
            )
        )
    return configs


def s4_cold_start_configs() -> list[dict[str, Any]]:
    """S4: Providers with significant cold start time."""
    return [
        make_provider_config(
            f"cold_{i}",
            call_delay_ms=50,
            startup_delay_ms=500,
            num_tools=1,
            tool_prefix=f"cold{i}",
        )
        for i in range(3)
    ]


def s5_mixed_latency_configs() -> list[dict[str, Any]]:
    """S5: Fast, medium, slow providers."""
    return [
        make_provider_config("fast", call_delay_ms=10, num_tools=5, tool_prefix="fast"),
        make_provider_config(
            "medium", call_delay_ms=100, num_tools=3, tool_prefix="medium"
        ),
        make_provider_config("slow", call_delay_ms=500, num_tools=1, tool_prefix="slow"),
    ]


def s6_agent_workflow_configs() -> list[dict[str, Any]]:
    """S6: Providers simulating realistic agent tools."""
    return [
        make_provider_config(
            "fetch",
            call_delay_ms=200,
            num_tools=1,
            tool_prefix="fetch",
            payload_size=1024,
        ),
        make_provider_config(
            "search",
            call_delay_ms=300,
            num_tools=1,
            tool_prefix="search",
            payload_size=512,
        ),
        make_provider_config(
            "filesystem",
            call_delay_ms=50,
            num_tools=1,
            tool_prefix="fs",
            payload_size=128,
        ),
    ]
