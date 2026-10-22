# Narrows one A2A surface to A2A 1.0 and back, following "Recipe: accept only A2A v1.0 on a surface" in
# skills/affinidi-agent-gateway/references/protocols.md, in front of an agent that speaks both versions.
# Blocks: 1 read the agent card's versions and the counter, 2 save the surface's settings, 3 accept 1.0 only,
# 4 a request with no A2A-Version and one with A2A-Version 1.0, 5 restore the saved settings. The counter the
# recipe reads must then show each of those requests under this surface's name.

setup() {
    local routing="$E2E_CASE_DIR/routing.json" listen prefix name
    start_target a2a1
    fab agent-gateway runtime show surface-routing -o json > "$routing"
    listen=$(jq -r --arg g "$GATEWAY" \
        '([.available_listen_addresses[] | select(startswith($g))] + .available_listen_addresses)[0]' "$routing")
    prefix=$(jq -r '.channel_path_prefix[0].prefix' "$routing" | sed 's#/$##')
    name=$(unique v1-only)
    fab agent-gateway surfaces create --name "$name" --protocol a2a --listen-address "$listen" --route "$prefix/$name" \
        --target-endpoint "$A2A1_URL" -o json > "$E2E_CASE_DIR/setup-surface.json"
    SURFACE_ID=$(jq -r .surface_id "$E2E_CASE_DIR/setup-surface.json")
    SURFACE_URL="$listen$prefix/$name"
    SURFACE_NAME=$name
    export SURFACE_ID SURFACE_URL SURFACE_NAME
    clear_target A2A1_URL
}

verify() {
    expect_json 1 'doc == {"name": "e2e-a2a", "versions": ["0.3", "1.0"]}' \
        "the agent's card, read through the surface, lists A2A 1.0"
    expect_json 2 'doc == {"accepted_versions": ["0.3", "1.0"], "validation": "envelope"}' \
        "a new A2A surface accepts both versions and checks the JSON-RPC envelope"
    expect_json 3 'doc == {"accepted_versions": ["1.0"], "validation": "envelope"}' \
        "the surface accepts 1.0 only and keeps its validation level"
    expect_block 4 '^HTTP 400$'
    expect_json 4 'doc["error"]["code"] == -32009 and doc["error"]["data"]["requested"] == "0.3" and doc["error"]["data"]["supported"] == ["1.0"] and doc["id"] is None' \
        "a request with no A2A-Version counts as 0.3 and gets -32009 with only 1.0 supported"
    expect_block 4 '^HTTP 200$'
    expect_block 4 'Task not found'
    target_requests A2A1_URL > "$E2E_CASE_DIR/a2a-requests.json"
    jq -e '[.[] | select(.method == "POST") | .body.method] == ["GetTask"]' "$E2E_CASE_DIR/a2a-requests.json" > /dev/null \
        || fail "the agent should have seen only the A2A-Version 1.0 request" "$E2E_CASE_DIR/a2a-requests.json"
    pass "the refused request never reached the agent, and the agent answered the A2A-Version 1.0 request itself"
    expect_json 5 'doc == {"accepted_versions": ["0.3", "1.0"], "validation": "envelope"}' \
        "the undo puts the saved settings back"
    clear_target A2A1_URL
    curl -sS -w '\nHTTP %{http_code}\n' "$SURFACE_URL" -H 'Content-Type: application/json' \
        -d '{"jsonrpc":"2.0","id":3,"method":"tasks/get","params":{"id":"probe"}}' > "$E2E_CASE_DIR/after-undo.out" 2>&1
    if grep -q -- '-32009' "$E2E_CASE_DIR/after-undo.out"; then
        fail "after the undo, a request with no A2A-Version is still refused" "$E2E_CASE_DIR/after-undo.out"
    fi
    target_requests A2A1_URL > "$E2E_CASE_DIR/a2a-requests-after.json"
    jq -e 'any(.[]; .body.method == "tasks/get")' "$E2E_CASE_DIR/a2a-requests-after.json" > /dev/null \
        || fail "after the undo, the request did not reach the A2A target" "$E2E_CASE_DIR/after-undo.out"
    pass "after the undo, a request with no A2A-Version is forwarded again"
    local metrics="$E2E_CASE_DIR/metrics.out" negotiated era
    fab agent-gateway metrics scrape > "$metrics"
    for negotiated in rejected:0.3 1.0:1.0 0.3:0.3; do
        era=${negotiated#*:} negotiated=${negotiated%%:*}
        grep '^agent_gateway_a2a_protocol_version_total{' "$metrics" | grep -F "channel_id=\"$SURFACE_NAME\"" \
            | grep -F "negotiated_version=\"$negotiated\"" | grep -F "method_era=\"$era\"" > /dev/null \
            || fail "the A2A version counter has no $negotiated series with method_era $era for the surface" "$metrics"
    done
    pass "agent_gateway_a2a_protocol_version_total counts the refused request as rejected, then 1.0 and 0.3"
}

cleanup() {
    if [ -n "${SURFACE_ID:-}" ] && fab agent-gateway surfaces get "$SURFACE_ID" -o json > /dev/null 2>&1; then
        fab agent-gateway surfaces delete "$SURFACE_ID"
    fi
}
