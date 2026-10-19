# Rate-limit an A2A surface, from references/operations.md "Rate-limit a surface".
# Blocks: 1 two message/send calls. setup creates the surface and applies the recipe's change
# (the same add-feature command the MCP case runs as a block), writing after.json.

setup() {
    start_target a2a
    SURFACE_NAME="$(unique rl-a2a)"
    fab agent-gateway runtime show surface-routing -o json > "$E2E_CASE_DIR/routing.json"
    local listen prefix
    listen=$("$PYTHON" -c 'import json, sys; print(json.load(open(sys.argv[1]))["available_listen_addresses"][0])' "$E2E_CASE_DIR/routing.json")
    prefix=$("$PYTHON" -c 'import json, sys; print(json.load(open(sys.argv[1]))["channel_path_prefix"][0]["prefix"])' "$E2E_CASE_DIR/routing.json")
    fab agent-gateway surfaces create --name "$SURFACE_NAME" --protocol a2a --listen-address "$listen" \
        --route "$prefix/$SURFACE_NAME" --target-endpoint "$A2A_URL" -o json > "$E2E_CASE_DIR/surface.json"
    SURFACE_ID=$("$PYTHON" -c 'import json, sys; print(json.load(open(sys.argv[1]))["surface_id"])' "$E2E_CASE_DIR/surface.json")
    [ -n "$SURFACE_ID" ] || fail "setup could not create the A2A surface" "$E2E_CASE_DIR/surface.json"
    fab agent-gateway surfaces add-feature "$SURFACE_ID" rate-limit \
        --json '{"requests":1,"window_secs":60}' -o json > "$E2E_CASE_DIR/after.json"
    "$PYTHON" -c 'import json, sys; assert json.load(open(sys.argv[1]))["access_point"]["rate_limit"] == {"requests": 1, "window_secs": 60}' \
        "$E2E_CASE_DIR/after.json" || fail "setup could not apply the rate limit" "$E2E_CASE_DIR/after.json"
}

verify() {
    expect_block 1 '^call 1: HTTP 200$'
    expect_block 1 '^call 2: HTTP 429$'
    expect_json 1 'doc["status"] == 429 and doc["detail"] == "Rate limit exceeded" and doc["type"] == "https://a2a-protocol.org/errors/proxy-error"' \
        "the 429 is problem+json with detail Rate limit exceeded"
    expect_block 1 '^retry-after: [0-9]+'
    "$PYTHON" - "$E2E_CASE_DIR/last-headers.txt" <<'PY' || fail "the 429 has no Retry-After header of 1 to 60 whole seconds" "$E2E_CASE_DIR/last-headers.txt"
import re, sys
values = [l.split(":", 1)[1].strip() for l in open(sys.argv[1]) if l.lower().startswith("retry-after:")]
assert len(values) == 1 and re.fullmatch(r"[0-9]+", values[0]) and 1 <= int(values[0]) <= 60, values
PY
    pass "the 429 carries Retry-After in whole seconds, at most the 60 s window"
    grep -qi '^content-type: *application/problem+json' "$E2E_CASE_DIR/last-headers.txt" \
        || fail "the 429 is not application/problem+json" "$E2E_CASE_DIR/last-headers.txt"
    pass "the 429 content type is application/problem+json"
    target_requests A2A_URL > "$E2E_CASE_DIR/requests.json"
    "$PYTHON" - "$E2E_CASE_DIR/requests.json" <<'PY' || fail "the agent saw the rate-limited call" "$E2E_CASE_DIR/requests.json"
import json, sys
reqs = [r for r in json.load(open(sys.argv[1])) if r["method"] == "POST"]
assert len(reqs) == 1, len(reqs)
PY
    pass "only the first call reached the agent"
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
