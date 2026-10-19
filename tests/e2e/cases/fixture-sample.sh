# Proves the runner against a live gateway with two read-only commands. The recipes are in
# tests/e2e/fixtures/sample.md, so run it with E2E_DOCS_ROOT=tests/e2e/fixtures.

verify() {
    expect_json 1 'doc.get("authenticated") is True' "whoami reports an authenticated session"
    expect_json 1 'doc.get("connection") == "e2e"' "whoami resolves the sandbox connection e2e"
    expect_json 1 'doc.get("host") == env["GATEWAY"]' "whoami reports the gateway under test"
    expect_json 2 'isinstance(doc.get("oauth_callback_route"), str) and doc["oauth_callback_route"].startswith("/")' \
        "surface-routing reports the OAuth callback route"
    expect_json 2 'isinstance(doc.get("available_listen_addresses"), list)' "surface-routing lists inbound listen addresses"
}
