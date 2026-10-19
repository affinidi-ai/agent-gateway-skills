# Recipe: static target credential, A2A (skills/affinidi-agent-gateway/references/credentials.md).
# setup() stores the secret (the MCP case covers that step); the recipe block adds target.auth with the
# default bearer form and sends message/send. verify() checks the upstream's Authorization header.

setup() {
    start_target a2a A2A_URL
    fab agent-gateway runtime show surface-routing -o json > routing.json
    local listen prefix name
    listen=$(jq -r --arg gw "$GATEWAY" \
        '[.available_listen_addresses[] | select(. == $gw)][0] // .available_listen_addresses[0]' routing.json)
    prefix=$(jq -r '.channel_path_prefix[0].prefix' routing.json)
    name=$(unique cred-a2a)
    SECRET_ID=$(unique upstream-token)
    UPSTREAM_KEY_VALUE="e2e-$E2E_RUN_ID-upstream"
    export SECRET_ID UPSTREAM_KEY_VALUE
    printf '%s' "$UPSTREAM_KEY_VALUE" | fab agent-gateway secrets create --name "$SECRET_ID" --secret-id "$SECRET_ID" \
        --value-stdin -o json > /dev/null
    fab agent-gateway surfaces create --name "$name" --protocol a2a --listen-address "$listen" --route "$prefix/$name" \
        --target-endpoint "$A2A_URL" -o json > setup-surface.json
    SURFACE_ID=$(jq -r .surface_id setup-surface.json)
    export SURFACE_ID
}

verify() {
    expect_block 1 'HTTP 200'
    expect_block 1 'echo: ping'
    target_requests A2A_URL > requests.json
    "$PYTHON" - requests.json <<'PY' || fail "the upstream did not receive Authorization: Bearer <stored value>"
import json, os, sys
reqs = json.load(open(sys.argv[1]))
want = "Bearer " + os.environ["UPSTREAM_KEY_VALUE"]
sent = [r for r in reqs if isinstance(r.get("body"), dict) and r["body"].get("method") == "message/send"]
sys.exit(0 if sent and all(r["headers"].get("authorization") == want for r in sent) else 1)
PY
    pass "message/send reached the upstream with Authorization: Bearer <stored value>"
}

cleanup() {
    if [ -n "${SURFACE_ID:-}" ] && fab agent-gateway surfaces get "$SURFACE_ID" > /dev/null 2>&1; then
        fab agent-gateway surfaces delete "$SURFACE_ID" > /dev/null
    fi
    if [ -n "${SECRET_ID:-}" ] && fab agent-gateway secrets get "$SECRET_ID" > /dev/null 2>&1; then
        fab agent-gateway secrets delete "$SECRET_ID" > /dev/null
    fi
}
