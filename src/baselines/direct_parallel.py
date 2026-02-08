"""Direct parallel baseline: MCP calls via asyncio.gather, no Hangar."""

from __future__ import annotations

import asyncio

from src.baselines.direct_sequential import DirectMCPClient
from src.harness import ToolCall
from src.utils.timing import BatchTimingRecord, TimingRecord, now_ns


async def _call_with_timing(
    client: DirectMCPClient,
    call: ToolCall,
) -> TimingRecord:
    """Execute a single call and return its timing record."""
    start = now_ns()
    await client.call_tool(call.provider, call.tool, call.arguments)
    end = now_ns()
    return TimingRecord(start_ns=start, end_ns=end)


async def run_parallel(
    calls: list[ToolCall],
    client: DirectMCPClient,
) -> BatchTimingRecord:
    """Execute tool calls in parallel using asyncio.gather.

    All calls are dispatched simultaneously. Wall-clock time should
    approximate max(individual latencies) rather than sum.
    """
    timing = BatchTimingRecord()
    timing.batch_start_ns = now_ns()

    tasks = [_call_with_timing(client, call) for call in calls]
    call_records = await asyncio.gather(*tasks)

    timing.batch_end_ns = now_ns()
    timing.call_records = list(call_records)
    return timing
