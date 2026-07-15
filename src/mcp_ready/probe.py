"""Live readiness probe for a running Streamable HTTP MCP server.

Speaks the *old* protocol (2025-06-18 era) on purpose: existing servers
understand it, and the point is to measure how far the deployment is from
2026-07-28 behaviour — does it mint sessions, does it refuse sessionless
requests, does it emit the new cache/result metadata, does it implement
server/discover.
"""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from . import __version__
from .rules import RULES

_MAX_SSE_BYTES = 1_000_000


@dataclass
class RpcResponse:
    status: int = 0
    headers: dict = field(default_factory=dict)
    payload: dict | None = None
    error: str = ""  # transport-level problem, "" if a response was parsed

    @property
    def result(self) -> dict | None:
        if self.payload and isinstance(self.payload.get("result"), dict):
            return self.payload["result"]
        return None

    @property
    def rpc_error(self) -> dict | None:
        if self.payload and isinstance(self.payload.get("error"), dict):
            return self.payload["error"]
        return None


@dataclass
class CheckResult:
    status: str          # pass | fail | info | skip
    title: str
    detail: str
    rule_code: str = ""  # links a failure back to a rule/SEP

    def to_dict(self) -> dict:
        d = {"status": self.status, "title": self.title, "detail": self.detail}
        if self.rule_code:
            rule = RULES[self.rule_code]
            d.update({"rule": self.rule_code, "sep": rule.sep,
                      "hint": rule.hint})
        return d


class Prober:
    def __init__(self, url: str, headers: dict[str, str] | None = None,
                 timeout: float = 10.0):
        self.url = url
        self.base_headers = headers or {}
        self.timeout = timeout
        self._id = 0

    # -- transport ---------------------------------------------------------

    def _request(self, body: bytes | None, method: str = "POST",
                 extra: dict[str, str] | None = None,
                 head_only: bool = False) -> RpcResponse:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "User-Agent": f"mcp-ready/{__version__}",
            **self.base_headers, **(extra or {}),
        }
        req = urllib.request.Request(self.url, data=body, headers=headers,
                                     method=method)
        try:
            resp = urllib.request.urlopen(req, timeout=self.timeout)
        except urllib.error.HTTPError as e:
            raw = e.read() or b""
            payload = None
            try:
                payload = json.loads(raw)
            except (ValueError, UnicodeDecodeError):
                pass
            return RpcResponse(status=e.code, headers={k.lower(): v for k, v
                                                       in e.headers.items()},
                               payload=payload)
        except (urllib.error.URLError, socket.timeout, OSError) as e:
            return RpcResponse(error=str(e))
        if head_only:
            out = RpcResponse(status=resp.status,
                              headers={k.lower(): v for k, v
                                       in resp.headers.items()})
            resp.close()
            return out
        return self._read(resp)

    def _read(self, resp) -> RpcResponse:
        headers = {k.lower(): v for k, v in resp.headers.items()}
        out = RpcResponse(status=resp.status, headers=headers)
        ctype = headers.get("content-type", "")
        try:
            if "text/event-stream" in ctype:
                out.payload = self._read_sse(resp)
            else:
                raw = resp.read()
                if raw.strip():
                    out.payload = json.loads(raw)
        except (ValueError, socket.timeout, OSError) as e:
            out.error = f"could not parse response: {e}"
        finally:
            resp.close()
        return out

    def _read_sse(self, resp) -> dict | None:
        data_lines: list[str] = []
        seen = 0
        for raw in resp:
            seen += len(raw)
            if seen > _MAX_SSE_BYTES:
                break
            line = raw.decode("utf-8", errors="ignore").rstrip("\r\n")
            if line.startswith("data:"):
                data_lines.append(line[5:].lstrip())
            elif line == "" and data_lines:
                try:
                    event = json.loads("\n".join(data_lines))
                except ValueError:
                    event = None
                data_lines = []
                if isinstance(event, dict) and "id" in event:
                    return event
        return None

    def rpc(self, method: str, params: dict | None = None,
            extra: dict[str, str] | None = None) -> RpcResponse:
        self._id += 1
        msg: dict = {"jsonrpc": "2.0", "id": self._id, "method": method}
        if params is not None:
            msg["params"] = params
        return self._request(json.dumps(msg).encode(), extra=extra)

    def notify(self, method: str, extra: dict[str, str] | None = None) -> None:
        msg = {"jsonrpc": "2.0", "method": method}
        self._request(json.dumps(msg).encode(), extra=extra)

    # -- the probe -----------------------------------------------------------

    def run(self) -> tuple[list[CheckResult], str]:
        """Returns (checks, fatal_error). fatal_error != '' if unreachable."""
        checks: list[CheckResult] = []

        # 1. Cold, sessionless request — the defining 2026-07-28 behaviour.
        cold = self.rpc("tools/list")
        cold_ok = cold.result is not None

        # 2. Old-style initialize, to see whether a session gets minted.
        init = self.rpc("initialize", {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "mcp-ready", "version": __version__},
        })
        if init.error and not cold_ok:
            return checks, f"server unreachable: {init.error or cold.error}"
        if init.payload is None and not cold_ok:
            return checks, (f"no JSON-RPC response (HTTP {init.status}) — is "
                            "this a Streamable HTTP MCP endpoint?")

        session_id = init.headers.get("mcp-session-id", "")
        session_hdr = {"mcp-session-id": session_id} if session_id else {}
        if session_id:
            self.notify("notifications/initialized", extra=session_hdr)
            checks.append(CheckResult(
                "fail", "No protocol-level session",
                "server minted an Mcp-Session-Id on initialize; the header "
                "and the session are removed in 2026-07-28", "S001"))
        else:
            checks.append(CheckResult(
                "pass", "No protocol-level session",
                "initialize response carries no Mcp-Session-Id header"))

        if cold_ok:
            checks.append(CheckResult(
                "pass", "Serves sessionless requests",
                "tools/list succeeded with no prior initialize and no "
                "session header"))
        else:
            err = cold.rpc_error or {}
            detail = (f"HTTP {cold.status}" if cold.status else cold.error)
            if err:
                detail = f"{detail}: {err.get('message', '')}".strip(": ")
            checks.append(CheckResult(
                "fail", "Serves sessionless requests",
                "tools/list without initialize was refused (" + detail + "); "
                "in 2026-07-28 any request may be the first one an instance "
                "sees", "S002"))

        # 3. tools/list (with the session if one was required) — metadata.
        tl = self.rpc("tools/list", extra=session_hdr)
        result = tl.result if tl.result is not None else (
            cold.result if cold_ok else None)
        if result is not None:
            has_cache = "ttlMs" in result and "cacheScope" in result
            checks.append(CheckResult(
                "pass" if has_cache else "info",
                "Cache metadata on list results",
                "ttlMs and cacheScope present" if has_cache else
                "tools/list result has no ttlMs/cacheScope (required by "
                "SEP-2549)", "" if has_cache else "C303"))
            has_rt = "resultType" in result
            checks.append(CheckResult(
                "pass" if has_rt else "info",
                "resultType on results",
                "resultType present" if has_rt else
                "results omit resultType (treated as \"complete\" by new "
                "clients)", "" if has_rt else "C304"))
            names = [t.get("name", "") for t in result.get("tools", [])]
            tl2 = self.rpc("tools/list", extra=session_hdr)
            if tl2.result is not None:
                names2 = [t.get("name", "") for t in tl2.result.get("tools", [])]
                same = names == names2
                checks.append(CheckResult(
                    "pass" if same else "info",
                    "Deterministic tools/list order",
                    "two consecutive calls returned the same order" if same
                    else "tool order differed between two calls",
                    "" if same else "C306"))
        else:
            checks.append(CheckResult(
                "skip", "Cache metadata on list results",
                "could not obtain a tools/list result"))

        # 4. server/discover — the new discovery RPC.
        disc = self.rpc("server/discover", extra=session_hdr)
        if disc.result is not None:
            checks.append(CheckResult(
                "pass", "server/discover implemented",
                "server answered the 2026-07-28 discovery RPC"))
        else:
            checks.append(CheckResult(
                "info", "server/discover implemented",
                "not implemented (mandatory in 2026-07-28)", "C305"))

        # 5. Resource-not-found error code.
        rr = self.rpc("resources/read",
                      {"uri": "mcp-ready://probe/does-not-exist"},
                      extra=session_hdr)
        err = rr.rpc_error
        if err is None:
            checks.append(CheckResult(
                "skip", "Resource-not-found error code",
                "server returned no JSON-RPC error for a bogus resource"))
        elif err.get("code") == -32601:
            checks.append(CheckResult(
                "skip", "Resource-not-found error code",
                "resources/read not supported"))
        elif err.get("code") == -32002:
            checks.append(CheckResult(
                "fail", "Resource-not-found error code",
                "server returned -32002; 2026-07-28 uses -32602 (JSON-RPC "
                "Invalid Params)", "C301"))
        elif err.get("code") == -32602:
            checks.append(CheckResult(
                "pass", "Resource-not-found error code",
                "server returned -32602 (the 2026-07-28 code)"))
        else:
            checks.append(CheckResult(
                "skip", "Resource-not-found error code",
                f"server returned {err.get('code')} — inconclusive"))

        # 6. Legacy GET notification stream.
        get = self._request(None, method="GET", extra=session_hdr,
                            head_only=True)
        if get.status == 200 and "text/event-stream" in get.headers.get(
                "content-type", ""):
            checks.append(CheckResult(
                "info", "Legacy GET stream",
                "server offers the standalone GET SSE stream (replaced by "
                "subscriptions/listen)", "C307"))
        else:
            checks.append(CheckResult(
                "pass", "Legacy GET stream",
                "no standalone GET SSE stream"))

        return checks, ""
