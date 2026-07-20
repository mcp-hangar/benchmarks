"""Axis 3 — deprecated / governance surface through the transition window.

Asserts the gateway's *advertised* posture is consistent across generations and
that dormant task governance is NOT advertised — the relay-only stance of
ADR-008. This assertion **flips** once ADR-014 (relay-with-governance) + #322
land and the task capability is advertised on activation.
"""

from __future__ import annotations


def test_capabilities_advertised(discover: dict, record) -> None:
    caps = discover.get("capabilities") or {}
    # The gateway advertises tools with listChanged; that is the stable surface.
    assert caps.get("tools", {}).get("listChanged") is True, caps
    record(
        "modern",
        "governance",
        "capabilities.tools.listChanged",
        "pass",
        f"capabilities={caps}",
    )


def test_task_governance_is_not_advertised(discover: dict, record) -> None:
    """Relay-only (ADR-008): no task/experimental-tasks capability is advertised.

    Flips to an asserted *presence* when ADR-014's relay seam activates (#322).
    """
    caps = discover.get("capabilities") or {}
    experimental = caps.get("experimental") or {}
    advertises_tasks = bool(caps.get("tasks")) or any(
        "task" in k.lower() for k in experimental
    )
    assert not advertises_tasks, (
        f"task governance unexpectedly advertised (ADR-014 activated?): {caps}"
    )
    record(
        "both",
        "governance",
        "tasks capability advertised?",
        "relay-only (absent)",
        "flips to present after ADR-014/#322",
    )
