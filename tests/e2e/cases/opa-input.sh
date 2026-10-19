# Captures the real policy input on an MCP and an A2A surface with the header-free capture policy,
# following "Recipe: capture the real input" in skills/affinidi-agent-gateway/references/policies.md.
# Serial: the recipe turns audit on with policy_decision selected.
E2E_SERIAL=1

# make_surface PROTOCOL UPSTREAM NAME PREFIX_VAR: creates a surface and sets <PREFIX_VAR>_SURFACE_ID.
make_surface() {
    local routing="$E2E_CASE_DIR/routing.json" listen prefix name
    fab agent-gateway runtime show surface-routing -o json > "$routing"
    listen=$(jq -r --arg g "$GATEWAY" \
        '([.available_listen_addresses[] | select(startswith($g))] + .available_listen_addresses)[0]' "$routing")
    prefix=$(jq -r '.channel_path_prefix[0].prefix' "$routing" | sed 's#/$##')
    name=$(unique "$3")
    fab agent-gateway surfaces create --name "$name" --protocol "$1" --listen-address "$listen" --route "$prefix/$name" \
        --target-endpoint "$2" -o json > "$E2E_CASE_DIR/setup-$1.json"
    jq -r .surface_id "$E2E_CASE_DIR/setup-$1.json"
}

setup() {
    fab agent-gateway settings show -o json | jq '{audit_enabled, audit_events}' > "$E2E_CASE_DIR/e2e-settings-saved.json"
    start_target mcp
    start_target a2a
    export MCP_SURFACE_ID A2A_SURFACE_ID CAPTURE_POLICY_ID
    MCP_SURFACE_ID=$(make_surface mcp "$MCP_URL/mcp" opa-input-mcp)
    A2A_SURFACE_ID=$(make_surface a2a "$A2A_URL" opa-input-a2a)
    CAPTURE_POLICY_ID=$(unique input-capture)
}

verify() {
    expect_json 2 'set(doc) <= {"agent", "channel", "gateway", "http", "mcp"}' "MCP input keys are a subset of agent, channel, gateway, http, mcp"
    expect_json 2 'doc["gateway"]["direction"] == "inbound"' "MCP input has gateway.direction inbound"
    expect_json 2 'doc["http"]["path"] == "/"' "MCP input http.path is /"
    expect_json 2 '"source_auth" not in doc' "an anonymous caller has no source_auth"
    expect_json 2 'doc["mcp"]["method"] == "tools/call" and doc["mcp"]["tool_name"] == "echo"' "MCP input names the tool"
    expect_json 2 '"headers" not in doc["http"]' "the MCP capture carries no headers"
    expect_block 3 '^403$'
    expect_json 3 'doc["a2a"]["method"] == "message/send" and "mcp" not in doc' "A2A input carries a2a.method message/send"
    expect_json 3 'doc["a2a"].get("method_canonical") == "message/send"' "A2A input carries a2a.method_canonical"
    expect_json 3 '"headers" not in doc["http"]' "the A2A capture carries no headers"
}

cleanup() {
    local id
    for id in "${MCP_SURFACE_ID:-}" "${A2A_SURFACE_ID:-}"; do
        if [ -n "$id" ] && fab agent-gateway surfaces get "$id" -o json > /dev/null 2>&1; then
            fab agent-gateway surfaces delete "$id"
        fi
    done
    if [ -n "${CAPTURE_POLICY_ID:-}" ] && fab agent-gateway policies get "$CAPTURE_POLICY_ID" -o json > /dev/null 2>&1; then
        fab agent-gateway policies delete "$CAPTURE_POLICY_ID"
    fi
    if [ -s "$E2E_CASE_DIR/e2e-settings-saved.json" ]; then
        fab agent-gateway settings set --file "$E2E_CASE_DIR/e2e-settings-saved.json" -o json > /dev/null
    fi
}
