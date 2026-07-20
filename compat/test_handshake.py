"""Axis 1 — dual-generation handshake against ONE gateway.

Proves the same running Hangar serves both a legacy (`initialize` + session)
and a modern (`server/discover`, stateless) client.
"""

from __future__ import annotations

import pytest

from compat import clients


def test_legacy_initialize_handshake(hangar: str, record) -> None:
    if not clients.legacy_available():
        pytest.skip("legacy MCP SDK (v1) not importable in this interpreter")
    hs = clients.legacy_handshake(hangar)
    # The stateful handshake must complete and expose a governed tool surface.
    assert hs["server_name"], f"initialize returned no serverInfo.name: {hs}"
    assert hs["tools"], "legacy tools/list returned no tools"
    record(
        "legacy",
        "handshake",
        "initialize",
        "pass",
        f"serverInfo.name={hs['server_name']} protocol={hs['protocol_version']} tools={len(hs['tools'])}",
    )


def test_legacy_invoke_upstream_via_hangar_call(hangar: str, record) -> None:
    if not clients.legacy_available():
        pytest.skip("legacy MCP SDK (v1) not importable in this interpreter")
    out = clients.legacy_hangar_call(hangar, "math", "add", {"a": 2, "b": 3})
    assert out["is_error"] is False, out
    blob = " ".join(c for c in out["content"] if c)
    assert "5" in blob, out
    record(
        "legacy",
        "handshake",
        "tools/call (hangar_call add)",
        "pass",
        f"content~={blob[:60]}",
    )


def test_modern_server_discover(discover: dict, record) -> None:
    assert discover.get("serverInfo", {}).get("name") == "mcp-hangar", discover
    assert discover.get("supportedVersions"), (
        "server/discover advertised no supportedVersions"
    )
    assert isinstance(discover.get("tools"), list), discover
    record(
        "modern",
        "handshake",
        "server/discover",
        "pass",
        f"versions={discover['supportedVersions']} tools={len(discover['tools'])}",
    )
