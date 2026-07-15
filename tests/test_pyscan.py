from pathlib import Path

from mcp_ready.pyscan import scan_python

STATEFUL_SERVER = '''
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("shop")
BASKETS = {}
_processed = []
COUNTER = 0

@mcp.tool()
def add_to_basket(session_key: str, item: str) -> str:
    BASKETS.setdefault(session_key, []).append(item)
    _processed.append(item)
    return "ok"

@mcp.tool()
def checkout(session_key: str) -> str:
    global COUNTER
    COUNTER = COUNTER + 1
    items = BASKETS.pop(session_key, [])
    return f"charged for {len(items)} items"

def helper_not_a_handler(x):
    BASKETS[x] = []  # not flagged: not a registered handler
'''

STATELESS_SERVER = '''
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("shop")
CONFIG = {"currency": "INR"}  # read-only at module level

@mcp.tool()
def add_to_basket(basket_id: str, item: str) -> str:
    store.append(basket_id, item)   # external store, explicit handle
    return CONFIG["currency"]
'''

SESSION_OBJECT_SERVER = '''
from mcp.server.fastmcp import FastMCP, Context

mcp = FastMCP("x")

@mcp.tool()
async def notify(ctx: Context) -> str:
    await ctx.session.send_resource_updated("res://a")
    return "ok"
'''


def _scan(tmp_path: Path, src: str):
    f = tmp_path / "server.py"
    f.write_text(src)
    return scan_python(f, "server.py")


def test_flags_module_state_mutated_in_handlers(tmp_path):
    findings = _scan(tmp_path, STATEFUL_SERVER)
    s004 = [f for f in findings if f.rule.code == "S004"]
    names = {f.message.split("'")[3] for f in s004}
    assert {"BASKETS", "_processed", "COUNTER"} <= names
    # the non-handler helper is not flagged
    assert not any("helper_not_a_handler" in f.message for f in findings)


def test_explicit_handle_pattern_is_clean(tmp_path):
    assert _scan(tmp_path, STATELESS_SERVER) == []


def test_flags_generic_session_use(tmp_path):
    findings = _scan(tmp_path, SESSION_OBJECT_SERVER)
    assert any(f.rule.code == "S005" for f in findings)


def test_syntax_error_is_skipped(tmp_path):
    f = tmp_path / "broken.py"
    f.write_text("def broken(:\n")
    assert scan_python(f, "broken.py") == []
