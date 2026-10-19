# Exposes the e2e REST target as MCP tools through an MCP proxy and a proxy:// surface, following
# the recipe in skills/affinidi-agent-gateway/references/proxies.md. The proxy base_url must not be
# loopback, so the REST target listens on the LAN address.

setup() {
    start_target rest --lan
    export REST_API_URL="$REST_URL"
    export PROXY_NAME SURFACE_NAME POLICY_ID
    PROXY_NAME="$(unique weather-api)"
    SURFACE_NAME="$(unique weather-mcp)"
    POLICY_ID="$(unique weather-forecast-allow)"
    clear_target REST_URL
}

verify() {
    expect_json 1 'isinstance(doc.get("listen"), list) and len(doc["listen"]) > 0' \
        "the routing view lists an inbound listen address"
    expect_json 2 'doc.get("valid") is True' "validate accepts the spec"
    expect_fail_block 3 'is blocked: cloud-provider metadata services and loopback'
    expect_json 4 'doc.get("status") == "active" and doc.get("name") == env["PROXY_NAME"]' "the proxy is saved and active"
    expect_block 4 '"createAlert"'
    expect_block 4 '"getForecast"'
    expect_json 5 'doc.get("status") == "active" and doc.get("endpoint", "").startswith("proxy://")' \
        "the surface targets the proxy"
    expect_json 6 'doc.get("tools") and doc["tools"][0].get("tool_name") == "getForecast"' \
        "the surface carries the per-tool policy"
    expect_json 7 'doc["result"]["protocolVersion"] == "2024-11-05" and doc["result"]["serverInfo"]["name"] == env["PROXY_NAME"]' \
        "initialize reports the proxy as the MCP server"
    expect_block 7 '"name": ?"createAlert"'
    expect_block 7 '"name": ?"getForecast"'
    expect_json 8 'doc["result"]["isError"] is False and doc["result"]["content"]' "getForecast succeeds"
    expect_block 8 '"code": ?-32000'
    expect_block 8 'Access denied: insufficient permissions for this tool'
    target_requests REST_URL > "$E2E_CASE_DIR/rest-requests.json"
    case "$(json_get "$E2E_CASE_DIR/rest-requests.json" 'any(r["method"] == "GET" and r["path"] == "/forecast/paris" for r in doc)')" in
        True|true) pass "the REST target received GET /forecast/paris" ;;
        *) fail "the REST target did not receive GET /forecast/paris" "$E2E_CASE_DIR/rest-requests.json" ;;
    esac
    case "$(json_get "$E2E_CASE_DIR/rest-requests.json" 'any(r["path"] == "/alerts" for r in doc)')" in
        False|false) pass "the denied createAlert never reached the REST target" ;;
        *) fail "createAlert reached the REST target despite the tool policy" "$E2E_CASE_DIR/rest-requests.json" ;;
    esac
}

cleanup() {
    local dir=$E2E_CASE_DIR id
    if [ -s "$dir/surface.json" ]; then
        id=$(jq -r '.surface_id // empty' "$dir/surface.json")
        if [ -n "$id" ] && fab agent-gateway surfaces get "$id" -o json >/dev/null 2>&1; then
            fab agent-gateway surfaces delete "$id" >/dev/null
        fi
    fi
    if [ -n "${POLICY_ID:-}" ] && fab agent-gateway policies get "$POLICY_ID" -o json >/dev/null 2>&1; then
        fab agent-gateway policies delete "$POLICY_ID" >/dev/null
    fi
    if [ -s "$dir/proxy-created.json" ]; then
        id=$(jq -r '.id // empty' "$dir/proxy-created.json")
        if [ -n "$id" ] && fab agent-gateway mcp-proxies get "$id" -o json >/dev/null 2>&1; then
            fab agent-gateway mcp-proxies delete "$id" >/dev/null
        fi
    fi
    # Block 3's loopback create is expected to fail; when the case fails because it did not, remove that proxy by name.
    if [ -n "${PROXY_NAME:-}" ]; then
        fab agent-gateway mcp-proxies list -o json | jq -r --arg n "$PROXY_NAME" '.[] | select(.name == $n) | .id' |
            while read -r id; do fab agent-gateway mcp-proxies delete "$id" >/dev/null; done
    fi
}
