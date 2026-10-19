# Recipe: static target credential, MCP (skills/affinidi-agent-gateway/references/credentials.md).
# The recipe stores a throwaway key and adds target.auth with the header X-Upstream-Key. verify() checks
# that the upstream received exactly that value, then deletes the secret and expects the documented 502.

setup() {
    start_target mcp MCP_URL
    fab agent-gateway runtime show surface-routing -o json > routing.json
    local listen prefix name
    listen=$(jq -r --arg gw "$GATEWAY" \
        '[.available_listen_addresses[] | select(. == $gw)][0] // .available_listen_addresses[0]' routing.json)
    prefix=$(jq -r '.channel_path_prefix[0].prefix' routing.json)
    name=$(unique cred-mcp)
    fab agent-gateway surfaces create --name "$name" --protocol mcp --listen-address "$listen" --route "$prefix/$name" \
        --target-endpoint "$MCP_URL/mcp" -o json > setup-surface.json
    SURFACE_ID=$(jq -r .surface_id setup-surface.json)
    SECRET_ID=$(unique upstream-key)
    UPSTREAM_KEY_VALUE="e2e-$E2E_RUN_ID-upstream"
    HEADER_NAME=X-Upstream-Key
    HEADER_FORMAT='{value}'
    export SURFACE_ID SECRET_ID UPSTREAM_KEY_VALUE HEADER_NAME HEADER_FORMAT
}

verify() {
    expect_json 1 'doc.get("secret_id") == env["SECRET_ID"]' "the secret exists under the chosen secret_id"
    expect_json 2 'doc["method"]["static_secret"]["header_name"] == "X-Upstream-Key" and doc["fallback"] == "reject"' \
        "target.auth is saved with fallback reject"
    expect_block 3 'HTTP 200'
    expect_block 3 '"tools"'
    target_requests MCP_URL > requests.json
    "$PYTHON" - requests.json <<'PY' || fail "the upstream did not receive x-upstream-key with the stored value"
import json, os, sys
reqs = json.load(open(sys.argv[1]))
want = os.environ["UPSTREAM_KEY_VALUE"]
sys.exit(0 if any(r.get("headers", {}).get("x-upstream-key") == want for r in reqs) else 1)
PY
    pass "the upstream received x-upstream-key with the stored value"

    fab agent-gateway secrets delete "$SECRET_ID" > /dev/null
    local url code
    url=$(jq -r '.access_point.listen_address + .access_point.route' surface.json)
    code=$(curl -sS -o after-delete.json -w '%{http_code}' -X POST "$url" -H 'Content-Type: application/json' \
        -H 'Accept: application/json, text/event-stream' -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}')
    [ "$code" = 502 ] || fail "after the secret was deleted the call returned $code, not 502" after-delete.json
    "$PYTHON" - after-delete.json <<'PY' || fail "the 502 body is not the documented problem+json" after-delete.json
import json, os, sys
doc = json.load(open(sys.argv[1]))
want = "Target authentication failed: Secret with secret_id '%s' not found" % os.environ["SECRET_ID"]
sys.exit(0 if doc.get("detail") == want and doc.get("status") == 502 else 1)
PY
    pass "a deleted target.auth secret gives 502 Target authentication failed"
}

cleanup() {
    if [ -n "${SURFACE_ID:-}" ] && fab agent-gateway surfaces get "$SURFACE_ID" > /dev/null 2>&1; then
        fab agent-gateway surfaces delete "$SURFACE_ID" > /dev/null
    fi
    if [ -n "${SECRET_ID:-}" ] && fab agent-gateway secrets get "$SECRET_ID" > /dev/null 2>&1; then
        fab agent-gateway secrets delete "$SECRET_ID" > /dev/null
    fi
}
