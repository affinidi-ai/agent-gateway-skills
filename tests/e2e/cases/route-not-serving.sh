# A saved surface that is not serving: the worked example in skills/affinidi-agent-gateway/references/surfaces.md,
# "Why a saved surface is not serving". The surface is stored with the flag default listen address 0.0.0.0:8080,
# the data plane answers 404, a single-surface reload names the mapping error, and an update with the listen
# address from the routing view makes the same call reach the mcp target.
# Serial: the mis-addressed create fails the single-surface apply, which falls back to a full in-process reload
# that rebinds all listeners, which would disturb cases running in parallel.
E2E_SERIAL=1

setup() {
    fab agent-gateway runtime show surface-routing -o json > "$E2E_CASE_DIR/setup-routing.json"
    "$PYTHON" - "$E2E_CASE_DIR/setup-routing.json" <<'PY' || fail "a listener's external URL is 0.0.0.0:8080 on this gateway, so the flag default would be routable; this case needs a gateway where it is not"
import json, re, sys
addrs = json.load(open(sys.argv[1])).get("available_listen_addresses") or []
sys.exit(1 if any(re.sub(r"^https?://", "", a) == "0.0.0.0:8080" for a in addrs) else 0)
PY
    start_target mcp
    export UPSTREAM_URL="$MCP_URL/mcp"
    SURFACE_NAME="$(unique not-serving)"
    export SURFACE_NAME
}

verify() {
    expect_json 1 'doc.get("listen_address") == "0.0.0.0:8080" and doc.get("status") == "active"' \
        "create stored the flag default listen address and reported the surface active"
    expect_block 1 'HTTP 404 application/problem\+json'
    expect_block 1 'No route configured for path'
    expect_fail_block 2 'Could not map channel listen_address to internal port'
    expect_block 3 'HTTP 200'
    expect_block 3 '"name": ?"echo"'
    target_requests MCP_URL > "$E2E_CASE_DIR/mcp-requests.json"
    "$PYTHON" - "$E2E_CASE_DIR/mcp-requests.json" <<'PY' || fail "the mcp target should see only the tools/list sent after the fix"
import json, sys
reqs = json.load(open(sys.argv[1]))
ids = [r["body"].get("id") for r in reqs if isinstance(r["body"], dict) and r["body"].get("method") == "tools/list"]
sys.exit(0 if ids == [2] else 1)
PY
    pass "only the call after the fix reached the mcp target"
}

cleanup() {
    local id
    [ -s "$E2E_CASE_DIR/surface.json" ] || return 0
    id=$("$PYTHON" -c 'import json, sys; print(json.load(open(sys.argv[1])).get("surface_id") or "")' "$E2E_CASE_DIR/surface.json" 2>/dev/null) || return 0
    [ -n "$id" ] || return 0
    if fab agent-gateway surfaces get "$id" -o json >/dev/null 2>&1; then
        fab agent-gateway surfaces delete "$id" >/dev/null
    fi
}
