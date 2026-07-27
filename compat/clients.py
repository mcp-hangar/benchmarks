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

import json
import os
from pathlib import Path
import subprocess
from typing import Any

import httpx

MODERN_PROTOCOL_VERSION = "2026-07-28"

# Per-message HTTP header names the modern (SEP-2243/2575) transport sets.
H_METHOD = "Mcp-Method"
H_NAME = "Mcp-Name"
H_PROTOCOL = "MCP-Protocol-Version"
H_SESSION = "Mcp-Session-Id"

# A 2026-07-28 request is self-describing: with no `initialize` to negotiate
# them, the protocol version, client info and client capabilities travel in the
# reserved `params._meta` envelope on EVERY request. Omitting it is answered
# -32602, which reads like "the gateway does not serve this" but is a client
# error -- the same trap as sending a json-only `Accept` and reading the 406 as
# an unserved endpoint.
META_PROTOCOL_VERSION = "io.modelcontextprotocol/protocolVersion"
META_CLIENT_INFO = "io.modelcontextprotocol/clientInfo"
META_CLIENT_CAPABILITIES = "io.modelcontextprotocol/clientCapabilities"


def modern_meta_envelope() -> dict[str, Any]:
    """The reserved `_meta` envelope every modern request must carry."""
    return {
        META_PROTOCOL_VERSION: MODERN_PROTOCOL_VERSION,
        META_CLIENT_INFO: {"name": "compat-modern", "version": "0"},
        META_CLIENT_CAPABILITIES: {},
    }


# --------------------------------------------------------------------------- #
# Legacy generation (SDK v1, stateful) -- runs OUT OF PROCESS
# --------------------------------------------------------------------------- #
# SDK v1 and v2 cannot coexist in one interpreter (one `mcp` distribution, and
# v2 renamed `streamablehttp_client` -> `streamable_http_client`), so the legacy
# client is driven by `legacy_runner.py` under `.venv-legacy`. `legacy_python()`
# resolves that interpreter; without it the legacy axes skip rather than fail.
_RUNNER = Path(__file__).with_name("legacy_runner.py")
_LEGACY_VENV = Path(__file__).resolve().parents[1] / ".venv-legacy"


def legacy_python() -> str | None:
    """Path to the SDK-v1 interpreter, or ``None`` if the venv is not built."""
    override = os.environ.get("MCP_HANGAR_LEGACY_PYTHON")
    if override and Path(override).exists():
        return override
    candidate = _LEGACY_VENV / "bin" / "python"
    return str(candidate) if candidate.exists() else None


def legacy_available() -> bool:
    """True when the legacy generation can actually be driven."""
    return legacy_python() is not None


def legacy_sdk_version() -> str:
    """The `mcp` version installed in the legacy venv (recorded in the matrix)."""
    python = legacy_python()
    if python is None:
        return "absent"
    out = subprocess.run(
        [python, "-c", "import importlib.metadata as m; print(m.version('mcp'))"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return (out.stdout or "unknown").strip()


def _legacy(request: dict[str, Any], timeout: float = 90.0) -> dict[str, Any]:
    """Run one legacy operation in the v1 interpreter; raises on driver failure."""
    python = legacy_python()
    if python is None:
        raise RuntimeError("legacy venv not built (make compat-venv-legacy)")
    out = subprocess.run(
        [python, str(_RUNNER), json.dumps(request)],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if out.returncode != 0 or not out.stdout.strip():
        raise RuntimeError(f"legacy runner failed rc={out.returncode}: {(out.stderr or '')[:300]}")
    parsed = json.loads(out.stdout.strip().splitlines()[-1])
    if not parsed.get("ok"):
        raise RuntimeError(parsed.get("error", "unknown legacy error"))
    return parsed["data"]


def legacy_handshake(base_url: str) -> dict[str, Any]:
    """Legacy `initialize` handshake + `tools/list`; returns serverInfo + tool names."""
    return _legacy({"base_url": base_url, "op": "handshake"})


def legacy_call(base_url: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Legacy `initialize` + `call_tool(tool, arguments)`."""
    return _legacy({"base_url": base_url, "op": "call", "tool": tool, "arguments": arguments})


def legacy_hangar_call(
    base_url: str, mcp_server: str, tool: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    """Invoke an upstream tool through Hangar's `hangar_call` governance tool (legacy)."""
    return legacy_call(
        base_url,
        "hangar_call",
        {"calls": [{"mcp_server": mcp_server, "tool": tool, "arguments": arguments}]},
    )


def legacy_task_lifecycle(
    base_url: str, mcp_server: str, tool: str, arguments: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Invoke a task-emitting upstream and follow the relayed task to a verdict."""
    return _legacy(
        {
            "base_url": base_url,
            "op": "tasks",
            "mcp_server": mcp_server,
            "tool": tool,
            "arguments": arguments or {},
        }
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

    Returns the raw response so a caller can record status + body.
    """
    body = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "tools/call",
        "params": {"name": tool, "arguments": arguments, "_meta": modern_meta_envelope()},
    }
    headers = {
        H_METHOD: "tools/call",
        H_NAME: tool,
        H_PROTOCOL: MODERN_PROTOCOL_VERSION,
        # Both media types: the modern entry answers 406 without the SSE accept,
        # since a result may be delivered on a stream.
        "Accept": "application/json, text/event-stream",
    }
    return httpx.post(f"{base_url}/mcp", json=body, headers=headers, timeout=timeout)
