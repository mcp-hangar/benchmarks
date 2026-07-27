"""Axis 3 — deprecated / governance surface through the transition window.

Asserts the gateway's *advertised* posture is consistent across generations and
that task governance **is** advertised — the relay-with-governance stance of
ADR-014, **activated 2026-07-22** (#322). This flipped from ADR-008's relay-only
assertion (that the task capability was absent) when the relay seam went live.
Run against an activated gateway (``relay_tasks_enabled`` at its default True).
"""

from __future__ import annotations


def test_capabilities_advertised(discover: dict, record) -> None:
    """The stateless surface advertises a real capability set.

    Asserts the *shape*, not a specific flag value. This used to assert
    `tools.listChanged is True`, which passed only because the gateway returned a
    hardcoded capability set; the true value is `False` — Hangar does not emit
    per-session `tools/list_changed` (mcp-hangar#234, blocked upstream). Pinning
    the fabricated value would have kept the harness green through exactly the
    bug it exists to catch (mcp-hangar#605).
    """
    caps = discover.get("capabilities") or {}
    has_tools = isinstance(caps.get("tools"), dict)

    record(
        "modern",
        "governance",
        "capabilities shape",
        "pass" if has_tools else "fail",
        f"advertised={sorted(caps)} listChanged={caps.get('tools', {}).get('listChanged')}",
    )

    assert has_tools, f"no tools capability advertised: {caps}"


def test_task_governance_is_advertised(discover: dict, record) -> None:
    """Relay-with-governance (ADR-014, activated 2026-07-22): the task capability
    is advertised once the relay seam is live (#322).

    Flipped from ADR-008's relay-only assertion that it was absent. The seam is
    live per D6/ADR-009 ("advertise once it runs"); the relay itself still only
    engages on an upstream's first real task (D5).
    """
    caps = discover.get("capabilities") or {}
    experimental = caps.get("experimental") or {}
    advertises_tasks = bool(caps.get("tasks")) or any(
        "task" in k.lower() for k in experimental
    )

    # Record BEFORE asserting: a red cell in the matrix is the point of the
    # artifact, and a test that dies before recording leaves a hole instead.
    record(
        "modern",
        "governance",
        "tasks capability via server/discover",
        "pass" if advertises_tasks else "fail",
        f"capabilities={caps}",
    )

    assert advertises_tasks, (
        "task governance is not advertised on the stateless discovery surface. "
        "`initialize` does advertise it, so a modern client -- which has no "
        f"handshake to learn from -- sees a smaller capability set (mcp-hangar#605): {caps}"
    )
