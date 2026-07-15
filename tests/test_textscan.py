from pathlib import Path

from mcp_migration.textscan import scan_text


def _codes(tmp_path: Path, name: str, content: str) -> set[str]:
    f = tmp_path / name
    f.write_text(content)
    return {x.rule.code for x in scan_text(f, name)}


def test_session_header_any_language(tmp_path):
    ts = 'res.setHeader("Mcp-Session-Id", sessionId);\n'
    assert "S001" in _codes(tmp_path, "server.ts", ts)


def test_removed_methods(tmp_path):
    src = (
        'await client.request("tasks/list")\n'
        'server.setRequestHandler("resources/subscribe", h)\n'
        'case "logging/setLevel":\n'
        '{"method": "ping"}\n'
    )
    codes = _codes(tmp_path, "handlers.js", src)
    assert {"R101", "R102", "R103"} <= codes


def test_deprecated_features(tmp_path):
    src = (
        "roots = await ctx.session.list_roots()\n"
        "msg = await ctx.session.create_message(messages=[m])\n"
        "await ctx.session.send_log_message(level='info', data=d)\n"
        "from mcp.server.sse import SseServerTransport\n"
    )
    codes = _codes(tmp_path, "server.py", src)
    assert {"D201", "D202", "D203", "D204"} <= codes


def test_error_code_and_resumability(tmp_path):
    src = (
        "raise McpError(code=-32002, message='not found')\n"
        "last_event_id = request.headers.get('Last-Event-ID')\n"
    )
    codes = _codes(tmp_path, "errors.py", src)
    assert {"C301", "S003"} <= codes


def test_clean_file_has_no_findings(tmp_path):
    src = (
        "def add(a, b):\n"
        "    return a + b\n"
        "# talks about sessions in a comment is fine\n"
        "basket = load_basket(basket_id)\n"
    )
    assert _codes(tmp_path, "clean.py", src) == set()
