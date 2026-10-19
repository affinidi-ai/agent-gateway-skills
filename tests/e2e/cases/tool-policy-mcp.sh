# Allow-lists one MCP tool with target.mcp_tool_policies, following "Recipe: allow-list tools with
# per-tool MCP policies" in skills/affinidi-agent-gateway/references/policies.md.

make_mcp_surface() {
    local routing="$E2E_CASE_DIR/routing.json" listen prefix name
    fab agent-gateway runtime show surface-routing -o json > "$routing"
    listen=$(jq -r --arg g "$GATEWAY" \
        '([.available_listen_addresses[] | select(startswith($g))] + .available_listen_addresses)[0]' "$routing")
    prefix=$(jq -r '.channel_path_prefix[0].prefix' "$routing" | sed 's#/$##')
    name=$(unique tool-policy-mcp)
    fab agent-gateway surfaces create --name "$name" --protocol mcp --listen-address "$listen" --route "$prefix/$name" \
        --target-endpoint "$MCP_URL/mcp" -o json > "$E2E_CASE_DIR/setup-surface.json"
    SURFACE_ID=$(jq -r .surface_id "$E2E_CASE_DIR/setup-surface.json")
    SURFACE_URL="$listen$prefix/$name"
    export SURFACE_ID SURFACE_URL
}

setup() {
    start_target mcp
    make_mcp_surface
    export ALLOW_POLICY_ID
    ALLOW_POLICY_ID=$(unique allow-tool)
    clear_target MCP_URL
}

verify() {
    expect_block 1 '"tool_name":"echo"'
    expect_block 1 "\"policy_definition_id\":\"$ALLOW_POLICY_ID\""
    expect_json 2 'doc["id"] == 7 and doc["error"]["code"] == -32000 and doc["error"]["message"] == "Access denied: insufficient permissions for this tool"' \
        "an unlisted tool gets -32000 with the request id"
    expect_block 2 '"text": ?"allowed"'
    expect_block 2 '\{"listed":\["echo","add","delete_everything"\]\}'
    target_requests MCP_URL > "$E2E_CASE_DIR/mcp-requests.json"
    jq -e 'any(.[]; .body.params.name? == "delete_everything") | not' "$E2E_CASE_DIR/mcp-requests.json" > /dev/null \
        || fail "the refused delete_everything call reached the MCP target" "$E2E_CASE_DIR/mcp-requests.json"
    pass "the refused call never reached the MCP target"
}

cleanup() {
    if [ -n "${SURFACE_ID:-}" ] && fab agent-gateway surfaces get "$SURFACE_ID" -o json > /dev/null 2>&1; then
        fab agent-gateway surfaces delete "$SURFACE_ID"
    fi
    if [ -n "${ALLOW_POLICY_ID:-}" ] && fab agent-gateway policies get "$ALLOW_POLICY_ID" -o json > /dev/null 2>&1; then
        fab agent-gateway policies delete "$ALLOW_POLICY_ID"
    fi
}
