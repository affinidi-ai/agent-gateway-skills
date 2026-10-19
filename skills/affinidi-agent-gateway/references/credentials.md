# Credentials: secrets, target credentials and delegated OAuth

Load this file when an upstream needs a credential, a call returns 502 `Target authentication failed`,
401 `consent-required`, 503 `Delegated credentials unavailable` or an MCP `input_required` consent link, a user
leaves, or a credential may be compromised.

## Contents

[Before you change anything](#before-you-change-anything) ·
[Three things called credentials](#three-things-called-credentials) · [Secrets](#secrets) ·
[Certificates](#certificates) ·
[Recipe: static target credential](#recipe-static-target-credential) ·
[Recipe: rotate a secret with no downtime](#recipe-rotate-a-secret-with-no-downtime) ·
[Credential providers and the callback URL](#credential-providers-and-the-callback-url) ·
[Recipe: per-user delegation, MCP and A2A](#recipe-per-user-delegation-mcp-and-a2a) ·
[Consent modes and the clients that can use them](#consent-modes-and-the-clients-that-can-use-them) ·
[The delegation vault](#the-delegation-vault) ·
[Recipe: offboard a user or respond to a compromise](#recipe-offboard-a-user-or-respond-to-a-compromise) ·
[When it fails](#when-it-fails) · [Known issues here](#known-issues-here)

## Before you change anything

None of these commands prints a secret value or a token.

```bash
fabric agent-gateway secrets list -o json              # metadata only; no secrets call returns a value
fabric agent-gateway credential-providers list -o json # no secret refs and no callback_path; use get <uuid> for those
fabric agent-gateway delegation-vault list -o json     # grants: metadata only, never tokens
fabric agent-gateway runtime show surface-routing -o json | jq .oauth_callback_route
fabric agent-gateway surfaces get <surface-id> -o json | jq '{auth: .target.auth, outbound_credentials}'
```

By default the `secrets`, `credential-providers` and `delegation-vault` commands need the `administrator` role,
`surfaces` reads need only `user`, and `runtime show surface-routing` needs no role.

## Three things called credentials

| What | Who holds it | Where it is configured | Read |
| --- | --- | --- | --- |
| The caller's credential (API key, JWT, DID, mTLS, or a gateway-issued MCP token) | the agent calling the surface | `access_point.caller_authentication`, or on an MCP surface `mcp_http.authorization` instead | [identity.md](identity.md) |
| A static target credential: one key the gateway sends to the upstream for every caller | the gateway's secret store | `target.auth` | [Recipe: static target credential](#recipe-static-target-credential) |
| A per-user delegated OAuth token: the upstream sees each user's own token | the delegation vault | `outbound_credentials[]` plus a credential provider | [Recipe: per-user delegation, MCP and A2A](#recipe-per-user-delegation-mcp-and-a2a) |

Two OAuth legs exist: an MCP client obtaining a gateway-issued token for a surface that sets
`mcp_http.authorization` (a token-exchange or JWT-bearer grant at the `sts.mcp_issuer` profile, never a browser
sign-in, [KI-27](known-issues.md); see [identity.md](identity.md#mcp-client-sign-in)), and the gateway
obtaining a user's token from a provider, which is this file.

## Secrets

A secret is a named value in the gateway's store. Create takes `name`, `secret_id` and `value`; the
server does not derive `secret_id` from the name (only the dashboard does), refuses a duplicate with 400,
and never lets `secret_id` change afterwards. Pass the value on standard input
so it stays out of shell history and process lists: `--value-stdin` removes one trailing line ending (`\n` or `\r\n`),
while `--value` stores its argument exactly as given.

- No secrets call returns the value: `create`, `get`, `update` and `list` answer with the secret's metadata only,
  so `--reveal` shows nothing more for a secret. To show a user that a secret exists, use
  `fabric agent-gateway secrets list -o json`.
- A field refers to a secret in one of two forms, and each field accepts only its own:

| Form | Fields |
| --- | --- |
| Bare `<secret_id>` | `target.auth`, a Transit Point's `target_auth`, source-auth `api_key`, the A2A proxy's Direct Line `backend.secret_id`, OTLP `opentelemetry.auth.secret_id`, the STS `client_secret_ref`, every credential-provider `*_secret_ref` |
| `"$SECRET:<secret_id>"` | MPP `secret_key` and `stripe_secret_key`, the x402 wallet `private_key`, string values in `custom_metadata.payload`. Only a whole string is resolved: `"Bearer $SECRET:x"` is sent literally |

- A surface save checks that the secrets named by `target.auth`, a transit `target_auth` and source-auth
  `api_key` exist, and refuses with 400 `Secret reference is not accessible`. It does not check
  `$SECRET:` references, so a typo there saves and fails only on a request.
- `fabric agent-gateway secrets delete` returns at once and checks no references: every surface that used the secret
  breaks on its next request.
- Secrets live where `secrets_backend` in `config.toml` says ([operations.md](operations.md#configuration-files)). `filesystem`, the default, is the only working
  one: `aws` starts, but every secret call then fails with
  `AWS Secrets Manager backend not yet implemented. Please use filesystem backend.`, and any other value logs
  a warning and uses `filesystem`. Whether the files are encrypted is [KI-03](known-issues.md).

## Certificates

Certificates are a separate store for mTLS, `fabric agent-gateway certificates`; reading and writing need
`administrator` by default. A certificate has `name`, `certificate_pem`, an optional `private_key_pem` and a
`kind`:

- `ca`, a trust anchor. When the gateway checks client certificates on its listeners (see
  `fabric agent-gateway runtime show networking`), it loads every active one at startup, and an `mtls`
  caller-auth method names them in `"trust": {"type": "ca", "ca_certificate_ids": [...]}`.
- `client_leaf`, one client's certificate, for `"trust": {"type": "pinned", "certificate_ids": [...]}` and for
  a `from_mtls` identity ([identity.md](identity.md)), which refuses any other kind.
- `server_leaf`, the default when `kind` is left out. The startup check skips it, so set `kind` on every
  certificate you add for mTLS.

fabric shows `private_key_pem` as the mask unless you pass `--reveal`; the API returns the key itself to anyone
with `certificates.view`. `certificates update` changes only the fields you send, so leave `private_key_pem` out
to keep the stored key. The `mtls` method and the listener settings: [identity.md](identity.md).

## Recipe: static target credential

Use it when the upstream needs one key or token from the gateway, whoever the caller is. This is also
the shared-secret way of closing the direct path to the upstream ([identity.md](identity.md)).

**Confirm with the user:** from the update on, the gateway sends the header on every request except a public
discovery read (a `GET` or `HEAD` that skips caller authentication) and a request whose caller credential failed;
if the secret is missing, the requests that would carry it get 502 instead of reaching the upstream, and if its
value is wrong, the upstream's own 401 or 403.

**Before.** `fabric agent-gateway surfaces get <surface-id> -o json | jq .target.auth` must be `null`, and the upstream
must already accept the key.

**Change.** Store the key, then add `target.auth` to the surface. The shape is
`{"method":{"static_secret":{"secret_id","header_name","header_format"}},"fallback":"reject"}`, where
`header_format` defaults to `{value}` and `fallback` to `reject`. Never use
`"method": "credential_lookup"`: it is accepted but not implemented, and sends the request with no
credential even under `reject`. Check key spelling inside `auth` yourself:
the gateway rejects an unknown key directly under `target` but ignores a misspelled one inside `auth`,
so `header_fomat` silently falls back to `{value}`.

<!-- e2e: target-auth-mcp -->
```bash
SECRET_ID="${SECRET_ID:?set SECRET_ID to a new secret id, for example orders-upstream-key}"
UPSTREAM_KEY_VALUE="${UPSTREAM_KEY_VALUE:?export the upstream key in UPSTREAM_KEY_VALUE}"
printf '%s' "$UPSTREAM_KEY_VALUE" | fabric agent-gateway secrets create --name "$SECRET_ID" \
  --secret-id "$SECRET_ID" --value-stdin -o json | jq '{id, secret_id, updated_at}'
```

<!-- e2e: target-auth-mcp -->
```bash
SURFACE_ID="${SURFACE_ID:?set SURFACE_ID to the surface in front of the upstream}"
SECRET_ID="${SECRET_ID:?set SECRET_ID}"
HEADER_NAME="${HEADER_NAME:-Authorization}"
[ -n "${HEADER_FORMAT:-}" ] || HEADER_FORMAT='Bearer {value}'
fabric agent-gateway surfaces get "$SURFACE_ID" -o json > surface.json
jq --arg s "$SECRET_ID" --arg h "$HEADER_NAME" --arg f "$HEADER_FORMAT" '.target.auth = {
    method: {static_secret: {secret_id: $s, header_name: $h, header_format: $f}},
    fallback: "reject"}' surface.json > surface-new.json
fabric agent-gateway surfaces update "$SURFACE_ID" --file surface-new.json -o json > /dev/null
fabric agent-gateway surfaces get "$SURFACE_ID" -o json | tee surface.json | jq .target.auth
```

**Verify.** One request through the surface must succeed. The gateway reads the secret on every
request and sends it as one value, so the first call after the update already
carries it.

<!-- e2e: target-auth-mcp -->
```bash
URL="$(jq -r '.access_point.listen_address + .access_point.route' surface.json)"
curl -sS -w '\nHTTP %{http_code}\n' -X POST "$URL" -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

For an A2A agent the change is the same and only the call differs:

<!-- e2e: target-auth-a2a -->
```bash
SURFACE_ID="${SURFACE_ID:?set SURFACE_ID to the A2A surface}"
SECRET_ID="${SECRET_ID:?set SECRET_ID to an existing secret}"
fabric agent-gateway surfaces get "$SURFACE_ID" -o json | jq --arg s "$SECRET_ID" '.target.auth = {method: {static_secret:
  {secret_id: $s, header_name: "Authorization", header_format: "Bearer {value}"}}, fallback: "reject"}' > surface-new.json
fabric agent-gateway surfaces update "$SURFACE_ID" --file surface-new.json -o json > /dev/null
URL="$(fabric agent-gateway surfaces get "$SURFACE_ID" -o json | jq -r '.access_point.listen_address + .access_point.route')"
curl -sS -w '\nHTTP %{http_code}\n' -X POST "$URL" -H 'Content-Type: application/json' -d '{"jsonrpc":"2.0",
  "id":"1","method":"message/send","params":{"message":{"role":"user","messageId":"m1",
  "parts":[{"kind":"text","text":"ping"}]}}}'
```

**Undo.** **Confirm with the user:** the upstream stops receiving the key on the next request. Remove `.target.auth` with `jq 'del(.target.auth)'` and `fabric agent-gateway surfaces update`, and only then
`fabric agent-gateway secrets delete <secret-id>`: a surface whose secret is gone answers 502 to every request that would carry it.

**If it fails.** A 502 `Target authentication ...` is a missing secret, see [When it fails](#when-it-fails).
An upstream 401 or 403 means a wrong header name, format or value.

## Recipe: rotate a secret with no downtime

**Confirm with the user:** which system holds the other side of the key, and that it can accept the old
and the new value at the same time. Only source-auth API keys overlap on the gateway side.

**Before.** Find every consumer of the secret, because each picks up a new value differently:
`fabric agent-gateway surfaces list -o json | jq --arg s <secret-id> '[.[] | select(tostring | contains($s)) | .surface_id]'`.
The match is on a substring, so check each hit.

| Consumer | When the new value applies | Order of the rotation |
| --- | --- | --- |
| `target.auth`, transit `target_auth`, `proxy://` | next request | upstream accepts both, update the secret, upstream drops the old one |
| Source-auth API key (callers present it) | up to 60 seconds; a comma-separated value holds several keys at once | set `old,new`, move the callers, set `new` |
| Credential provider client ID, client secret, API key | next use | rotate at the IdP with both valid, then update |
| OTLP collector auth | only after `fabric agent-gateway metrics config set` or a restart | update the secret, then re-save the metrics config unchanged and read its `message` |
| MPP `secret_key` | next payment; challenges already issued fail until `challenge_ttl_seconds` (default 300) passes | rotate in a quiet period, or lower the TTL first |
| x402 wallet `private_key` | next payment for the same address; a new address needs `x402-proxy.json` edited and a restart | same address: update; new address: edit, update, restart together |
| STS client secret | at once, with no overlap | coordinate with the client |
| Direct Line secret (A2A proxy) | next request | new secret in Copilot Studio, update, revoke the old one there |

**Change.** An update changes the value only when the document says `"update_value": true`, and the
CLI refuses a document with `value` but no `update_value`. An update also clears `description` when the
document leaves it out, so carry it over.

<!-- e2e: secret-rotate-a2a -->
```bash
SECRET_ID="${SECRET_ID:?set SECRET_ID to the secret to rotate}"
export NEW_KEY_VALUE="${NEW_KEY_VALUE:?export the new value; the other side must already accept it}"
fabric agent-gateway secrets get "$SECRET_ID" -o json > before.json
umask 077
jq '{update_value: true, value: env.NEW_KEY_VALUE}
  + (if .description == null then {} else {description} end)' before.json > rotate.json
fabric agent-gateway secrets update "$SECRET_ID" --file rotate.json -o json | jq '{secret_id, description, updated_at}'
rm -f rotate.json
```

**Verify.** `updated_at` moves only when something changed, and only `-o json` shows it.
Then send one request through a surface that uses the secret.

<!-- e2e: secret-rotate-a2a -->
```bash
SURFACE_ID="${SURFACE_ID:?set SURFACE_ID to a surface that uses the secret}"
fabric agent-gateway secrets get "$SECRET_ID" -o json | jq --arg before "$(jq -r .updated_at before.json)" \
  '{secret_id, updated_at, moved: (.updated_at != $before)}'
URL="$(fabric agent-gateway surfaces get "$SURFACE_ID" -o json | jq -r '.access_point.listen_address + .access_point.route')"
curl -sS -w '\nHTTP %{http_code}\n' -X POST "$URL" -H 'Content-Type: application/json' -d '{"jsonrpc":"2.0",
  "id":"1","method":"message/send","params":{"message":{"role":"user","messageId":"m2",
  "parts":[{"kind":"text","text":"after rotation"}]}}}'
```

**Undo.** The same update with the old value, while the other side still accepts it.

**If it fails.** An upstream 401 right after the update: the other side does not accept the new value
yet, so roll back. Never delete the OTLP secret while `auth` names it: the next boot fails.

## Credential providers and the callback URL

A provider tells the gateway how to get a token for the upstream. `provider_type` is
`oauth2_authorization_code` (the default, one token per user), `oauth2_client_credentials` (one token
for the whole surface) or `api_key` (a stored key, no OAuth).

- Create requires `name`, `provider_id`, `token_endpoint` and both `*_secret_ref` for OAuth types, and
  `api_key_secret_ref` for `api_key`. It does not require `authorization_endpoint`, which every consent URL
  needs.
- Each `*_secret_ref` is a secret's `secret_id`, not its UUID or name; otherwise the answer is 400
  `Secret reference is not accessible`.
- `token_endpoint`, `authorization_endpoint` and `callback_url` must be http or https, resolve in DNS,
  and not be loopback or a cloud metadata address; private addresses are allowed.
- `resource` and `consent_identity_strategy_id` are for MCP `2026-07-28` consent
  ([MCP `2026-07-28` requests](#mcp-2026-07-28-requests)). `resource` must be a canonical HTTPS URI, otherwise 400
  `resource must be a canonical HTTPS URI`. `consent_identity_strategy_id` names a JWT verification strategy with
  an HTTPS `expected_issuer`, which checks the IdP's `id_token`; it is accepted only on an
  `oauth2_authorization_code` provider that sets `resource`, otherwise 400
  `Consent identity strategy is invalid or not accessible`.
- `provider_id` is lowercased after the duplicate check, so creating `GitHub` next to `github` stores a second
  provider with the same `provider_id` and `callback_path`. Send it lowercase.
- `fabric agent-gateway api post /v1/credential-providers/validate --data '{"token_endpoint":"<url>"}'` sends one
  unauthenticated GET and answers 200 once the URL passes its check, with `reachable: false` when the GET fails.
  `reachable: true` with a 400 or 405 status is a pass. A missing or refused `token_endpoint` gets 400.
- The OAuth flow is authorisation code with PKCE S256. The client authenticates with
  `client_secret_post` only, never HTTP Basic; an IdP that insists on `client_secret_basic` fails the
  token exchange.

### The callback URL, settled

The docs show the callback at `/v1/identity/oauth/callback/<provider>`, and a gateway built from the shipped
example configuration serves `/oauth/callback/<provider>`. Both are real, and configuration picks one.

1. The gateway serves the callback at `<oauth_callback_route>/<provider_id>`, at the root of the
   gateway (not under `/api`), without authentication. `oauth_callback_route` is a `gateway.json`
   setting: the code default is `/v1/identity/oauth/callback`, and the shipped example configuration
   sets `/oauth/callback`. Read it from `fabric agent-gateway runtime show surface-routing -o json`.
2. At create, each provider stores `callback_path` = `<oauth_callback_route>/<provider_id>`, and neither
   `provider_id` nor `callback_path` can change afterwards. Update merges, except that `default_scopes` and
   `additional_params` are replaced, so `[]` or `{}` clears them, and a changed `provider_type` skips the
   create-time checks for the new type.
3. The `redirect_uri` sent to the IdP is the provider's `callback_url` when set, otherwise
   `https://<did.domain><callback_path>`. A loopback `did.domain` fails every token exchange with
   `Blocked callback_url for provider`, so set `callback_url` to the public URL and register exactly
   that URL at the IdP.
4. The callback takes the provider from the OAuth `state`, not from the path segment, so a slug typo
   in the path is not the cause of a consent loop under `on_demand`. The path segment still names the provider
   in the `consent_granted` audit event and in the `elicit` wake-up ([KI-17](known-issues.md)).
5. `fabric agent-gateway runtime show surface-routing` re-reads `gateway.json` on every call, while the mounted route
   and each `callback_path` are fixed at startup and at create. After an edit to `oauth_callback_route`
   they can disagree until a restart (inference). `fabric agent-gateway api` cannot reach the callback, because it
   prefixes `/api`; probe it with `curl`.
6. An MCP `2026-07-28` request uses its own callback, and `oauth_callback_route`, `callback_path` and
   `callback_url` play no part in it: the `redirect_uri` is `/mcp-consent/callback/<id>` on the origin of the
   `sts.mcp_issuer` issuer, where `<id>` is the provider's UUID `id`. Register that URL at the IdP as well
   ([MCP `2026-07-28` requests](#mcp-2026-07-28-requests)).

To move a provider to another route, update its `callback_url` or recreate it; recreating changes its
UUID, so every binding must change and every grant is orphaned.

## Recipe: per-user delegation, MCP and A2A

Use it when the upstream must act as each user (their GitHub, their calendar), not as one account.

**Confirm with the user:** callers of the bound tools get a 401 with a sign-in link until each user
consents once, and every user's tokens are then stored on the gateway.

**Before.**
- The surface must authenticate callers. An anonymous caller on a delegating surface gets 403
  `identity-required`; an identity slot is optional, and without one the vault keys grants on the
  surface ID.
- **Use JWT bearer caller auth with one token per user.** The vault keys a grant on the SHA-256 of the
  JWT `sub`, the API-key secret's `secret_id`, the `api_key_provider` key ID, the DID or the mTLS principal.
  So every caller of one `api_key` method is one user, whichever key in the secret it
  sends ([KI-14](known-issues.md)), and so are all JWTs without `sub`.
- Turn on encryption at rest first ([KI-03](known-issues.md)), and register an OAuth client at the IdP
  whose redirect URI is the `callback_url` below.
- The target must not be `proxy://`. An MCP proxy answers a `2024-11-05` request before delegation runs, so
  its surface's `outbound_credentials` are never resolved: no consent prompt and no delegated token
  ([proxies.md](proxies.md)).

**Change.** **Confirm with the user:** this stores the IdP client's ID and secret on the gateway. Store them,
then create the provider. The last line fails when the stored `callback_path` differs from the route that
`callback_url` was built from.

<!-- e2e: delegation-mcp -->
```bash
PROVIDER_SLUG="${PROVIDER_SLUG:?set PROVIDER_SLUG, lowercase, for example github}"
AUTHORIZE_URL="${AUTHORIZE_URL:?set AUTHORIZE_URL to the IdP authorization endpoint}"
TOKEN_URL="${TOKEN_URL:?set TOKEN_URL to the IdP token endpoint}"
PUBLIC_GATEWAY_URL="${PUBLIC_GATEWAY_URL:?set PUBLIC_GATEWAY_URL to the gateway URL users reach}"
printf '%s' "${IDP_CLIENT_ID:?export IDP_CLIENT_ID}" | fabric agent-gateway secrets create --name "$PROVIDER_SLUG client id" \
  --secret-id "$PROVIDER_SLUG-client-id" --value-stdin -o json > /dev/null
printf '%s' "${IDP_CLIENT_SECRET:?export IDP_CLIENT_SECRET}" | fabric agent-gateway secrets create --name "$PROVIDER_SLUG client secret" \
  --secret-id "$PROVIDER_SLUG-client-secret" --value-stdin -o json > /dev/null
fabric agent-gateway api post /v1/credential-providers/validate --data "$(jq -nc --arg t "$TOKEN_URL" '{token_endpoint: $t}')"
ROUTE="$(fabric agent-gateway runtime show surface-routing -o json | jq -r .oauth_callback_route)"
jq -n --arg slug "$PROVIDER_SLUG" --arg a "$AUTHORIZE_URL" --arg t "$TOKEN_URL" \
  --arg cb "$PUBLIC_GATEWAY_URL$ROUTE/$PROVIDER_SLUG" '{name: $slug, provider_id: $slug,
  provider_type: "oauth2_authorization_code", authorization_endpoint: $a, token_endpoint: $t,
  client_id_secret_ref: ($slug + "-client-id"), client_secret_secret_ref: ($slug + "-client-secret"),
  default_scopes: ["read"], callback_url: $cb}' > provider-doc.json
fabric agent-gateway credential-providers create --file provider-doc.json -o json > provider.json
jq '{id, provider_id, callback_path, callback_url}' provider.json
test "$(jq -r .callback_path provider.json)" = "$ROUTE/$PROVIDER_SLUG"
```

Bind the provider by its UUID `id`, never the slug. A binding defaults to
`required_for` `"all"`, `consent_mode` `on_demand` and `inject_as` `{"type":"bearer_header"}`; a
`custom_header` injection needs both `name` and `format`. On MCP, bind only the
tools that need the token: `{"tools":[...]}` matches any MCP request whose `params.name` is listed, not only
`tools/call`, and a request with no name, `tools/list` included, goes upstream without it.

<!-- e2e: delegation-mcp -->
```bash
SURFACE_ID="${SURFACE_ID:?set SURFACE_ID to the surface whose upstream needs the user token}"
TOOL_NAME="${TOOL_NAME:?set TOOL_NAME to the MCP tool that needs the user token}"
fabric agent-gateway surfaces get "$SURFACE_ID" -o json > surface.json
jq -e '.access_point.caller_authentication.methods[0].type' surface.json
jq --arg p "$(jq -r .id provider.json)" --arg tool "$TOOL_NAME" '.outbound_credentials =
  ((.outbound_credentials // []) + [{credential_provider_id: $p, required_for: {tools: [$tool]},
  consent_mode: "on_demand"}])' surface.json > surface-new.json
fabric agent-gateway surfaces update "$SURFACE_ID" --file surface-new.json -o json | jq .outbound_credentials
```

**Verify.** The user's first call gets 401 `application/problem+json` of type `consent-required`, with
`consent_required[].authorization_url` and no `WWW-Authenticate` header.
Keep the user's credential and the sign-in link off the command line, where the process list shows
them: curl reads the header from a file only you can read (`-H @file`), and the link from a curl
config file (`-K`).

<!-- e2e: delegation-mcp -->
```bash
CALLER_AUTH_HEADER_FILE="${CALLER_AUTH_HEADER_FILE:?set to a mode-600 file holding the header that identifies the user, e.g. 'Authorization: Bearer <JWT>'}"
URL="$(jq -r '.access_point.listen_address + .access_point.route' surface.json)"
jq -nc --arg t "$TOOL_NAME" '{jsonrpc: "2.0", id: 1, method: "tools/call",
  params: {name: $t, arguments: {text: "hello"}}}' > call.json
curl -sS -o consent.json -w 'HTTP %{http_code}\n' -X POST "$URL" -H @"$CALLER_AUTH_HEADER_FILE" \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' -d @call.json
jq '{type, authorization_url: .consent_required[0].authorization_url}' consent.json
```

The user opens `authorization_url` in a browser and signs in, and the callback page says
`Authorization Successful`. Against a test IdP that approves every request, `curl -L` can stand in for
the browser. The retry then reaches the upstream with the user's token, and the grant is in the vault:

<!-- e2e: delegation-mcp -->
```bash
URL="$(jq -r '.access_point.listen_address + .access_point.route' surface.json)"
umask 077
jq -r '"url = \"" + .consent_required[0].authorization_url + "\""' consent.json > authorize.curl
curl -sSL -K authorize.curl | grep -o 'Authorization Successful'
curl -sS -w '\nHTTP %{http_code}\n' -X POST "$URL" -H @"$CALLER_AUTH_HEADER_FILE" \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' -d @call.json
fabric agent-gateway delegation-vault list -o json | jq --arg p "$(jq -r .id provider.json)" \
  '[.[] | select(.credential_provider_id == $p) | {id, user_identity_hash, agent_did, consent_granted_at}]'
```

With audit on and `consent_granted` and `token_injected` selected ([operations.md](operations.md)), this shows
the consent and each injection:

```bash
fabric agent-gateway audit list --category consent_granted,token_injected -o json \
  | jq '[.events[] | {timestamp, surface_id, trace_id, category: (.event | if type == "object" then keys[0] else . end)}]'
```

`consent_required` events need a resolved agent identity.

On A2A, bind with `required_for: "all"`, because a tool list never matches an A2A request and the
request then goes upstream without the token ([KI-16](known-issues.md)). An A2A client sees the 401 as
a transport failure, not as a task in `auth-required` state (inference), so the calling agent's code
must read the body and show the link.

<!-- e2e: delegation-a2a -->
```bash
SURFACE_ID="${SURFACE_ID:?set SURFACE_ID to the A2A surface}"
PROVIDER_UUID="${PROVIDER_UUID:?set PROVIDER_UUID to the id from fabric agent-gateway credential-providers list}"
CALLER_AUTH_HEADER_FILE="${CALLER_AUTH_HEADER_FILE:?set to a mode-600 file holding the header that identifies the user}"
fabric agent-gateway surfaces get "$SURFACE_ID" -o json | jq --arg p "$PROVIDER_UUID" '.outbound_credentials =
  ((.outbound_credentials // []) + [{credential_provider_id: $p, required_for: "all"}])' > surface-new.json
fabric agent-gateway surfaces update "$SURFACE_ID" --file surface-new.json -o json > surface.json
URL="$(jq -r '.access_point.listen_address + .access_point.route' surface.json)"
BODY='{"jsonrpc":"2.0","id":"1","method":"message/send","params":{"message":{"role":"user","messageId":"m1","parts":[{"kind":"text","text":"ping"}]}}}'
curl -sS -o consent.json -w 'HTTP %{http_code}\n' -X POST "$URL" -H @"$CALLER_AUTH_HEADER_FILE" -H 'Content-Type: application/json' -d "$BODY"
umask 077
jq -r '"url = \"" + .consent_required[0].authorization_url + "\""' consent.json > authorize.curl
curl -sSL -K authorize.curl | grep -o 'Authorization Successful'
curl -sS -w '\nHTTP %{http_code}\n' -X POST "$URL" -H @"$CALLER_AUTH_HEADER_FILE" -H 'Content-Type: application/json' -d "$BODY"
```

**Undo.** **Confirm with the user:** bound tools go upstream without a token and the users' grants are revoked.
Remove the binding and update the surface, revoke the grants
([Recipe: offboard a user or respond to a compromise](#recipe-offboard-a-user-or-respond-to-a-compromise)),
then delete the provider and its two secrets. Provider delete checks nothing: bound surfaces then send
A2A and `2024-11-05` MCP requests without a token, a `2026-07-28` request that a binding applies to gets
400 `-32602` `Invalid MCP continuation`, and the grants stay in the vault.

**If it fails.** A missing grant, a failed refresh and an expired grant without a refresh token all answer the
401. A grant from the `2026-07-28` consent flow that this caller did not consent to, or whose refresh fails, and a
refreshed or client-credentials token the vault refuses to store answer 503 `Delegated credentials unavailable`.
Any other delegation failure returns no error: the request goes upstream with no token, and you see the upstream's
own 401 ([KI-12](known-issues.md)). See [When it fails](#when-it-fails).

## Consent modes and the clients that can use them

| `consent_mode` | What the gateway does | What the client must do | Clients |
| --- | --- | --- | --- |
| `on_demand` (default) | 401 problem+json `consent-required` with `authorization_url`, no `WWW-Authenticate` | read the body of a 401, show the link to the user, retry after sign-in | can: `curl`, scripts, custom agents. Cannot render the link (inference from client source, not verified live): Claude Code, MCP Inspector, `mcp-remote` (they fail with the body inside an error string, or start their own OAuth flow against the gateway), VS Code (shows the status and body as a server error) |
| `elicit` | pushes an MCP `elicitation/create` onto the session's GET stream, waits up to `elicit_timeout_secs` (default 300) for the answer and, after Accept, up to as long again for the sign-in | advertise `elicitation` at `initialize`, keep an MCP session and an open GET SSE stream | may receive it: VS Code, the only inspected client that opens the GET stream after a 204 (inference). Cannot: Claude Code, MCP Inspector, `mcp-remote` (they open the stream only after a 202, and the gateway answers `notifications/initialized` with 204); every A2A client; transit and gateway-to-gateway calls. Even when delivered, the wake-up fails ([KI-17](known-issues.md)) |
| `pre_authorize` | behaves exactly as `on_demand` ([KI-02](known-issues.md)) | as `on_demand` | as `on_demand` |

- `elicit` also needs `required_for: {"tools":[...]}`. With `"all"`, `initialize` itself needs the token,
  has no session yet, and gets the 401.
- The gateway records a client's capabilities only for a session it minted, which happens only when the
  client accepts SSE and the upstream answered `initialize` with JSON.
- `elicit_fallback` is `on_demand` (the 401) or `fail`. A decline, cancel, timeout or `fail` forwards the
  tool call **without** the token, although the docs say it fails.
- Choose `on_demand` unless you control the client and tested `elicit` end to end; client details are in
  [protocols.md](protocols.md).

### MCP `2026-07-28` requests

`consent_mode`, `elicit` and the 401 apply to A2A and to MCP `2024-11-05`. A `2026-07-28` request to a surface
with `outbound_credentials` takes a separate consent flow, with no fallback to the 401:

- Every such request needs `[mcp.continuations]` in `config.toml` and `sts.mcp_issuer` in `gateway.json`, or it
  gets 503, JSON-RPC `-32603` `MCP credential service unavailable`. It also needs the surface's
  `mcp_http.authorization` and an identity slot, and a call that a binding applies to needs a caller token issued
  by `sts.mcp_issuer`; otherwise it gets 403, `-32001` `MCP credential authorization denied`.
- Every bound provider except `api_key` needs an HTTPS `resource` (403 otherwise), and an
  `oauth2_authorization_code` provider needs `consent_identity_strategy_id`, the JWT verification strategy that
  checks the provider's ID token (400 `-32602` `Invalid MCP continuation` otherwise).
- `{"tools":[...]}` matches only a `tools/call` whose `name` is listed.
- With no usable grant, a `tools/call`, `prompts/get` or `resources/read` gets a JSON-RPC result whose
  `resultType` is `input_required`, holding an `elicitation/create` request in `url` mode. Its link is
  `/mcp-consent/connect/<provider UUID>` on the origin of the `sts.mcp_issuer` issuer. The client must declare
  the `elicitation.url` capability, or the answer is 400, `-32021` `Missing required client capability`. Any
  other method without a grant gets 403 `-32001`.
- The IdP redirects to the callback in [The callback URL, settled](#the-callback-url-settled), item 6. The
  provider's `authorization_endpoint` must be `https`; the gateway sends the provider's `resource`, adds the
  `openid` scope, needs an `id_token` in the token response, and its page then says `Authorization completed`.
- The grant it stores records who consented. A `2026-07-28` request uses only such a grant, and refreshes it
  only while the provider's `token_refresh_enabled` is true. Through the 401 flow it is released only to the
  same caller; anyone else, a Transit Point and fabric receive get 503 `Delegated credentials unavailable` for it.
- On a `fabric://` route the user's delegated access token travels to the peer gateway only when the route sets
  `fabric_delegated_credentials: true`, on the Target or on the Transit Point; it is off by default. Then the
  calling gateway resolves the bindings before the send and puts the token in the header or `_meta` field the
  binding names, never the refresh token (`ContinuationRoute::FabricSend` in `src/proxy/handler.rs`). Turn it on
  only when the peer may hold that token ([g2g.md](g2g.md#policies-across-gateways)).

## The delegation vault

**What is stored.** Each grant holds the provider's raw `access_token` and `refresh_token`, plus scopes,
expiry and timestamps. The management API never returns the tokens. A token issued without `expires_in` never
expires at the gateway. An expired token with a refresh token from the 401 sign-in is always refreshed, whatever
`token_refresh_enabled` says; one from the `2026-07-28` flow is refreshed only while it is true.
Client-credentials tokens are cached under the fixed user hash `__client_credentials__` per agent DID and
provider, so every caller with the same agent DID shares one; `api_key` providers bypass the vault.

**Keyed by what.** On the direct path (`agent_did`, `user_identity_hash`, provider UUID), where the user hash
is plain lowercase hex SHA-256 with no prefix and no pepper.
On fabric receive the target endpoint stands in for `agent_did`, and the user hash is the caller identity from the
message, which can be `sha256:<hex>`.
A change to any part orphans the grant and the user is asked again: a new provider UUID, a changed agent
DID (an ephemeral pepper changes derived DIDs on restart, [KI-15](known-issues.md)), or adding or
removing an identity slot. A new consent for the same key replaces the old grant. A grant from the
`2026-07-28` flow also records who consented ([MCP `2026-07-28` requests](#mcp-2026-07-28-requests)).

**Key custody.**
- Encryption at rest is **off** by default, although the docs say secrets are encrypted. It is set under
  `[encryption]` in the bootstrap `config.toml`, needs a restart, and the boot log says
  `Encryption at rest is DISABLED` while it is off ([KI-03](known-issues.md)).
- `key_source` is `environment` (the variable `key_env_var` names, `AG_MASTER_KEY` by default, not trimmed,
  so a trailing newline breaks it), `file` (trimmed) or `aws_kms`; `local` does not encrypt. The key is 32
  bytes, as 64 hex characters or base64; any other length is read as base64.
- Records become `<id>.json.enc`. The gateway refuses to boot when stored envelopes do not match the
  active key source, and there is no command to rotate the master key.
- The OAuth `state` holds the vault key and the PKCE verifier, travels in the authorisation URL and is never
  stored. It is sealed under the at-rest key while encryption is on, and otherwise with AES-256-GCM under a key
  derived from the identity-hash pepper (`AG_IDENTITY_HASH_PEPPER`). The callback refuses a state this gateway
  did not seal, one older than 10 minutes, and one that already completed a sign-in; the gateway process
  remembers used states for 15 minutes. With encryption off and an ephemeral pepper, a restart invalidates
  every open sign-in link ([KI-15](known-issues.md)).

**Revocation.** `fabric agent-gateway delegation-vault revoke <grant-id>` removes one grant.
`fabric agent-gateway delegation-vault revoke-user <user-hash>` removes a user's grants for every agent and provider
and answers `{"revoked": n}`, with `n = 0` and status 200 when nothing matched; fabric prints that answer with
`-o json` and `Revoked n grants for user '<hash>'` without it. The match is exact, so
pass the hash exactly as `fabric agent-gateway delegation-vault list -o json` shows it: bare hex on the direct path, not
the `sha256:<hex>` the CLI help shows ([KI-18](known-issues.md)). A grant made by
gateway-to-gateway traffic keeps its own form. Revocation is **local only**: the gateway stops
injecting the token at once but never calls the provider, so a copied token stays valid there until it
expires ([KI-13](known-issues.md)).

**Blast radius.**

| Event | What the attacker holds | What you do |
| --- | --- | --- |
| Vault files leaked, encryption off (disk, volume snapshot, or a debug export decrypted with its recipient's key, which keeps `refresh_token` but not `access_token`) | every user's access and refresh token for every provider, in plain JSON | revoke at every provider, rotate each provider's client secret at the IdP, then `revoke-user` per user |
| Vault files leaked, encryption on, key not leaked | ciphertext only (inference) | rotate nothing yet; find how the files left |
| Portable backup leaked with its backup key | every secret, grant and private key, decrypted | as for a host compromise |
| Host compromised | the master key (`environment` or `file`) or the node's KMS role, so every record; every stored client secret, so refresh tokens can be redeemed (inference) | revoke at every provider, rotate every secret in the store and every client secret at its IdP, move to a new key source on a clean host |
| One API key leaked | the grants of every caller of every key in that secret, which share one hash ([KI-14](known-issues.md)) | rotate the key, then `revoke-user` the secret's hash: a new value keeps the same hash, so the grants would pass to it |

A single file that does not decrypt (wrong key, corruption) breaks every vault lookup: A2A and `2024-11-05`
MCP requests are then forwarded without a token, and `2026-07-28` requests get 503 `-32603`
`MCP credential service unavailable`.

## Recipe: offboard a user or respond to a compromise

**Confirm with the user:** the user's next call through every delegating surface asks for consent again.

**Before.** The user's hash is the SHA-256 of the JWT `sub` (`printf '%s' "$SUB" | sha256sum | cut -d' ' -f1`, or `shasum -a 256` where `sha256sum` is missing),
of an `api_key_provider` key ID, the DID, the mTLS principal, or an API-key secret's `secret_id`, which every
caller of that secret shares; a `consent-required` body also shows it as
`_debug_user_hash`. Pass it exactly as `fabric agent-gateway delegation-vault list -o json` shows it, which on the direct
path is bare hex: `revoke-user sha256:<hex>`, the form the CLI help gives, revokes nothing and still answers
200 `{"revoked":0}` ([KI-18](known-issues.md)). **Change and verify.**

<!-- e2e: delegation-mcp -->
```bash
USER_HASH="${USER_HASH:?set USER_HASH to the bare hex user_identity_hash}"
fabric agent-gateway delegation-vault list -o json | jq --arg h "$USER_HASH" '[.[] | select(.user_identity_hash == $h) | {id, provider_id, agent_did}]'
fabric agent-gateway delegation-vault revoke-user "$USER_HASH" -o json
fabric agent-gateway delegation-vault list -o json | jq --arg h "$USER_HASH" '[.[] | select(.user_identity_hash == $h)] | length'
```

Expect `{"revoked": n}` with `n` at least 1, then a count of 0. The user's next call gets the 401 again:

<!-- e2e: delegation-mcp -->
```bash
URL="$(jq -r '.access_point.listen_address + .access_point.route' surface.json)"
curl -sS -o consent-after.json -w 'HTTP %{http_code}\n' -X POST "$URL" -H @"$CALLER_AUTH_HEADER_FILE" \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' -d @call.json
jq -r .type consent-after.json
```

Then revoke the user's tokens at each provider, because the gateway does not.
For a compromise, follow the blast-radius table above. **Undo.** None; the user consents again.

**If it fails.** `{"revoked":0}` means the hash matched no grant. Compare it with the list. A grant made by
gateway-to-gateway traffic is keyed on the caller identity in the fabric message, a DID or `sha256:<hex>`,
not on the user's hash, and its `agent_did` is the surface's target endpoint: find it by `agent_did` and pass
its hash as listed ([KI-18](known-issues.md)).

## When it fails

| Exact text | Cause | Fix |
| --- | --- | --- |
| 502 `Target authentication failed: Secret with secret_id '<id>' not found` | the `target.auth` secret was deleted after the save | re-create it under the same `secret_id`; the next request uses it |
| 502 `Target authentication configuration error` / `Target authentication credentials unavailable` | the same on `proxy://` / on a Transit Point (there it can also be a blocked destination) | as above; then check the destination |
| 400 `Secret reference is not accessible` | a `secret_id` that does not exist or is out of scope, or a UUID where a `secret_id` belongs | use `secret_id` from `fabric agent-gateway secrets list -o json` |
| the upstream's own 401, no gateway error | wrong header name or format in `target.auth`, `credential_lookup`, `passthrough`, or a delegation failure other than consent | check `target.auth`; for delegation, `fabric agent-gateway audit list --category token_not_found -o json` |
| 403 `https://affinidi.com/atg/errors/identity-required` | bindings on a surface whose caller did not authenticate | configure caller auth and send the credential |
| 401 `consent-required` again right after `Authorization Successful` | the request's key differs from the grant's: `agent_did` or provider UUID changed | compare `_debug_user_hash` and `_debug_agent_did` with `fabric agent-gateway delegation-vault list -o json` |
| every user gets the first user's data | callers of one `api_key` method, or JWTs without `sub` | per-user JWTs or `api_key_provider` keys |
| page `Blocked callback_url for provider '<id>'` | default `redirect_uri` built from a loopback `did.domain` | set a public `callback_url` |
| page `Invalid or expired state parameter: ...` | more than 10 minutes passed, or the state was sealed under another key: another gateway's, or before a restart with an ephemeral pepper while encryption is off | retry the call for a new link |
| page `This authorization link was already used.` | the link already completed a sign-in | retry the call for a new link |
| page `Failed to exchange authorization code for tokens.` | `redirect_uri` differs from the IdP registration, or the IdP needs `client_secret_basic` | register `callback_url` exactly |
| gateway 404 on the callback | the IdP redirects to a route that is not mounted | set `callback_url` to `<oauth_callback_route>/<provider_id>` on the right host |
| boot: `Invalid key length: expected 32 bytes, got N` | the key decodes to other than 32 bytes | 64 hex characters or base64 of 32 bytes |
| boot: `Failed to decode base64 key` | a key that is not exactly 64 characters, such as 64 hex characters plus a newline from `environment` | strip the newline, or use base64 |
| boot: `Environment variable AG_MASTER_KEY not found` | `key_source` is `environment` and the variable the message names, `key_env_var` (`AG_MASTER_KEY` by default), is not set for the gateway process | set it, with no trailing newline, and restart |
| boot: `encryption backend mismatch: ...` | stored records were encrypted under another `key_source` | restore the original `key_source`, or migrate the data, before starting |
| `Failed to decrypt entity secret <id> ...` | the record was encrypted under another master key | restore the key it was written with; there is no command to re-encrypt |
| `<entity> <id> exists only as an encrypted file but encryption at rest is disabled` | encryption at rest was turned off after records were written encrypted | turn it back on with the same key, or migrate the records to plaintext first |
| any secret call: `AWS Secrets Manager backend not yet implemented. Please use filesystem backend.` | `secrets_backend = "aws"` | set `secrets_backend = "filesystem"` and restart |
| fabric: `the document sets "value" without "update_value": true, ...` | `secrets update --file` with a `value` the gateway would ignore | add `"update_value": true` to replace the value, or drop `value` |
| page `Credential provider configuration not found. It may have been deleted.` | the provider was deleted between the authorisation link and the callback | re-create the provider and bind it again, then retry the call for a new link |
| 503 `Delegated credentials unavailable` | a grant from the `2026-07-28` flow used by a caller who did not consent to it, or its refresh failed; or the vault refused a refreshed or client-credentials token. The gateway log says which | call as the user who consented, or revoke the grant so the user consents again |
| `2026-07-28`: 503 `-32603` `MCP credential service unavailable` | a delegating surface without `[mcp.continuations]` or `sts.mcp_issuer`, or a vault lookup that failed | configure both ([MCP `2026-07-28` requests](#mcp-2026-07-28-requests)); for a failed lookup, see the decrypt rows above |
| `2026-07-28`: 403 `-32001` `MCP credential authorization denied` | no `mcp_http.authorization`, no identity slot, a caller token not from `sts.mcp_issuer`, a provider without an HTTPS `resource`, or no grant on a method other than `tools/call`, `prompts/get` and `resources/read` | see [MCP `2026-07-28` requests](#mcp-2026-07-28-requests) |
| `2026-07-28`: 400 `-32021` `Missing required client capability` | the client did not declare `elicitation.url` and has no grant | use a client that declares it, or MCP `2024-11-05` |
| 500 `Failed to inject delegated credential into MCP metadata` | a binding with `inject_as` `{"type":"meta","field":"<f>"}`, and the request body or its `_meta` cannot take the token; the log line of the same text has the reason | send one JSON-RPC object per POST, or inject into a header instead |

## Known issues here

[KI-02](known-issues.md), [KI-03](known-issues.md), [KI-12](known-issues.md),
[KI-13](known-issues.md), [KI-14](known-issues.md), [KI-15](known-issues.md), [KI-16](known-issues.md),
[KI-17](known-issues.md), [KI-18](known-issues.md), [KI-27](known-issues.md).

Sources: [Credentials](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/concepts/credentials/), [A2A protocol](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/concepts/protocols/a2a/), [Secrets concepts](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/concepts/secrets/), [Glossary](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/get-started/glossary/), [Limit surface access by agent identity](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/how-to-guides/access/limit-surface-access-by-agent-identity/), [Configure per-caller Credential Delegation](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/how-to-guides/setup/configure-per-caller-credential-delegation/), [Secrets reference](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/reference/authentication/secrets/); gateway source: `src/proxy/handler.rs`, `src/proxy/credential_delegation.rs`, `src/credential_providers/handlers.rs`, `src/delegation_vault/handlers.rs`, `src/delegation_vault/oauth.rs`, `src/config/types.rs`, `src/certificates/mod.rs`, `src/encryption/key_management.rs`, `src/storage/filesystem.rs`, `src/proxy/credential_delegation/modern.rs`, `src/delegation_vault/modern_consent.rs`; fabric's `src/client.rs`, `src/commands.rs`.
