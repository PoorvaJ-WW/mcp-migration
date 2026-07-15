"""mcp-migration — is your MCP server ready for the 2026-07-28 spec?"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import SPEC_REVISION, __version__
from . import report
from .probe import Prober
from .rules import RULES
from .scanner import scan_path


def _use_color(choice: str) -> bool:
    return choice == "always" or (choice == "auto" and sys.stdout.isatty())


def cmd_scan(args: argparse.Namespace) -> int:
    root = Path(args.path)
    if not root.exists():
        print(f"mcp-migration: {root} does not exist", file=sys.stderr)
        return 2
    findings, scanned = scan_path(root)

    if args.format == "json":
        print(report.scan_json(findings, scanned, str(root)))
    elif args.format == "md":
        print(report.scan_markdown(findings, scanned, str(root)))
    else:
        report.print_scan_human(findings, scanned, _use_color(args.color))

    has_blockers = any(f.rule.severity == "blocker" for f in findings)
    if has_blockers or (args.strict and findings):
        return 1
    return 0


def cmd_probe(args: argparse.Namespace) -> int:
    headers = {}
    for h in args.header or []:
        name, _, value = h.partition(":")
        if not value:
            print(f"mcp-migration: bad --header {h!r} (want 'Name: value')",
                  file=sys.stderr)
            return 2
        headers[name.strip()] = value.strip()

    prober = Prober(args.url, headers=headers, timeout=args.timeout)
    checks, fatal = prober.run()
    if fatal:
        print(f"mcp-migration: {fatal}", file=sys.stderr)
        return 2

    if args.format == "json":
        print(report.probe_json(checks, args.url))
    else:
        report.print_probe_human(checks, args.url, _use_color(args.color))
    return 1 if any(c.status == "fail" for c in checks) else 0


def cmd_rules(args: argparse.Namespace) -> int:
    if args.format == "json":
        import json
        print(json.dumps([{
            "code": r.code, "severity": r.severity, "title": r.title,
            "sep": r.sep, "hint": r.hint} for r in RULES.values()], indent=2))
        return 0
    for r in RULES.values():
        sep = f" [{r.sep}]" if r.sep else ""
        print(f"{r.code} {r.severity:7} {r.title}{sep}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="mcp-migration",
        description=f"Check MCP servers for {SPEC_REVISION} spec readiness: "
                    "scan source for hidden session state and removed/"
                    "deprecated protocol features, or probe a live server.")
    parser.add_argument("--version", action="version",
                        version=f"mcp-migration {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_scan = sub.add_parser("scan", help="statically scan a source tree")
    p_scan.add_argument("path", nargs="?", default=".")
    p_scan.add_argument("--format", choices=["human", "json", "md"],
                        default="human")
    p_scan.add_argument("--strict", action="store_true",
                        help="exit 1 on any finding, not just blockers")
    p_scan.add_argument("--color", choices=["auto", "always", "never"],
                        default="auto")
    p_scan.set_defaults(func=cmd_scan)

    p_probe = sub.add_parser(
        "probe", help="probe a live Streamable HTTP server")
    p_probe.add_argument("url", help="MCP endpoint, e.g. https://host/mcp")
    p_probe.add_argument("--header", action="append", metavar="'Name: value'",
                         help="extra request header (repeatable)")
    p_probe.add_argument("--timeout", type=float, default=10.0)
    p_probe.add_argument("--format", choices=["human", "json"],
                         default="human")
    p_probe.add_argument("--color", choices=["auto", "always", "never"],
                         default="auto")
    p_probe.set_defaults(func=cmd_probe)

    p_rules = sub.add_parser("rules", help="list all rules")
    p_rules.add_argument("--format", choices=["human", "json"],
                         default="human")
    p_rules.set_defaults(func=cmd_rules)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
