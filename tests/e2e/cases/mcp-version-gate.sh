# The MCP version gate and notification handling, from references/protocols.md "Recipe: check the version
# gate on a surface". Blocks: 1 create the surface, 2 initialize asking for 2025-11-25, 3 notifications/initialized,
# 4 tools/list with MCP-Protocol-Version 2025-06-18, 5 tools/list with 2024-11-05, 6 a complete 2026-07-28
# request, forwarded. The test target answers in the 2024-11-05 shape only, so block 6 gets the 502.

setup() {
    start_target mcp
    export UPSTREAM_URL="$MCP_URL/mcp"
    SURFACE_NAME="$(unique gate-mcp)"
    export SURFACE_NAME
}

verify() {
    expect_json 1 'doc.get("status") == "active" and bool(doc.get("surface_id"))' "the surface is created active"
    expect_block 2 '^HTTP 200$'
    expect_block 2 '"protocolVersion": ?"2024-11-05"'
    expect_block 3 '^HTTP 204$'
    expect_block 4 '^HTTP 400$'
    expect_json 4 'doc["error"]["code"] == -32022 and doc["error"]["message"] == "Unsupported protocol version"' \
        "an MCP-Protocol-Version the gateway does not serve gets -32022 Unsupported protocol version"
    expect_json 4 'doc["error"]["data"]["supported"] == ["2024-11-05", "2026-07-28"] and doc["error"]["data"]["requested"] == "2025-06-18"' \
        "the -32022 error names the requested and the supported versions"
    expect_block 5 '^HTTP 200$'
    expect_block 5 '"name": ?"echo"'
    expect_block 6 '^HTTP 502$'
    expect_json 6 'doc.get("status") == 502 and doc.get("detail") == "Invalid modern MCP upstream response"' \
        "a complete 2026-07-28 request is forwarded, and the upstream's 2024-11-05-shaped answer gets 502"

    target_requests MCP_URL > "$E2E_CASE_DIR/requests.json"
    "$PYTHON" - "$E2E_CASE_DIR/requests.json" <<'PY' || fail "the upstream saw the wrong requests" "$E2E_CASE_DIR/requests.json"
import json, sys
reqs = json.load(open(sys.argv[1]))
bodies = [r["body"] for r in reqs if isinstance(r.get("body"), dict)]
methods = [b.get("method") for b in bodies]
asked = [b.get("params", {}).get("protocolVersion") for b in bodies if b.get("method") == "initialize"]
assert asked == ["2024-11-05"], asked
assert "notifications/initialized" not in methods, methods
assert methods.count("tools/list") == 2, methods
modern = [r for r in reqs if r["headers"].get("mcp-protocol-version") == "2026-07-28"]
assert len(modern) == 1 and modern[0]["body"].get("id") == 4, [r["headers"] for r in reqs]
assert "mcp-session-id" not in modern[0]["headers"], modern[0]["headers"]
PY
    pass "the upstream saw initialize asking for 2024-11-05 and both tools/list calls, the 2026-07-28 one without a session id, and neither the notification nor the refused 2025-06-18 call"
}

cleanup() {
    local id
    [ -f "$E2E_CASE_DIR/surface.json" ] || return 0
    id=$("$PYTHON" -c 'import json, sys; print(json.load(open(sys.argv[1])).get("surface_id") or "")' "$E2E_CASE_DIR/surface.json" 2>/dev/null || true)
    [ -n "$id" ] || return 0
    if fab agent-gateway surfaces get "$id" -o json >/dev/null 2>&1; then
        fab agent-gateway surfaces delete "$id" >/dev/null
    fi
}
