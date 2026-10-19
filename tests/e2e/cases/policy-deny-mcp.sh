# Denies one MCP tool with a target.policy, following "Recipe: deny a tool (MCP) or a message (A2A)"
# in skills/affinidi-agent-gateway/references/policies.md.

# Creates an MCP surface on the listener that matches $GATEWAY and exports SURFACE_ID and SURFACE_URL.
make_mcp_surface() {
    local routing="$E2E_CASE_DIR/routing.json" listen prefix name
    fab agent-gateway runtime show surface-routing -o json > "$routing"
    listen=$(jq -r --arg g "$GATEWAY" \
        '([.available_listen_addresses[] | select(startswith($g))] + .available_listen_addresses)[0]' "$routing")
    prefix=$(jq -r '.channel_path_prefix[0].prefix' "$routing" | sed 's#/$##')
    name=$(unique pol-deny-mcp)
    fab agent-gateway surfaces create --name "$name" --protocol mcp --listen-address "$listen" --route "$prefix/$name" \
        --target-endpoint "$MCP_URL/mcp" -o json > "$E2E_CASE_DIR/setup-surface.json"
    SURFACE_ID=$(jq -r .surface_id "$E2E_CASE_DIR/setup-surface.json")
    SURFACE_URL="$listen$prefix/$name"
    export SURFACE_ID SURFACE_URL
}

setup() {
    start_target mcp
    make_mcp_surface
    export POLICY_ID
    POLICY_ID=$(unique block-dangerous-tools)
    clear_target MCP_URL
}

verify() {
    expect_block 1 "data plane: $SURFACE_URL"
    expect_block 2 "\"policy_definition_id\":\"$POLICY_ID\""
    expect_json 3 'doc["result"]["content"][0]["text"] == "still here"' "echo still works"
    expect_block 3 '"code": ?-32001'
    expect_block 3 "Tool 'delete_everything' is not allowed by policy: tool delete_everything is blocked on this surface"
    expect_block 3 '\{"listed":\["echo","add"\]\}'
    target_requests MCP_URL > "$E2E_CASE_DIR/mcp-requests.json"
    jq -e 'any(.[]; .body.params.name? == "echo")' "$E2E_CASE_DIR/mcp-requests.json" > /dev/null \
        || fail "the MCP target never received the echo call" "$E2E_CASE_DIR/mcp-requests.json"
    pass "the MCP target received the echo call"
    jq -e 'any(.[]; .body.params.name? == "delete_everything") | not' "$E2E_CASE_DIR/mcp-requests.json" > /dev/null \
        || fail "the denied delete_everything call reached the MCP target" "$E2E_CASE_DIR/mcp-requests.json"
    pass "the denied call never reached the MCP target"
}

cleanup() {
    if [ -n "${SURFACE_ID:-}" ] && fab agent-gateway surfaces get "$SURFACE_ID" -o json > /dev/null 2>&1; then
        fab agent-gateway surfaces delete "$SURFACE_ID"
    fi
    if [ -n "${POLICY_ID:-}" ] && fab agent-gateway policies get "$POLICY_ID" -o json > /dev/null 2>&1; then
        fab agent-gateway policies delete "$POLICY_ID"
    fi
}
