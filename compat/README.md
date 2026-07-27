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
make compat-venv-legacy          # once: builds .venv-legacy with the SDK v1 client
make compat-test                 # runs both generations against one gateway
make compat-matrix               # renders the matrix from the last run
```

Or directly:

```bash
MCP_HANGAR_COMPAT=1 python -m pytest compat/ -v
python -m compat.render_matrix --format markdown
```

Opt-in and skip-safe: without `MCP_HANGAR_COMPAT=1` everything skips; a missing
`mcp-hangar` CLI, a startup timeout, or an unserved endpoint skips/records rather
than crashing. The gateway is launched via the shipped `mcp-hangar serve --http`
CLI (mirrors `mcp-hangar/tests/live`); the math stub is resolved from the sibling
`mcp-hangar` checkout (override with `MCP_HANGAR_REPO=/path/to/mcp-hangar`).

### Two client generations, one gateway

The two SDK generations **cannot share an interpreter** — one `mcp` distribution
per environment, and v2 renamed `streamablehttp_client` to
`streamable_http_client`. So:

- **legacy** runs out of process under `.venv-legacy` (`mcp==1.28.1`), driven by
  `legacy_runner.py` over stdout JSON. Missing venv ⇒ those axes skip, not fail.
- **modern** is driven with plain `httpx` against `server/discover` and a
  stateless `POST /mcp`, so it exercises the gateway's surface without pinning a
  client build.

Two client-side requirements bit us and are now encoded in `clients.py`, because
getting them wrong looks exactly like an unserved endpoint:

- every modern request carries the reserved `params._meta` envelope (protocol
  version, client info, client capabilities) — there is no handshake to
  negotiate them, and omitting it is answered `-32602`;
- `Accept` must cover `text/event-stream`, or the modern entry answers `406`.

## Axes

| Axis | Asserts |
|------|---------|
| **Handshake** (`test_handshake.py`) | legacy `initialize` completes + governed tools listed + `hangar_call` invocation works; modern `server/discover` answers — both on one gateway. |
| **Negotiation** (`test_negotiation.py`) | `server/discover` advertises `supportedVersions` (incl. the modern `2026-07-28` version) and a shaped tool surface; stateless `POST /mcp` `tools/call` is **recorded** as served / not-served. |
| **Governance surface** (`test_governance_surface.py`) | advertised `capabilities` are consistent across generations; task governance is **advertised** (relay-with-governance, ADR-014, [#322](https://github.com/mcp-hangar/mcp-hangar/issues/322)) — flipped from ADR-008's relay-only *absence* assertion when the relay seam went live. |
| **Tasks relay** (`test_tasks_relay.py`) | a task handle is **relayed, not refused**; the task reaches a terminal state (no hang); `tasks/result` returns the governed payload; a client that cannot be asked for consent fails **closed**. Rewritten from the issue's original ADR-008 `TaskRelayNotSupported` assertion, which ADR-014 superseded. |

## The artifact

Each check appends a row to `compat/results/cross_gen_matrix.json` with the
environment (gateway version, both client SDK versions). Checks record their
verdict **before** asserting, so a failure shows up as a red cell rather than a
missing one — the matrix is the deliverable, not a side effect of a green run.

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
