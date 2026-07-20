"""Two client generations, one gateway.

- **legacy** (protocol 2025-11-25): the MCP SDK v1 ``streamablehttp_client`` +
  ``ClientSession.initialize()`` — a stateful handshake that issues an
  ``Mcp-Session-Id``. Async under the hood; exposed here as sync helpers.
- **modern** (SEP-2575 stateless): plain HTTP against ``server/discover`` and a
  stateless ``POST /mcp`` carrying the ``Mcp-Method`` / ``Mcp-Name`` /
  ``MCP-Protocol-Version`` routing headers and **no** session id. Driven with
  ``httpx`` directly, so it exercises the gateway's modern surface without
  depending on a specific client SDK build.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

MODERN_PROTOCOL_VERSION = "2026-07-28"

# Per-message HTTP header names the modern (SEP-2243/2575) transport sets.
H_METHOD = "Mcp-Method"
H_NAME = "Mcp-Name"
H_PROTOCOL = "MCP-Protocol-Version"
H_SESSION = "Mcp-Session-Id"


# --------------------------------------------------------------------------- #
# Legacy generation (SDK v1, stateful)
# --------------------------------------------------------------------------- #
async def _legacy_session(base_url: str, work):
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    async with streamablehttp_client(f"{base_url}/mcp") as (read, write, _):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            return await work(session, init)


async def _handshake(session, init) -> dict[str, Any]:
    tools = await session.list_tools()
    return {
        "server_name": getattr(getattr(init, "serverInfo", None), "name", None),
        "protocol_version": getattr(init, "protocolVersion", None),
        "tools": [t.name for t in getattr(tools, "tools", []) or []],
    }


async def _call_tool(
    session, init, tool: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    result = await session.call_tool(tool, arguments)
    return {
        "is_error": bool(getattr(result, "isError", False)),
        "content": [
            getattr(c, "text", None) for c in getattr(result, "content", []) or []
        ],
    }


def legacy_available() -> bool:
    """True if the SDK v1 legacy client is importable in this interpreter."""
    try:
        import mcp.client.streamable_http  # noqa: F401
        from mcp import ClientSession  # noqa: F401

        return True
    except Exception:  # noqa: BLE001
        return False


def legacy_handshake(base_url: str) -> dict[str, Any]:
    """Legacy `initialize` handshake + `tools/list`; returns serverInfo + tool names."""
    return asyncio.run(_legacy_session(base_url, _handshake))


def legacy_call(base_url: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Legacy `initialize` + `call_tool(tool, arguments)`."""
    return asyncio.run(
        _legacy_session(base_url, lambda s, i: _call_tool(s, i, tool, arguments))
    )


def legacy_hangar_call(
    base_url: str, mcp_server: str, tool: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    """Invoke an upstream tool through Hangar's `hangar_call` governance tool (legacy)."""
    return legacy_call(
        base_url,
        "hangar_call",
        {"calls": [{"mcp_server": mcp_server, "tool": tool, "arguments": arguments}]},
    )


# --------------------------------------------------------------------------- #
# Modern generation (stateless, header-routed)
# --------------------------------------------------------------------------- #
DISCOVER_PATHS = ("/server/discover", "/mcp/server/discover")


def modern_discover_probe(
    base_url: str, timeout: float = 10.0
) -> tuple[bool, dict[str, Any] | None, str]:
    """Probe the modern `server/discover` entrypoint across candidate paths.

    Returns ``(served, discover_result, detail)``. ``served`` is False (rather
    than raising) when the running gateway does not expose the endpoint — the
    harness records that as a mapped compatibility result, not a crash.
    """
    last = ""
    for path in DISCOVER_PATHS:
        try:
            resp = httpx.get(f"{base_url}{path}", timeout=timeout)
        except httpx.HTTPError as exc:
            last = f"{path}: {exc}"
            continue
        if resp.status_code == 200:
            try:
                return True, resp.json(), f"served at {path}"
            except Exception:  # noqa: BLE001
                last = f"{path}: 200 but non-JSON body"
                continue
        last = f"{path}: {resp.status_code}"
    return False, None, last


def modern_discover(base_url: str, timeout: float = 10.0) -> dict[str, Any]:
    """`GET /server/discover` — raises if unavailable. Prefer `modern_discover_probe`."""
    served, data, detail = modern_discover_probe(base_url, timeout)
    if not served or data is None:
        raise RuntimeError(f"server/discover not served: {detail}")
    return data


def modern_tool_call(
    base_url: str,
    tool: str,
    arguments: dict[str, Any],
    *,
    request_id: int = 1,
    timeout: float = 10.0,
) -> httpx.Response:
    """Stateless `POST /mcp` for `tools/call`, with modern routing headers and no session.

    Returns the raw response so a caller can record status + body (the gateway
    may or may not serve a stateless tools/call yet — the harness records which).
    """
    body = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "tools/call",
        "params": {"name": tool, "arguments": arguments},
    }
    headers = {
        H_METHOD: "tools/call",
        H_NAME: tool,
        H_PROTOCOL: MODERN_PROTOCOL_VERSION,
    }
    return httpx.post(f"{base_url}/mcp", json=body, headers=headers, timeout=timeout)
