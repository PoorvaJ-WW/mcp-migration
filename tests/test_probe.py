"""Probe tests against tiny in-process fake servers."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from mcp_migration.probe import Prober


class _FakeServer(BaseHTTPRequestHandler):
    """Base: JSON-RPC over plain application/json responses."""

    def log_message(self, *args):
        pass

    def _send(self, obj, status=200, headers=None):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.send_response(405)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        msg = json.loads(self.rfile.read(length) or b"{}")
        if "id" not in msg:  # notification
            self.send_response(202)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.handle_rpc(msg)

    def _err(self, msg, code, text, status=200):
        self._send({"jsonrpc": "2.0", "id": msg.get("id"),
                    "error": {"code": code, "message": text}}, status=status)


class OldStatefulServer(_FakeServer):
    """Pre-2026 behaviour: sessions, handshake required, -32002."""

    def handle_rpc(self, msg):
        session = self.headers.get("Mcp-Session-Id")
        method = msg["method"]
        if method == "initialize":
            self._send({"jsonrpc": "2.0", "id": msg["id"], "result": {
                "protocolVersion": "2025-06-18",
                "capabilities": {"tools": {}, "resources": {}},
                "serverInfo": {"name": "old", "version": "1.0"},
            }}, headers={"Mcp-Session-Id": "abc123"})
        elif session != "abc123":
            self._err(msg, -32000, "Bad Request: no valid session ID",
                      status=400)
        elif method == "tools/list":
            self._send({"jsonrpc": "2.0", "id": msg["id"], "result": {
                "tools": [{"name": "a"}, {"name": "b"}]}})
        elif method == "resources/read":
            self._err(msg, -32002, "Resource not found")
        else:
            self._err(msg, -32601, "Method not found")


class ReadyStatelessServer(_FakeServer):
    """2026-07-28 behaviour: no session, cache metadata, server/discover."""

    def handle_rpc(self, msg):
        method = msg["method"]
        if method == "initialize":
            self._send({"jsonrpc": "2.0", "id": msg["id"], "result": {
                "protocolVersion": "2025-06-18", "capabilities": {},
                "serverInfo": {"name": "ready", "version": "2.0"}}})
        elif method == "tools/list":
            self._send({"jsonrpc": "2.0", "id": msg["id"], "result": {
                "resultType": "complete", "ttlMs": 60000,
                "cacheScope": "public",
                "tools": [{"name": "a"}, {"name": "b"}]}})
        elif method == "server/discover":
            self._send({"jsonrpc": "2.0", "id": msg["id"], "result": {
                "protocolVersions": ["2026-07-28"], "capabilities": {},
                "serverInfo": {"name": "ready", "version": "2.0"}}})
        elif method == "resources/read":
            self._err(msg, -32602, "Invalid params: unknown resource")
        else:
            self._err(msg, -32601, "Method not found")


@pytest.fixture
def serve():
    servers = []

    def _start(handler):
        httpd = HTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        servers.append(httpd)
        return f"http://127.0.0.1:{httpd.server_port}/mcp"

    yield _start
    for s in servers:
        s.shutdown()


def _by_title(checks):
    return {c.title: c for c in checks}


def test_old_stateful_server_fails(serve):
    url = serve(OldStatefulServer)
    checks, fatal = Prober(url, timeout=5).run()
    assert fatal == ""
    got = _by_title(checks)
    assert got["No protocol-level session"].status == "fail"
    assert got["Serves sessionless requests"].status == "fail"
    assert got["Resource-not-found error code"].status == "fail"
    assert got["Cache metadata on list results"].status == "info"
    assert got["server/discover implemented"].status == "info"


def test_ready_stateless_server_passes(serve):
    url = serve(ReadyStatelessServer)
    checks, fatal = Prober(url, timeout=5).run()
    assert fatal == ""
    assert all(c.status in ("pass", "skip") for c in checks), [
        (c.title, c.status, c.detail) for c in checks]


def test_unreachable_server_is_fatal():
    checks, fatal = Prober("http://127.0.0.1:1/mcp", timeout=2).run()
    assert fatal != ""
