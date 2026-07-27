"""Render the cross-generation matrix as a readable grid.

Turns ``compat/results/cross_gen_matrix.json`` into the artifact the harness
exists to produce: generations down one axis, the contracts each was checked
against down the other, and the environment both ran in. Mirrors the perf
suite's ``src/analysis`` split — the run collects, the renderer presents.

    python -m compat.render_matrix                    # console
    python -m compat.render_matrix --format markdown  # for a PR or a post
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

_RESULTS = Path(__file__).with_name("results") / "cross_gen_matrix.json"

#: Verdict -> (console glyph, markdown glyph). "info"/"skipped" are deliberately
#: neither pass nor fail: the harness records what it could not assert.
_GLYPH = {
    "pass": ("PASS", "✅"),
    "fail": ("FAIL", "❌"),
    "not-served": ("NOT SERVED", "⬜"),
    "info": ("info", "ℹ️"),
    "skipped": ("skipped", "⏭️"),
}


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"no matrix at {path} — run the harness first (make compat-test)")
    return json.loads(path.read_text())


def _rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    return data.get("rows") or []


def _render_console(data: dict[str, Any]) -> str:
    rows = _rows(data)
    env = data.get("environment", {})
    width = max((len(r.get("method", "")) for r in rows), default=20) + 2

    out: list[str] = []
    out.append("Cross-generation compatibility — both client generations, one gateway")
    out.append(
        f"  hangar={env.get('hangar_version', '?')}  "
        f"modern-sdk={env.get('mcp_sdk_version', '?')}  legacy-sdk={env.get('legacy_sdk_version', '?')}"
    )
    out.append("")
    for generation in ("legacy", "modern"):
        gen_rows = [r for r in rows if r.get("generation") == generation]
        if not gen_rows:
            continue
        out.append(f"{generation.upper()}")
        for axis in dict.fromkeys(r.get("axis") for r in gen_rows):
            out.append(f"  {axis}")
            for row in [r for r in gen_rows if r.get("axis") == axis]:
                glyph = _GLYPH.get(row.get("verdict", ""), (row.get("verdict", "?"), "?"))[0]
                out.append(f"    {row.get('method', ''):<{width}} {glyph:<11} {row.get('detail', '')[:70]}")
        out.append("")

    verdicts = [r.get("verdict") for r in rows]
    out.append(
        f"{verdicts.count('pass')} pass · {verdicts.count('fail')} fail · "
        f"{verdicts.count('not-served')} not-served · {verdicts.count('skipped')} skipped"
    )
    return "\n".join(out)


def _render_markdown(data: dict[str, Any]) -> str:
    rows = _rows(data)
    env = data.get("environment", {})
    out: list[str] = []
    out.append("### Cross-generation compatibility")
    out.append("")
    out.append(
        f"One gateway (`{env.get('hangar_version', '?')}`), two client generations — "
        f"legacy SDK `{env.get('legacy_sdk_version', '?')}`, modern SDK `{env.get('mcp_sdk_version', '?')}`."
    )
    out.append("")
    out.append("| Generation | Axis | Contract | Verdict | Detail |")
    out.append("| --- | --- | --- | --- | --- |")
    for row in rows:
        glyph = _GLYPH.get(row.get("verdict", ""), ("?", "?"))[1]
        detail = str(row.get("detail", "")).replace("|", "\\|").replace("\n", " ")[:90]
        out.append(
            f"| {row.get('generation', '')} | {row.get('axis', '')} | "
            f"{row.get('method', '')} | {glyph} {row.get('verdict', '')} | {detail} |"
        )
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--format", choices=("console", "markdown"), default="console")
    parser.add_argument("--results", type=Path, default=_RESULTS)
    args = parser.parse_args()

    data = _load(args.results)
    print(_render_markdown(data) if args.format == "markdown" else _render_console(data))
    return 1 if any(r.get("verdict") == "fail" for r in _rows(data)) else 0


if __name__ == "__main__":
    sys.exit(main())
