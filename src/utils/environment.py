"""System environment capture for benchmark reproducibility."""

from __future__ import annotations

import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any


def capture_environment() -> dict[str, Any]:
    """Capture system environment information for benchmark reproducibility."""
    env: dict[str, Any] = {
        "hostname": platform.node(),
        "os": f"{platform.system()} {platform.release()}",
        "os_version": platform.version(),
        "architecture": platform.machine(),
        "cpu": _get_cpu_model(),
        "cpu_cores_physical": os.cpu_count() or 0,
        "python_version": sys.version,
        "python_implementation": platform.python_implementation(),
        "mcp_hangar_version": _get_package_version("mcp-hangar"),
        "mcp_version": _get_package_version("mcp"),
        "asyncio_implementation": _get_asyncio_impl(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "git_commit": _get_git_commit(),
    }
    return env


def _get_cpu_model() -> str:
    """Get CPU model string."""
    try:
        if platform.system() == "Linux":
            result = subprocess.run(
                ["grep", "-m1", "model name", "/proc/cpuinfo"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0 and ":" in result.stdout:
                return result.stdout.split(":", 1)[1].strip()
        elif platform.system() == "Darwin":
            result = subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return platform.processor() or "unknown"


def _get_package_version(package: str) -> str:
    """Get installed package version."""
    try:
        from importlib.metadata import version

        return version(package.replace("-", "_"))
    except Exception:
        try:
            from importlib.metadata import version

            return version(package)
        except Exception:
            return "unknown"


def _get_asyncio_impl() -> str:
    """Detect asyncio event loop implementation."""
    try:
        import uvloop  # noqa: F401

        return "uvloop"
    except ImportError:
        return "default (asyncio)"


def _get_git_commit() -> str:
    """Get current git commit hash."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return "unknown"
