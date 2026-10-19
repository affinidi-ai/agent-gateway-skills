# Changes an attached policy with fabric agent-gateway policies update: the new Rego applies without a surface
# save, enabled:false is still enforced, simulate catches Rego that does not parse while update
# stores it and the surface then denies every call, and a known-good version restores service. Follows
# "Recipe: change a policy safely" in skills/affinidi-agent-gateway/references/policies.md.

make_mcp_surface() {
    local routing="$E2E_CASE_DIR/routing.json" listen prefix name
    fab agent-gateway runtime show surface-routing -o json > "$routing"
    listen=$(jq -r --arg g "$GATEWAY" \
        '([.available_listen_addresses[] | select(startswith($g))] + .available_listen_addresses)[0]' "$routing")
    prefix=$(jq -r '.channel_path_prefix[0].prefix' "$routing" | sed 's#/$##')
    name=$(unique pol-update-mcp)
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
    POLICY_ID=$(unique echo-guard)
}

verify() {
    expect_block 1 '"text": ?"before"'
    expect_json 2 'doc["allow"] is False and doc["reason"] == "echo is paused" and doc["query"] == "data.surface.policy.allow"' \
        "simulate evaluates the draft"
    expect_block 2 '"version":2'
    expect_block 3 "Tool 'echo' is not allowed by policy: echo is paused"
    expect_block 4 '"enabled":false'
    expect_block 4 "Tool 'echo' is not allowed by policy: echo is paused"
    expect_fail_block 5 'Policy failed to compile'
    expect_block 6 '"version":3'
    expect_block 6 "Tool 'echo' is not allowed by policy: no policy is loaded for this channel"
    expect_block 7 '"text": ?"restored"'
}

cleanup() {
    if [ -n "${SURFACE_ID:-}" ] && fab agent-gateway surfaces get "$SURFACE_ID" -o json > /dev/null 2>&1; then
        fab agent-gateway surfaces delete "$SURFACE_ID"
    fi
    if [ -n "${POLICY_ID:-}" ] && fab agent-gateway policies get "$POLICY_ID" -o json > /dev/null 2>&1; then
        fab agent-gateway policies delete "$POLICY_ID"
    fi
}
