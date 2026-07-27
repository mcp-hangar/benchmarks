"""Cross-protocol-generation compatibility harness — fixtures.

Runs a *legacy* MCP client (protocol 2025-11-25: ``initialize`` + ``Mcp-Session-Id``,
SDK v1) and a *modern* client (SEP-2575 stateless: ``server/discover`` + ``Mcp-Method``
headers) against **one running Hangar**, asserting both generations are served.

Opt-in and skip-safe, mirroring ``mcp-hangar/tests/live``: without
``MCP_HANGAR_COMPAT=1`` the suite skips; any missing prerequisite (the
``mcp-hangar`` CLI, a free port, a healthy startup) skips rather than fails, so
it is safe to run anywhere. See ``compat/README.md``.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import closing
from pathlib import Path
import os
import shutil
import socket
import subprocess
import sys
import time

import httpx
import pytest

_OPT_IN_ENV = "MCP_HANGAR_COMPAT"

_STARTUP_TIMEOUT_S = 30.0
_POLL_INTERVAL_S = 0.3

# Reuse the math stub shipped with mcp-hangar. Resolved relative to the sibling
# checkout; overridable for other layouts.
# benchmarks/ and mcp-hangar/ are sibling checkouts under repos/.
_MCP_HANGAR_REPO = Path(
    os.environ.get(
        "MCP_HANGAR_REPO",
        str(Path(__file__).resolve().parents[2] / "mcp-hangar"),
    )
)
_MATH_SERVER = _MCP_HANGAR_REPO / "examples" / "provider_math" / "server.py"
# A task-emitting upstream (v2-native Tasks extension) for the relay axis.
_TASK_SERVER = _MCP_HANGAR_REPO / "examples" / "task_upstream" / "server.py"

# Minimal, backend-lazy config: one cold subprocess provider (math). The gateway
# serves /health, /metrics, server/discover, and (on invoke) the math tools.
# The topology mode is overridable via MCP_HANGAR_COMPAT_MODE (default | front_door)
# so the matrix can test both.
_MINIMAL_CONFIG = """\
logging:
  level: WARNING
{tool_access}mcp_servers:
  math:
    mode: subprocess
    command: ["{python}", "{server}"]
    idle_ttl_s: 60
{task_backend}"""

# Appended to the config when the task upstream is available. `remote` because
# that server speaks streamable HTTP, so the harness starts it separately and
# points the gateway at it.
_TASK_BACKEND_CONFIG = """\
  task-upstream:
    mode: remote
    endpoint: http://127.0.0.1:{port}/mcp
    idle_ttl_s: 60
"""


def _tool_access_block() -> str:
    mode = os.environ.get("MCP_HANGAR_COMPAT_MODE", "").strip()
    return f"tool_access:\n  mode: {mode}\n" if mode else ""


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    if os.environ.get(_OPT_IN_ENV) == "1":
        return
    skip = pytest.mark.skip(reason=f"compat harness is opt-in: set {_OPT_IN_ENV}=1")
    for item in items:
        item.add_marker(skip)


def _free_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _hangar_bin() -> str:
    binary = shutil.which("mcp-hangar")
    if binary is None:
        pytest.skip(
            "`mcp-hangar` not on PATH (install the gateway under test, e.g. `pip install --pre mcp-hangar`)"
        )
    return binary


def _serve_hangar(workdir: Path, config_text: str) -> Iterator[str]:
    """Start `mcp-hangar serve --http` with ``config_text``; yield its base URL.

    Skips cleanly if the binary is missing or the server never becomes healthy.
    """
    binary = _hangar_bin()
    config_path = workdir / "config.yaml"
    config_path.write_text(config_text)

    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    proc = subprocess.Popen(
        [
            binary,
            "--config",
            str(config_path),
            "serve",
            "--http",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=str(workdir),
    )

    deadline = time.monotonic() + _STARTUP_TIMEOUT_S
    healthy = False
    try:
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                break
            try:
                if httpx.get(f"{base_url}/health/live", timeout=1.0).status_code == 200:
                    healthy = True
                    break
            except httpx.HTTPError:
                pass
            time.sleep(_POLL_INTERVAL_S)

        if not healthy:
            proc.terminate()
            out = b""
            try:
                out = proc.communicate(timeout=5)[0] or b""
            except subprocess.TimeoutExpired:
                proc.kill()
            pytest.skip(
                f"hangar did not become healthy in {_STARTUP_TIMEOUT_S}s:\n{out.decode(errors='replace')[-2000:]}"
            )

        yield base_url
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


@pytest.fixture(scope="session")
def task_backend() -> Iterator[int | None]:
    """Start the v2-native task-emitting upstream; yields its port, or ``None``.

    Skip-safe by design: the relay axis records "backend absent" rather than
    failing when the sibling checkout has no `examples/task_upstream` (it landed
    with mcp-hangar#597) or when the server cannot start.
    """
    if not _TASK_SERVER.exists():
        yield None
        return
    port = _free_port()
    env = {**os.environ, "MCP_HOST": "127.0.0.1", "MCP_PORT": str(port), "MCP_TASK_WORK_SECONDS": "1.0"}
    proc = subprocess.Popen(
        [sys.executable, str(_TASK_SERVER)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + _STARTUP_TIMEOUT_S
    ready = False
    while time.time() < deadline and proc.poll() is None:
        try:
            # An un-negotiated POST is enough to prove the port is serving.
            httpx.post(f"http://127.0.0.1:{port}/mcp", timeout=1.0)
            ready = True
            break
        except Exception:  # noqa: BLE001 -- still starting
            time.sleep(_POLL_INTERVAL_S)
    try:
        yield port if ready else None
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


@pytest.fixture(scope="session")
def hangar(task_backend: int | None) -> Iterator[str]:
    """A single running Hangar over HTTP; both client generations target it."""
    if not _MATH_SERVER.exists():
        pytest.skip(f"math stub not found at {_MATH_SERVER} (set MCP_HANGAR_REPO)")
    import tempfile

    with tempfile.TemporaryDirectory(prefix="compat_hangar_") as d:
        yield from _serve_hangar(
            Path(d),
            _MINIMAL_CONFIG.format(
                python=sys.executable,
                server=str(_MATH_SERVER),
                tool_access=_tool_access_block(),
                task_backend=(_TASK_BACKEND_CONFIG.format(port=task_backend) if task_backend else ""),
            ),
        )


@pytest.fixture(scope="session")
def hangar_version(hangar: str) -> str:
    """The gateway's own version, read from server/discover — recorded in results."""
    try:
        r = httpx.get(f"{hangar}/server/discover", timeout=5.0)
        if r.status_code == 200:
            return str(r.json().get("serverInfo", {}).get("version", "unknown"))
    except Exception:  # noqa: BLE001 -- best-effort metadata
        pass
    # server/discover may be unavailable; fall back to the CLI version.
    try:
        out = subprocess.run(
            [_hangar_bin(), "--version"], capture_output=True, text=True, timeout=10
        )
        return (out.stdout or out.stderr).strip().split()[-1] or "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


def _legacy_sdk_version() -> str:
    """The `mcp` version in the legacy venv, for the artifact metadata."""
    from compat import clients

    try:
        return clients.legacy_sdk_version()
    except Exception:  # noqa: BLE001 -- metadata is best-effort
        return "unknown"


@pytest.fixture(scope="session")
def record(hangar_version: str) -> Iterator:
    """Collect one row per compatibility check and write the cross-gen matrix.

    Row = {generation, axis, method, verdict, detail}. Written to
    ``compat/results/cross_gen_matrix.json`` with environment metadata — the
    shareable "we ran both protocol generations through one gateway" artifact.
    """
    import datetime
    import importlib.metadata as im
    import json
    import platform

    rows: list[dict] = []

    def _add(
        generation: str, axis: str, method: str, verdict: str, detail: str = ""
    ) -> None:
        rows.append(
            {
                "generation": generation,
                "axis": axis,
                "method": method,
                "verdict": verdict,
                "detail": detail,
            }
        )

    yield _add

    try:
        mcp_ver = im.version("mcp")
    except Exception:  # noqa: BLE001
        mcp_ver = "unknown"
    out = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "environment": {
            "hangar_version": hangar_version,
            "legacy_sdk_version": _legacy_sdk_version(),
            "mcp_sdk_version": mcp_ver,
            "python": platform.python_version(),
        },
        "rows": rows,
    }
    results_dir = Path(__file__).resolve().parent / "results"
    results_dir.mkdir(exist_ok=True)
    (results_dir / "cross_gen_matrix.json").write_text(json.dumps(out, indent=2) + "\n")


@pytest.fixture(scope="session")
def discover(hangar: str, record) -> dict:
    """The modern `server/discover` result, or record-a-gap-and-skip if unserved.

    Keeps modern-surface tests from hard-failing when the running gateway does
    not expose `server/discover` (e.g. it is only wired in the factory path, not
    over `serve --http`) — the matrix records the gap instead.
    """
    from compat import clients

    served, data, detail = clients.modern_discover_probe(hangar)
    if not served or data is None:
        record(
            "modern",
            "handshake",
            "server/discover",
            "GAP: not served on `serve --http`",
            detail,
        )
        pytest.skip(
            f"modern server/discover not exposed by this gateway ({detail}); recorded as a gap"
        )
    return data
