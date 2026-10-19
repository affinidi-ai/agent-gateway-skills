# End-to-end runner fixture

Not part of the skill. These two read-only recipes drive `tests/e2e/cases/fixture-sample.sh`,
which proves the runner against a live gateway:
`E2E_DOCS_ROOT=tests/e2e/fixtures tests/e2e/run.sh fixture-sample`.

Which connection, gateway and identity the token resolves to:

<!-- e2e: fixture-sample -->
```bash
fabric agent-gateway whoami -o json
```

The gateway's surface routing, including its OAuth callback route:

<!-- e2e: fixture-sample -->
```bash
fabric agent-gateway runtime show surface-routing -o json
```
