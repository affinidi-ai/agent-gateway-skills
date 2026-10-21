#!/usr/bin/env python3
"""Minimal upstream servers for the live e2e cases, standard library only.

    targets.py mcp  [--host H] [--port P]   MCP server (JSON-RPC over HTTP, protocol 2024-11-05)
    targets.py a2a  [--host H] [--port P]   A2A 0.3 agent (agent card + JSON-RPC message/send)
    targets.py a2a1 [--host H] [--port P]   A2A agent that also speaks 1.0 (SendMessage, GetTask)
    targets.py idp  [--host H] [--port P]   OAuth 2.0 authorization server that approves every request
    targets.py rest [--host H] [--port P]   REST API with an OpenAPI 3 document at /openapi.json

Port 0 picks a free port. The first line on stdout is `listening http://H:P`.
Every server records the requests it receives; `GET /_e2e/requests` returns them as JSON and
`DELETE /_e2e/requests` clears them, so a case can check exactly what the gateway forwarded. Both need the
header `X-E2E-Recorder` set to E2E_RECORDER_SECRET, which the run picks at random, so nothing else on the
network can read the recorded requests. The idp server approves every request: start it on a LAN address
(`--lan`) only on a network you trust.
"""
import argparse
import hmac
import json
import os
import sys
import threading
import urllib.parse
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MCP_TOOLS = [
    {"name": "echo", "description": "Return the text you send.",
     "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}},
    {"name": "add", "description": "Add two numbers.",
     "inputSchema": {"type": "object", "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
                     "required": ["a", "b"]}},
    {"name": "delete_everything", "description": "A dangerous tool a policy should block.",
     "inputSchema": {"type": "object", "properties": {}}},
]


class Recorder:
    def __init__(self):
        self.lock = threading.Lock()
        self.items = []

    def add(self, item):
        with self.lock:
            self.items.append(item)

    def dump(self):
        with self.lock:
            return list(self.items)

    def clear(self):
        with self.lock:
            self.items.clear()


class Base(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    recorder = None
    recorder_secret = ""
    public_url = ""

    def log_message(self, *args):
        pass

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def send(self, status, payload=None, ctype="application/json", headers=None):
        data = b"" if payload is None else (payload if isinstance(payload, bytes) else json.dumps(payload).encode())
        self.send_response(status)
        if payload is not None:
            self.send_header("Content-Type", ctype)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def record(self, raw):
        text = raw.decode("utf-8", "replace")
        try:
            parsed = json.loads(text) if text else None
        except ValueError:
            parsed = None
        self.recorder.add({"method": self.command, "path": self.path,
                           "headers": {k.lower(): v for k, v in self.headers.items()},
                           "body": parsed if parsed is not None else text})
        return parsed

    def control(self):
        if self.path.split("?")[0] != "/_e2e/requests":
            return False
        if not hmac.compare_digest(self.headers.get("X-E2E-Recorder", ""), self.recorder_secret):
            self.send(403, {"error": "recorder secret missing or wrong"})
            return True
        if self.command == "GET":
            self.send(200, self.recorder.dump())
        elif self.command == "DELETE":
            self.recorder.clear()
            self.send(204)
        return True

    def do_GET(self):
        if not self.control():
            self.record(b"")
            self.get()

    def do_DELETE(self):
        if not self.control():
            self.record(self.body())
            self.send(405, {"error": "method not allowed"})

    def do_POST(self):
        self.post(self.body())

    def get(self):
        self.send(404, {"error": "not found"})


def rpc_result(req_id, result):
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def rpc_error(req_id, code, message):
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


class Mcp(Base):
    def post(self, raw):
        msg = self.record(raw)
        if not isinstance(msg, dict):
            return self.send(400, rpc_error(None, -32700, "Parse error"))
        if "id" not in msg:
            return self.send(202)
        method, rid, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
        if method == "initialize":
            return self.send(200, rpc_result(rid, {
                "protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                "serverInfo": {"name": "e2e-mcp", "version": "1.0.0"}}))
        if method == "tools/list":
            return self.send(200, rpc_result(rid, {"tools": MCP_TOOLS}))
        if method == "tools/call":
            name, args = params.get("name"), params.get("arguments") or {}
            if name == "echo":
                text = str(args.get("text", ""))
            elif name == "add":
                text = str(args.get("a", 0) + args.get("b", 0))
            elif name == "delete_everything":
                text = "everything deleted"
            else:
                return self.send(200, rpc_error(rid, -32602, "Unknown tool: %s" % name))
            auth = self.headers.get("Authorization") or ""
            content = [{"type": "text", "text": text}]
            if auth:
                content.append({"type": "text", "text": "upstream saw Authorization: %s" % auth.split(" ")[0]})
            return self.send(200, rpc_result(rid, {"content": content, "isError": False}))
        if method == "ping":
            return self.send(200, rpc_result(rid, {}))
        return self.send(200, rpc_error(rid, -32601, "Method not found"))


class A2a(Base):
    def card(self):
        return {
            "name": "e2e-a2a", "description": "Echo agent for end-to-end tests.",
            "url": self.public_url + "/", "version": "1.0.0", "protocolVersion": "0.3.0",
            "preferredTransport": "JSONRPC",
            "capabilities": {"streaming": False, "pushNotifications": False},
            "defaultInputModes": ["text/plain"], "defaultOutputModes": ["text/plain"],
            "skills": [{"id": "echo", "name": "Echo", "description": "Replies with the text it receives.",
                        "tags": ["test"]}],
        }

    def get(self):
        path = self.path.split("?")[0]
        if path.endswith("/.well-known/agent-card.json") or path.endswith("/.well-known/agent.json"):
            return self.send(200, self.card())
        return self.send(404, {"error": "not found"})

    def post(self, raw):
        msg = self.record(raw)
        if not isinstance(msg, dict):
            return self.send(400, rpc_error(None, -32700, "Parse error"))
        return self.answer(msg.get("method"), msg.get("id"), msg.get("params") or {})

    def answer(self, method, rid, params):
        if method == "message/send":
            incoming = params.get("message") or {}
            texts = [p.get("text", "") for p in incoming.get("parts", []) if p.get("kind") == "text"]
            reply = {"kind": "message", "role": "agent", "messageId": str(uuid.uuid4()),
                     "contextId": incoming.get("contextId") or str(uuid.uuid4()),
                     "parts": [{"kind": "text", "text": "echo: " + " ".join(texts)}]}
            return self.send(200, rpc_result(rid, reply))
        if method == "tasks/get":
            return self.send(200, rpc_error(rid, -32001, "Task not found"))
        return self.send(200, rpc_error(rid, -32601, "Method not found"))


class A2a1(A2a):
    """An agent that speaks A2A 1.0 as well as 0.3: its card lists both, and it answers both spellings."""

    def card(self):
        card = super().card()
        card["supportedInterfaces"] = [
            {"url": self.public_url + "/", "protocolBinding": "JSONRPC", "protocolVersion": version}
            for version in ("1.0", "0.3")]
        return card

    def answer(self, method, rid, params):
        if method == "SendMessage":
            incoming = params.get("message") or {}
            texts = [p["text"] for p in incoming.get("parts", []) if isinstance(p.get("text"), str)]
            reply = {"messageId": str(uuid.uuid4()), "role": "ROLE_AGENT",
                     "contextId": incoming.get("contextId") or str(uuid.uuid4()),
                     "parts": [{"text": "echo: " + " ".join(texts)}]}
            return self.send(200, rpc_result(rid, {"message": reply}))
        if method == "GetTask":
            return self.send(200, rpc_error(rid, -32001, "Task not found"))
        return super().answer(method, rid, params)


class Idp(Base):
    """Authorization-code grant with PKCE accepted but not enforced; every sign-in succeeds."""
    codes = {}
    issued = 0

    def get(self):
        url = urllib.parse.urlparse(self.path)
        if url.path == "/authorize":
            q = dict(urllib.parse.parse_qsl(url.query))
            code = uuid.uuid4().hex
            Idp.codes[code] = q
            sep = "&" if "?" in q.get("redirect_uri", "") else "?"
            location = "%s%s%s" % (q.get("redirect_uri", ""), sep,
                                   urllib.parse.urlencode({"code": code, "state": q.get("state", "")}))
            return self.send(302, headers={"Location": location})
        return self.send(404, {"error": "not found"})

    def post(self, raw):
        self.record(raw)
        url = urllib.parse.urlparse(self.path)
        if url.path != "/token":
            return self.send(404, {"error": "not found"})
        form = dict(urllib.parse.parse_qsl(raw.decode()))
        grant = form.get("grant_type")
        if grant == "authorization_code" and form.get("code") in Idp.codes:
            Idp.codes.pop(form["code"])
        elif grant == "refresh_token" and form.get("refresh_token", "").startswith("e2e-refresh-"):
            pass
        elif grant == "client_credentials":
            pass
        else:
            return self.send(400, {"error": "invalid_grant"})
        Idp.issued += 1
        return self.send(200, {"access_token": "e2e-access-%d" % Idp.issued, "token_type": "Bearer",
                               "expires_in": 3600, "refresh_token": "e2e-refresh-%d" % Idp.issued,
                               "scope": form.get("scope", "read")})


class Rest(Base):
    def spec(self):
        return {
            "openapi": "3.0.3",
            "info": {"title": "e2e weather", "version": "1.0.0"},
            "servers": [{"url": self.public_url}],
            "paths": {
                "/forecast/{city}": {"get": {
                    "operationId": "getForecast", "summary": "Forecast for a city",
                    "parameters": [{"name": "city", "in": "path", "required": True, "schema": {"type": "string"}}],
                    "responses": {"200": {"description": "Forecast",
                                          "content": {"application/json": {"schema": {"type": "object"}}}}}}},
                "/alerts": {"post": {
                    "operationId": "createAlert", "summary": "Create a weather alert",
                    "requestBody": {"required": True, "content": {"application/json": {"schema": {
                        "type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}}},
                    "responses": {"201": {"description": "Created"}}}},
            },
        }

    def get(self):
        path = self.path.split("?")[0]
        if path == "/openapi.json":
            return self.send(200, self.spec())
        if path.startswith("/forecast/"):
            city = urllib.parse.unquote(path[len("/forecast/"):])
            return self.send(200, {"city": city, "forecast": "sunny", "celsius": 21})
        return self.send(404, {"error": "not found"})

    def post(self, raw):
        body = self.record(raw)
        if self.path.split("?")[0] == "/alerts":
            return self.send(201, {"created": True, "city": (body or {}).get("city")})
        return self.send(404, {"error": "not found"})


KINDS = {"mcp": Mcp, "a2a": A2a, "a2a1": A2a1, "idp": Idp, "rest": Rest}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("kind", choices=sorted(KINDS))
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=0)
    a = ap.parse_args()
    secret = os.environ.get("E2E_RECORDER_SECRET", "")
    if len(secret) < 16:
        sys.exit("targets.py: set E2E_RECORDER_SECRET to a random value of at least 16 characters")
    handler = type(a.kind.title(), (KINDS[a.kind],), {"recorder": Recorder(), "recorder_secret": secret})
    server = ThreadingHTTPServer((a.host, a.port), handler)
    handler.public_url = "http://%s:%d" % (a.host, server.server_address[1])
    print("listening %s" % handler.public_url, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
