"""
Controlled-delay MCP server for benchmarking.

A custom MCP server with configurable latency for reproducible benchmarks.
Each tool sleeps for a configured duration and returns structured data.

Configurable via environment variables:
  BENCH_STARTUP_DELAY_MS  - Simulated startup time (default: 0)
  BENCH_CALL_DELAY_MS     - Per-call latency in ms (default: 100)
  BENCH_NUM_TOOLS         - Number of tools to expose (default: 5)
  BENCH_TOOL_PREFIX       - Tool name prefix (default: "bench_tool")
  BENCH_PAYLOAD_SIZE      - Response payload size in bytes (default: 256)

Run standalone:
  python -m src.providers.controlled_delay
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time


def _get_env_int(name: str, default: int) -> int:
    return int(os.environ.get(name, str(default)))


def _get_env_str(name: str, default: str) -> str:
    return os.environ.get(name, default)


STARTUP_DELAY_MS = _get_env_int("BENCH_STARTUP_DELAY_MS", 0)
CALL_DELAY_MS = _get_env_int("BENCH_CALL_DELAY_MS", 100)
NUM_TOOLS = _get_env_int("BENCH_NUM_TOOLS", 5)
TOOL_PREFIX = _get_env_str("BENCH_TOOL_PREFIX", "bench_tool")
PAYLOAD_SIZE = _get_env_int("BENCH_PAYLOAD_SIZE", 256)


def _build_payload(size: int) -> str:
    """Build a deterministic payload of approximately the given size."""
    if size <= 0:
        return ""
    base = "x" * size
    return base[:size]


async def _handle_tool_call(tool_name: str, arguments: dict) -> dict:
    """Handle a single tool call with configured delay."""
    request_id = arguments.get("request_id", "")
    delay_override = arguments.get("delay_ms")

    delay_ms = delay_override if delay_override is not None else CALL_DELAY_MS
    delay_s = delay_ms / 1000.0

    start_ns = time.perf_counter_ns()
    if delay_s > 0:
        await asyncio.sleep(delay_s)
    end_ns = time.perf_counter_ns()

    actual_delay_ms = (end_ns - start_ns) / 1_000_000

    return {
        "tool": tool_name,
        "request_id": request_id,
        "configured_delay_ms": delay_ms,
        "actual_delay_ms": round(actual_delay_ms, 3),
        "scheduling_overhead_ms": round(actual_delay_ms - delay_ms, 3),
        "timestamp_ns": end_ns,
        "payload": _build_payload(PAYLOAD_SIZE),
    }


def _build_tool_schemas() -> list[dict]:
    """Build tool schemas for the configured number of tools."""
    schemas = []
    for i in range(NUM_TOOLS):
        tool_name = f"{TOOL_PREFIX}_{i}"
        schemas.append(
            {
                "name": tool_name,
                "description": f"Benchmark tool {i} with configurable delay. "
                f"Default delay: {CALL_DELAY_MS}ms.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "request_id": {
                            "type": "string",
                            "description": "Optional correlation ID for tracking",
                        },
                        "delay_ms": {
                            "type": "number",
                            "description": "Override delay in milliseconds (optional)",
                        },
                    },
                    "required": [],
                },
            }
        )
    return schemas


# --- JSON-RPC stdio MCP server implementation ---
# Uses newline-delimited JSON (NDJSON) transport, matching the `mcp` library.
# Each message is a single line of JSON terminated by \n.


async def _read_message(reader: asyncio.StreamReader) -> dict | None:
    """Read a JSON-RPC message from stdin (NDJSON: one JSON object per line)."""
    while True:
        line_bytes = await reader.readline()
        if not line_bytes:
            return None
        line = line_bytes.decode("utf-8").strip()
        if not line:
            continue
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue


# Write lock to prevent interleaved output from concurrent handlers.
# Created lazily on first use within the event loop.
_write_lock: asyncio.Lock | None = None


def _get_write_lock() -> asyncio.Lock:
    global _write_lock
    if _write_lock is None:
        _write_lock = asyncio.Lock()
    return _write_lock


async def _write_message(data: dict) -> None:
    """Write a JSON-RPC message to stdout (NDJSON: one JSON object per line).

    Uses a lock to prevent interleaved output from concurrent handlers.
    """
    line = json.dumps(data, separators=(",", ":")) + "\n"
    async with _get_write_lock():
        sys.stdout.write(line)
        sys.stdout.flush()


def _make_response(req_id: int | str | None, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _make_error(req_id: int | str | None, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


async def _handle_message(
    msg: dict,
    tool_schemas: list[dict],
    valid_tool_names: set[str],
) -> None:
    """Handle a single JSON-RPC message. Safe to run concurrently."""
    method = msg.get("method", "")
    req_id = msg.get("id")
    params = msg.get("params", {})

    if method == "initialize":
        await _write_message(
            _make_response(
                req_id,
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {
                        "name": "controlled-delay-benchmark",
                        "version": "1.0.0",
                    },
                },
            )
        )
    elif method == "notifications/initialized":
        pass
    elif method == "tools/list":
        await _write_message(
            _make_response(req_id, {"tools": tool_schemas})
        )
    elif method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})
        if tool_name not in valid_tool_names:
            await _write_message(
                _make_error(req_id, -32602, f"Unknown tool: {tool_name}")
            )
        else:
            result = await _handle_tool_call(tool_name, arguments)
            await _write_message(
                _make_response(
                    req_id,
                    {
                        "content": [
                            {"type": "text", "text": json.dumps(result)}
                        ],
                        "isError": False,
                    },
                )
            )
    elif method == "ping":
        await _write_message(_make_response(req_id, {}))
    else:
        if req_id is not None:
            await _write_message(
                _make_error(req_id, -32601, f"Method not found: {method}")
            )


async def _serve() -> None:
    """Run the MCP stdio server with concurrent request handling.

    Reads messages sequentially from stdin but dispatches each to a
    concurrent task, allowing multiple tool calls to execute in parallel.
    """
    # Simulate startup delay
    if STARTUP_DELAY_MS > 0:
        await asyncio.sleep(STARTUP_DELAY_MS / 1000.0)

    tool_schemas = _build_tool_schemas()
    valid_tool_names = {s["name"] for s in tool_schemas}

    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await asyncio.get_event_loop().connect_read_pipe(lambda: protocol, sys.stdin)

    pending_tasks: set[asyncio.Task[None]] = set()

    while True:
        msg = await _read_message(reader)
        if msg is None:
            break

        # Dispatch each message to a concurrent task
        task = asyncio.create_task(
            _handle_message(msg, tool_schemas, valid_tool_names)
        )
        pending_tasks.add(task)
        task.add_done_callback(pending_tasks.discard)

    # Wait for any remaining tasks
    if pending_tasks:
        await asyncio.gather(*pending_tasks, return_exceptions=True)


def main() -> None:
    """Entry point for the controlled delay provider."""
    asyncio.run(_serve())


if __name__ == "__main__":
    main()
