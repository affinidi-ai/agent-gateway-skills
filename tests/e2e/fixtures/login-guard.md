# Keychain guard fixture

Not part of the skill. The recipe below runs `fabric agent-gateway login`, which writes a token to the OS
keychain, so the runner must refuse the case before running any of it:
`E2E_DOCS_ROOT=tests/e2e/fixtures tests/e2e/run.sh fixture-login-guard` exits 1 with REFUSED.

<!-- e2e: fixture-login-guard -->
```bash
fabric agent-gateway login --host "$GATEWAY" --token-stdin <<<"$FABRIC_TOKEN"
```
