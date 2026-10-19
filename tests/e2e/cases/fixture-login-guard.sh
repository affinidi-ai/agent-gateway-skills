# Proves the keychain guard. The fixture recipe under tests/e2e/fixtures/ signs in, so run.sh must
# refuse the case before setup runs.

setup() {
    fail "the keychain guard let a sign-in recipe run"
}
