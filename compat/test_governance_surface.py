"""Axis 3 — deprecated / governance surface through the transition window.

Asserts the gateway's *advertised* posture is consistent across generations and
that task governance **is** advertised — the relay-with-governance stance of
ADR-014, **activated 2026-07-22** (#322). This flipped from ADR-008's relay-only
assertion (that the task capability was absent) when the relay seam went live.
Run against an activated gateway (``relay_tasks_enabled`` at its default True).
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
    assert advertises_tasks, (
        "task governance capability not advertised — expected an ADR-014-activated "
        f"gateway (relay_tasks_enabled default True): {caps}"
    )
    record(
        "both",
        "governance",
        "tasks capability advertised?",
        "present (governed relay)",
        "flipped on ADR-014/#322 activation 2026-07-22",
    )
