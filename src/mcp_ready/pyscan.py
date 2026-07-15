"""Python AST checks: the statefulness heuristics regexes can't do.

Detects the "hidden session dependency" pattern the 2026-07-28 migration is
about: module-level mutable state written from inside an MCP handler, and
handlers that reach into the protocol session object.
"""

from __future__ import annotations

import ast
from pathlib import Path

from .rules import RULES, Finding

# Decorator attribute names that register an MCP handler, across the official
# python SDK's FastMCP and low-level Server APIs.
_HANDLER_DECORATORS = {
    "tool", "resource", "prompt", "call_tool", "read_resource", "list_tools",
    "list_resources", "list_resource_templates", "list_prompts", "get_prompt",
    "completion", "complete", "subscribe_resource", "unsubscribe_resource",
    "set_logging_level", "progress_notification",
}

# Container constructors whose module-level result counts as mutable state.
_MUTABLE_CALLS = {"dict", "list", "set", "defaultdict", "OrderedDict",
                  "Counter", "deque"}

_MUTATOR_METHODS = {"append", "add", "update", "setdefault", "pop", "popitem",
                    "extend", "insert", "remove", "discard", "clear",
                    "appendleft", "extendleft"}

# .session attributes already covered by a dedicated (deprecation) rule.
_SESSION_ATTR_RULES = {
    "create_message": None,     # D202 via textscan
    "list_roots": None,         # D201 via textscan
    "send_log_message": None,   # D203 via textscan
}


def _decorator_name(dec: ast.expr) -> str | None:
    """Return the trailing attribute name of `@x.y()` / `@x.y` decorators."""
    if isinstance(dec, ast.Call):
        dec = dec.func
    if isinstance(dec, ast.Attribute):
        return dec.attr
    if isinstance(dec, ast.Name):
        return dec.id
    return None


def _is_handler(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(_decorator_name(d) in _HANDLER_DECORATORS
               for d in fn.decorator_list)


def _module_level_mutables(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in tree.body:
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        if value is None:
            continue
        mutable = isinstance(value, (ast.Dict, ast.List, ast.Set,
                                     ast.DictComp, ast.ListComp, ast.SetComp))
        if isinstance(value, ast.Call):
            fn = value.func
            callee = fn.id if isinstance(fn, ast.Name) else (
                fn.attr if isinstance(fn, ast.Attribute) else "")
            mutable = callee in _MUTABLE_CALLS
        if mutable:
            for t in targets:
                if isinstance(t, ast.Name):
                    names.add(t.id)
    return names


def _check_handler(fn: ast.FunctionDef | ast.AsyncFunctionDef,
                   mutables: set[str], rel: str) -> list[Finding]:
    findings: list[Finding] = []
    flagged_state: set[tuple[str, int]] = set()
    globals_declared: set[str] = set()

    def flag_state(name: str, lineno: int) -> None:
        key = (name, lineno)
        if key in flagged_state:
            return
        flagged_state.add(key)
        findings.append(Finding(
            rule=RULES["S004"],
            message=(f"handler '{fn.name}' mutates module-level '{name}' — "
                     "this state is lost when requests land on another "
                     "instance"),
            path=rel, line=lineno))

    for node in ast.walk(fn):
        if isinstance(node, ast.Global):
            globals_declared.update(node.names)

    for node in ast.walk(fn):
        # d[key] = ..., d[key] += ..., del d[key]
        if isinstance(node, (ast.Assign, ast.AugAssign, ast.Delete)):
            targets = (node.targets if isinstance(node, ast.Assign)
                       else [node.target] if isinstance(node, ast.AugAssign)
                       else node.targets)
            for t in targets:
                if (isinstance(t, ast.Subscript)
                        and isinstance(t.value, ast.Name)
                        and t.value.id in mutables):
                    flag_state(t.value.id, node.lineno)
                # global X; X = ... — rebinding module state also counts
                if (isinstance(t, ast.Name) and t.id in globals_declared):
                    flag_state(t.id, node.lineno)
        # d.update(...), l.append(...), s.add(...)
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in _MUTATOR_METHODS
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in mutables):
            flag_state(node.func.value.id, node.lineno)
        # anything.session.<attr> — protocol-session dependency
        if (isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Attribute)
                and node.value.attr == "session"
                and node.attr not in _SESSION_ATTR_RULES):
            findings.append(Finding(
                rule=RULES["S005"],
                message=(f"handler '{fn.name}' uses the session object "
                         f"(.session.{node.attr})"),
                path=rel, line=node.lineno))
    return findings


def scan_python(path: Path, rel: str) -> list[Finding]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    except (OSError, SyntaxError):
        return []

    mutables = _module_level_mutables(tree)
    findings: list[Finding] = []
    for node in ast.walk(tree):
        if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and _is_handler(node)):
            findings.extend(_check_handler(node, mutables, rel))
    return findings
