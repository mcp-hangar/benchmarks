# Cross-protocol-generation compatibility harness

Runs a **legacy** MCP client (protocol `2025-11-25`: `initialize` + `Mcp-Session-Id`,
SDK v1) and a **modern** client (SEP-2575 stateless: `server/discover` +
`Mcp-Method`/`Mcp-Name`/`MCP-Protocol-Version` headers, no session) against **one
running Hangar**, and records a compatibility matrix — the data behind
"we ran both protocol generations through one gateway."

This is an **additive** suite under `compat/`, independent of the performance
benchmarks in `src/`.

## Run

```bash
# Point at a gateway on PATH (a local editable build, or `pip install --pre mcp-hangar`)
MCP_HANGAR_COMPAT=1 python -m pytest compat/ -v
```

Opt-in and skip-safe: without `MCP_HANGAR_COMPAT=1` everything skips; a missing
`mcp-hangar` CLI, a startup timeout, or an unserved endpoint skips/records rather
than crashing. The gateway is launched via the shipped `mcp-hangar serve --http`
CLI (mirrors `mcp-hangar/tests/live`); the math stub is resolved from the sibling
`mcp-hangar` checkout (override with `MCP_HANGAR_REPO=/path/to/mcp-hangar`).

### Two client generations, one gateway

The legacy generation needs the **SDK v1** client (`mcp==1.28.x`). The modern
generation is driven with plain `httpx` (stateless `server/discover` + `Mcp-*`
routing headers), so it exercises the gateway's modern surface without pinning a
specific client SDK build. To test the modern path against the actual SDK v2
client too, add a second venv (`mcp==2.0.0bN`) once the SDK v2 migration lands
([mcp-hangar#547](https://github.com/mcp-hangar/mcp-hangar/issues/547)).

## Axes

| Axis | Asserts |
|------|---------|
| **Handshake** (`test_handshake.py`) | legacy `initialize` completes + governed tools listed + `hangar_call` invocation works; modern `server/discover` answers — both on one gateway. |
| **Negotiation** (`test_negotiation.py`) | `server/discover` advertises `supportedVersions` (incl. the modern `2026-07-28` version) and a shaped tool surface; stateless `POST /mcp` `tools/call` is **recorded** as served / not-served. |
| **Governance surface** (`test_governance_surface.py`) | advertised `capabilities` are consistent; dormant task governance is **absent** (relay-only, ADR-008) — this flips to an asserted *presence* when ADR-014 (relay-with-governance) + [#322](https://github.com/mcp-hangar/mcp-hangar/issues/322) activate. |

Modern-surface tests depend on the `discover` fixture: if the running gateway
does not expose `server/discover`, they **record the gap and skip** rather than
fail — the matrix maps reality.

## Output

`compat/results/cross_gen_matrix.json` — one row per check
(`generation`, `axis`, `method`, `verdict`, `detail`) plus environment metadata
(both `mcp` SDK version, Hangar version, Python). This is the shareable artifact.

## Findings surfaced so far (gateway = the local `mcp2`/1.6.0 build)

- **Legacy generation fully served:** `initialize` handshake + `hangar_call` tool
  invocation work over `serve --http`.
- **Modern `server/discover` is NOT served over `serve --http`** (404) — it is
  wired in the factory path and unit-tested, but not exposed on the CLI HTTP
  surface. The stateless `POST /mcp` `tools/call` returns 406. The modern
  generation is not yet reachable end-to-end via the shipped serve command.
- **`serverInfo.name` differs by surface:** `initialize` reports `mcp-registry`,
  `server/discover` reports `mcp-hangar`.

These gaps are the point — they must close before the 2.x line can claim the
modern/stateless protocol works end-to-end.
