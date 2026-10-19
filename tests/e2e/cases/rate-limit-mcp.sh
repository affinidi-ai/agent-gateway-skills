# Rate-limit an MCP surface, from references/operations.md "Rate-limit a surface".
# Blocks: 1 add rate-limit {"requests":1,"window_secs":60}, 2 two initialize calls.
# setup creates the surface the recipe limits; the recipe itself only takes SURFACE_ID.

setup() {
    start_target mcp
    SURFACE_NAME="$(unique rl-mcp)"
    fab agent-gateway runtime show surface-routing -o json > "$E2E_CASE_DIR/routing.json"
    local listen prefix
    listen=$("$PYTHON" -c 'import json, sys; print(json.load(open(sys.argv[1]))["available_listen_addresses"][0])' "$E2E_CASE_DIR/routing.json")
    prefix=$("$PYTHON" -c 'import json, sys; print(json.load(open(sys.argv[1]))["channel_path_prefix"][0]["prefix"])' "$E2E_CASE_DIR/routing.json")
    fab agent-gateway surfaces create --name "$SURFACE_NAME" --protocol mcp --listen-address "$listen" \
        --route "$prefix/$SURFACE_NAME" --target-endpoint "$MCP_URL/mcp" -o json > "$E2E_CASE_DIR/surface.json"
    SURFACE_ID=$("$PYTHON" -c 'import json, sys; print(json.load(open(sys.argv[1]))["surface_id"])' "$E2E_CASE_DIR/surface.json")
    [ -n "$SURFACE_ID" ] || fail "setup could not create the MCP surface" "$E2E_CASE_DIR/surface.json"
    export SURFACE_ID REQUESTS=1 WINDOW_SECS=60
}

verify() {
    "$PYTHON" -c 'import json, sys; assert json.load(open(sys.argv[1]))["access_point"].get("rate_limit") is None' \
        "$E2E_CASE_DIR/surface.json" || fail "the new surface already had a rate limit" "$E2E_CASE_DIR/surface.json"
    expect_json 1 'doc == {"requests": 1, "window_secs": 60}' "the surface now carries the rate limit"
    expect_block 2 '^call 1: HTTP 200$'
    expect_block 2 '^call 2: HTTP 429$'
    expect_json 2 'doc["jsonrpc"] == "2.0" and doc["id"] is None and doc["error"]["code"] == -32000 and doc["error"]["message"] == "Rate limit exceeded"' \
        "the 429 body is JSON-RPC -32000 Rate limit exceeded with id null"
    expect_json 2 'doc["error"]["data"]["retry_after"].startswith("Rate limit exceeded. Retry after")' \
        "data.retry_after is a sentence, not a number of seconds"
    expect_block 2 '^retry-after: [0-9]+'
    "$PYTHON" - "$E2E_CASE_DIR/last-headers.txt" <<'PY' || fail "the 429 has no Retry-After header of 1 to 60 whole seconds" "$E2E_CASE_DIR/last-headers.txt"
import re, sys
values = [l.split(":", 1)[1].strip() for l in open(sys.argv[1]) if l.lower().startswith("retry-after:")]
assert len(values) == 1 and re.fullmatch(r"[0-9]+", values[0]) and 1 <= int(values[0]) <= 60, values
PY
    pass "the 429 carries Retry-After in whole seconds, at most the 60 s window"
    target_requests MCP_URL > "$E2E_CASE_DIR/requests.json"
    "$PYTHON" - "$E2E_CASE_DIR/requests.json" <<'PY' || fail "the upstream saw the rate-limited call" "$E2E_CASE_DIR/requests.json"
import json, sys
reqs = [r for r in json.load(open(sys.argv[1])) if r["method"] == "POST"]
assert len(reqs) == 1, len(reqs)
PY
    pass "only the first call reached the upstream"
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
