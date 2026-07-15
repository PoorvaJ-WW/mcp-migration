"""Cross-language line-level checks.

These are deliberately narrow patterns for strings that only appear in MCP
plumbing (header names, JSON-RPC method names, SDK identifiers), so they work
on TypeScript, Go, C#, Java, Ruby, Rust... as well as Python.
"""

from __future__ import annotations

import re
from pathlib import Path

from .rules import RULES, Finding

SOURCE_EXTENSIONS = {
    ".py", ".pyi", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts",
    ".cts", ".go", ".cs", ".java", ".kt", ".kts", ".rb", ".rs", ".php",
    ".swift", ".scala",
}

# (rule code, compiled pattern, message)
_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    ("S001", re.compile(r"mcp-session-id", re.I),
     "references the removed Mcp-Session-Id header"),
    ("S002", re.compile(r"notifications/initialized"),
     "depends on the removed initialize/initialized handshake"),
    ("S003", re.compile(r"Last-Event-ID|last[_-]event[_-]id", re.I),
     "uses removed SSE resumability (Last-Event-ID)"),
    ("S003", re.compile(r"\bEventStore\b|\bevent_store\s*="),
     "wires an SSE event store; redelivery is removed from Streamable HTTP"),
    ("R101", re.compile(r"tasks/list|tasks/result"),
     "calls a removed Tasks method"),
    ("R102", re.compile(r"resources/(un)?subscribe"),
     "uses removed resources/subscribe|unsubscribe (now subscriptions/listen)"),
    ("R103", re.compile(r"logging/setLevel"),
     "handles removed logging/setLevel (log level moves to _meta)"),
    ("R103", re.compile(r"notifications/roots/list_changed"),
     "uses removed notifications/roots/list_changed"),
    ("R103", re.compile(r"""method["']?\s*[:=]\s*["']ping["']|\bsend_ping\s*\("""),
     "uses the removed ping method"),
    ("R104", re.compile(r"elicitation/create|\.elicit\s*\("),
     "server-initiated elicitation becomes a Multi Round-Trip Request"),
    ("R105", re.compile(r"notifications/elicitation/complete|elicitationId"),
     "uses the removed elicitation completion signal"),
    ("D201", re.compile(r"roots/list\b|\blist_roots\s*\(|\blistRoots\s*\(|RootsCapability"),
     "uses the deprecated Roots feature"),
    ("D202", re.compile(r"sampling/createMessage|\.create_message\s*\(|\.createMessage\s*\("),
     "uses the deprecated Sampling feature"),
    ("D203", re.compile(r"\bsend_log_message\s*\(|\bsendLoggingMessage\s*\(|notifications/message"),
     "uses deprecated MCP Logging"),
    ("D204", re.compile(r"\bSseServerTransport\b|\bSSEServerTransport\b|mcp\.server\.sse\b|WithSSEEndpoint"),
     "uses the deprecated HTTP+SSE transport"),
    ("D205", re.compile(r"""include[_C]ontext.{0,40}(thisServer|allServers)"""),
     "uses deprecated includeContext values"),
    ("C301", re.compile(r"-32002\b"),
     "emits/handles error -32002; resource-not-found is -32602 in 2026-07-28"),
]

_MAX_BYTES = 2_000_000


def scan_text(path: Path, rel: str) -> list[Finding]:
    try:
        if path.stat().st_size > _MAX_BYTES:
            return []
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []

    findings: list[Finding] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for code, pattern, message in _PATTERNS:
            if pattern.search(line):
                findings.append(Finding(
                    rule=RULES[code], message=message, path=rel,
                    line=lineno, snippet=line.strip()[:160]))
    return findings
