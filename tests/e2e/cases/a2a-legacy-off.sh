# Turns the a2a_legacy_compatibility flag off and back on, following "Recipe: refuse A2A v0.3 callers" in
# skills/affinidi-agent-gateway/references/protocols.md. Blocks: 1 read the counter and save the settings,
# 2 turn the flag off, 3 a request with no A2A-Version, 4 restore the saved map. Serial: the flag applies to
# every A2A surface on the gateway.
E2E_SERIAL=1

setup() {
    local routing="$E2E_CASE_DIR/routing.json" listen prefix name
    fab agent-gateway settings show -o json | jq '{feature_flags: ((.feature_flags // {}) | del(.terms))}' \
        > "$E2E_CASE_DIR/e2e-flags-saved.json"
    start_target a2a
    fab agent-gateway runtime show surface-routing -o json > "$routing"
    listen=$(jq -r --arg g "$GATEWAY" \
        '([.available_listen_addresses[] | select(startswith($g))] + .available_listen_addresses)[0]' "$routing")
    prefix=$(jq -r '.channel_path_prefix[0].prefix' "$routing" | sed 's#/$##')
    name=$(unique legacy-off)
    fab agent-gateway surfaces create --name "$name" --protocol a2a --listen-address "$listen" --route "$prefix/$name" \
        --target-endpoint "$A2A_URL" -o json > "$E2E_CASE_DIR/setup-surface.json"
    SURFACE_ID=$(jq -r .surface_id "$E2E_CASE_DIR/setup-surface.json")
    SURFACE_URL="$listen$prefix/$name"
    export SURFACE_ID SURFACE_URL
    clear_target A2A_URL
}

verify() {
    expect_block 2 '"a2a_legacy_compatibility": ?false'
    expect_block 3 '^HTTP 400$'
    expect_json 3 'doc["error"]["code"] == -32009 and doc["error"]["data"]["supported"] == ["1.0"] and doc["id"] is None' \
        "with the flag off, a request with no A2A-Version gets -32009 and only 1.0 is supported"
    target_requests A2A_URL > "$E2E_CASE_DIR/a2a-requests.json"
    jq -e 'length == 0' "$E2E_CASE_DIR/a2a-requests.json" > /dev/null \
        || fail "the refused request reached the A2A target" "$E2E_CASE_DIR/a2a-requests.json"
    pass "the refused request never reached the A2A target"
    curl -sS -w '\nHTTP %{http_code}\n' "$SURFACE_URL" -H 'Content-Type: application/json' \
        -d '{"jsonrpc":"2.0","id":2,"method":"tasks/get","params":{"id":"probe"}}' > "$E2E_CASE_DIR/after-undo.out" 2>&1
    if grep -q -- '-32009' "$E2E_CASE_DIR/after-undo.out"; then
        fail "after the undo, a request with no A2A-Version is still refused" "$E2E_CASE_DIR/after-undo.out"
    fi
    target_requests A2A_URL > "$E2E_CASE_DIR/a2a-requests-after.json"
    jq -e 'any(.[]; .body.method == "tasks/get")' "$E2E_CASE_DIR/a2a-requests-after.json" > /dev/null \
        || fail "after the undo, the request did not reach the A2A target" "$E2E_CASE_DIR/after-undo.out"
    pass "after the undo, a request with no A2A-Version is forwarded again"
}

cleanup() {
    if [ -n "${SURFACE_ID:-}" ] && fab agent-gateway surfaces get "$SURFACE_ID" -o json > /dev/null 2>&1; then
        fab agent-gateway surfaces delete "$SURFACE_ID"
    fi
    if [ -s "$E2E_CASE_DIR/e2e-flags-saved.json" ]; then
        fab agent-gateway settings set --file "$E2E_CASE_DIR/e2e-flags-saved.json" -o json > /dev/null
    fi
}
