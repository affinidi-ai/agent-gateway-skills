# Runs "Scope a token and prove it" in skills/affinidi-agent-gateway/references/fabric.md: a
# view-only personal access token reads but cannot write, a full-role token acts with its
# owner's full role, and a revoked token stops authenticating. No targets; not serial.
# Both token secrets stay in mode-600 files in the case work directory; verify checks that no
# secret reached any block output and that the last block deleted both files; cleanup revokes
# whatever is still active and removes what is left.

verify() {
    expect_json 2 'doc.get("authenticated") is True and doc.get("scopes") == ["surfaces.view"]' \
        "the view-only token authenticates and reports only surfaces.view"
    expect_fail_block 3 "gateway returned 403 Forbidden: no additional detail from server"
    expect_json 4 'doc.get("authenticated") is True and "scopes" not in doc and doc.get("role") == "administrator"' \
        "the full-role token reports no scopes and its owner's administrator role"
    expect_json 5 'doc.get("authenticated") is False' "the revoked token no longer authenticates"
    if grep -l 'agpat_' "$E2E_CASE_DIR"/block-*.out >/dev/null 2>&1; then
        fail "a token secret reached block output"
    fi
    pass "no token secret in any block output"
    if [ -e "$E2E_CASE_DIR/pat-view.json" ] || [ -e "$E2E_CASE_DIR/pat-full.json" ]; then
        fail "a token file is still on disk after the last block"
    fi
    pass "the last block deletes both token files"
}

cleanup() {
    local f id active
    for f in pat-view.json pat-full.json; do
        [ -s "$E2E_CASE_DIR/$f" ] || { rm -f "$E2E_CASE_DIR/$f"; continue; }
        id=$("$PYTHON" -c 'import json, sys; print(json.load(open(sys.argv[1])).get("id", ""))' "$E2E_CASE_DIR/$f")
        if [ -n "$id" ]; then
            active=$(fab agent-gateway tokens get "$id" -o json | "$PYTHON" -c 'import json, sys; print(json.load(sys.stdin).get("active"))')
            if [ "$active" = True ]; then
                fab agent-gateway tokens revoke "$id" --yes >/dev/null
            fi
        fi
        rm -f "$E2E_CASE_DIR/$f"
    done
    # Block 3 is expected to be refused; when the case fails because it was not, remove the surface it created.
    fab agent-gateway surfaces list -o json | "$PYTHON" -c '
import json, sys
for s in json.load(sys.stdin):
    if s.get("name") == "scope-check-probe":
        print(s["surface_id"])
' | while read -r sid; do
        fab agent-gateway surfaces delete "$sid" >/dev/null
    done
}
