# Turn on audit events without switching others off, from references/operations.md
# "Turn on audit events without switching others off". Changes appliance-wide settings, so it runs alone
# and restores exactly the two fields it touches.
# Blocks: 1 list the audit event catalog, 2 save audit_enabled and audit_events, 3 write them back with
# policy_decision added, 4 read back.
# verify() then proves the traps the recipe avoids: a one-event list turns the others off, an unknown event
# name is refused, and a document that sends audit_categories changes nothing.
E2E_SERIAL=1

setup() {
    fab agent-gateway settings show -o json > "$E2E_CASE_DIR/settings-full.json"
    "$PYTHON" - "$E2E_CASE_DIR/settings-full.json" "$E2E_CASE_DIR/settings-restore.json" <<'PY'
import json, sys
doc = json.load(open(sys.argv[1]))
json.dump({"audit_enabled": doc.get("audit_enabled", False),
           "audit_events": doc.get("audit_events") or []}, open(sys.argv[2], "w"))
PY
    rm -f "$E2E_CASE_DIR/settings-full.json"
    printf '%s\n' '{"audit_enabled":false,"audit_events":["trust_check","vp_injected"]}' \
        > "$E2E_CASE_DIR/settings-start.json"
    fab agent-gateway settings set --file "$E2E_CASE_DIR/settings-start.json" -o json > /dev/null
}

verify() {
    expect_block 1 '^policies[[:space:]]policy_decision$'
    expect_block 1 '^requests[[:space:]]request_rejected$'
    expect_json 2 'doc["audit_enabled"] is False and sorted(doc["audit_events"]) == ["trust_check", "vp_injected"]' \
        "the starting point selects trust_check and vp_injected"
    expect_json 4 'doc["audit_enabled"] is True and sorted(doc["audit_events"]) == ["policy_decision", "trust_check", "vp_injected"]' \
        "the recipe turned audit on, added policy_decision and kept the other events"

    printf '%s\n' '{"audit_events":["policy_decision"]}' > "$E2E_CASE_DIR/partial.json"
    fab agent-gateway settings set --file "$E2E_CASE_DIR/partial.json" -o json > /dev/null
    fab agent-gateway settings show -o json > "$E2E_CASE_DIR/after-partial.json"
    "$PYTHON" "$E2E_HERE/expr.py" check "$E2E_CASE_DIR/after-partial.json" \
        'doc["audit_events"] == ["policy_decision"] and doc["audit_enabled"] is True' \
        || fail "a one-event list left other events on, or changed audit_enabled" "$E2E_CASE_DIR/after-partial.json"
    pass "audit_events is replaced whole, and fields the document leaves out keep their values"

    printf '%s\n' '{"audit_events":["policy_decision","no_such_event"]}' > "$E2E_CASE_DIR/unknown.json"
    if fab agent-gateway settings set --file "$E2E_CASE_DIR/unknown.json" -o json > "$E2E_CASE_DIR/unknown.out" 2>&1; then
        fail "an unknown event name was accepted" "$E2E_CASE_DIR/unknown.out"
    fi
    grep -q 'Audit events must be names from the audit event catalog' "$E2E_CASE_DIR/unknown.out" \
        || fail "the refusal does not name the audit event catalog" "$E2E_CASE_DIR/unknown.out"
    pass "an unknown event name is refused with the catalog message"

    printf '%s\n' '{"audit_categories":{"trust_checks":true}}' > "$E2E_CASE_DIR/legacy.json"
    fab agent-gateway settings set --file "$E2E_CASE_DIR/legacy.json" -o json > /dev/null \
        || fail "a document with audit_categories was refused" "$E2E_CASE_DIR/legacy.json"
    fab agent-gateway settings show -o json > "$E2E_CASE_DIR/after-legacy.json"
    "$PYTHON" "$E2E_HERE/expr.py" check "$E2E_CASE_DIR/after-legacy.json" \
        'doc["audit_events"] == ["policy_decision"] and "audit_categories" not in doc' \
        || fail "audit_categories changed the selection" "$E2E_CASE_DIR/after-legacy.json"
    pass "a document that sends audit_categories is accepted and changes nothing"
}

cleanup() {
    [ -f "$E2E_CASE_DIR/settings-restore.json" ] || return 0
    fab agent-gateway settings set --file "$E2E_CASE_DIR/settings-restore.json" -o json > /dev/null
}
