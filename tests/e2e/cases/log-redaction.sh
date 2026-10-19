# Reads the log redaction settings and counts redaction markers in the log archive, from
# references/operations.md "Turn on log redaction". The change itself edits gateway.json and restarts
# the gateway, so the case runs only the Before and Verify blocks against the gateway as it is.
# Blocks: 1 read logging.redaction from the file on disk, 2 download the log and count markers.

verify() {
    expect_json 1 'isinstance(doc["rules"], int) and doc["enabled"] in (True, False, None)' \
        "the Before block reads enabled and a rule count"
    if [ "$(json_get "$(e2e_block_file 1)" 'bool(doc["enabled"]) and doc["rules"] > 0')" = true ]; then
        expect_block 2 '^[1-9][0-9]*$'
    else
        pass "redaction is off on this gateway, so no marker count is expected"
    fi
}
