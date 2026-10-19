# priority: P2
# Transit points: the worked example in skills/affinidi-agent-gateway/references/surfaces.md, "Transit Points".
# An MCP surface with one transit point `orders` to an a2a target. The inbound tools/call makes the mcp target
# receive X-Transit-Token; the tokenless outbound call gets 401. verify() then plays the managed agent: it copies
# the token from the mcp target's recorded request, calls the transit point with it (the a2a target answers), and
# calls an alias that does not exist (404). The token is never printed.
# Serial: saving a surface with transit points runs a full in-process reload that rebinds all listeners.
E2E_SERIAL=1

setup() {
    fab agent-gateway runtime show surface-routing -o json > "$E2E_CASE_DIR/setup-routing.json"
    "$PYTHON" - "$E2E_CASE_DIR/setup-routing.json" > "$E2E_CASE_DIR/outbound-address.txt" <<'PY'
import json, os, sys, urllib.parse
host = urllib.parse.urlsplit(os.environ["GATEWAY"]).hostname
for addr in json.load(open(sys.argv[1])).get("available_outbound_listen_addresses") or []:
    url = addr if "://" in addr else "http://" + addr
    if urllib.parse.urlsplit(url).hostname == host:
        print(addr)
        break
PY
    OUTBOUND_ADDRESS=$(cat "$E2E_CASE_DIR/outbound-address.txt")
    [ -n "$OUTBOUND_ADDRESS" ] || fail "no outbound listen address on the gateway's host; this case needs an outbound listener"
    export OUTBOUND_ADDRESS
    start_target mcp
    start_target a2a
    export UPSTREAM_URL="$MCP_URL/mcp" DOWNSTREAM_URL="$A2A_URL"
    SURFACE_NAME="$(unique transit)"
    export SURFACE_NAME
}

verify() {
    expect_json 1 'doc["points"] == [{"alias": "orders", "protocol": "a2a", "require_transit_token": True}]' \
        "the transit point defaults to requiring a token"
    expect_block 2 'HTTP 401'
    expect_block 2 'missing X-Transit-Token header'
    target_requests MCP_URL > "$E2E_CASE_DIR/mcp-requests.json"
    "$PYTHON" - "$E2E_CASE_DIR/mcp-requests.json" "$E2E_CASE_DIR/transit-token" <<'PY' || fail "the mcp target received no X-Transit-Token on the inbound tools/call"
import json, sys
for r in json.load(open(sys.argv[1])):
    body = r.get("body")
    transit = r.get("headers", {}).get("x-transit-token")
    if isinstance(body, dict) and body.get("method") == "tools/call" and transit:
        open(sys.argv[2], "w").write(transit)
        sys.exit(0)
sys.exit(1)
PY
    pass "the managed agent received X-Transit-Token on the inbound leg"
    local base status
    base=$("$PYTHON" -c 'import json, sys
s = json.load(open(sys.argv[1]))
u = s["transit"]["outbound_listen_address"] + "/outbound" + s["access_point"]["route"]
print(u if "://" in u else "http://" + u)' "$E2E_CASE_DIR/surface.json")
    status=$(curl -sS -o "$E2E_CASE_DIR/tp-reply.json" -w '%{http_code}' "$base/orders" \
        -H 'Content-Type: application/json' -H "X-Transit-Token: $(cat "$E2E_CASE_DIR/transit-token")" \
        -d '{"jsonrpc":"2.0","id":"1","method":"message/send","params":{"message":{"role":"user","messageId":"m-1","parts":[{"kind":"text","text":"status"}]}}}')
    [ "$status" = 200 ] && grep -q 'echo: status' "$E2E_CASE_DIR/tp-reply.json" \
        || fail "the transit point call with the token got HTTP $status" "$E2E_CASE_DIR/tp-reply.json"
    pass "with the token, the transit point reached the a2a target"
    status=$(curl -sS -o /dev/null -w '%{http_code}' "$base/nope" -H 'Content-Type: application/json' \
        -H "X-Transit-Token: $(cat "$E2E_CASE_DIR/transit-token")" -d '{}')
    [ "$status" = 404 ] || fail "an unknown transit point alias got HTTP $status, expected 404"
    pass "an unknown transit point alias gets 404"
}

cleanup() {
    local id
    rm -f "$E2E_CASE_DIR/transit-token"
    [ -s "$E2E_CASE_DIR/surface.json" ] || return 0
    id=$("$PYTHON" -c 'import json, sys; print(json.load(open(sys.argv[1])).get("surface_id") or "")' "$E2E_CASE_DIR/surface.json" 2>/dev/null) || return 0
    [ -n "$id" ] || return 0
    if fab agent-gateway surfaces get "$id" -o json >/dev/null 2>&1; then
        fab agent-gateway surfaces delete "$id" >/dev/null
    fi
}
