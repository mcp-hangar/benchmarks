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

# Minimal, backend-lazy config: one cold subprocess provider (math). The gateway
# serves /health, /metrics, server/discover, and (on invoke) the math tools.
_MINIMAL_CONFIG = """\
logging:
  level: WARNING
mcp_servers:
  math:
    mode: subprocess
    command: ["{python}", "{server}"]
    idle_ttl_s: 60
"""


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
def hangar() -> Iterator[str]:
    """A single running Hangar over HTTP; both client generations target it."""
    if not _MATH_SERVER.exists():
        pytest.skip(f"math stub not found at {_MATH_SERVER} (set MCP_HANGAR_REPO)")
    import tempfile

    with tempfile.TemporaryDirectory(prefix="compat_hangar_") as d:
        yield from _serve_hangar(
            Path(d),
            _MINIMAL_CONFIG.format(python=sys.executable, server=str(_MATH_SERVER)),
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
