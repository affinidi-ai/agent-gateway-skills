# priority: P2
# The MCP half of "Recipe: per-user delegation, MCP and A2A", then "Recipe: offboard a user or respond to a
# compromise" (skills/affinidi-agent-gateway/references/credentials.md).
# setup() starts an MCP upstream and a test IdP on a LAN address (the provider URL check blocks
# loopback, unless E2E_LOOPBACK_TARGETS lists idp for a gateway that accepts it), creates a caller API key and a surface that authenticates with it. The recipe creates the
# provider, binds it to one tool, walks the consent flow with curl -L standing in for the browser, then
# revokes the user. No browser cookie is needed, because the callback reads only the query string, and no
# identity slot is needed, because the vault keys grants on the surface's config id when the request names
# no agent DID. One API key stands in for a per-user JWT, because the test IdP serves no JWKS.

surface_url() {
    jq -r '.access_point.listen_address + .access_point.route' surface.json
}

call_status() {
    curl -sS -o "$1" -w '%{http_code}' -X POST "$(surface_url)" -H @"$CALLER_AUTH_HEADER_FILE" \
        -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' -d @call.json
}

setup() {
    start_target mcp MCP_URL
    start_target idp IDP_URL --lan
    fab agent-gateway runtime show surface-routing -o json > routing.json
    local listen prefix name caller_value
    listen=$(jq -r --arg gw "$GATEWAY" \
        '[.available_listen_addresses[] | select(. == $gw)][0] // .available_listen_addresses[0]' routing.json)
    prefix=$(jq -r '.channel_path_prefix[0].prefix' routing.json)
    name=$(unique deleg-mcp)
    CALLER_SECRET_ID=$(unique caller-key)
    caller_value="e2e-$E2E_RUN_ID-caller"
    printf '%s' "$caller_value" | fab agent-gateway secrets create --name "$CALLER_SECRET_ID" --secret-id "$CALLER_SECRET_ID" \
        --value-stdin -o json > /dev/null
    jq -n --arg name "$name" --arg listen "$listen" --arg route "$prefix/$name" --arg endpoint "$MCP_URL/mcp" \
        --arg secret "$CALLER_SECRET_ID" '{name: $name,
        access_point: {listen_address: $listen, route: $route, protocol: "mcp",
            caller_authentication: {methods: [{type: "api_key",
                extraction: {source: "http_header", field: "X-API-Key"}, secret_id: $secret}]}},
        target: {endpoint: $endpoint}}' > setup-surface-doc.json
    fab agent-gateway surfaces create --file setup-surface-doc.json -o json > setup-surface.json
    SURFACE_ID=$(jq -r .surface_id setup-surface.json)
    CALLER_AUTH_HEADER_FILE="$E2E_CASE_DIR/caller.hdr"
    (umask 077; printf 'X-API-Key: %s\n' "$caller_value" > "$CALLER_AUTH_HEADER_FILE")
    TOOL_NAME=echo
    PROVIDER_SLUG=$(unique e2e-idp | tr '[:upper:]' '[:lower:]')
    IDP_CLIENT_ID=e2e-client
    IDP_CLIENT_SECRET="e2e-$E2E_RUN_ID-client-secret"
    AUTHORIZE_URL="$IDP_URL/authorize"
    TOKEN_URL="$IDP_URL/token"
    PUBLIC_GATEWAY_URL=$("$PYTHON" -c 'import os, urllib.parse as u
p = u.urlsplit(os.environ["GATEWAY"])
host = os.environ["LAN_HOST"] + (":%d" % p.port if p.port else "")
print(u.urlunsplit((p.scheme, host, "", "", "")))')
    USER_HASH=$(printf '%s' "$CALLER_SECRET_ID" | "$PYTHON" -c 'import hashlib, sys
print(hashlib.sha256(sys.stdin.buffer.read()).hexdigest())')
    export SURFACE_ID CALLER_SECRET_ID CALLER_AUTH_HEADER_FILE TOOL_NAME PROVIDER_SLUG IDP_CLIENT_ID \
        IDP_CLIENT_SECRET AUTHORIZE_URL TOKEN_URL PUBLIC_GATEWAY_URL USER_HASH
}

verify() {
    local route
    route=$(jq -r .oauth_callback_route routing.json)
    expect_block 1 '"callback_path"'
    "$PYTHON" - provider.json "$route" <<'PY' || fail "callback_path is not <oauth_callback_route>/<provider_id>" provider.json
import json, os, sys
doc = json.load(open(sys.argv[1]))
slug = os.environ["PROVIDER_SLUG"]
sys.exit(0 if doc["provider_id"] == slug and doc["callback_path"] == sys.argv[2] + "/" + slug else 1)
PY
    pass "the callback path is the configured oauth_callback_route plus the provider id"

    expect_json 2 'doc[-1]["consent_mode"] == "on_demand" and doc[-1]["required_for"] == {"tools": [env["TOOL_NAME"]]}' \
        "the binding is saved with the tool filter"
    expect_block 3 'HTTP 401'
    expect_json 3 'doc.get("type") == "https://affinidi.com/atg/errors/consent-required" and doc.get("authorization_url")' \
        "the first call asks for consent"
    "$PYTHON" - consent.json <<'PY' || fail "_debug_user_hash is not the SHA-256 of the caller secret_id" consent.json
import json, os, sys
sys.exit(0 if json.load(open(sys.argv[1])).get("_debug_user_hash") == os.environ["USER_HASH"] else 1)
PY
    pass "the user hash is the bare SHA-256 of the API key's secret_id"

    target_requests IDP_URL > idp-requests.json
    "$PYTHON" - idp-requests.json provider.json <<'PY' || fail "the IdP did not get redirect_uri equal to callback_url"
import json, sys, urllib.parse as u
reqs = json.load(open(sys.argv[1]))
want = json.load(open(sys.argv[2]))["callback_url"]
seen = [dict(u.parse_qsl(u.urlsplit(r["path"]).query)).get("redirect_uri")
        for r in reqs if r["method"] == "GET" and r["path"].startswith("/authorize")]
sys.exit(0 if seen and all(s == want for s in seen) else 1)
PY
    pass "redirect_uri sent to the IdP is the provider's callback_url"

    expect_block 4 'Authorization Successful'
    expect_block 4 'upstream saw Authorization: Bearer'
    expect_block 4 'HTTP 200'
    expect_block 4 "\"user_identity_hash\": \"$USER_HASH\""

    expect_json 5 'isinstance(doc, list) and len(doc) >= 1' "the user holds a grant before revoke-user"
    expect_block 5 '"revoked": [1-9]'
    expect_block 5 '^0$'
    expect_block 6 'HTTP 401'
    expect_block 6 'consent-required'

    curl -sS -D headers.txt -o /dev/null -X POST "$(surface_url)" -H @"$CALLER_AUTH_HEADER_FILE" \
        -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' -d @call.json
    if grep -qi '^www-authenticate:' headers.txt; then
        fail "the consent-required 401 carries a WWW-Authenticate header" headers.txt
    fi
    pass "the consent-required 401 has no WWW-Authenticate header"

    # KI-18: the CLI help says (sha256:...), but the direct-path hash has no prefix.
    local code
    code=$(call_status consent-again.json)
    [ "$code" = 401 ] || fail "consent was not asked again (HTTP $code)" consent-again.json
    (umask 077; jq -r '"url = \"" + .consent_required[0].authorization_url + "\""' consent-again.json \
        > authorize-again.curl)
    curl -sSL -K authorize-again.curl > callback-again.html
    grep -q 'Authorization Successful' callback-again.html || fail "the second sign-in did not complete" callback-again.html
    fab agent-gateway delegation-vault revoke-user "sha256:$USER_HASH" -o json > revoke-prefixed.json
    jq -e '.revoked == 0' revoke-prefixed.json > /dev/null || fail "a sha256: prefixed hash revoked grants" revoke-prefixed.json
    fab agent-gateway delegation-vault revoke-user "$USER_HASH" -o json > revoke-bare.json
    jq -e '.revoked >= 1' revoke-bare.json > /dev/null || fail "the bare hash revoked nothing" revoke-bare.json
    pass "revoke-user matches the bare hash only"
}

cleanup() {
    if [ -n "${USER_HASH:-}" ]; then
        fab agent-gateway delegation-vault revoke-user "$USER_HASH" -o json > /dev/null 2>&1 || true
    fi
    if [ -n "${SURFACE_ID:-}" ] && fab agent-gateway surfaces get "$SURFACE_ID" > /dev/null 2>&1; then
        fab agent-gateway surfaces delete "$SURFACE_ID" > /dev/null
    fi
    if [ -f provider.json ] && fab agent-gateway credential-providers get "$(jq -r .id provider.json)" > /dev/null 2>&1; then
        fab agent-gateway credential-providers delete "$(jq -r .id provider.json)" > /dev/null
    fi
    local s
    for s in "${CALLER_SECRET_ID:-}" "${PROVIDER_SLUG:+$PROVIDER_SLUG-client-id}" \
        "${PROVIDER_SLUG:+$PROVIDER_SLUG-client-secret}"; do
        if [ -n "$s" ] && fab agent-gateway secrets get "$s" > /dev/null 2>&1; then
            fab agent-gateway secrets delete "$s" > /dev/null
        fi
    done
}
