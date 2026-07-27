"""Legacy-generation driver, executed by the SDK **v1** interpreter.

The two client generations cannot share a process: SDK v1 exposes
``streamablehttp_client`` and v2 renamed it ``streamable_http_client``, and only
one ``mcp`` distribution can be installed per environment. So the legacy client
runs out-of-process under ``.venv-legacy`` (``mcp==1.28.1``) while pytest itself
runs wherever it likes, and they talk over stdout JSON.

Usage (invoked by :mod:`compat.clients`, not by hand)::

    .venv-legacy/bin/python compat/legacy_runner.py '<json request>'

Request:  {"base_url": ..., "op": "handshake"|"call"|"tasks", ...}
Response: {"ok": true, "data": {...}} | {"ok": false, "error": "..."}
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any


async def _with_session(base_url: str, work):
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    async with streamablehttp_client(f"{base_url}/mcp") as (read, write, _get_session_id):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            return await work(session, init)


def _dump_capabilities(init: Any) -> dict[str, Any]:
    caps = getattr(init, "capabilities", None)
    if caps is None:
        return {}
    if hasattr(caps, "model_dump"):
        return caps.model_dump(mode="json", exclude_none=True)
    return dict(caps)


async def _handshake(session, init) -> dict[str, Any]:
    tools = await session.list_tools()
    return {
        "server_name": getattr(getattr(init, "serverInfo", None), "name", None),
        "server_version": getattr(getattr(init, "serverInfo", None), "version", None),
        "protocol_version": getattr(init, "protocolVersion", None),
        "capabilities": _dump_capabilities(init),
        "tools": [t.name for t in getattr(tools, "tools", []) or []],
    }


def _result_payload(result: Any) -> dict[str, Any]:
    return {
        "is_error": bool(getattr(result, "isError", False)),
        "content": [getattr(c, "text", None) for c in getattr(result, "content", []) or []],
        "structured": getattr(result, "structuredContent", None),
    }


async def _call(session, _init, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return _result_payload(await session.call_tool(tool, arguments))


async def _tasks_raw(base_url: str, request: dict[str, Any]) -> dict[str, Any]:
    """Invoke a task-emitting upstream and follow the relayed task to a verdict.

    Raw JSON-RPC over the v1 transport rather than ``ClientSession``: ``tasks/*``
    are custom methods, and ``send_request`` validates against the typed
    ``ClientRequest`` union, which rejects them. This is also closer to what a
    real legacy client does when driving a surface its SDK does not model.
    """
    import anyio
    from mcp.client.streamable_http import streamablehttp_client
    from mcp.shared.message import SessionMessage
    from mcp.types import JSONRPCMessage, JSONRPCNotification, JSONRPCRequest

    async with streamablehttp_client(f"{base_url}/mcp") as (read, write, _sid):
        next_id = [0]
        pending: dict[int, Any] = {}
        events: dict[int, anyio.Event] = {}

        async with anyio.create_task_group() as tg:

            async def pump() -> None:
                async for message in read:
                    if isinstance(message, Exception):
                        continue
                    root = message.message.root if hasattr(message.message, "root") else message.message
                    rid = getattr(root, "id", None)
                    if rid in events:
                        pending[rid] = root
                        events[rid].set()

            tg.start_soon(pump)

            async def call(method: str, params: dict[str, Any], timeout: float = 30.0) -> dict[str, Any]:
                next_id[0] += 1
                rid = next_id[0]
                event = anyio.Event()
                events[rid] = event
                await write.send(
                    SessionMessage(JSONRPCMessage(JSONRPCRequest(jsonrpc="2.0", id=rid, method=method, params=params)))
                )
                with anyio.fail_after(timeout):
                    await event.wait()
                root = pending.pop(rid)
                error = getattr(root, "error", None)
                if error is not None:
                    raise RuntimeError(f"{method} -> {getattr(error, 'message', error)}")
                return root.result

            await call(
                "initialize",
                {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "compat-legacy", "version": "0"},
                },
            )
            await write.send(
                SessionMessage(
                    JSONRPCMessage(JSONRPCNotification(jsonrpc="2.0", method="notifications/initialized", params={}))
                )
            )

            batch = await call(
                "tools/call",
                {
                    "name": "hangar_call",
                    "arguments": {
                        "calls": [
                            {
                                "mcp_server": request["mcp_server"],
                                "tool": request["tool"],
                                "arguments": request.get("arguments", {}),
                            }
                        ]
                    },
                },
            )
            structured = batch.get("structuredContent") or {}
            first = (structured.get("results") or [{}])[0]
            task = ((first.get("result") or {}).get("task")) or {}
            task_id = task.get("taskId")
            out: dict[str, Any] = {
                "invoke": {
                    "success": first.get("success"),
                    "error": first.get("error"),
                    "error_type": first.get("error_type"),
                    "elapsed_ms": first.get("elapsed_ms"),
                },
                "task_id": task_id,
            }

            if task_id:
                status = None
                for _ in range(20):
                    status = (await call("tasks/get", {"taskId": task_id})).get("status")
                    if status in ("completed", "failed", "cancelled"):
                        break
                    await anyio.sleep(0.5)
                out["status"] = status
                if status == "completed":
                    result = await call("tasks/result", {"taskId": task_id})
                    out["result_text"] = ((result.get("content") or [{}])[0] or {}).get("text")

            tg.cancel_scope.cancel()
            return out


def main() -> int:
    request = json.loads(sys.argv[1])
    base_url = request["base_url"]
    op = request["op"]
    try:
        if op == "handshake":
            data = asyncio.run(_with_session(base_url, _handshake))
        elif op == "call":
            data = asyncio.run(
                _with_session(base_url, lambda s, i: _call(s, i, request["tool"], request.get("arguments", {})))
            )
        elif op == "tasks":
            data = asyncio.run(_tasks_raw(base_url, request))
        else:
            raise ValueError(f"unknown op: {op}")
    except Exception as exc:  # noqa: BLE001 -- the harness reports, never crashes
        import traceback

        detail = "".join(traceback.format_exception(exc))[-1200:]
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}", "traceback": detail}))
        return 0
    print(json.dumps({"ok": True, "data": data}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
