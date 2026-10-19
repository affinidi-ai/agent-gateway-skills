# Requires an API key on an A2A surface with the recipe in
# skills/affinidi-agent-gateway/references/identity.md ("Require an API key on an A2A surface").
# Proves that a missing and a wrong key both get the fixed 403 without the reason, that the right key
# reaches the agent, that the agent card stays public, and that only the keyed message reaches the
# upstream, without the X-API-Key header.

idc_listen_address() {
    "$PYTHON" -c 'import json, sys, urllib.parse as up
doc = json.load(open(sys.argv[1]))
addrs = doc.get("available_listen_addresses") or []
gw = up.urlsplit(sys.argv[2])[:2]
same = [a for a in addrs if up.urlsplit(a)[:2] == gw]
print((same or addrs or [""])[0])' "$1" "$GATEWAY"
}

setup() {
    start_target a2a
    fab agent-gateway runtime show surface-routing -o json > setup-routing.json
    local listen prefix name
    listen=$(idc_listen_address setup-routing.json)
    [ -n "$listen" ] || fail "surface-routing lists no inbound listen address" setup-routing.json
    prefix=$(jq -r '.channel_path_prefix[0].prefix // empty' setup-routing.json)
    [ -n "$prefix" ] || fail "surface-routing lists no channel prefix" setup-routing.json
    name=$(unique idauth-a2a)
    fab agent-gateway surfaces create --name "$name" --protocol a2a --listen-address "$listen" \
        --route "${prefix%/}/$name" --target-endpoint "$A2A_URL" -o json > setup-surface.json
    SURFACE_ID=$(jq -r '.surface_id // empty' setup-surface.json)
    [ -n "$SURFACE_ID" ] || fail "surfaces create returned no surface_id" setup-surface.json
    KEY_SECRET_ID=$(unique idauth-a2a-key)
    POLICY_ID=$(unique require-api-key-a2a)
    export SURFACE_ID KEY_SECRET_ID POLICY_ID
}

verify() {
    local out="$E2E_CASE_DIR/block-2.out"
    "$PYTHON" - "$out" <<'PY' || fail "the A2A calls did not answer as the recipe says" "$out"
import sys
lines = open(sys.argv[1], encoding="utf-8", errors="replace").read().splitlines()
def after(label):
    return lines[lines.index(label) + 1]
for label in ("no key:", "wrong key:"):
    line = after(label)
    assert "Agent trust policy denied the request" in line and line.endswith(" HTTP 403"), line
ok = after("right key:")
assert "echo: hello" in ok and ok.endswith(" HTTP 200"), ok
assert after("agent card without a key:") == "HTTP 200", after("agent card without a key:")
PY
    pass "no key and a wrong key get the fixed 403; the key gets the reply; the card stays public"
    target_requests A2A_URL > requests.json
    "$PYTHON" - requests.json <<'PY' || fail "the upstream saw a refused message or a credential header" requests.json
import json, sys
reqs = json.load(open(sys.argv[1]))
sends = [r for r in reqs if r.get("method") == "POST" and isinstance(r.get("body"), dict)
         and r["body"].get("method") == "message/send"]
assert len(sends) == 1, "expected one forwarded message/send, got %d" % len(sends)
for r in reqs:
    assert "x-api-key" not in r["headers"], "X-API-Key reached the upstream"
PY
    pass "only the keyed message/send reached the upstream, without X-API-Key"
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
