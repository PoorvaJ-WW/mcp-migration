"""Walk a source tree and run every applicable check."""

from __future__ import annotations

import fnmatch
from pathlib import Path

from .manifests import MANIFEST_GLOBS, MANIFEST_NAMES, scan_manifest
from .pyscan import scan_python
from .rules import Finding, sort_findings
from .textscan import SOURCE_EXTENSIONS, scan_text

_SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", ".venv", "venv", "env", ".tox",
    "dist", "build", "__pycache__", ".mypy_cache", ".pytest_cache",
    ".ruff_cache", "vendor", "third_party", ".next", "target",
    "site-packages", ".eggs", "coverage", ".idea", ".vscode",
}


def _is_manifest(path: Path) -> bool:
    return (path.name in MANIFEST_NAMES
            or any(fnmatch.fnmatch(path.name, g) for g in MANIFEST_GLOBS))


def scan_path(root: Path) -> tuple[list[Finding], int]:
    """Scan a file or directory tree; returns (findings, files_scanned)."""
    root = root.resolve()
    files = [root] if root.is_file() else [
        p for p in sorted(root.rglob("*"))
        if p.is_file() and not any(part in _SKIP_DIRS for part in p.parts)
    ]

    findings: list[Finding] = []
    scanned = 0
    for path in files:
        rel = (path.name if root.is_file()
               else str(path.relative_to(root)))
        applicable = False
        if path.suffix in SOURCE_EXTENSIONS:
            applicable = True
            findings.extend(scan_text(path, rel))
            if path.suffix in (".py", ".pyi"):
                findings.extend(scan_python(path, rel))
        if _is_manifest(path):
            applicable = True
            findings.extend(scan_manifest(path, rel))
        scanned += applicable
    return sort_findings(findings), scanned
