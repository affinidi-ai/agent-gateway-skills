# The A2A agent card and the JSON-RPC relay, from references/protocols.md "A2A on the wire".
# Blocks: 1 create the surface, 2 fetch the card at agent-card.json and agent.json, 3 message/send,
# 4 tasks/get for an unknown task, 5 a body without a method, 6 the card's media type, 7 an unsupported
# A2A-Version, 8 turn on the request-shape check, 9 a malformed v1.0 message, 10 a well-formed v1.0 SendMessage.

setup() {
    start_target a2a
    export UPSTREAM_URL="$A2A_URL"
    SURFACE_NAME="$(unique card-a2a)"
    export SURFACE_NAME
}

verify() {
    expect_json 1 'doc.get("status") == "active" and bool(doc.get("surface_id"))' "the surface is created active"
    expect_block 2 '^agent-card.json HTTP 200$'
    expect_block 2 '^agent.json HTTP 200$'
    "$PYTHON" - "$E2E_CASE_DIR" <<'PY' || fail "the card URL was not rewritten to the surface" "$E2E_CASE_DIR/block-2.out"
import json, os, sys
d = sys.argv[1]
surface = json.load(open(os.path.join(d, "surface.json")))
base = surface["access_point"]["listen_address"] + surface["access_point"]["route"]
upstream = os.environ["A2A_URL"]
for name in ("card.json", "card-legacy.json"):
    url = json.load(open(os.path.join(d, name)))["url"]
    assert url.startswith(base), (name, url, base)
    assert not url.startswith(upstream), (name, url, upstream)
PY
    pass "both card paths advertise the surface URL, not the agent's"
    expect_json 2 'doc == {"leaked": []}' "no string in the served card names the agent's own URL"
    expect_block 3 '^HTTP 200$'
    expect_block 3 'echo: hello'
    expect_block 4 '^HTTP 200$'
    expect_json 4 'doc["error"]["code"] == -32001 and doc["error"]["message"] == "Task not found" and doc["id"] == "req-2"' \
        "tasks/get returns the agent's own JSON-RPC error"
    expect_block 5 '^HTTP 400$'
    expect_json 5 'doc["error"]["code"] == -32600 and doc["id"] is None' "a body without a method gets -32600 with id null"
    expect_block 6 '^no header: application/json'
    expect_block 6 '^A2A-Version 1.0: application/a2a\+json'
    expect_block 7 '^HTTP 400$'
    expect_json 7 'doc["error"]["code"] == -32009 and doc["id"] is None and doc["error"]["data"]["requested"] == "9.9" and doc["error"]["data"]["supported"] == ["0.3", "1.0"]' \
        "an unsupported A2A-Version gets -32009 naming the requested version and the surface's accepted versions"
    expect_json 8 'doc == {"accepted_versions": ["0.3", "1.0"], "validation": "full"}' \
        "the surface checks the request shape and still accepts both versions"
    expect_block 9 '^HTTP 400$'
    expect_json 9 'doc["error"]["code"] == -32602 and doc["id"] is None and {e["field"] for e in doc["error"]["data"]["errors"]} == {"params.message.messageId", "params.message.role"} and any("in A2A 1.0 (SendMessage)" in e["message"] for e in doc["error"]["data"]["errors"])' \
        "a malformed v1.0 message gets -32602 with one entry per bad field, judged by the A2A 1.0 rules"
    expect_block 10 '^HTTP 200$'
    expect_json 10 'doc["error"]["code"] == -32601 and doc["id"] == "req-6"' \
        "a well-formed v1.0 SendMessage passes the shape check and reaches the v0.3-only agent, which answers with its own error"

    target_requests A2A_URL > "$E2E_CASE_DIR/requests.json"
    "$PYTHON" - "$E2E_CASE_DIR/requests.json" <<'PY' || fail "the agent saw the wrong requests" "$E2E_CASE_DIR/requests.json"
import json, sys
reqs = json.load(open(sys.argv[1]))
gets = [r["path"].split("?")[0] for r in reqs if r["method"] == "GET"]
assert any(p.endswith("/.well-known/agent-card.json") for p in gets), gets
assert not any(p.endswith("/agent.json") for p in gets), gets
posts = [r for r in reqs if r["method"] == "POST"]
methods = [r["body"].get("method") if isinstance(r.get("body"), dict) else None for r in posts]
assert methods == ["message/send", "tasks/get", "SendMessage"], methods
assert posts[2]["body"]["params"]["message"]["parts"] == [{"text": "hello"}], posts[2]["body"]
assert all(r["headers"].get("x-gateway-trace-id") for r in posts), [sorted(r["headers"]) for r in posts]
PY
    pass "the agent saw agent-card.json fetches (never agent.json), then message/send, tasks/get and SendMessage as sent, each POST with x-gateway-trace-id"
}

cleanup() {
    local id
    [ -f "$E2E_CASE_DIR/surface.json" ] || return 0
    id=$("$PYTHON" -c 'import json, sys; print(json.load(open(sys.argv[1])).get("surface_id") or "")' "$E2E_CASE_DIR/surface.json" 2>/dev/null || true)
    [ -n "$id" ] || return 0
    if fab agent-gateway surfaces get "$id" -o json >/dev/null 2>&1; then
        fab agent-gateway surfaces delete "$id" >/dev/null
    fi
}
