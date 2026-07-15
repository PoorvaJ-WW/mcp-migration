"""Terminal, JSON and markdown rendering for scan findings and probe checks."""

from __future__ import annotations

import json

from . import SPEC_REVISION
from .probe import CheckResult
from .rules import Finding

_RED = "\033[31m"
_YELLOW = "\033[33m"
_GREEN = "\033[32m"
_CYAN = "\033[36m"
_DIM = "\033[2m"
_RESET = "\033[0m"

_SEV_COLOR = {"blocker": _RED, "warning": _YELLOW, "info": _CYAN}
_STATUS = {"pass": (_GREEN, "PASS"), "fail": (_RED, "FAIL"),
           "info": (_CYAN, "NOTE"), "skip": (_DIM, "SKIP")}


def _paint(text: str, color: str, use_color: bool) -> str:
    return f"{color}{text}{_RESET}" if use_color else text


# --- scan ------------------------------------------------------------------

def print_scan_human(findings: list[Finding], scanned: int,
                     use_color: bool) -> None:
    for f in findings:
        sev = _paint(f.rule.severity, _SEV_COLOR[f.rule.severity], use_color)
        code = _paint(f.rule.code, _DIM, use_color)
        loc = f"{f.path}:{f.line}" if f.line else f.path
        print(f"{loc} {sev} {code} {f.message}")
        if f.snippet:
            print(_paint(f"    {f.snippet}", _DIM, use_color))

    counts = {"blocker": 0, "warning": 0, "info": 0}
    for f in findings:
        counts[f.rule.severity] += 1
    print()
    summary = ", ".join(
        _paint(f"{n} {sev}(s)", _SEV_COLOR[sev] if n else _DIM, use_color)
        for sev, n in counts.items())
    print(f"{scanned} file(s) checked against MCP {SPEC_REVISION}: {summary}")
    if counts["blocker"]:
        print("Blockers break against a 2026-07-28 client or gateway. "
              "Run with --format md for a migration report.")
    elif not findings:
        print("No migration hazards found.")


def scan_json(findings: list[Finding], scanned: int, path: str) -> str:
    return json.dumps({
        "spec_revision": SPEC_REVISION,
        "path": path,
        "files_scanned": scanned,
        "findings": [f.to_dict() for f in findings],
    }, indent=2)


def scan_markdown(findings: list[Finding], scanned: int, path: str) -> str:
    lines = [f"# MCP {SPEC_REVISION} migration report",
             "",
             f"Scanned `{path}` ({scanned} files). "
             f"{len(findings)} finding(s).", ""]
    if not findings:
        lines.append("No migration hazards found.")
        return "\n".join(lines) + "\n"

    by_rule: dict[str, list[Finding]] = {}
    for f in findings:
        by_rule.setdefault(f.rule.code, []).append(f)

    for code in sorted(by_rule, key=lambda c: (
            {"blocker": 0, "warning": 1, "info": 2}[by_rule[c][0].rule.severity], c)):
        group = by_rule[code]
        rule = group[0].rule
        sep = f" ([{rule.sep}]({rule.sep_url}))" if rule.sep else ""
        lines.append(f"## {code} — {rule.title} `{rule.severity}`{sep}")
        lines.append("")
        lines.append(rule.hint)
        lines.append("")
        for f in group:
            loc = f"{f.path}:{f.line}" if f.line else f.path
            snippet = f" — `{f.snippet}`" if f.snippet else ""
            lines.append(f"- `{loc}` {f.message}{snippet}")
        lines.append("")
    return "\n".join(lines) + "\n"


# --- probe -------------------------------------------------------------------

def print_probe_human(checks: list[CheckResult], url: str,
                      use_color: bool) -> None:
    print(f"MCP {SPEC_REVISION} readiness probe — {url}\n")
    for c in checks:
        color, label = _STATUS[c.status]
        tag = _paint(f"[{label}]", color, use_color)
        print(f"{tag} {c.title}")
        print(_paint(f"       {c.detail}", _DIM, use_color))
        if c.rule_code and c.status in ("fail", "info"):
            from .rules import RULES
            rule = RULES[c.rule_code]
            ref = f" ({rule.sep})" if rule.sep else ""
            print(_paint(f"       fix: {rule.hint}{ref}", _DIM, use_color))
    fails = sum(1 for c in checks if c.status == "fail")
    notes = sum(1 for c in checks if c.status == "info")
    passes = sum(1 for c in checks if c.status == "pass")
    print(f"\n{passes} pass, {fails} fail, {notes} note(s).")
    if fails:
        print("This deployment depends on protocol behaviour that is removed "
              f"in MCP {SPEC_REVISION}.")


def probe_json(checks: list[CheckResult], url: str) -> str:
    return json.dumps({
        "spec_revision": SPEC_REVISION,
        "url": url,
        "checks": [c.to_dict() for c in checks],
        "ready": not any(c.status == "fail" for c in checks),
    }, indent=2)
