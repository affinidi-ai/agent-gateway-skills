# Denies A2A messages that mention refunds with a target.policy and reads the reason from the audit
# log, following "Recipe: deny a tool (MCP) or a message (A2A)" in
# skills/affinidi-agent-gateway/references/policies.md. Serial: the recipe turns audit on with
# policy_decision selected.
E2E_SERIAL=1

make_a2a_surface() {
    local routing="$E2E_CASE_DIR/routing.json" listen prefix name
    fab agent-gateway runtime show surface-routing -o json > "$routing"
    listen=$(jq -r --arg g "$GATEWAY" \
        '([.available_listen_addresses[] | select(startswith($g))] + .available_listen_addresses)[0]' "$routing")
    prefix=$(jq -r '.channel_path_prefix[0].prefix' "$routing" | sed 's#/$##')
    name=$(unique pol-deny-a2a)
    fab agent-gateway surfaces create --name "$name" --protocol a2a --listen-address "$listen" --route "$prefix/$name" \
        --target-endpoint "$A2A_URL" -o json > "$E2E_CASE_DIR/setup-surface.json"
    SURFACE_ID=$(jq -r .surface_id "$E2E_CASE_DIR/setup-surface.json")
    SURFACE_URL="$listen$prefix/$name"
    export SURFACE_ID SURFACE_URL
}

setup() {
    fab agent-gateway settings show -o json | jq '{audit_enabled, audit_events}' > "$E2E_CASE_DIR/e2e-settings-saved.json"
    start_target a2a
    make_a2a_surface
    export POLICY_ID
    POLICY_ID=$(unique route-refunds-to-people)
    clear_target A2A_URL
}

verify() {
    expect_block 1 "\"policy_definition_id\":\"$POLICY_ID\""
    expect_block 2 '"message": ?"Agent trust policy denied the request"'
    expect_block 2 'status 403'
    [ "$(grep -c '^status 403$' "$(e2e_block_file 2)")" -eq 2 ] \
        || fail "the v0.3 and the v1.0 refund message were not both denied" "$(e2e_block_file 2)"
    pass "both refund messages, message/send and SendMessage, were denied with 403"
    expect_block 2 'echo: Where is order 42\?'
    expect_block 2 'status 200'
    expect_block 2 '"deny_reason":"refund requests go to a person, not to this agent"'
    expect_block 2 '"scope":"surface"'
    expect_block 2 '"flow":"access_point"'
    target_requests A2A_URL > "$E2E_CASE_DIR/a2a-requests.json"
    jq -e 'any(.[]; (.body | tostring | ascii_downcase | contains("refund"))) | not' \
        "$E2E_CASE_DIR/a2a-requests.json" > /dev/null \
        || fail "the denied refund message reached the A2A target" "$E2E_CASE_DIR/a2a-requests.json"
    pass "the denied message never reached the A2A target"
}

cleanup() {
    if [ -n "${SURFACE_ID:-}" ] && fab agent-gateway surfaces get "$SURFACE_ID" -o json > /dev/null 2>&1; then
        fab agent-gateway surfaces delete "$SURFACE_ID"
    fi
    if [ -n "${POLICY_ID:-}" ] && fab agent-gateway policies get "$POLICY_ID" -o json > /dev/null 2>&1; then
        fab agent-gateway policies delete "$POLICY_ID"
    fi
    if [ -s "$E2E_CASE_DIR/e2e-settings-saved.json" ]; then
        fab agent-gateway settings set --file "$E2E_CASE_DIR/e2e-settings-saved.json" -o json > /dev/null
    fi
}
