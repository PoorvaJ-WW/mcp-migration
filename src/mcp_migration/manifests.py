"""Dependency-manifest checks: is the project pinned to a pre-2026-07-28 SDK?"""

from __future__ import annotations

import re
from pathlib import Path

from .rules import RULES, Finding

try:
    import tomllib
except ModuleNotFoundError:  # python 3.10
    tomllib = None

MANIFEST_NAMES = {"pyproject.toml", "setup.py", "setup.cfg", "package.json",
                  "go.mod"}
MANIFEST_GLOBS = ("requirements*.txt", "*.csproj")

# A PEP 508-ish requirement string for the `mcp` package.
_PY_REQ = re.compile(
    r"^\s*mcp(?![\w-])\s*(\[[^\]]*\])?\s*(==|>=|<=|~=|!=|<|>)?\s*([\w.*]+)?")
# Fallback for setup.py / setup.cfg / non-tomllib: quoted req with an operator.
_PY_QUOTED = re.compile(
    r"""["']\s*mcp(?![\w-])\s*(\[[^\]]*\])?\s*(==|>=|<=|~=|!=|<|>)\s*([\w.*]+)""")
_TS_SDK = re.compile(r'"@modelcontextprotocol/sdk"\s*:\s*"([^"]*)"')
_GO_SDK = re.compile(r"github\.com/modelcontextprotocol/go-sdk\s+v([\d.]+)")
_CS_SDK = re.compile(r'Include="ModelContextProtocol"\s+Version="([^"]*)"')


def _line_of(text: str, needle: str) -> int:
    idx = text.find(needle)
    return text.count("\n", 0, idx) + 1 if idx >= 0 else 0


def _mcp_finding(rule, rel, line, snippet, constraint) -> Finding:
    return Finding(
        rule=rule, path=rel, line=line, snippet=snippet,
        message=(f"python `mcp` requirement {constraint!r} predates the "
                 "2026-07-28 line — test against mcp==2.0.0b1"))


def _pyproject_requirements(text: str) -> list[str]:
    """All requirement strings from a pyproject.toml, or [] if unparsable."""
    try:
        data = tomllib.loads(text)
    except Exception:
        return []
    reqs: list[str] = []
    project = data.get("project", {})
    reqs += project.get("dependencies", [])
    for group in project.get("optional-dependencies", {}).values():
        reqs += group
    for group in data.get("dependency-groups", {}).values():
        reqs += [r for r in group if isinstance(r, str)]
    poetry = data.get("tool", {}).get("poetry", {})
    for section in ("dependencies", "dev-dependencies"):
        for pkg, spec in poetry.get(section, {}).items():
            if pkg == "mcp":
                reqs.append(f"mcp{spec if isinstance(spec, str) else ''}")
    return [r for r in reqs if isinstance(r, str)]


def _scan_python_reqs(text: str, rel: str, rule) -> list[Finding]:
    findings = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#")[0].strip()
        m = _PY_REQ.match(line)
        if m and not (m.group(3) or "").startswith("2"):
            constraint = f"{m.group(2) or ''}{m.group(3) or ''}" or "(unpinned)"
            findings.append(_mcp_finding(rule, rel, lineno, line, constraint))
    return findings


def scan_manifest(path: Path, rel: str) -> list[Finding]:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    rule = RULES["C302"]
    findings: list[Finding] = []
    name = path.name

    if name.startswith("requirements"):
        findings += _scan_python_reqs(text, rel, rule)
    elif name == "pyproject.toml" and tomllib is not None:
        for req in dict.fromkeys(_pyproject_requirements(text)):
            m = _PY_REQ.match(req)
            if m and not (m.group(3) or "").startswith("2"):
                constraint = (f"{m.group(2) or ''}{m.group(3) or ''}"
                              or "(unpinned)")
                findings.append(_mcp_finding(
                    rule, rel, _line_of(text, req), req, constraint))
    elif name in {"pyproject.toml", "setup.py", "setup.cfg"}:
        for m in _PY_QUOTED.finditer(text):
            if (m.group(3) or "").startswith("2"):
                continue
            snippet = m.group(0).strip("\"'")
            findings.append(_mcp_finding(
                rule, rel, text.count("\n", 0, m.start()) + 1, snippet,
                f"{m.group(2)}{m.group(3)}"))
    elif name == "package.json":
        for m in _TS_SDK.finditer(text):
            findings.append(Finding(
                rule=rule, path=rel, line=text.count("\n", 0, m.start()) + 1,
                snippet=m.group(0),
                message=("@modelcontextprotocol/sdk is the v1 package; v2 "
                         "splits into @modelcontextprotocol/server and "
                         "/client — run: npx @modelcontextprotocol/"
                         "codemod@beta v1-to-v2 .")))
    elif name == "go.mod":
        for m in _GO_SDK.finditer(text):
            ver = tuple(int(x) for x in m.group(1).split(".")[:2])
            if ver < (1, 7):
                findings.append(Finding(
                    rule=rule, path=rel,
                    line=text.count("\n", 0, m.start()) + 1,
                    snippet=m.group(0),
                    message=("go-sdk v%s predates the 2026-07-28 beta "
                             "(v1.7.0-pre.1)" % m.group(1))))
    elif name.endswith(".csproj"):
        for m in _CS_SDK.finditer(text):
            if not m.group(1).startswith("2"):
                findings.append(Finding(
                    rule=rule, path=rel,
                    line=text.count("\n", 0, m.start()) + 1,
                    snippet=m.group(0),
                    message=("ModelContextProtocol %s predates the "
                             "2026-07-28 beta (2.0.0-preview.1)" % m.group(1))))
    return findings
