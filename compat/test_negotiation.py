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
    tools = discover.get("tools") or []
    assert tools, "server/discover advertised no tools"
    # Each tool is a serialized MCP Tool: at minimum a name.
    assert all(isinstance(t, dict) and t.get("name") for t in tools), tools
    record(
        "modern",
        "negotiation",
        "discover.tools shape",
        "pass",
        f"tools={[t['name'] for t in tools][:8]}",
    )


def test_modern_stateless_tool_call_recorded(hangar: str, record) -> None:
    """A stateless POST /mcp with modern routing headers and no session.

    Recorded (not asserted): whether the gateway serves a stateless tools/call
    on this build. The value is the data point — the matrix shows served vs
    not-yet-served — not a hard gate, since the stateless invoke path is still
    landing.
    """
    resp = clients.modern_tool_call(
        hangar,
        "hangar_call",
        {
            "calls": [
                {"mcp_server": "math", "tool": "add", "arguments": {"a": 2, "b": 3}}
            ]
        },
    )
    served = resp.status_code == 200 and "result" in (
        resp.json()
        if resp.headers.get("content-type", "").startswith("application/json")
        else {}
    )
    record(
        "modern",
        "negotiation",
        "stateless POST /mcp tools/call",
        "pass" if served else "not-served",
        f"status={resp.status_code}",
    )
