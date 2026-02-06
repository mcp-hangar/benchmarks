"""Abstract base class for benchmark scenarios."""

from __future__ import annotations

import abc
import asyncio
import logging
import os
import sys
from typing import Any

# Suppress Hangar's verbose structlog output during benchmarks
os.environ["HANGAR_LOG_LEVEL"] = "ERROR"
logging.getLogger("mcp_hangar").setLevel(logging.ERROR)
logging.getLogger("structlog").setLevel(logging.ERROR)
logging.getLogger().setLevel(logging.ERROR)

try:
    import structlog
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(logging.ERROR),
    )
except Exception:
    pass

from rich.console import Console

from src.baselines.direct_sequential import DirectMCPClient, run_sequential
from src.baselines.direct_parallel import run_parallel
from src.baselines.hangar_sequential import run_hangar_sequential


def _reset_hangar_globals() -> None:
    """Reset all mcp-hangar global singletons to allow re-bootstrapping.

    Hangar uses global singletons for its CQRS command/query/event buses.
    These must be reset between Hangar instances in the same process.
    """
    try:
        # 1. Reset the three CQRS buses
        from mcp_hangar.infrastructure.command_bus import reset_command_bus
        from mcp_hangar.infrastructure.query_bus import reset_query_bus
        from mcp_hangar.infrastructure.event_bus import reset_event_bus

        reset_command_bus()
        reset_query_bus()
        reset_event_bus()

        # 2. Reset the application context
        from mcp_hangar.server.context import reset_context
        reset_context()

        # 3. Reset the security handler
        try:
            from mcp_hangar.application.event_handlers.security_handler import (
                reset_security_handler,
            )
            reset_security_handler()
        except (ImportError, AttributeError):
            pass

        # 4. Reset the saga manager
        try:
            from mcp_hangar.infrastructure import saga_manager as sm_module
            sm_module._saga_manager = None
        except (ImportError, AttributeError):
            pass

        # 5. Reset the rate limiter
        try:
            from mcp_hangar.domain.security.rate_limiter import reset_rate_limiter
            reset_rate_limiter()
        except (ImportError, AttributeError):
            pass

        # 6. Reset truncation
        try:
            from mcp_hangar.server.bootstrap.truncation import reset_truncation
            reset_truncation()
        except (ImportError, AttributeError):
            pass

        # 7. Reset knowledge base
        try:
            import mcp_hangar.infrastructure.knowledge_base as kb_module
            kb_module._instance = None
            kb_module._config = None
        except (ImportError, AttributeError):
            pass

        # 8. Reset server/state.py module-level globals
        try:
            import mcp_hangar.server.state as state_module
            from mcp_hangar.bootstrap.runtime import create_runtime

            new_runtime = create_runtime()
            state_module._RUNTIME = new_runtime
            state_module.PROVIDER_REPOSITORY = new_runtime.repository
            state_module.EVENT_BUS = new_runtime.event_bus
            state_module.COMMAND_BUS = new_runtime.command_bus
            state_module.QUERY_BUS = new_runtime.query_bus
            state_module.RATE_LIMIT_CONFIG = new_runtime.rate_limit_config
            state_module.RATE_LIMITER = new_runtime.rate_limiter
            state_module.INPUT_VALIDATOR = new_runtime.input_validator
            state_module.SECURITY_HANDLER = new_runtime.security_handler
            state_module.PROVIDERS = state_module.ProviderDict(new_runtime.repository)
            state_module.GROUPS.clear()
            state_module.RUNTIME_PROVIDERS = state_module.RuntimeProviderStore()
            state_module._GROUP_REBALANCE_SAGA = None
            state_module._DISCOVERY_ORCHESTRATOR = None
        except (ImportError, AttributeError):
            pass

    except Exception:
        pass  # Best effort — if reset fails, the benchmark will error out naturally
from src.baselines.hangar_parallel import run_hangar_parallel
from src.harness import BenchmarkConfig, ToolCall, run_benchmark
from src.providers.configs import make_provider_config
from src.utils.timing import BatchTimingRecord

from mcp_hangar import Hangar, HangarConfig

console = Console()


class BaseScenario(abc.ABC):
    """Base class for all benchmark scenarios.

    Subclasses must implement:
      - name: human-readable scenario name
      - scenario_id: short identifier (e.g., "s1_baseline")
      - get_provider_configs: return provider configurations
      - get_calls: return the list of tool calls to benchmark
      - get_baselines: return which baselines to run

    The base class handles:
      - Setting up direct MCP clients
      - Setting up Hangar instances
      - Running each baseline through the harness
      - Teardown
    """

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Human-readable scenario name."""
        ...

    @property
    @abc.abstractmethod
    def scenario_id(self) -> str:
        """Short identifier like 's1_baseline'."""
        ...

    @abc.abstractmethod
    def get_provider_configs(self) -> list[dict[str, Any]]:
        """Return provider configurations for this scenario."""
        ...

    @abc.abstractmethod
    def get_calls(self) -> list[ToolCall]:
        """Return the tool calls to benchmark."""
        ...

    def get_parameters(self) -> dict[str, Any]:
        """Return scenario-specific parameters for the result file."""
        return {}

    def get_baselines(self) -> list[str]:
        """Return which baselines to run. Override to customize."""
        return ["sequential", "direct_parallel", "hangar_sequential", "hangar_parallel"]

    async def setup_direct_client(self) -> DirectMCPClient:
        """Create and connect a direct MCP client to all providers."""
        client = DirectMCPClient()
        for cfg in self.get_provider_configs():
            await client.connect(
                cfg["name"],
                cfg["command"],
                cfg.get("env"),
            )
        return client

    async def setup_hangar(self) -> Hangar:
        """Create and start a Hangar instance with all providers."""
        # Reset Hangar's global CQRS singletons to allow multiple instances
        _reset_hangar_globals()

        builder = HangarConfig()
        for cfg in self.get_provider_configs():
            builder.add_provider(
                cfg["name"],
                command=cfg["command"],
                env=cfg.get("env"),
            )
        config = builder.build()
        hangar = await Hangar.from_builder(config).__aenter__()
        return hangar

    async def run(
        self,
        config: BenchmarkConfig,
        baselines: list[str] | None = None,
        output_dir: str = "results/raw",
    ) -> list[dict[str, Any]]:
        """Execute all baselines for this scenario.

        Returns list of result dicts from each baseline.
        """
        active_baselines = baselines or self.get_baselines()
        calls = self.get_calls()
        results: list[dict[str, Any]] = []

        console.print(f"\n[bold magenta]Scenario: {self.name}[/]")
        console.print(f"  ID: {self.scenario_id}")
        console.print(f"  Calls: {len(calls)}")
        console.print(f"  Baselines: {', '.join(active_baselines)}")

        # --- Direct baselines ---
        direct_client: DirectMCPClient | None = None
        needs_direct = any(
            b in active_baselines for b in ["sequential", "direct_parallel"]
        )

        if needs_direct:
            console.print("[dim]Setting up direct MCP clients...[/]")
            direct_client = await self.setup_direct_client()

        try:
            if "sequential" in active_baselines and direct_client:
                result = await run_benchmark(
                    name=f"{self.name} — Sequential",
                    scenario=self.scenario_id,
                    baseline="sequential",
                    calls=calls,
                    benchmark_fn=lambda c: run_sequential(c, direct_client),  # type: ignore[arg-type]
                    config=config,
                    parameters=self.get_parameters(),
                    output_dir=output_dir,
                )
                results.append(result)

            if "direct_parallel" in active_baselines and direct_client:
                result = await run_benchmark(
                    name=f"{self.name} — Direct Parallel",
                    scenario=self.scenario_id,
                    baseline="direct_parallel",
                    calls=calls,
                    benchmark_fn=lambda c: run_parallel(c, direct_client),  # type: ignore[arg-type]
                    config=config,
                    parameters=self.get_parameters(),
                    output_dir=output_dir,
                )
                results.append(result)
        finally:
            if direct_client:
                await direct_client.close()

        # --- Hangar baselines ---
        hangar: Hangar | None = None
        needs_hangar = any(
            b in active_baselines for b in ["hangar_sequential", "hangar_parallel"]
        )

        if needs_hangar:
            console.print("[dim]Setting up Hangar...[/]")
            hangar = await self.setup_hangar()

        try:
            if "hangar_sequential" in active_baselines and hangar:
                result = await run_benchmark(
                    name=f"{self.name} — Hangar Sequential",
                    scenario=self.scenario_id,
                    baseline="hangar_sequential",
                    calls=calls,
                    benchmark_fn=lambda c: run_hangar_sequential(c, hangar),  # type: ignore[arg-type]
                    config=config,
                    parameters=self.get_parameters(),
                    output_dir=output_dir,
                )
                results.append(result)

            if "hangar_parallel" in active_baselines and hangar:
                result = await run_benchmark(
                    name=f"{self.name} — Hangar Parallel",
                    scenario=self.scenario_id,
                    baseline="hangar_parallel",
                    calls=calls,
                    benchmark_fn=lambda c: run_hangar_parallel(c, hangar),  # type: ignore[arg-type]
                    config=config,
                    parameters=self.get_parameters(),
                    output_dir=output_dir,
                )
                results.append(result)
        finally:
            if hangar:
                await hangar.stop()

        return results
