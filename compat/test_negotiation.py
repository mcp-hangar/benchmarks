"""Axis 2 — version negotiation and the modern stateless surface."""

from __future__ import annotations

from compat import clients


def test_supported_versions_advertised(discover: dict, record) -> None:
    versions = discover.get("supportedVersions") or []
    assert versions, "no supportedVersions advertised"
    has_modern = clients.MODERN_PROTOCOL_VERSION in versions
    record(
        "modern",
        "negotiation",
        "supportedVersions",
        "pass" if has_modern else "info",
        f"advertised={versions} modern({clients.MODERN_PROTOCOL_VERSION})={'yes' if has_modern else 'no'}",
    )


def test_discover_tools_are_shaped(discover: dict, record) -> None:
    """The stateless surface must actually describe a tool surface.

    `server/discover` is how a modern client learns what it may call — there is
    no `initialize` and no `tools/list` handshake to fall back on. An empty
    `tools` on a gateway with a configured backend leaves that client with
    nothing (mcp-hangar#606).
    """
    tools = discover.get("tools") or []
    shaped = bool(tools) and all(isinstance(t, dict) and t.get("name") for t in tools)

    record(
        "modern",
        "negotiation",
        "discover.tools shape",
        "pass" if shaped else "fail",
        f"tools={[t.get('name') for t in tools][:8] if tools else '[] (empty)'}",
    )

    assert tools, "server/discover advertised no tools"
    assert shaped, tools


def test_modern_stateless_tool_call_is_served(hangar: str, record) -> None:
    """A stateless POST /mcp tools/call — no session, modern routing headers.

    A hard gate, not a recorded observation. It was recorded while the modern
    surface was still landing; the gateway serves it now (mcp-hangar#560/#594),
    so a regression here should fail the harness rather than quietly flip a cell
    in the matrix.

    Note what "served" required on the client side: the reserved `params._meta`
    envelope AND an Accept covering `text/event-stream`. Omitting either is
    answered -32602 / 406 and reads like an unserved endpoint.
    """
    resp = clients.modern_tool_call(
        hangar,
        "hangar_call",
        {"calls": [{"mcp_server": "math", "tool": "add", "arguments": {"a": 2, "b": 3}}]},
    )
    body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
    served = resp.status_code == 200 and "result" in body

    record(
        "modern",
        "negotiation",
        "stateless POST /mcp tools/call",
        "pass" if served else "fail",
        f"status={resp.status_code}",
    )

    assert served, f"stateless tools/call not served: HTTP {resp.status_code} {resp.text[:200]}"
