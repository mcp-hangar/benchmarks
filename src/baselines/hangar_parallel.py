"""Hangar parallel baseline: concurrent execution through Hangar."""

from __future__ import annotations

import asyncio
from typing import Any

from src.harness import ToolCall
from src.utils.timing import BatchTimingRecord, TimingRecord, now_ns

from mcp_hangar import Hangar


async def _invoke_with_timing(
    hangar: Hangar,
    call: ToolCall,
) -> TimingRecord:
    """Execute a single Hangar invoke and return its timing record."""
    start = now_ns()
    await hangar.invoke(call.provider, call.tool, call.arguments)
    end = now_ns()
    return TimingRecord(start_ns=start, end_ns=end)


async def run_hangar_parallel(
    calls: list[ToolCall],
    hangar: Hangar,
) -> BatchTimingRecord:
    """Execute tool calls in parallel through Hangar using asyncio.gather.

    All calls are dispatched simultaneously via Hangar.invoke().
    Hangar manages provider lifecycle, connection pooling, and health.
    Wall-clock time should approximate max(individual latencies).
    """
    timing = BatchTimingRecord()
    timing.batch_start_ns = now_ns()

    tasks = [_invoke_with_timing(hangar, call) for call in calls]
    call_records = await asyncio.gather(*tasks)

    timing.batch_end_ns = now_ns()
    timing.call_records = list(call_records)
    return timing
