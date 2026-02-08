"""Hangar sequential baseline: route through Hangar but one call at a time."""

from __future__ import annotations

from mcp_hangar import Hangar

from src.harness import ToolCall
from src.utils.timing import BatchTimingRecord, TimingRecord, now_ns


async def run_hangar_sequential(
    calls: list[ToolCall],
    hangar: Hangar,
) -> BatchTimingRecord:
    """Execute tool calls sequentially through Hangar.

    Each call goes through Hangar's full pipeline (provider management,
    health tracking, etc.) but waits before starting the next.
    """
    timing = BatchTimingRecord()
    timing.batch_start_ns = now_ns()

    for call in calls:
        call_start = now_ns()
        await hangar.invoke(call.provider, call.tool, call.arguments)
        call_end = now_ns()
        timing.call_records.append(TimingRecord(start_ns=call_start, end_ns=call_end))

    timing.batch_end_ns = now_ns()
    return timing
