"""S7: how many in-flight governed tasks does one Hangar process actually hold?

Every other scenario in this suite measures throughput of *synchronous* tool
calls. This one measures a ceiling, and it exists because the ADR-014 task relay
has one that nobody declared.

## The mechanism under test

`fastmcp_server/task_relay_handlers.py` dispatches every follow-up through
`asyncio.to_thread(...)` -- both the ledger operations (`find_owned_key`,
`get_task`, `update_snapshot`, ...) and, critically, the upstream forward
`relay_request`, which is a **blocking network call with a 30 s timeout**.

`asyncio.to_thread` submits to the running loop's *default* executor. Nothing in
`mcp_hangar` ever calls `loop.set_default_executor(...)` -- verified by grep over
the whole package -- so that is CPython's stock `ThreadPoolExecutor`, whose
`max_workers` is `min(32, os.cpu_count() + 4)`.

So concurrent in-flight task follow-ups are capped by a thread pool sized off the
CPU count, while what they are waiting on is *network* latency. On a 2 vCPU pod
that is **6 workers**; on 4 vCPU, **8**. Past that, requests do not fail -- they
queue, and p99 grows in steps of the upstream latency:

    p99(N) ~= ceil(N / workers) * upstream_latency

That is the number this scenario produces, so the docs can state a supported
in-flight figure instead of implying it is unbounded.

## Two modes, because one of them would be arguing from theory

* `--mode pool` -- a bare `asyncio.to_thread` sweep against a sleep of known
  duration. Isolates the mechanism with nothing else in the frame. If the knee
  does not appear here, the premise is wrong and the relay numbers mean nothing.
* `--mode relay` -- the same sweep driven through a real `GovernedTaskStore`,
  `TaskOwnershipRegistry`, `TaskDigestGuard` and a stub upstream router with the
  same controlled latency. Adds the ledger, ownership check and event publishing
  that the synthetic mode omits, so the reported ceiling is the one an operator
  actually gets.

Both write the same record shape into `results/raw`, tagged `scenario: "s7"`.

## What this deliberately does NOT measure

Not an end-to-end HTTP benchmark. There is no gateway, no transport, no client.
Mixing those in would fold connection handling and the streamable-HTTP session
layer into a number whose whole point is to isolate the dispatch ceiling. The
e2e counterpart belongs in `examples/task_upstream`, which drives real traffic.

It also does not measure task *storage* limits. `GovernedTaskStore` is bounded by
its own TTL/LRU caps and evicts deterministically; that is a configured number,
not a discovered one.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

from rich.console import Console
from rich.table import Table

from src.utils.environment import capture_environment

console = Console()

#: Concurrency levels swept by default. Straddles the pool ceiling on every
#: plausible pod size (2 vCPU -> 6 workers, 4 -> 8, 8 -> 12, 16 -> 20) so the
#: knee is inside the sweep rather than off the end of it.
DEFAULT_CONCURRENCIES: tuple[int, ...] = (1, 2, 4, 8, 12, 16, 24, 32, 48, 64, 96, 128)

#: Stand-in for upstream round-trip time. Long enough to dominate scheduling
#: noise, short enough that a 128-wide sweep finishes in seconds.
DEFAULT_UPSTREAM_MS: float = 50.0


def default_pool_workers() -> int:
    """The ceiling CPython imposes on `asyncio.to_thread`, from its own formula."""
    return min(32, (os.cpu_count() or 1) + 4)


@dataclass
class LevelResult:
    """One concurrency level of the sweep."""

    concurrency: int
    completed: int
    failed: int
    wall_clock_ms: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    max_ms: float
    throughput_ops_s: float
    #: Latency predicted purely by queueing on the pool. The measured p99 tracking
    #: this is what identifies the pool as the binding constraint rather than, say,
    #: the ledger lock.
    predicted_p99_ms: float
    #: measured / predicted. Near 1.0 => pool-bound. Well above => something else
    #: is also serialising; well below => the operation is not actually blocking.
    p99_ratio: float


@dataclass
class CeilingResult:
    """A full sweep."""

    mode: str
    pool_workers: int
    upstream_ms: float
    ops_per_level: int
    levels: list[LevelResult] = field(default_factory=list)
    knee_concurrency: int | None = None
    environment: dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""
    run_id: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
        if not self.run_id:
            self.run_id = str(uuid.uuid4())[:8]


def _percentile(sorted_values: Sequence[float], q: float) -> float:
    """Nearest-rank percentile.

    Deliberately not `numpy.percentile`: with a handful of samples per level its
    linear interpolation invents latencies that were never observed, which is
    exactly the wrong behaviour when the question is "how bad does the tail get".
    """
    if not sorted_values:
        return 0.0
    rank = max(1, min(len(sorted_values), int(-(-q * len(sorted_values) // 1))))
    return sorted_values[rank - 1]


async def _sweep_level(
    concurrency: int,
    ops: int,
    operation: Callable[[int], Any],
    upstream_ms: float,
    pool_workers: int,
) -> LevelResult:
    """Fire `ops` operations `concurrency`-wide and measure the latency spread."""
    latencies: list[float] = []
    failures = 0
    semaphore = asyncio.Semaphore(concurrency)

    async def _one(index: int) -> None:
        nonlocal failures
        async with semaphore:
            started = time.perf_counter_ns()
            try:
                await operation(index)
            except Exception:
                failures += 1
                return
            finally:
                latencies.append((time.perf_counter_ns() - started) / 1_000_000)

    batch_started = time.perf_counter_ns()
    await asyncio.gather(*(_one(i) for i in range(ops)))
    wall_clock_ms = (time.perf_counter_ns() - batch_started) / 1_000_000

    latencies.sort()
    p99 = _percentile(latencies, 0.99)
    # Every worker can hold exactly one blocking call, so a level `concurrency`
    # wide drains in ceil(concurrency / workers) waves of `upstream_ms` each.
    waves = -(-concurrency // pool_workers)
    predicted_p99 = waves * upstream_ms

    return LevelResult(
        concurrency=concurrency,
        completed=len(latencies) - failures,
        failed=failures,
        wall_clock_ms=round(wall_clock_ms, 3),
        p50_ms=round(_percentile(latencies, 0.50), 3),
        p95_ms=round(_percentile(latencies, 0.95), 3),
        p99_ms=round(p99, 3),
        max_ms=round(latencies[-1] if latencies else 0.0, 3),
        throughput_ops_s=round(len(latencies) / (wall_clock_ms / 1000), 1) if wall_clock_ms else 0.0,
        predicted_p99_ms=round(predicted_p99, 3),
        p99_ratio=round(p99 / predicted_p99, 3) if predicted_p99 else 0.0,
    )


def _make_pool_operation(upstream_ms: float) -> Callable[[int], Any]:
    """Synthetic: a blocking sleep dispatched exactly the way the relay dispatches."""
    seconds = upstream_ms / 1000

    async def _operation(_index: int) -> None:
        await asyncio.to_thread(time.sleep, seconds)

    return _operation


def _make_relay_operation(upstream_ms: float, ops: int) -> Callable[[int], Any]:
    """Real `GovernedTaskStore` follow-up: ownership lookup, upstream hop, snapshot.

    Mirrors the read path of the `tasks/get` handler -- `find_owned_key`, the
    `to_thread`-dispatched upstream forward, then `update_snapshot` -- rather than
    calling the handler itself, which would drag in an MCP server, a request
    context and an identity bridge for no extra signal about the ceiling.
    """
    try:
        from mcp_hangar.application.tasks import GovernedTaskStore
        from mcp_hangar.domain.services.task_digest_guard import TaskDigestGuard
        from mcp_hangar.domain.services.task_ownership import TaskOwnershipRegistry
    except ModuleNotFoundError as exc:  # pragma: no cover -- environment guard
        import importlib.metadata as metadata

        try:
            installed = metadata.version("mcp-hangar")
        except metadata.PackageNotFoundError:
            installed = "not installed"
        raise RuntimeError(
            f"--mode relay needs the governed task relay, which ships only on the 2.x line "
            f"(installed: mcp-hangar {installed}). Install a 2.x core into this venv -- "
            f"`uv pip install --pre 'mcp-hangar>=2.0.0rc1'`, or `uv pip install -e ../mcp-hangar` "
            f"for a local build -- and re-run. `--mode pool` needs no Hangar at all."
        ) from exc

    seconds = upstream_ms / 1000
    published: list[Any] = []

    store = GovernedTaskStore(
        registry=TaskOwnershipRegistry(),
        digest_guard=TaskDigestGuard(),
        # The real bus fans out to audit/metrics handlers whose cost is not what
        # is being measured; collecting keeps the publish call on the hot path.
        event_publisher=published.append,
    )

    target = "bench-upstream"
    keys = _seed_tasks(store, target, max(ops, 1))

    def _upstream_call(_method: str, _params: dict[str, Any]) -> dict[str, Any]:
        time.sleep(seconds)
        return {"result": {"task": {"status": "working"}}}

    async def _operation(index: int) -> None:
        key = keys[index % len(keys)]
        await asyncio.to_thread(store.get_task, key)
        await asyncio.to_thread(_upstream_call, "tasks/get", {"task_id": key[1]})
        await asyncio.to_thread(store.update_snapshot, key, "working", None)

    return _operation


def _seed_tasks(store: Any, target: str, count: int) -> list[tuple[str, str]]:
    """Register `count` owned tasks through the ledger's real registration path.

    Runs as the *unattributed* caller -- no identity contextvar is bound, so
    `GovernedTaskStore._current_caller()` yields `TaskOwner(None, None)` and the
    registration's `expected_owner` agrees with it. That is the honest setup for
    this measurement: binding a fake tenant would mean benchmarking a code path
    reachable only with an auth stack that is not present here, and the ledger
    work per operation is identical either way -- `authorize()` compares two
    fields whichever values they hold.

    The ledger's TTL/LRU cap is left at its default. If `count` ever exceeds it
    the oldest entries evict and their `get_task` returns `None`, which the
    operation tolerates: an evicted read still pays the full authorize + lock
    cost, which is what is being timed.
    """
    from mcp_hangar.domain.services.task_ownership import TaskOwner
    from mcp_types import Task

    owner = TaskOwner(tenant_id=None, principal_id=None)
    now = datetime.now(timezone.utc).isoformat()
    keys: list[tuple[str, str]] = []

    for index in range(count):
        task_id = f"bench-task-{index}"
        store.register_relayed_task(
            target_server_id=target,
            # Wire aliases, and `ttl` is REQUIRED here -- this is the SEP-1686
            # shape `mcp_types` still carries. SEP-2663 renames it `ttlMs` and
            # makes it nullable, which is the whole reason the relay wire is
            # being realigned; when that lands, this literal changes with it.
            task=Task.model_validate(
                {
                    "taskId": task_id,
                    "status": "working",
                    "createdAt": now,
                    "lastUpdatedAt": now,
                    "ttl": 300_000,
                }
            ),
            expected_owner=owner,
        )
        keys.append((target, task_id))
    return keys


def _find_knee(levels: list[LevelResult], upstream_ms: float) -> int | None:
    """Highest concurrency that still drains in a single pool wave.

    "Knee" here is where added concurrency stops buying throughput and starts
    only buying latency: below it every operation gets a worker immediately and
    p99 is one upstream round-trip; above it operations queue and p99 jumps by a
    whole round-trip per extra wave.

    So the comparison is against the *single-wave floor* (`upstream_ms`), NOT
    against `predicted_p99_ms`. The prediction grows with concurrency by
    construction, so a ratio against it stays near 1.0 at every level and would
    nominate the widest level swept as the knee -- which is how the first version
    of this function reported 128 on a 22-worker pool.

    A threshold rather than a slope: the steps are sharp, and a slope estimate
    over a dozen points would smear the very edge being reported.
    """
    knee: int | None = None
    for level in levels:
        if level.failed or level.p99_ms > 1.5 * upstream_ms:
            break
        knee = level.concurrency
    return knee


async def run_task_ceiling(
    mode: str = "pool",
    concurrencies: Sequence[int] = DEFAULT_CONCURRENCIES,
    ops_per_level: int = 200,
    upstream_ms: float = DEFAULT_UPSTREAM_MS,
    output_dir: str = "results/raw",
    workers: int | None = None,
) -> CeilingResult:
    """Sweep concurrency and report where in-flight task follow-ups stop scaling.

    `workers` overrides the default executor width, which is how a pod size other
    than the benchmark host's can be measured rather than extrapolated: a 2 vCPU
    pod gets `min(32, 2 + 4) = 6`, a 4 vCPU pod 8. Passing it installs a pool of
    exactly that width as the loop's default executor, so `asyncio.to_thread`
    -- and therefore the relay -- lands on it unchanged.
    """
    pool_workers = workers if workers is not None else default_pool_workers()

    if workers is not None:
        # Must be the *default* executor, not one passed explicitly: the relay
        # calls bare `asyncio.to_thread`, which only ever consults this slot.
        from concurrent.futures import ThreadPoolExecutor

        asyncio.get_running_loop().set_default_executor(
            ThreadPoolExecutor(max_workers=workers, thread_name_prefix="s7-bench-")
        )

    if mode == "pool":
        operation = _make_pool_operation(upstream_ms)
    elif mode == "relay":
        operation = _make_relay_operation(upstream_ms, ops_per_level)
    else:
        raise ValueError(f"unknown mode: {mode!r} (expected 'pool' or 'relay')")

    result = CeilingResult(
        mode=mode,
        pool_workers=pool_workers,
        upstream_ms=upstream_ms,
        ops_per_level=ops_per_level,
        environment=capture_environment(),
    )

    # One wave at the narrowest level so the pool has spawned its threads before
    # anything is recorded -- CPython creates them lazily, and the first call
    # into a cold pool pays a thread-creation cost that is not upstream latency.
    await _sweep_level(1, min(8, ops_per_level), operation, upstream_ms, pool_workers)

    for concurrency in concurrencies:
        level = await _sweep_level(concurrency, ops_per_level, operation, upstream_ms, pool_workers)
        result.levels.append(level)
        console.print(
            f"  c={level.concurrency:>4}  "
            f"p50={level.p50_ms:>8.1f}ms  p99={level.p99_ms:>8.1f}ms  "
            f"pred={level.predicted_p99_ms:>7.1f}ms  ratio={level.p99_ratio:>5.2f}  "
            f"{level.throughput_ops_s:>7.1f} ops/s"
            + ("  [red]FAILURES[/]" if level.failed else "")
        )

    result.knee_concurrency = _find_knee(result.levels, upstream_ms)
    _write_result(result, output_dir)
    return result


def _write_result(result: CeilingResult, output_dir: str) -> None:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"s7_task_ceiling_{result.mode}_{result.run_id}.json"
    payload = asdict(result)
    payload["scenario"] = "s7"
    payload["scenario_name"] = "Task In-Flight Ceiling"
    path.write_text(json.dumps(payload, indent=2))
    console.print(f"\n[dim]Wrote {path}[/]")


def print_ceiling_summary(result: CeilingResult) -> None:
    """Print the sweep, and state the number the docs are allowed to quote."""
    table = Table(title=f"S7 Task In-Flight Ceiling ({result.mode} mode)")
    table.add_column("Concurrency", justify="right")
    table.add_column("p50 (ms)", justify="right")
    table.add_column("p99 (ms)", justify="right")
    table.add_column("Predicted p99", justify="right")
    table.add_column("Ratio", justify="right")
    table.add_column("Throughput", justify="right")
    table.add_column("Failed", justify="right")

    for level in result.levels:
        pool_bound = level.concurrency > result.pool_workers
        table.add_row(
            f"[yellow]{level.concurrency}[/]" if pool_bound else str(level.concurrency),
            f"{level.p50_ms:.1f}",
            f"{level.p99_ms:.1f}",
            f"{level.predicted_p99_ms:.1f}",
            f"{level.p99_ratio:.2f}",
            f"{level.throughput_ops_s:.1f} ops/s",
            f"[red]{level.failed}[/]" if level.failed else "0",
        )

    console.print(table)
    console.print(
        f"\n[bold]Default executor workers:[/] {result.pool_workers} "
        f"(min(32, cpu_count={os.cpu_count()} + 4))"
    )
    console.print(
        f"[bold]Knee:[/] {result.knee_concurrency} concurrent in-flight follow-ups "
        f"at {result.upstream_ms:.0f} ms upstream latency"
    )
    console.print(
        "\n[dim]Nothing fails past the knee -- work queues, and p99 grows in steps of\n"
        "the upstream latency. Quote the knee as the sustained figure, not a hard cap.[/]"
    )


__all__ = [
    "CeilingResult",
    "DEFAULT_CONCURRENCIES",
    "DEFAULT_UPSTREAM_MS",
    "LevelResult",
    "default_pool_workers",
    "print_ceiling_summary",
    "run_task_ceiling",
]
