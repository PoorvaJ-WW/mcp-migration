# mcp-ready

**Is your MCP server ready for the 2026-07-28 spec?**

The [2026-07-28 revision](https://modelcontextprotocol.io/specification/draft/changelog)
is the largest change to the Model Context Protocol since launch: the protocol
goes **stateless**. `Mcp-Session-Id` is gone, the `initialize` handshake is
gone, any request can land on any server instance, list responses must carry
cache metadata, and Roots/Sampling/Logging are deprecated. Nearly every
existing server was written against the stateful spec.

`mcp-ready` finds your hidden session dependencies before your clients do:

- **`mcp-ready scan <path>`** — static scan of a server's source tree
  (Python, TypeScript, Go, C#, Java, ...). Flags removed protocol features,
  deprecated primitives, pre-2.0 SDK pins, and — for Python — the classic
  hazard: **in-memory state mutated inside tool handlers**, which silently
  breaks once requests stop sticking to one instance.
- **`mcp-ready probe <url>`** — points at a *running* Streamable HTTP server,
  speaks the old protocol to it, and reports a readiness checklist: does it
  mint sessions, does it refuse sessionless requests, does it emit
  `ttlMs`/`cacheScope`/`resultType`, does it implement `server/discover`,
  which error code does it use for missing resources.

Every finding cites the SEP that changed the behaviour and says what to do
instead. Zero dependencies, Python ≥ 3.10.

## Install

```
pip install mcp-ready
```

## Scan a source tree

```
$ mcp-ready scan path/to/server
server.py:12 warning S004 handler 'add_to_basket' mutates module-level 'BASKETS' — this state is lost when requests land on another instance
transport.py:88 blocker S001 references the removed Mcp-Session-Id header
pyproject.toml:14 info C302 python `mcp` requirement '>=1.2.0' predates the 2026-07-28 line — test against mcp==2.0.0b1

3 file(s) checked against MCP 2026-07-28: 1 blocker(s), 1 warning(s), 1 info(s)
```

Exit code is `1` when blockers are found (`--strict`: on any finding), so it
drops straight into CI. `--format json` for machines, `--format md` for a
migration report you can paste into an issue:

```
mcp-ready scan . --format md > MIGRATION.md
```

## Probe a live server

```
$ mcp-ready probe https://example.com/mcp
MCP 2026-07-28 readiness probe — https://example.com/mcp

[FAIL] No protocol-level session
       server minted an Mcp-Session-Id on initialize; the header and the session are removed in 2026-07-28
[FAIL] Serves sessionless requests
       tools/list without initialize was refused (HTTP 400: Bad Request: no valid session ID); in 2026-07-28 any request may be the first one an instance sees
[NOTE] Cache metadata on list results
       tools/list result has no ttlMs/cacheScope (required by SEP-2549)
...
```

Authenticated servers: `--header 'Authorization: Bearer ...'` (repeatable).

## What it checks

| Code | Severity | Change |
|------|----------|--------|
| S001 | blocker | `Mcp-Session-Id` / protocol sessions removed (SEP-2567) |
| S002 | blocker | `initialize`/`initialized` handshake removed (SEP-2575) |
| S003 | blocker | SSE resumability / `Last-Event-ID` / event stores removed (SEP-2575) |
| S004 | warning | In-memory state mutated across tool calls (Python AST) |
| S005 | warning | Handler depends on the session object (Python AST) |
| R101 | blocker | `tasks/list` / `tasks/result` removed — Tasks is now an extension (SEP-2663) |
| R102 | blocker | `resources/subscribe`|`unsubscribe` → `subscriptions/listen` (SEP-2575) |
| R103 | blocker | `ping`, `logging/setLevel`, `notifications/roots/list_changed` removed (SEP-2575) |
| R104 | warning | Server-initiated requests become Multi Round-Trip Requests (SEP-2322) |
| R105 | warning | `notifications/elicitation/complete` / `elicitationId` removed (SEP-2322) |
| D201–D205 | warning | Roots, Sampling, Logging, HTTP+SSE transport, `includeContext` deprecated (SEP-2577, SEP-2596) |
| C301 | warning | Resource-not-found error code `-32002` → `-32602` |
| C302 | info | SDK pinned below the 2026-07-28 beta line |
| C303–C307 | info | New-spec adoption: `ttlMs`/`cacheScope`, `resultType`, `server/discover`, deterministic tool order, legacy GET stream |

`mcp-ready rules` prints the full list with migration hints.

## What it is not

- Not a conformance suite — the official one is
  [modelcontextprotocol/conformance](https://github.com/modelcontextprotocol/conformance),
  which tests *new* implementations against the spec. `mcp-ready` looks at
  *existing* servers for migration hazards.
- Not a codemod — TypeScript users should also run
  `npx @modelcontextprotocol/codemod@beta v1-to-v2 .`; `mcp-ready` tells you
  about the behavioural hazards a codemod can't rewrite.
- Static findings are heuristics. S004 in particular flags state that may be
  a deliberate per-process cache — review, don't blindly delete.

The spec is a release candidate (locked 2026-05-21, final on 2026-07-28);
rules track the RC changelog.

## Why this exists

I maintain [okft](https://github.com/PoorvaJ-WW/okft), which ships an MCP
server. Auditing it for the 2026-07-28 changes by hand meant re-reading the
changelog with one finger on grep — so I turned the checklist into a tool.

## License

Apache-2.0
