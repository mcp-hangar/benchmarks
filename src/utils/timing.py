"""High-resolution timing utilities for benchmarking."""

from __future__ import annotations

import contextlib
import time
from dataclasses import dataclass, field
from typing import AsyncIterator, Iterator


def now_ns() -> int:
    """Return current monotonic time in nanoseconds."""
    return time.perf_counter_ns()


def ns_to_ms(ns: int) -> float:
    """Convert nanoseconds to milliseconds."""
    return ns / 1_000_000


@dataclass
class TimingRecord:
    """A single timing measurement."""

    start_ns: int
    end_ns: int

    @property
    def elapsed_ns(self) -> int:
        return self.end_ns - self.start_ns

    @property
    def elapsed_ms(self) -> float:
        return ns_to_ms(self.elapsed_ns)


@dataclass
class BatchTimingRecord:
    """Timing for a batch of calls: overall wall-clock + per-call latencies."""

    batch_start_ns: int = 0
    batch_end_ns: int = 0
    call_records: list[TimingRecord] = field(default_factory=list)

    @property
    def wall_clock_ns(self) -> int:
        return self.batch_end_ns - self.batch_start_ns

    @property
    def wall_clock_ms(self) -> float:
        return ns_to_ms(self.wall_clock_ns)

    @property
    def per_call_latencies_ns(self) -> list[int]:
        return [r.elapsed_ns for r in self.call_records]

    @property
    def per_call_latencies_ms(self) -> list[float]:
        return [r.elapsed_ms for r in self.call_records]


@contextlib.contextmanager
def timed() -> Iterator[TimingRecord]:
    """Context manager that records start/end timestamps.

    Usage:
        with timed() as t:
            do_work()
        print(t.elapsed_ms)
    """
    record = TimingRecord(start_ns=now_ns(), end_ns=0)
    try:
        yield record
    finally:
        record.end_ns = now_ns()


@contextlib.asynccontextmanager
async def async_timed() -> AsyncIterator[TimingRecord]:
    """Async context manager that records start/end timestamps."""
    record = TimingRecord(start_ns=now_ns(), end_ns=0)
    try:
        yield record
    finally:
        record.end_ns = now_ns()
