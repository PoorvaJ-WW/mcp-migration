import json

import pytest

from mcp_migration.cli import main

STATEFUL = '''
from mcp.server.fastmcp import FastMCP
mcp = FastMCP("x")
SESSIONS = {}

@mcp.tool()
def remember(session_id: str, value: str) -> str:
    SESSIONS[session_id] = value
    return "ok"
'''


@pytest.fixture
def project(tmp_path):
    (tmp_path / "server.py").write_text(STATEFUL)
    (tmp_path / "transport.py").write_text(
        "SESSION_HEADER = 'Mcp-Session-Id'\n")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\ndependencies = ["mcp>=1.2.0"]\n')
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "junk.ts").write_text(
        "x = 'Mcp-Session-Id'")  # must be skipped
    return tmp_path


def test_scan_human_exit_code(project, capsys):
    rc = main(["scan", str(project)])
    out = capsys.readouterr().out
    assert rc == 1  # S001 is a blocker
    assert "S001" in out and "S004" in out and "C302" in out
    assert "node_modules" not in out


def test_scan_json(project, capsys):
    main(["scan", str(project), "--format", "json"])
    data = json.loads(capsys.readouterr().out)
    codes = {f["code"] for f in data["findings"]}
    assert {"S001", "S004", "C302"} <= codes
    assert data["spec_revision"] == "2026-07-28"


def test_scan_markdown_report(project, capsys):
    main(["scan", str(project), "--format", "md"])
    out = capsys.readouterr().out
    assert "# MCP 2026-07-28 migration report" in out
    assert "SEP-2567" in out


def test_clean_tree_exits_zero(tmp_path, capsys):
    (tmp_path / "app.py").write_text("print('hello')\n")
    rc = main(["scan", str(tmp_path)])
    assert rc == 0
    assert "No migration hazards" in capsys.readouterr().out


def test_strict_flag(tmp_path):
    (tmp_path / "app.py").write_text(
        "ctx.session.send_log_message('hi')\n"
        "def f():\n    pass\n")
    assert main(["scan", str(tmp_path)]) == 0        # warning only
    assert main(["scan", str(tmp_path), "--strict"]) == 1


def test_missing_path(capsys):
    assert main(["scan", "/nonexistent/x"]) == 2


def test_rules_listing(capsys):
    assert main(["rules"]) == 0
    out = capsys.readouterr().out
    assert "S001" in out and "D202" in out
