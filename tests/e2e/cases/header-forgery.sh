# Sends caller-forgeable headers through a plain MCP surface with the recipe in
# skills/affinidi-agent-gateway/references/identity.md ("What the upstream receives, and what it may
# trust") and checks what the upstream recorded.
#
# What this case proves: the upstream receives the caller's X-Gateway-Trace-Id value, an arbitrary
# caller header, and the gateway's x-caller-did and x-caller-identity-source.
# What it cannot prove yet: that the forged x-caller-did arrives next to the gateway's value. The
# targets.py recorder stores headers in a dict, so only the last value of a repeated header survives.
# That part of the claim rests on source reading until the recorder keeps every value.

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
    name=$(unique idforge-mcp)
    fab agent-gateway surfaces create --name "$name" --protocol mcp --listen-address "$listen" \
        --route "${prefix%/}/$name" --target-endpoint "$MCP_URL/mcp" -o json > setup-surface.json
    SURFACE_ID=$(jq -r '.surface_id // empty' setup-surface.json)
    [ -n "$SURFACE_ID" ] || fail "surfaces create returned no surface_id" setup-surface.json
    export SURFACE_ID
}

verify() {
    expect_block 1 '"tools"'
    target_requests MCP_URL > requests.json
    "$PYTHON" - requests.json <<'PY' || fail "the upstream did not receive the headers the recipe describes" requests.json
import json, sys
reqs = json.load(open(sys.argv[1]))
lists = [r for r in reqs if r.get("method") == "POST" and isinstance(r.get("body"), dict)
         and r["body"].get("method") == "tools/list"]
assert len(lists) == 1, "expected one forwarded tools/list, got %d" % len(lists)
h = lists[0]["headers"]
assert h.get("x-gateway-trace-id") == "00000000-0000-0000-0000-000000000000", h.get("x-gateway-trace-id")
assert h.get("x-probe") == "sent-by-caller", h.get("x-probe")
assert h.get("x-caller-identity-source") in ("gateway-computed", "self-presented"), h.get("x-caller-identity-source")
assert h.get("x-caller-did"), "no x-caller-did"
assert h["x-caller-did"] != "did:example:forged", "the last x-caller-did the upstream saw is the forged one"
print("recorded x-caller-did (last value only): %s" % h["x-caller-did"])
PY
    pass "the upstream got the caller's trace id, the caller's own header and the gateway's caller headers"
}

cleanup() {
    if [ -n "${SURFACE_ID:-}" ] && fab agent-gateway surfaces get "$SURFACE_ID" -o json > /dev/null 2>&1; then
        fab agent-gateway surfaces delete "$SURFACE_ID" > /dev/null
    fi
}
