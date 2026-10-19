# Variants: the worked example in skills/affinidi-agent-gateway/references/surfaces.md, "Variants". A beta variant
# created with fabric agent-gateway api and pointed at a second a2a target; `$beta` reaches only that target, the alias-less call
# reaches the base target, and an unknown alias gets 400.
# Serial: every variant save runs a full in-process reload that rebinds all listeners, which would
# disturb cases running in parallel.
E2E_SERIAL=1

setup() {
    start_target a2a
    start_target a2a A2A_BETA_URL
    export UPSTREAM_URL="$A2A_URL" BETA_UPSTREAM_URL="$A2A_BETA_URL"
    SURFACE_NAME="$(unique variant-a2a)"
    export SURFACE_NAME
}

texts_seen() {
    # The message texts a target received in message/send calls, one per line.
    target_requests "$1" > "$E2E_CASE_DIR/$1-requests.json"
    "$PYTHON" - "$E2E_CASE_DIR/$1-requests.json" <<'PY'
import json, sys
for r in json.load(open(sys.argv[1])):
    body = r.get("body")
    if r.get("method") == "POST" and isinstance(body, dict) and body.get("method") == "message/send":
        for part in body["params"]["message"].get("parts", []):
            print(part.get("text", ""))
PY
}

verify() {
    expect_json 2 'doc.get("alias") == "beta" and doc.get("enabled") is True and doc["overrides"]["target"]["endpoint"] == env["BETA_UPSTREAM_URL"]' \
        "the beta variant is enabled and overrides the target endpoint"
    expect_block 3 'echo: via \$beta'
    expect_block 3 'echo: via base'
    expect_block 3 "Virtual channel alias 'nope' not found for this channel"
    expect_block 3 'HTTP 400'
    local beta base
    beta=$(texts_seen A2A_BETA_URL) || fail "could not read the beta target's requests"
    base=$(texts_seen A2A_URL) || fail "could not read the base target's requests"
    [ "$beta" = 'via $beta' ] || fail "the beta target should receive only the \$beta call, got: $beta"
    pass "the \$beta call reached only the beta target"
    [ "$base" = 'via base' ] || fail "the base target should receive only the alias-less call, got: $base"
    pass "the alias-less call reached the base target and the unknown alias reached neither"
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
