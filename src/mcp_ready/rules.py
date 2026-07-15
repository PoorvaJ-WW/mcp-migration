"""Rule registry and finding types for mcp-ready.

Every rule maps to a concrete change in the MCP 2026-07-28 specification
(release candidate locked 2026-05-21). Severities:

- blocker: the construct is removed in 2026-07-28 — the server breaks against
  a new-spec client/gateway.
- warning: deprecated (12-month removal window per SEP-2596) or a strong
  statefulness heuristic that needs human review.
- info: new-spec adoption note — nothing breaks, but the server is not taking
  advantage of (or not yet emitting) what the new revision expects.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Rule:
    code: str
    severity: str  # blocker | warning | info
    title: str
    sep: str  # e.g. "SEP-2567"; "" when none applies
    hint: str

    @property
    def sep_url(self) -> str:
        if not self.sep:
            return ""
        return ("https://github.com/modelcontextprotocol/modelcontextprotocol/pull/"
                + self.sep.split("-")[1])


@dataclass
class Finding:
    rule: Rule
    message: str
    path: str = ""
    line: int = 0
    snippet: str = ""

    def to_dict(self) -> dict:
        return {
            "code": self.rule.code,
            "severity": self.rule.severity,
            "title": self.rule.title,
            "sep": self.rule.sep,
            "message": self.message,
            "path": self.path,
            "line": self.line,
            "snippet": self.snippet,
            "hint": self.rule.hint,
        }


_ALL = [
    # --- Statefulness / session hazards ------------------------------------
    Rule("S001", "blocker", "Protocol-level session (Mcp-Session-Id) removed",
         "SEP-2567",
         "The Mcp-Session-Id header and the protocol session are gone. Move "
         "cross-call state into an explicit server-minted handle passed back "
         "as an ordinary tool argument, or into external storage keyed by "
         "such a handle."),
    Rule("S002", "blocker", "initialize/initialized handshake removed",
         "SEP-2575",
         "There is no handshake in 2026-07-28. Protocol version, client info "
         "and capabilities arrive in _meta on every request "
         "(io.modelcontextprotocol/protocolVersion, .../clientInfo, "
         ".../clientCapabilities); implement server/discover for up-front "
         "discovery. Anything computed at initialize time must be derivable "
         "per-request."),
    Rule("S003", "blocker", "SSE resumability / event store removed",
         "SEP-2575",
         "Last-Event-ID and SSE event IDs are gone from Streamable HTTP. A "
         "broken response stream loses the in-flight request; clients re-issue "
         "it as a new request. Delete event-store plumbing and make handlers "
         "safe to re-run (idempotent or retry-tolerant)."),
    Rule("S004", "warning", "In-memory state shared across tool calls",
         "SEP-2567",
         "Module-level mutable state written inside a handler will not survive "
         "requests landing on different server instances once sessions are "
         "gone and any request can hit any replica. Mint an explicit handle "
         "from a tool and key external storage on it, or accept that the "
         "value is per-process cache only (document it)."),
    Rule("S005", "warning", "Handler depends on the session object",
         "SEP-2567",
         "ctx.session / request_context.session APIs are tied to the removed "
         "protocol session. Check each use: server-initiated requests become "
         "Multi Round-Trip Requests (InputRequiredResult) in 2026-07-28, and "
         "session-scoped storage must move to explicit handles."),

    # --- Removed protocol features ------------------------------------------
    Rule("R101", "blocker", "tasks/list and tasks/result removed",
         "SEP-2663",
         "Tasks moved to the io.modelcontextprotocol/tasks extension: poll "
         "with tasks/get, send input with tasks/update; tasks/list is gone "
         "(no session to scope it) and blocking tasks/result is replaced by "
         "polling."),
    Rule("R102", "blocker", "resources/subscribe and unsubscribe removed",
         "SEP-2575",
         "Change notifications move to subscriptions/listen — one long-lived "
         "POST-response stream the client opts into (resourceSubscriptions, "
         "toolsListChanged, ...). Replace subscribe/unsubscribe handlers."),
    Rule("R103", "blocker", "ping / logging-setLevel / roots-list_changed removed",
         "SEP-2575",
         "ping, logging/setLevel and notifications/roots/list_changed are "
         "removed. Log level now arrives per-request via "
         "io.modelcontextprotocol/logLevel in _meta; servers MUST NOT emit "
         "notifications/message for requests that did not include it."),
    Rule("R104", "warning", "Server-initiated request becomes MRTR",
         "SEP-2322",
         "elicitation/create (and any server-to-client request) no longer "
         "flows as a live request over the stream. Return an "
         "InputRequiredResult (resultType: \"input_required\") carrying "
         "inputRequests + requestState; the client retries the original "
         "request with inputResponses. SDK v2 handles the plumbing — verify "
         "your handler survives the retry."),
    Rule("R105", "warning", "notifications/elicitation/complete removed",
         "SEP-2322",
         "The completion notification and elicitationId (added 2025-11-25) "
         "are removed; the client learns the outcome by retrying the original "
         "request. Correlate across retries via your own id in requestState."),

    # --- Deprecated features (12-month removal window) -----------------------
    Rule("D201", "warning", "Roots is deprecated",
         "SEP-2577",
         "Pass directories/files via tool parameters, resource URIs, or "
         "server configuration instead of Roots."),
    Rule("D202", "warning", "Sampling is deprecated",
         "SEP-2577",
         "Integrate directly with your LLM provider's API instead of "
         "sampling/createMessage."),
    Rule("D203", "warning", "MCP Logging is deprecated",
         "SEP-2577",
         "Log to stderr (stdio transport) or use OpenTelemetry instead of "
         "notifications/message. Trace context (traceparent/tracestate/"
         "baggage) now propagates via _meta (SEP-414)."),
    Rule("D204", "warning", "HTTP+SSE transport is deprecated",
         "SEP-2596",
         "The pre-2025-03-26 HTTP+SSE transport is formally Deprecated. "
         "Migrate to Streamable HTTP."),
    Rule("D205", "warning", "includeContext thisServer/allServers deprecated",
         "SEP-2596",
         "Omit includeContext or use \"none\"; these values disappear no "
         "later than Sampling itself."),

    # --- Compatibility details ------------------------------------------------
    Rule("C301", "warning", "Resource-not-found error code changed",
         "",
         "-32002 (MCP custom) becomes -32602 (JSON-RPC Invalid Params) in "
         "2026-07-28. Update emitters and any client-side handling. Note "
         "-32020..-32099 is now reserved for the MCP spec itself."),
    Rule("C302", "info", "SDK version predates the 2026-07-28 betas",
         "",
         "Beta SDKs: Python mcp==2.0.0b1; TypeScript @modelcontextprotocol/"
         "server + client @beta (codemod: npx @modelcontextprotocol/"
         "codemod@beta v1-to-v2 .); Go go-sdk v1.7.0-pre.1; C# "
         "ModelContextProtocol 2.0.0-preview.1."),
    Rule("C303", "info", "List results lack ttlMs/cacheScope",
         "SEP-2549",
         "tools/list, prompts/list, resources/list, resources/read and "
         "resources/templates/list results must carry ttlMs (freshness, ms) "
         "and cacheScope (\"public\"|\"private\") so clients and shared "
         "intermediaries can cache them."),
    Rule("C304", "info", "Results lack the resultType field",
         "SEP-2322",
         "Every result carries resultType: \"complete\" or "
         "\"input_required\" in 2026-07-28. Old-server results are treated "
         "as complete, so this only breaks servers that adopt MRTR."),
    Rule("C305", "info", "server/discover not implemented",
         "SEP-2575",
         "Servers MUST implement server/discover in 2026-07-28 to advertise "
         "protocol versions, capabilities and identity — it replaces "
         "initialize-time discovery."),
    Rule("C306", "info", "tools/list order is not deterministic",
         "",
         "Servers SHOULD return tools in a deterministic order to enable "
         "client caching and LLM prompt-cache hits."),
    Rule("C307", "info", "Legacy GET notification stream offered",
         "SEP-2575",
         "The standalone HTTP GET stream is replaced by subscriptions/listen. "
         "Harmless today; plan to migrate opted-in change notifications."),
]

RULES: dict[str, Rule] = {r.code: r for r in _ALL}

SEVERITY_ORDER = {"blocker": 0, "warning": 1, "info": 2}


def sort_findings(findings: list[Finding]) -> list[Finding]:
    return sorted(findings, key=lambda f: (SEVERITY_ORDER[f.rule.severity],
                                           f.rule.code, f.path, f.line))
