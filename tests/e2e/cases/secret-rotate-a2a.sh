# Recipe: rotate a secret with no downtime (skills/affinidi-agent-gateway/references/credentials.md).
# setup() creates a secret with a description and an A2A surface whose target.auth uses it. The recipe
# rotates the value with no surface write. verify() checks the description survived, updated_at moved,
# and the next message/send carried the new value.

setup() {
    start_target a2a A2A_URL
    fab agent-gateway runtime show surface-routing -o json > routing.json
    local listen prefix name
    listen=$(jq -r --arg gw "$GATEWAY" \
        '[.available_listen_addresses[] | select(. == $gw)][0] // .available_listen_addresses[0]' routing.json)
    prefix=$(jq -r '.channel_path_prefix[0].prefix' routing.json)
    name=$(unique rotate-a2a)
    SECRET_ID=$(unique rotate-key)
    NEW_KEY_VALUE="e2e-$E2E_RUN_ID-new"
    export SECRET_ID NEW_KEY_VALUE
    printf '%s' "e2e-$E2E_RUN_ID-old" | fab agent-gateway secrets create --name "$SECRET_ID" --secret-id "$SECRET_ID" \
        --description "e2e rotation" --value-stdin -o json > /dev/null
    jq -n --arg name "$name" --arg listen "$listen" --arg route "$prefix/$name" --arg endpoint "$A2A_URL" \
        --arg secret "$SECRET_ID" '{name: $name,
        access_point: {listen_address: $listen, route: $route, protocol: "a2a"},
        target: {endpoint: $endpoint, auth: {method: {static_secret: {secret_id: $secret,
            header_name: "Authorization", header_format: "Bearer {value}"}}, fallback: "reject"}}}' \
        > setup-surface-doc.json
    fab agent-gateway surfaces create --file setup-surface-doc.json -o json > setup-surface.json
    SURFACE_ID=$(jq -r .surface_id setup-surface.json)
    export SURFACE_ID
}

verify() {
    expect_json 1 'doc.get("secret_id") == env["SECRET_ID"] and doc.get("description") == "e2e rotation"' \
        "the update kept the description"
    expect_json 2 'doc.get("moved") is True' "updated_at moved"
    expect_block 2 'HTTP 200'
    [ ! -e rotate.json ] || fail "the recipe left rotate.json with the new value on disk"
    target_requests A2A_URL > requests.json
    "$PYTHON" - requests.json <<'PY' || fail "the request after the rotation did not carry the new value"
import json, os, sys
reqs = json.load(open(sys.argv[1]))
sent = [r for r in reqs if isinstance(r.get("body"), dict) and r["body"].get("method") == "message/send"]
sys.exit(0 if sent and sent[-1]["headers"].get("authorization") == "Bearer " + os.environ["NEW_KEY_VALUE"] else 1)
PY
    pass "the next request carried the new value, with no surface write"
}

cleanup() {
    if [ -n "${SURFACE_ID:-}" ] && fab agent-gateway surfaces get "$SURFACE_ID" > /dev/null 2>&1; then
        fab agent-gateway surfaces delete "$SURFACE_ID" > /dev/null
    fi
    if [ -n "${SECRET_ID:-}" ] && fab agent-gateway secrets get "$SECRET_ID" > /dev/null 2>&1; then
        fab agent-gateway secrets delete "$SECRET_ID" > /dev/null
    fi
}
