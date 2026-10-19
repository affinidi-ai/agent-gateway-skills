# priority: P2
# The A2A half of "Recipe: per-user delegation, MCP and A2A" (skills/affinidi-agent-gateway/references/credentials.md).
# setup() starts an A2A upstream and a test IdP on a LAN address (or loopback,
# see E2E_LOOPBACK_TARGETS), creates a caller API key, the
# provider and two A2A surfaces that authenticate callers with that key. The recipe binds the provider
# to the first surface with required_for "all" and walks the consent flow. verify() checks the upstream
# got the delegated token, then shows KI-16 on the second surface, bound with a tool filter: its
# requests go upstream with no token at all.

a2a_surface() {
    jq -n --arg name "$1" --arg listen "$2" --arg route "$3" --arg endpoint "$A2A_URL" \
        --arg secret "$CALLER_SECRET_ID" --argjson bindings "$4" '{name: $name,
        access_point: {listen_address: $listen, route: $route, protocol: "a2a",
            caller_authentication: {methods: [{type: "api_key",
                extraction: {source: "http_header", field: "X-API-Key"}, secret_id: $secret}]}},
        target: {endpoint: $endpoint}, outbound_credentials: $bindings}'
}

setup() {
    start_target a2a A2A_URL
    start_target idp IDP_URL --lan
    fab agent-gateway runtime show surface-routing -o json > routing.json
    local listen prefix name1 name2 caller_value slug public route
    listen=$(jq -r --arg gw "$GATEWAY" \
        '[.available_listen_addresses[] | select(. == $gw)][0] // .available_listen_addresses[0]' routing.json)
    prefix=$(jq -r '.channel_path_prefix[0].prefix' routing.json)
    route=$(jq -r .oauth_callback_route routing.json)
    CALLER_SECRET_ID=$(unique caller-key)
    caller_value="e2e-$E2E_RUN_ID-caller"
    printf '%s' "$caller_value" | fab agent-gateway secrets create --name "$CALLER_SECRET_ID" --secret-id "$CALLER_SECRET_ID" \
        --value-stdin -o json > /dev/null
    PROVIDER_SLUG=$(unique e2e-idp | tr '[:upper:]' '[:lower:]')
    printf '%s' e2e-client | fab agent-gateway secrets create --name "$PROVIDER_SLUG-client-id" \
        --secret-id "$PROVIDER_SLUG-client-id" --value-stdin -o json > /dev/null
    printf '%s' "e2e-$E2E_RUN_ID-client-secret" | fab agent-gateway secrets create --name "$PROVIDER_SLUG-client-secret" \
        --secret-id "$PROVIDER_SLUG-client-secret" --value-stdin -o json > /dev/null
    public=$("$PYTHON" -c 'import os, urllib.parse as u
p = u.urlsplit(os.environ["GATEWAY"])
host = os.environ["LAN_HOST"] + (":%d" % p.port if p.port else "")
print(u.urlunsplit((p.scheme, host, "", "", "")))')
    jq -n --arg slug "$PROVIDER_SLUG" --arg a "$IDP_URL/authorize" --arg t "$IDP_URL/token" \
        --arg cb "$public$route/$PROVIDER_SLUG" '{name: $slug, provider_id: $slug,
        provider_type: "oauth2_authorization_code", authorization_endpoint: $a, token_endpoint: $t,
        client_id_secret_ref: ($slug + "-client-id"), client_secret_secret_ref: ($slug + "-client-secret"),
        default_scopes: ["read"], callback_url: $cb}' > setup-provider-doc.json
    fab agent-gateway credential-providers create --file setup-provider-doc.json -o json > setup-provider.json
    PROVIDER_UUID=$(jq -r .id setup-provider.json)
    name1=$(unique deleg-a2a)
    a2a_surface "$name1" "$listen" "$prefix/$name1" '[]' > setup-surface-doc.json
    fab agent-gateway surfaces create --file setup-surface-doc.json -o json > setup-surface.json
    SURFACE_ID=$(jq -r .surface_id setup-surface.json)
    name2=$(unique deleg-a2a-tools)
    a2a_surface "$name2" "$listen" "$prefix/$name2" \
        "$(jq -nc --arg p "$PROVIDER_UUID" '[{credential_provider_id: $p, required_for: {tools: ["x"]}}]')" \
        > setup-surface2-doc.json
    fab agent-gateway surfaces create --file setup-surface2-doc.json -o json > setup-surface2.json
    SURFACE2_ID=$(jq -r .surface_id setup-surface2.json)
    CALLER_AUTH_HEADER_FILE="$E2E_CASE_DIR/caller.hdr"
    (umask 077; printf 'X-API-Key: %s\n' "$caller_value" > "$CALLER_AUTH_HEADER_FILE")
    USER_HASH=$(printf '%s' "$CALLER_SECRET_ID" | "$PYTHON" -c 'import hashlib, sys
print(hashlib.sha256(sys.stdin.buffer.read()).hexdigest())')
    export CALLER_SECRET_ID PROVIDER_SLUG PROVIDER_UUID SURFACE_ID SURFACE2_ID CALLER_AUTH_HEADER_FILE USER_HASH
}

verify() {
    expect_block 1 'HTTP 401'
    expect_block 1 'Authorization Successful'
    expect_block 1 'echo: ping'
    expect_block 1 'HTTP 200'
    jq -e '.type == "https://affinidi.com/atg/errors/consent-required"' consent.json > /dev/null \
        || fail "the first message/send did not ask for consent" consent.json
    target_requests A2A_URL > requests.json
    "$PYTHON" - requests.json <<'PY' || fail "the upstream did not receive the delegated bearer token"
import json, sys
reqs = json.load(open(sys.argv[1]))
sent = [r for r in reqs if isinstance(r.get("body"), dict) and r["body"].get("method") == "message/send"]
sys.exit(0 if sent and sent[-1]["headers"].get("authorization", "").startswith("Bearer e2e-access-") else 1)
PY
    pass "required_for all injects the user's token on message/send"

    # KI-16: a tool filter never matches an A2A request, so the request goes upstream with no token.
    clear_target A2A_URL
    local url code
    url=$(jq -r '.access_point.listen_address + .access_point.route' setup-surface2.json)
    code=$(curl -sS -o tools-filter.json -w '%{http_code}' -X POST "$url" -H @"$CALLER_AUTH_HEADER_FILE" \
        -H 'Content-Type: application/json' -d '{"jsonrpc":"2.0","id":"2","method":"message/send",
        "params":{"message":{"role":"user","messageId":"m2","parts":[{"kind":"text","text":"filtered"}]}}}')
    [ "$code" = 200 ] || fail "the tool-filtered surface returned $code, not 200" tools-filter.json
    target_requests A2A_URL > requests2.json
    "$PYTHON" - requests2.json <<'PY' || fail "the tool-filtered A2A request carried an Authorization header"
import json, sys
reqs = json.load(open(sys.argv[1]))
sent = [r for r in reqs if isinstance(r.get("body"), dict) and r["body"].get("method") == "message/send"]
sys.exit(0 if sent and all("authorization" not in r["headers"] for r in sent) else 1)
PY
    pass "KI-16: a tool-filtered binding on A2A forwards with no token"
}

cleanup() {
    if [ -n "${USER_HASH:-}" ]; then
        fab agent-gateway delegation-vault revoke-user "$USER_HASH" -o json > /dev/null 2>&1 || true
    fi
    local s
    for s in "${SURFACE_ID:-}" "${SURFACE2_ID:-}"; do
        if [ -n "$s" ] && fab agent-gateway surfaces get "$s" > /dev/null 2>&1; then
            fab agent-gateway surfaces delete "$s" > /dev/null
        fi
    done
    if [ -n "${PROVIDER_UUID:-}" ] && fab agent-gateway credential-providers get "$PROVIDER_UUID" > /dev/null 2>&1; then
        fab agent-gateway credential-providers delete "$PROVIDER_UUID" > /dev/null
    fi
    for s in "${CALLER_SECRET_ID:-}" "${PROVIDER_SLUG:+$PROVIDER_SLUG-client-id}" \
        "${PROVIDER_SLUG:+$PROVIDER_SLUG-client-secret}"; do
        if [ -n "$s" ] && fab agent-gateway secrets get "$s" > /dev/null 2>&1; then
            fab agent-gateway secrets delete "$s" > /dev/null
        fi
    done
}
