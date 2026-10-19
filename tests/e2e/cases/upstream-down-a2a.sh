# Rehearse an upstream outage on an A2A surface, from references/operations.md
# "Rehearse an upstream outage". No target: the surface points at a loopback port nothing listens on.
# Blocks: 1 create the drill surface, 2 six calls with no breaker, 3 add networking with a
# circuit breaker (failure_threshold 3), 4 four calls.

setup() {
    if curl -sS --connect-timeout 2 -o /dev/null http://127.0.0.1:9/ 2>/dev/null; then
        fail "something answers on 127.0.0.1:9; the drill needs a port that refuses connections"
    fi
    export UPSTREAM_URL="http://127.0.0.1:9"
    SURFACE_NAME="$(unique outage-a2a)"
    export SURFACE_NAME FAILURE_THRESHOLD=3
}

verify() {
    expect_json 1 'doc.get("status") == "active" and bool(doc.get("surface_id")) and doc.get("networking") is None' \
        "the drill surface is active with no networking block"
    local i
    for i in 1 2 3 4 5 6; do
        expect_block 2 "^call $i: HTTP 502\$"
    done
    expect_json 2 'doc["status"] == 502 and doc["detail"].startswith("Connection failed to target endpoint") and doc["type"] == "https://a2a-protocol.org/errors/proxy-error"' \
        "with no breaker every call is a 502 Connection failed problem+json"
    expect_json 3 'doc["circuit_breaker"]["failure_threshold"] == 3 and doc["timeout"]["request_secs"] == 30' \
        "the networking object holds the breaker and the timeout"
    for i in 1 2 3; do
        expect_block 4 "^call $i: HTTP 502\$"
    done
    expect_block 4 '^call 4: HTTP 503$'
    expect_json 4 'doc["status"] == 503 and doc["detail"].startswith("Service temporarily unavailable. Retry after")' \
        "after failure_threshold failures the breaker answers 503"
}

cleanup() {
    local id
    [ -f "$E2E_CASE_DIR/drill.json" ] || return 0
    id=$("$PYTHON" -c 'import json, sys; print(json.load(open(sys.argv[1])).get("surface_id") or "")' "$E2E_CASE_DIR/drill.json" 2>/dev/null || true)
    [ -n "$id" ] || return 0
    if fab agent-gateway surfaces get "$id" -o json >/dev/null 2>&1; then
        fab agent-gateway surfaces delete "$id" >/dev/null
    fi
}
