# Follows one MCP request through the gateway by a caller-chosen trace id: the upstream receives
# it, the audit log has a policy decision carrying it, and the log archive has lines carrying it.
# The recipes are in skills/affinidi-agent-gateway/references/triage.md, "Follow one request".
# setup selects policy_decision and turns audit on (appliance-wide, so the case is serial), and restores
# both after.

E2E_SERIAL=1

setup() {
    start_target mcp MCP_URL

    fab agent-gateway settings show -o json > settings-before.json
    "$PYTHON" - settings-before.json settings-restore.json settings-on.json <<'PY'
import json, sys
before = json.load(open(sys.argv[1]))
restore = {"audit_enabled": before.get("audit_enabled", False),
           "audit_events": before.get("audit_events") or []}
json.dump(restore, open(sys.argv[2], "w"))
on = {"audit_enabled": True, "audit_events": sorted(set(restore["audit_events"]) | {"policy_decision"})}
json.dump(on, open(sys.argv[3], "w"))
PY
    fab agent-gateway settings set --file settings-on.json -o json > /dev/null

    POLICY_ID="$(unique trace-allow)"
    printf '%s\n' "$POLICY_ID" > policy-id.txt
    printf 'package surface.policy\n\ndefault allow = true\n' > allow.rego
    fab agent-gateway policies create --id "$POLICY_ID" --name "$POLICY_ID" --policy-type agent-surface \
        --policy-file allow.rego -o json > /dev/null

    fab agent-gateway runtime show surface-routing -o json > routing.json
    local listen prefix name
    listen="$(json_get routing.json 'next((a for a in doc["available_listen_addresses"] if "://localhost" in a or "://127.0.0.1" in a), doc["available_listen_addresses"][0])')"
    prefix="$(json_get routing.json 'doc["channel_path_prefix"][0]["prefix"]')"
    name="$(unique trace-mcp)"
    fab agent-gateway surfaces create --name "$name" --protocol mcp --listen-address "$listen" \
        --route "$prefix/$name" --target-endpoint "$MCP_URL/mcp" -o json > created.json
    SURFACE_ID="$(json_get created.json 'doc["surface_id"]')"
    printf '%s\n' "$SURFACE_ID" > surface-id.txt

    fab agent-gateway surfaces get "$SURFACE_ID" -o json > surface.json
    "$PYTHON" - surface.json "$POLICY_ID" <<'PY'
import json, sys
doc = json.load(open(sys.argv[1]))
doc.setdefault("target", {})["policy"] = {"policy_definition_id": sys.argv[2]}
json.dump(doc, open(sys.argv[1], "w"))
PY
    fab agent-gateway surfaces update "$SURFACE_ID" --file surface.json -o json > /dev/null

    SURFACE_URL="$listen$(json_get surface.json 'doc["access_point"]["route"]')"
    export SURFACE_URL
    clear_target MCP_URL
}

verify() {
    TRACE="$(cat trace-id.txt)"
    export TRACE
    expect_block 2 '^200 '
    expect_json 3 'doc["total"] >= 1 and any(r["trace_id"] == env["TRACE"] and r["category"] == "policy_decision" for r in doc["rows"])' \
        "the audit log has a policy decision carrying the caller's trace id"
    expect_block 4 'log lines with the trace id: [1-9]'

    target_requests MCP_URL > target-requests.json
    "$PYTHON" - target-requests.json <<'PY' || fail "the upstream did not receive the caller's trace id" target-requests.json
import json, os, sys
reqs = json.load(open(sys.argv[1]))
calls = [r for r in reqs if isinstance(r.get("body"), dict) and r["body"].get("method") == "tools/call"]
sys.exit(0 if calls and all(os.environ["TRACE"] in r["headers"].get("x-gateway-trace-id", "") for r in calls) else 1)
PY
    pass "the upstream received X-Gateway-Trace-Id with the caller's UUID"

    [ ! -e gw-logs.zip ] || fail "the recipe left the log archive behind"
    pass "the log archive was removed"
}

cleanup() {
    rm -f gw-logs.zip
    if [ -s surface-id.txt ] && fab agent-gateway surfaces get "$(cat surface-id.txt)" -o json > /dev/null 2>&1; then
        fab agent-gateway surfaces delete "$(cat surface-id.txt)" > /dev/null
    fi
    if [ -s policy-id.txt ] && fab agent-gateway policies get "$(cat policy-id.txt)" -o json > /dev/null 2>&1; then
        fab agent-gateway policies delete "$(cat policy-id.txt)" > /dev/null
    fi
    if [ -s settings-restore.json ]; then
        fab agent-gateway settings set --file settings-restore.json -o json > /dev/null
    fi
}
