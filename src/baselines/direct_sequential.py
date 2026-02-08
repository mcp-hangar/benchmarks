"""Direct sequential baseline: MCP calls one at a time, no Hangar."""

from __future__ import annotations

from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from src.harness import ToolCall
from src.utils.timing import BatchTimingRecord, TimingRecord, now_ns


class DirectMCPClient:
    """Manages direct MCP client connections to provider subprocesses."""

    def __init__(self) -> None:
        self._sessions: dict[str, ClientSession] = {}
        self._cleanup_fns: list[Any] = []

    async def connect(
        self,
        provider_name: str,
        command: list[str],
        env: dict[str, str] | None = None,
    ) -> None:
        """Connect to a provider subprocess via MCP stdio."""
        import os

        full_env = {**os.environ, **(env or {})}
        server_params = StdioServerParameters(
            command=command[0],
            args=command[1:],
            env=full_env,
        )

        # Use stdio_client to get read/write streams
        ctx = stdio_client(server_params)
        streams = await ctx.__aenter__()
        self._cleanup_fns.append(ctx.__aexit__)

        session = ClientSession(*streams)
        await session.__aenter__()
        self._cleanup_fns.append(session.__aexit__)

        await session.initialize()
        self._sessions[provider_name] = session

    async def call_tool(
        self, provider: str, tool: str, arguments: dict[str, Any]
    ) -> Any:
        """Call a tool on a connected provider."""
        session = self._sessions.get(provider)
        if session is None:
            raise RuntimeError(f"Provider '{provider}' not connected")
        result = await session.call_tool(tool, arguments)
        return result

    async def close(self) -> None:
        """Close all connections."""
        for cleanup in reversed(self._cleanup_fns):
            try:
                await cleanup(None, None, None)
            except Exception:
                pass
        self._sessions.clear()
        self._cleanup_fns.clear()


async def run_sequential(
    calls: list[ToolCall],
    client: DirectMCPClient,
) -> BatchTimingRecord:
    """Execute tool calls sequentially through direct MCP connections.

    Each call waits for the previous one to complete before starting.
    """
    timing = BatchTimingRecord()
    timing.batch_start_ns = now_ns()

    for call in calls:
        call_start = now_ns()
        await client.call_tool(call.provider, call.tool, call.arguments)
        call_end = now_ns()
        timing.call_records.append(TimingRecord(start_ns=call_start, end_ns=call_end))

    timing.batch_end_ns = now_ns()
    return timing
