"""Axis 4 — the governed task relay, driven through the same one gateway.

The issue that specified this harness wrote the axis against **ADR-008**: assert
that an upstream task handle is refused with ``TaskRelayNotSupported``, promptly.
ADR-014 superseded that — the relay is live and governed (mcp-hangar#585) — so
the axis now asserts the opposite contract: the handle is *relayed*, the task
runs to completion under Hangar's governance, and the payload comes back.

The failure this still guards against is the same one ADR-008 feared: a client
left hanging on a task nobody owns. Hence the bound on elapsed time and the
explicit terminal-status assertion.
"""

from __future__ import annotations

import pytest

from compat import clients

_SERVER = "task-upstream"


@pytest.fixture(scope="module")
def relay_ready(hangar: str, task_backend: int | None, record) -> str:
    """Skip the axis (recording why) unless a task-emitting backend is running."""
    if task_backend is None:
        record(
            "legacy",
            "tasks",
            "relay lifecycle",
            "skipped",
            "no task-emitting upstream available (examples/task_upstream, mcp-hangar#597)",
        )
        pytest.skip("task-emitting upstream not available")
    if not clients.legacy_available():
        record("legacy", "tasks", "relay lifecycle", "skipped", "legacy SDK venv not built")
        pytest.skip("legacy venv not built (make compat-venv-legacy)")
    return hangar


def test_task_handle_is_relayed_not_refused(relay_ready: str, record) -> None:
    """A tool call that returns a task handle survives the gateway (ADR-014)."""
    outcome = clients.legacy_task_lifecycle(relay_ready, _SERVER, "long_job", {"prompt": "compat"})
    invoke = outcome.get("invoke") or {}

    record(
        "legacy",
        "tasks",
        "tools/call -> task handle",
        "pass" if outcome.get("task_id") else "fail",
        f"success={invoke.get('success')} error_type={invoke.get('error_type')} task={outcome.get('task_id')}",
    )

    assert invoke.get("error_type") != "TaskRelayNotSupported", (
        "the gateway still refuses task handles — ADR-008 behaviour on an ADR-014 build"
    )
    assert outcome.get("task_id"), f"no task handle came back: {invoke}"


def test_relayed_task_reaches_a_terminal_state(relay_ready: str, record) -> None:
    """The client is never left hanging: the task resolves, and it resolves *completed*."""
    outcome = clients.legacy_task_lifecycle(relay_ready, _SERVER, "long_job", {"prompt": "compat"})
    status = outcome.get("status")

    record(
        "legacy",
        "tasks",
        "tasks/get -> terminal status",
        "pass" if status == "completed" else "fail",
        f"status={status}",
    )

    assert status in ("completed", "failed", "cancelled"), f"task never reached a terminal state: {status}"
    assert status == "completed", f"expected the governed task to complete, got {status}"


def test_relayed_task_returns_its_payload(relay_ready: str, record) -> None:
    """tasks/result returns the upstream payload through Hangar's governance."""
    outcome = clients.legacy_task_lifecycle(relay_ready, _SERVER, "long_job", {"prompt": "compat"})
    text = outcome.get("result_text") or ""

    record(
        "legacy",
        "tasks",
        "tasks/result -> payload",
        "pass" if text.startswith("Completed") else "fail",
        f"payload={text[:60]!r}",
    )

    assert text.startswith("Completed"), f"unexpected task payload: {text[:120]!r}"


def test_consent_gated_task_fails_closed_for_a_client_that_cannot_answer(
    relay_ready: str, record
) -> None:
    """A task parking on input_required must fail closed, not hang, when nobody can consent.

    This legacy client negotiates no ``elicitation`` capability, so Hangar has no
    back channel to ask. Governance must resolve that terminally.
    """
    outcome = clients.legacy_task_lifecycle(relay_ready, _SERVER, "long_job_consent", {"prompt": "gate"})
    status = outcome.get("status")

    record(
        "legacy",
        "tasks",
        "consent gate without elicitation",
        "pass" if status == "failed" else "fail",
        f"status={status}",
    )

    assert status == "failed", f"expected the consent gate to fail closed, got {status}"
