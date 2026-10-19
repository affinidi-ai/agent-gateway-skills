# First A2A surface: the recipe in skills/affinidi-agent-gateway/references/surfaces.md, "Recipe: first surface,
# A2A", creates a surface with a listen address and prefix from the routing view, fetches the agent card through
# the gateway and sends one message/send to the a2a target.
# Also demonstrates the protocols.md A2A card and message behaviour.

setup() {
    start_target a2a
    export UPSTREAM_URL="$A2A_URL"
    SURFACE_NAME="$(unique qs-a2a)"
    export SURFACE_NAME
}

verify() {
    expect_json 1 'doc.get("status") == "active" and bool(doc.get("surface_id"))' "create stored an active surface"
    expect_json 2 'isinstance(doc.get("url"), str) and not doc["url"].startswith(env["A2A_URL"]) and doc["url"].rstrip("/").endswith("/" + env["SURFACE_NAME"])' \
        "the card fetched through the gateway advertises the gateway route, not the upstream"
    expect_block 2 'echo: hello'
    target_requests A2A_URL > "$E2E_CASE_DIR/a2a-requests.json"
    "$PYTHON" - "$E2E_CASE_DIR/a2a-requests.json" <<'PY' || fail "the a2a target did not receive the card fetch and one message/send"
import json, sys
reqs = json.load(open(sys.argv[1]))
cards = [r for r in reqs if r["method"] == "GET" and r["path"].split("?")[0].endswith("/.well-known/agent-card.json")]
sends = [r for r in reqs if r["method"] == "POST" and isinstance(r["body"], dict) and r["body"].get("method") == "message/send"]
sys.exit(0 if cards and len(sends) == 1 else 1)
PY
    pass "the a2a target received the card fetch and one message/send"
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
