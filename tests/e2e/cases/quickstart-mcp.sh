# The MCP quickstart in skills/affinidi-agent-gateway/SKILL.md: read the routing view, create an MCP
# surface from flags with a listen address and a prefixed route copied from it, then initialize and
# list tools through the data plane. The upstream is the e2e MCP target on loopback.

setup() {
    start_target mcp MCP_URL
    clear_target MCP_URL
    export UPSTREAM_URL="$MCP_URL/mcp"
    SURFACE_NAME="$(unique qs-mcp)"
    export SURFACE_NAME
    # The recipe picks the listen address equal to $GATEWAY; without it, it would fall back to the first
    # listed address, which is a placeholder on a gateway built from the example configuration.
    fab agent-gateway runtime show surface-routing -o json > "$E2E_CASE_DIR/routing-setup.json"
    "$PYTHON" -c 'import json, os, sys
doc = json.load(open(sys.argv[1]))
gw = os.environ["GATEWAY"].rstrip("/")
sys.exit(0 if any(a.rstrip("/") == gw for a in doc.get("available_listen_addresses", [])) else 1)' \
        "$E2E_CASE_DIR/routing-setup.json" ||
        fail "GATEWAY ($GATEWAY) is not one of the gateway's available_listen_addresses"
}

verify() {
    expect_json 1 'isinstance(doc.get("listen"), list) and len(doc["listen"]) > 0' \
        "the routing view lists at least one inbound listen address"
    expect_json 1 'doc.get("prefixes") and all(isinstance(p, str) and p.startswith("/") for p in doc["prefixes"])' \
        "every channel_path_prefix entry has a prefix field that starts with /"
    expect_json 1 'isinstance(doc.get("oauth_callback_route"), str) and doc["oauth_callback_route"].startswith("/")' \
        "the routing view reports oauth_callback_route"
    expect_json 2 'doc.get("status") == "active" and bool(doc.get("surface_id"))' \
        "the created surface is active and has a surface_id"
    expect_json 2 'doc.get("route", "").endswith("/" + env["SURFACE_NAME"])' \
        "the stored route is the prefixed route the recipe sent"
    expect_block 3 '"protocolVersion": ?"2024-11-05"'
    expect_block 3 '"name": ?"echo"'
    local seen
    seen=$(target_requests MCP_URL)
    printf '%s' "$seen" | grep -q '"initialize"' || fail "the upstream never received initialize"
    pass "the upstream received initialize through the gateway"
    printf '%s' "$seen" | grep -q '"tools/list"' || fail "the upstream never received tools/list"
    pass "the upstream received tools/list through the gateway"
}

cleanup() {
    local f="$E2E_CASE_DIR/surface.json" id
    [ -s "$f" ] || return 0
    id=$(jq -r '.surface_id // empty' "$f")
    [ -n "$id" ] || return 0
    if fab agent-gateway surfaces get "$id" -o json >/dev/null 2>&1; then
        fab agent-gateway surfaces delete "$id" >/dev/null
    fi
}
