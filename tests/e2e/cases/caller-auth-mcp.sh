# Requires an API key on an MCP surface with the recipe in
# skills/affinidi-agent-gateway/references/identity.md ("Require an API key on an MCP surface").
# Proves that a missing and a wrong key are not blocked by caller auth itself but reach the policy as
# `failed` with distinct reasons, that the right key passes, and that neither the refused calls nor the
# X-API-Key header reach the upstream.

# The listen address callers use: the one on the gateway's own origin when it is listed, else the first.
idc_listen_address() {
    "$PYTHON" -c 'import json, sys, urllib.parse as up
doc = json.load(open(sys.argv[1]))
addrs = doc.get("available_listen_addresses") or []
gw = up.urlsplit(sys.argv[2])[:2]
same = [a for a in addrs if up.urlsplit(a)[:2] == gw]
print((same or addrs or [""])[0])' "$1" "$GATEWAY"
}

setup() {
    start_target mcp
    fab agent-gateway runtime show surface-routing -o json > setup-routing.json
    local listen prefix name
    listen=$(idc_listen_address setup-routing.json)
    [ -n "$listen" ] || fail "surface-routing lists no inbound listen address" setup-routing.json
    prefix=$(jq -r '.channel_path_prefix[0].prefix // empty' setup-routing.json)
    [ -n "$prefix" ] || fail "surface-routing lists no channel prefix" setup-routing.json
    name=$(unique idauth-mcp)
    fab agent-gateway surfaces create --name "$name" --protocol mcp --listen-address "$listen" \
        --route "${prefix%/}/$name" --target-endpoint "$MCP_URL/mcp" -o json > setup-surface.json
    SURFACE_ID=$(jq -r '.surface_id // empty' setup-surface.json)
    [ -n "$SURFACE_ID" ] || fail "surfaces create returned no surface_id" setup-surface.json
    KEY_SECRET_ID=$(unique idauth-mcp-key)
    POLICY_ID=$(unique require-api-key-mcp)
    export SURFACE_ID KEY_SECRET_ID POLICY_ID
}

verify() {
    expect_block 3 "not allowed by policy: Missing credential: API key not found in request"
    expect_block 3 "not allowed by policy: Invalid credential: API key not found or inactive"
    expect_block 3 '"name": ?"echo"'
    target_requests MCP_URL > requests.json
    "$PYTHON" - requests.json <<'PY' || fail "the upstream saw a refused call or a credential header" requests.json
import json, sys
reqs = json.load(open(sys.argv[1]))
posts = [r for r in reqs if r.get("method") == "POST" and isinstance(r.get("body"), dict)]
methods = [r["body"].get("method") for r in posts]
assert "tools/call" not in methods, "a refused tools/call was forwarded: %r" % methods
assert methods.count("tools/list") == 1, "expected one forwarded tools/list, got %r" % methods
for r in posts:
    assert "x-api-key" not in r["headers"], "X-API-Key reached the upstream"
    assert "authorization" not in r["headers"], "Authorization reached the upstream"
PY
    pass "only the keyed tools/list reached the upstream, without X-API-Key"
}

cleanup() {
    if [ -n "${SURFACE_ID:-}" ] && fab agent-gateway surfaces get "$SURFACE_ID" -o json > /dev/null 2>&1; then
        fab agent-gateway surfaces delete "$SURFACE_ID" > /dev/null
    fi
    if [ -n "${POLICY_ID:-}" ] && fab agent-gateway policies get "$POLICY_ID" -o json > /dev/null 2>&1; then
        fab agent-gateway policies delete "$POLICY_ID" > /dev/null
    fi
    if [ -n "${KEY_SECRET_ID:-}" ] && fab agent-gateway secrets get "$KEY_SECRET_ID" -o json > /dev/null 2>&1; then
        fab agent-gateway secrets delete "$KEY_SECRET_ID" > /dev/null
    fi
}
