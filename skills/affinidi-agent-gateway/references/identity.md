# Caller identity and what the upstream may trust

Load this file when the question is who may call a surface, what the upstream learns about the caller, or whether
a surface is actually protected. Rego is in [policies.md](policies.md); the credential the gateway presents to
the upstream is in [credentials.md](credentials.md).

## Contents

[Before you change anything](#before-you-change-anything) · [Caller auth is input, not a gate](#caller-auth-is-input-not-a-gate) ·
[Require an API key](#require-an-api-key) · [JWT bearer](#jwt-bearer) · [Per-client API keys, DID Auth and mTLS](#per-client-api-keys-did-auth-and-mtls) ·
[Closing the direct path](#closing-the-direct-path) · [What the upstream receives, and what it may trust](#what-the-upstream-receives-and-what-it-may-trust) ·
[Presentations the gateway verifies](#presentations-the-gateway-verifies) · [Stable identities](#stable-identities) · [MCP client sign-in](#mcp-client-sign-in) ·
[Identity errors](#identity-errors) · [When it fails](#when-it-fails) · [Known issues here](#known-issues-here)

## Before you change anything

These commands only read. In `before.json`, look at `access_point.caller_authentication`, `mcp_http`,
`target.policy`, `target.auth` and `identity_slots`.

```bash
fabric agent-gateway surfaces get "$SURFACE_ID" -o json > before.json
fabric agent-gateway runtime show networking -o json
fabric agent-gateway api-keys list --agent-id "$SURFACE_ID" -o json
fabric agent-gateway jwt-verification-strategies list -o json
```

`runtime show networking` shows the inbound client-certificate (mTLS) settings, which apply at startup only.
`fabric agent-gateway identities get` and `fabric agent-gateway secrets get` print no private key or secret value,
with or without `--reveal`: the gateway returns neither (`DidWebVhIdentityResponse` in
`src/identity/didwebvh/identity_manager.rs`; secrets: [credentials.md](credentials.md#secrets)).

## Caller auth is input, not a gate

Caller authentication is `access_point.caller_authentication.methods`, a list of methods tagged by `type`:
`api_key`, `api_key_provider`, `jwt_bearer`, `did_auth` or `mtls`. Two facts decide the rest of this file:

- **A missing or invalid credential does not refuse the request.** The gateway records the outcome and goes on:
  the policy input gets `input.source_auth.method == "failed"` with `attempted_method` and `reason`, and the
  request goes on without the stored target credential: no `target.auth` on a direct `http(s)` forward, a
  `proxy://` MCP target, a `fabric://` send or receive, and no Direct Line secret on `a2a-proxy://`. Only
  server-side faults refuse on their own, with a 500: a secret that cannot be loaded, a deleted JWT strategy, a
  JWKS that cannot be fetched. Their problem+json `type` is `about:blank` on MCP and
  `https://a2a-protocol.org/errors/proxy-error` on A2A; [When it fails](#when-it-fails) lists the `detail`.
  Caller authentication also refuses, with a 401, when a `jwt_bearer` method's `audiences` uses
  `{{ surface.agent_did }}` and the surface has no agent DID yet.
- **Only the first method is evaluated**, at request time and at save time. The source comment promises "First
  success wins", but a second method is neither a fallback nor validated. Put exactly one method in the list.

On success `input.source_auth` is tagged by `method`: `jwt_bearer` (`subject`, `claims`), `api_key`
(`key_name`), `did_auth` (`did`) or `mtls` (`principal`, `fingerprint`, `subject_dn`, `issuer_dn`, `sans`).
`subject` exists only for `jwt_bearer`, so a policy that tests `input.source_auth.subject`, as some docs examples
do, denies every other method. With no caller authentication, the key is absent.

So, apart from the server faults and the agent DID 401 above, the 403 `identity-required` on a delegating surface, the 500 of a
`from_jwt_claim` slot and the 422 of an A2A slot that reads a non-default extension
([Identity errors](#identity-errors)), the only ways to refuse a caller are a surface policy that requires
a method and, on an MCP surface, `mcp_http.authorization` ([MCP client sign-in](#mcp-client-sign-in)); the Caller
Context mode changes nothing ([KI-01](known-issues.md)). Public paths skip caller authentication and most policies
(next section).

### Public paths skip caller auth and most policies

On a direct inbound request, the gateway answers `<route>/.well-known/agent-card.json` and
`<route>/.well-known/agent.json` itself, whatever the method, before any caller or policy check, which is what keeps
an A2A card public on a protected surface. Beyond those two, a `GET` or `HEAD` whose path, less one trailing `/`,
ends in `/agent.json`, `/agent-card.json`, `/discovery`, `/.well-known/ucp` or `/.well-known/agent-card` is public.
Any other method on such a path is checked like every other request, and saving a surface whose route ends in one
of them is refused. A public request skips `caller_authentication`, the inbound identity slot in its
`from_jwt_claim`, `from_api_key`, `from_mtls` and `static` modes, the caller-leg Trust Check, the gateway policy,
`inbound_policy` and `target.policy`. When it is forwarded, its path is appended and the `target.auth` credential
is left out: `GET <route>/discovery` reaches `<target endpoint>/discovery` with no caller check. On an MCP surface
the gateway answers two kinds itself and forwards neither: a `GET` that accepts `text/event-stream` gets the
gateway's own notification stream, and a `GET` with `MCP-Protocol-Version: 2026-07-28` gets 405
(`EndpointHttpPolicy::non_post_response` in `src/mcp/modern_http.rs`). The rate limit, both appliance-wide planes,
`mcp_http.authorization` and the 403 `identity-required` of a delegating surface still apply. Serve nothing at
those paths on the upstream that callers may not read without a credential.

## Require an API key

**Confirm with the user:** this makes a key and stores it as a gateway secret, and once the policy is attached,
every caller without the key is refused. Hand the key to the callers first, out of band, never in this chat.

The key lives in a secret whose value is a comma-separated list of valid keys, compared in constant time; on
success `input.source_auth.key_name` is the secret's `secret_id`. The `caller-auth`
feature writes `access_point.caller_authentication`, and `policy` writes `target.policy`.

### Require an API key on an MCP surface

**Before.** Run [Before you change anything](#before-you-change-anything); a non-null `caller_authentication` or
`policy` means you are replacing it. **Change, 1 of 2.** Make a key, store it without printing it, and attach the method. The key stays in the file
`caller-key`, readable only by you.

<!-- e2e-file: caller-auth-mcp caller-auth.json -->
```json
{"methods":[{"type":"api_key","extraction":{"source":"http_header","field":"X-API-Key"},"secret_id":"SECRET_ID"}]}
```

<!-- e2e: caller-auth-mcp -->
```bash
SURFACE_ID="${SURFACE_ID:?set SURFACE_ID}"; KEY_SECRET_ID="${KEY_SECRET_ID:?set KEY_SECRET_ID, e.g. orders-callers}"
umask 077
[ -s caller-key ] || od -An -tx1 -N32 /dev/urandom | tr -d ' \n' > caller-key
fabric agent-gateway secrets create --secret-id "$KEY_SECRET_ID" --name "$KEY_SECRET_ID" --value-stdin < caller-key > /dev/null
jq --arg sid "$KEY_SECRET_ID" '.methods[0].secret_id = $sid' caller-auth.json > caller-auth.final.json
fabric agent-gateway surfaces add-feature "$SURFACE_ID" caller-auth --file caller-auth.final.json > /dev/null
```

**Change, 2 of 2.** Attach a policy that allows only an authenticated API key. `deny_reason` is optional; on MCP
it tells the caller why.

<!-- e2e-file: caller-auth-mcp require-api-key.rego -->
```rego
package surface.policy
default allow = false
allow if {
	input.source_auth.method == "api_key"
}
deny_reason := input.source_auth.reason if {
	input.source_auth.method == "failed"
}
```

<!-- e2e: caller-auth-mcp -->
```bash
SURFACE_ID="${SURFACE_ID:?set SURFACE_ID}"; POLICY_ID="${POLICY_ID:?set POLICY_ID, e.g. require-api-key}"
fabric agent-gateway policies create --id "$POLICY_ID" --name "Require API key" --policy-file require-api-key.rego > /dev/null
fabric agent-gateway surfaces add-feature "$SURFACE_ID" policy --policy-id "$POLICY_ID" > /dev/null
```

**Verify.** No key and a wrong key get HTTP 200 with JSON-RPC `-32001` and the `deny_reason`; the key gets through.

<!-- e2e: caller-auth-mcp -->
```bash
SURFACE_ID="${SURFACE_ID:?set SURFACE_ID}"
fabric agent-gateway surfaces get "$SURFACE_ID" -o json > surface.json
URL="$(jq -r '.access_point.listen_address + .access_point.route' surface.json)"
mcp() { curl -sS "$URL" -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' "$@"; echo; }
CALL='{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"echo","arguments":{"text":"hi"}}}'
echo "no key:";    mcp -d "$CALL"
echo "wrong key:"; mcp -H 'X-API-Key: not-the-key' -d "$CALL"
echo "right key:"; mcp -H "X-API-Key: $(cat caller-key)" -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}'
```

Expect `Tool 'echo' is not allowed by policy: Missing credential: API key not found in request`, then
`... Invalid credential: API key not found or inactive`, then your tool list. Any tool
name works for the first two calls: nothing is forwarded. Other MCP methods are refused with HTTP 403
`Agent trust policy denied the request` and no reason. The upstream never sees
`X-API-Key`: the credential header is stripped, and so is `Authorization` unless a `jwt_bearer` method forwards
it.

**Undo.** Show it, never run it with the change. Detach the policy first, and delete it only once detached
([KI-10](known-issues.md)).

```bash
fabric agent-gateway surfaces remove-feature "$SURFACE_ID" policy
fabric agent-gateway surfaces remove-feature "$SURFACE_ID" caller-auth
fabric agent-gateway policies delete "$POLICY_ID"
fabric agent-gateway secrets delete "$KEY_SECRET_ID"
```

**If it fails.** The right key still denied means the policy tests the wrong value; capture the input
([policies.md](policies.md)). Every call allowed means the policy is not attached; every call denied with
`no policy is loaded for this channel` means it did not compile. Read the
key from an HTTP header: `mcp_meta` and `a2a_extension` never yield a credential.

### Require an API key on an A2A surface

The change is the same, in one block. A missing and a wrong key both get HTTP 403 `{"error":"Forbidden",
"message":"Agent trust policy denied the request"}`; the `deny_reason` goes only to the audit log.

<!-- e2e: caller-auth-a2a -->
```bash
SURFACE_ID="${SURFACE_ID:?set SURFACE_ID}"; KEY_SECRET_ID="${KEY_SECRET_ID:?set KEY_SECRET_ID}"; POLICY_ID="${POLICY_ID:?set POLICY_ID}"
umask 077
[ -s caller-key ] || od -An -tx1 -N32 /dev/urandom | tr -d ' \n' > caller-key
fabric agent-gateway secrets create --secret-id "$KEY_SECRET_ID" --name "$KEY_SECRET_ID" --value-stdin < caller-key > /dev/null
jq -n --arg sid "$KEY_SECRET_ID" '{methods: [{type: "api_key", extraction: {source: "http_header", field: "X-API-Key"}, secret_id: $sid}]}' > caller-auth.json
fabric agent-gateway surfaces add-feature "$SURFACE_ID" caller-auth --file caller-auth.json > /dev/null
printf '%s\n' 'package surface.policy' 'default allow = false' 'allow if {' '	input.source_auth.method == "api_key"' '}' > require-api-key.rego
fabric agent-gateway policies create --id "$POLICY_ID" --name "Require API key" --policy-file require-api-key.rego > /dev/null
fabric agent-gateway surfaces add-feature "$SURFACE_ID" policy --policy-id "$POLICY_ID" > /dev/null
```

<!-- e2e: caller-auth-a2a -->
```bash
SURFACE_ID="${SURFACE_ID:?set SURFACE_ID}"
fabric agent-gateway surfaces get "$SURFACE_ID" -o json > surface.json
URL="$(jq -r '.access_point.listen_address + .access_point.route' surface.json)"
MSG='{"jsonrpc":"2.0","id":1,"method":"message/send","params":{"message":{"kind":"message","role":"user","messageId":"m-1","parts":[{"kind":"text","text":"hello"}]}}}'
a2a() { curl -sS -w ' HTTP %{http_code}\n' "$URL" -H 'Content-Type: application/json' "$@" -d "$MSG"; }
echo "no key:";    a2a
echo "wrong key:"; a2a -H 'X-API-Key: not-the-key'
echo "right key:"; a2a -H "X-API-Key: $(cat caller-key)"
echo "agent card without a key:"; curl -sS -o /dev/null -w 'HTTP %{http_code}\n' "$URL/.well-known/agent-card.json"
```

Expect two 403s, the agent's reply with HTTP 200, and HTTP 200 for the card. Undo as for MCP.

## JWT bearer

Use JWT bearer when each caller has its own identity from an identity provider. Per-user delegation needs it or
per-client keys, because all callers of one `api_key` method share one identity hash ([KI-14](known-issues.md)).

1. `fabric agent-gateway jwt-verification-strategies validate-jwks-uri "$JWKS_URI"` must report `valid: true` and a `key_count`.
2. `fabric agent-gateway jwt-verification-strategies create --file strategy.json` with `{"name", "expected_issuer", "jwks_source":
   {"type": "remote", "jwks_uri"}}` (or `"static"` with `"jwks"` set to the JWKS document's `keys` array, not the whole document); keep the returned `id`.
3. Make `{"type":"jwt_bearer","jwt_verification_strategy_id":"<id>","audiences":["<aud>"]}` the only method.
   `audiences` has no default: send `[]` to skip the `aud` check, never omit it. `token_header` defaults to
   `Authorization`, `token_scheme` to `Bearer` (`""` for a raw token), `forward_header` to false.
4. Attach a policy that allows only `input.source_auth.method == "jwt_bearer"`, as in the API-key recipe.

The token needs an `exp` and an `iss` equal to `expected_issuer` as a string, so `https://login.example.com/` and
`https://login.example.com` are different issuers: copy `iss` from a real token. A token with no `iss` is
reported as an audience error. Accepted algorithms are RS256/384/512, ES256/384 and
EdDSA.

Remote keys are cached per strategy for the JWKS `Cache-Control: max-age`, 24 hours by default, and nothing
evicts them when `jwks_uri` changes. The docs say a change applies on the next request; the skill follows the
source. For a hard cut, create a new strategy and repoint the surfaces. Deleting a
strategy does not check its users; their surfaces answer every bearer request with a 500.

## Per-client API keys, DID Auth and mTLS

**Per-client API keys** (`api_key_provider`) are issued per surface, so one client can be revoked alone.
**Confirm with the user** before `rotate` or `revoke`: the client's current secret stops working at once.
Both prompt, so without a terminal pass `--yes` once the user has agreed:

```bash
fabric agent-gateway api-keys create "$SURFACE_ID" --client-id "$CLIENT_ID" --label env=prod -o json > new-key.json
fabric agent-gateway api-keys rotate "$KEY_ID" --agent-id "$SURFACE_ID" --yes -o json > rotated-key.json
fabric agent-gateway api-keys revoke "$KEY_ID" --agent-id "$SURFACE_ID" --yes
```

`create` and `rotate` each return the secret (`atgs_...`) once: move it to the client and delete `new-key.json` and `rotated-key.json`. The method is
`{"type":"api_key_provider","extraction":{"source":"http_header","field":"X-API-Key"},"agent_id":"<surface-id>"}`.
A success reports `method: "api_key"` with `key_name` set to the `atgk_...` key ID; a failure reports
`attempted_method: "api_key_provider"`. Rotation is in place: the key ID stays and the
old secret stops working. The docs describe revoke-and-reissue; the skill follows the source.
Keys outlive their surface: deleting the surface leaves them listed as `active` under the old `agent_id`
([KI-57](known-issues.md)), so list and delete a surface's keys before deleting the surface.
**Confirm with the user:** each key's client stops authenticating at once.

```bash
fabric agent-gateway api-keys list --agent-id "$SURFACE_ID" -o json | jq -r '.[].key_id' |
  while read -r k; do fabric agent-gateway api-keys delete "$k" --agent-id "$SURFACE_ID" --yes; done
```

**DID Auth.** The caller posts `{"did"}` to `<route>/authenticate/challenge`, signs the challenge as a compact JWS
whose `kid` names a verification method of its DID, posts that to `<route>/authenticate`, and sends the returned
`session_id` in the extraction header. Set `allowed_dids`: empty admits any DID that signs correctly. Challenges
live 300 s (at most 3600), sessions 86400 s. `{{ surface.agent_did }}` is substituted in `jwt_bearer.audiences`
only; in `did_auth.audience` it is compared literally, so every real `aud` fails.

**mTLS.** The API accepts an `mtls` method (pinned or CA `trust`, an `identity_binding`, `allowed_subjects`)
although the dashboard cannot select it. Certificates come from the gateway's own TLS client
check, `[tls.client_auth] direct` in `config.toml` (`optional` or `required`; default `disabled`), which applies
to every listener and trusts every active certificate of `kind` `ca` loaded at startup, or in a forwarded header
from an address in `[tls.client_auth] trusted_proxies`. With `required` and no active CA certificate the gateway
does not start (`Inbound mTLS mode is 'required' but client auth failed to initialise`); with `optional` it starts
without the check. Both are startup settings: check `fabric agent-gateway runtime show networking` first.
Certificate kinds: [credentials.md](credentials.md#certificates). `check_crl` and `require_ocsp` must be false;
neither is implemented, and `surfaces update` refuses either set to true.

## Closing the direct path

A surface is a second door to the upstream. Until the upstream refuses calls that did not come through the
gateway, every policy on the surface can be bypassed. **Confirm with the user:** this change is on the upstream
and the network, not in the gateway, and anything that calls the upstream directly will break.

The gateway's locks are static: `target.auth` with `static_secret`, one header from one secret on
forwarded requests, or an `api_key` credential provider bound with `required_for: "all"`, which injects its stored
secret the same way. The gateway withholds the `target.auth` header from a public discovery read
([Public paths](#public-paths-skip-caller-auth-and-most-policies)) and from a call whose caller credential is
missing or bad, so such a call reaches the upstream with nothing to prove a caller was vetted
(`CallerAssertion::for_request` in `src/proxy/handler.rs`). The gateway has no
client certificate, source address or egress allowlist setting, so those are network work. Set up `target.auth`
with [credentials.md](credentials.md), then:

1. Make the upstream accept a request only when that header has the right value **and appears once** (callers
   can send the same name themselves, see the next section), and answer 401 otherwise, on every path. The calls
   that arrive without the header are then refused like any other unauthenticated call. An A2A surface's agent
   card keeps working: the gateway fetches it from the upstream itself, with the header.
2. Allow the upstream port only from the gateway's egress address.
3. To rotate: upstream accepts old and new, update the secret, call through the surface, drop the old value.

Verify, and report each item to the user: a direct call without the header gets 401; a call through the surface
with a bad caller key is denied; a governed call succeeds; every other route to that upstream is listed
(`fabric agent-gateway surfaces list -o json`, `fabric agent-gateway runtime show surface-routing -o json`, anything outside the gateway).

## What the upstream receives, and what it may trust

The gateway adds `X-Gateway-Trace-Id`, `x-caller-did` and `x-caller-identity-source` to every request it forwards
to an `http(s)` target. One exception: with `access_point.didwebvh_identity.injection_mode`
`protocol_native` on an MCP surface, a POST is rebuilt after the identity goes into `_meta`, and the rebuilt request
loses the `x-caller-*` headers, `X-Transit-Token`, custom-metadata headers and the gateway's `Accept`.
None of them proves anything:

| Header | What it carries |
| --- | --- |
| `X-Gateway-Trace-Id` | the caller's own value when it parses as a UUID, else a fresh one; always a fresh one with `access_point.terminate_trace_id`; correlation only |
| `x-caller-did` | `anonymous`, unless the surface has a `target.policy` or a caller Trust Check; then the DID the caller put in its own request body, never the identity the gateway derived |
| `x-caller-identity-source` | `self-presented` when the gateway resolved a managed identity, else `gateway-computed`; never `verified-presentation` |

The caller's headers are forwarded except hop-by-hop headers, `Host`, `Content-Length`, `X-Transit-Token`,
`Authorization`, the credential header and the headers `access_point.header_metadata_mapping` maps (while its
`strip_mapped_headers` is true, the default). The gateway adds its own after them and
removes none, so a caller-sent `x-caller-did`, `x-caller-identity-source`, `x-gateway-did` or
`X-Gateway-Trace-Id` can reach the upstream next to the gateway's value
([KI-09](known-issues.md)). Trust such a header only once the direct path is closed, and only with exactly one value.
An upstream can verify only a forwarded JWT (`jwt_bearer` with `forward_header: true`) or an injected VP.

See it on your own upstream: send headers a caller could forge, then read what the upstream logged. It gets your
trace ID, your `X-Probe`, and the gateway's `x-caller-did` and `x-caller-identity-source` next to your forged
`x-caller-did` (inference from the source; check which value your framework reads).

<!-- e2e: header-forgery -->
```bash
SURFACE_ID="${SURFACE_ID:?set SURFACE_ID}"
fabric agent-gateway surfaces get "$SURFACE_ID" -o json > surface.json
URL="$(jq -r '.access_point.listen_address + .access_point.route' surface.json)"
curl -sS "$URL" -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -H 'X-Gateway-Trace-Id: 00000000-0000-0000-0000-000000000000' -H 'x-caller-did: did:example:forged' \
  -H 'X-Probe: sent-by-caller' -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

**Identity injection.** With `target.identity_injection.inject_vp` or `identity_slots.inbound` set, and once an
inbound identity resolved, POST requests with a body get `{"verifiablePresentation": "<string>"}` under the
`agent-identity-binding/v1` extension URI: in `message.metadata` for A2A, and in `_meta` for MCP, where a request
at MCP protocol version `2026-07-28`, or any request on a surface whose `mcp_legacy_metadata_output` is
`canonical`, gets the key `io.affinidi.fabric/agent-identity-binding` instead. The string is a
JSON-LD VP, not a JWT; parse it as JSON. The VP proof is signed with the agent (holder)
key and its credential is issued by the gateway's issuer DID, so verify each against its own DID document; the
docs say the issuer key signs the VP; the skill follows the source. Both documents answer without a sign-in at the root of the gateway's public
host, so the upstream must reach it: a managed agent DID ending `:surface:<id>` under `/surface/<id>/`, and the
gateway's issuer DID under `/.well-known/` (`fabric agent-gateway api get /v1/identity/did-document -o json` prints
it). The caller's raw identity descriptor stays in the
request unless an MCP `payload_extraction` slot sets `strip_raw_meta: true`.

**Workload binding** (`target.workload_binding`) adds caller context to that VP. With `caller_source`
`transit_token` or `authorization_bearer_jwt`, the gateway lifts the inbound bearer JWT's claims without checking
its signature and labels them `gateway_attested`; only a policy that requires `jwt_bearer` keeps forged claims
out. Saving it enabled without an identity slot is refused, and `caller_context_fields`
takes top-level claim names only.

**Custom metadata** (`target.custom_metadata`) sends fixed context, never caller identity: `$SECRET:<secret_id>`
strings are resolved per request, and the MCP `headers` target sends `X-Gateway-<key>`.

## Presentations the gateway verifies

The gateway verifies every presentation it is handed: an identity-binding VP in an MCP request's `_meta` or an A2A
message, a presentation that arrives over `fabric://` from a peer gateway ([g2g.md](g2g.md)), and an STS subject
token. The presentation proof must come from a key of its `holder`, and each embedded credential's proof from a
key of that credential's `issuer`. Each credential's subject must be the holder, and it must be inside its
validity dates. A credential with no proof is refused. The presentation's own proof must be unexpired: before its
`expires`, or within 5 minutes of its `created` when it has none, which is also how long a presentation the gateway
issues lasts. A holder or issuer DID that is `did:web` or `did:webvh` on a loopback, private-network or link-local
host resolves only when `allow_private_hosts` is true under `[did_cache]` in `config.toml` (read at startup).
Revocation is not checked: a `credentialStatus` is logged and ignored, so a revoked credential still passes
([KI-54](known-issues.md)). On MCP, a presentation in `_meta` that fails gets 422
`Invalid MCP identity presentation` ([Identity errors](#identity-errors)).

## Stable identities

An identity slot (`identity_slots.inbound`) gives each caller an agent DID. Its `type` is `payload_extraction`,
`from_api_key`, `from_mtls`, `static` or `from_jwt_claim`, and all five work at runtime; the dashboard cannot
select `static` or `from_mtls`, so set those through the API.
`from_jwt_claim` needs `jwt_bearer` and breaks the non-blocking rule: a caller without a valid token gets a 500,
`from_jwt_claim requires jwt_bearer source auth on this surface`, which reads like a config error but is not.

The gateway mints `did:webvh:<SCID>:<domain>:surface:<uuid>` once per identity hash and keeps it in the identity
store, `_storage/identities` by default. The DID changes:

| Mode | Hashed from | Changes when |
| --- | --- | --- |
| `payload_extraction` | SHA-256 of the identity fields | a hashed value changes; without `x-identity` markers every payload field counts |
| `from_jwt_claim`, `from_api_key`, `from_mtls` | HMAC with the identity-hash pepper; a client certificate pre-bound to an identity DID keeps that DID | every restart, unless `AG_IDENTITY_HASH_PEPPER` is set, and the same on every gateway |
| `static` | nothing: the DID is used verbatim | never |

Every hashed mode also changes when the identity store is wiped or not persisted across a redeploy
([KI-15](known-issues.md)). Delegation grants are keyed by the agent DID, or by the surface
when no identity resolved, so a DID change, or a new slot on a surface with grants, makes every user consent
again, and the old grants stay until revoked ([credentials.md](credentials.md)).

List managed DIDs that have usage stats with `fabric agent-gateway api get /v1/agents -o json`; there is no dedicated command, and the response holds
identity fields and last payloads, so keep it out of chat. `fabric agent-gateway identities` manages
did:webvh identities, not caller DIDs.

**STS clients** (`fabric agent-gateway sts-clients`) exchange a subject token for a short-lived gateway token (RFC 8693
token exchange). Tokens last at most 300 s. The endpoints sit under the management API prefix without a sign-in:
`/api/oauth2/token`, the signing keys at `/api/oauth2/jwks.json` and the metadata at
`/api/.well-known/oauth-authorization-server` in the example config.

1. **Confirm with the user:** this stores the client's secret on the gateway. Store it without printing it:
   `fabric agent-gateway secrets create --secret-id "$STS_SECRET_ID" --name "$STS_SECRET_ID" --value-stdin < sts-secret`.
   The whole value is the secret; it is not a list as for API keys.
2. `fabric agent-gateway sts-clients create --file sts-client.json` with `{"client_id", "name", "client_secret_ref"}`,
   where `client_secret_ref` is that `secret_id`. `allowed_audiences`, `allowed_scopes`,
   `allowed_subject_token_types` and `allowed_subject_audiences` restrict the client; left empty they allow any.
   Always set `client_secret_ref`: a client saved without it gets 401 `invalid_client` on every call.
3. The client posts a form to `/api/oauth2/token` with its ID and secret as HTTP Basic credentials (or as
   `client_id` and `client_secret` fields), `grant_type=urn:ietf:params:oauth:grant-type:token-exchange`,
   `subject_token`, `subject_token_type`, and `audience` and `scope` when the client is restricted.
4. A JWT subject token is verified with the JWT verification strategy whose `expected_issuer` equals its `iss`
   ([JWT bearer](#jwt-bearer)); without one the call fails with `invalid_grant`,
   `no verification strategy for issuer <iss>`. A presentation (`urn:affinidi:params:oauth:token-type:vp`) is
   checked as in [Presentations the gateway verifies](#presentations-the-gateway-verifies).

Failed client authentications are throttled in each gateway process: 10 per client ID and 60 per source address
in 60 s, then 429 `temporarily_unavailable` for 300 s. The source address comes only from `X-Forwarded-For` or
`Forwarded`, so with neither header only the per-client limit applies, and a caller can pick its own address:
have the proxy in front of the gateway overwrite both ([KI-55](known-issues.md)). Change the limits under `sts.token_endpoint_throttle` in
`gateway.json`.

## MCP client sign-in

A surface offers an MCP client OAuth only when it sets `mcp_http.authorization`,
`{"resource": "<the surface's public URL>", "scopes": [...]}`, on a gateway with `sts.mcp_issuer` in `gateway.json`
(`{"issuer": "<public origin>/api/oauth2/mcp"}` with the example configuration). A save is refused when the surface
also has caller authentication, or when `resource` is not the surface's listener origin plus route. The gateway
then refuses a call itself unless it carries exactly one bearer token from that issuer whose audience is the
`resource` and whose scopes include every entry of `scopes`: 401 for a missing or invalid token, 403 for a missing
scope, each with a `WWW-Authenticate` header that starts
`Bearer resource_metadata="<origin>/.well-known/oauth-protected-resource<route>"`. Public paths other than the
agent card do not skip this.
The gateway strips the token before forwarding, and policies see `input.source_auth.method == "jwt_bearer"`. The
metadata names the gateway's issuer as the only authorisation server. That issuer grants tokens only by token
exchange or ID-JAG redemption, to an STS client ([Stable identities](#stable-identities)) whose
`allowed_audiences` lists the resource, `allowed_scopes` every scope and `allowed_subject_audiences` the subject
token's audience. It has no browser sign-in, authorisation code, PKCE or dynamic registration, so a client that
signs users in only through a browser cannot use it. A 503 with an empty body means the gateway has no usable
`sts.mcp_issuer` or `resource` does not match the surface ([When it fails](#when-it-fails)).

Without `mcp_http.authorization`, a `WWW-Authenticate` challenge is sent only when caller auth itself blocks with a
401, and a bad credential never blocks. A policy denial is a 403 or `-32001` with no challenge, so it never starts
discovery. A client that starts discovery on any 401, including the delegation 401 ([credentials.md](credentials.md)),
finds dashboard HTML at the well-known paths of a gateway without `sts.mcp_issuer` ([KI-27](known-issues.md)).
Configure such a client with a static API-key header or a bearer token from the user's identity provider.

## Identity errors

An identity slot that cannot resolve answers with problem+json whose `type` is an Affinidi error URI ending in
`/<code>`, not the `https://a2a-protocol.org/errors/proxy-error` of other gateway refusals. The body also carries
`code`, `slot` (`inbound_identity`, `protected_identity` or `external_identity`), `channel` (the surface name)
and `detail`. Branch on `code`, not on `detail`.

| `code` | Status | Cause |
| --- | --- | --- |
| `identity_validation_failed` | 422 | The caller's identity is missing or fails the slot's schema, or the upstream's identity fails it |
| `identity_extension_missing` | 422 | The upstream's response, or its agent card, carries no identity extension |
| `identity_invalid_response` | 422 | The upstream's response is not JSON |
| `identity_did_failed` | 500; 503 when the identity backend is unavailable | The gateway could not mint or find the DID. With `from_jwt_claim`, the call had no valid JWT |

`inbound_identity` fails before the upstream is called. Its `detail` says why:

- `` Inbound identity required: missing `<field>` in MCP `_meta` ``: the slot is `payload_extraction` and the MCP
  request has no `_meta.<field>`.
- `` Inbound identity required: A2A request has no `extensions` array carrying `<uri>` `` or
  `Inbound identity required: extension '<uri>' not present in A2A request`: the A2A message does not declare
  the identity extension.
- `Inbound identity from extension '<uri>' requires configured source authentication to resolve first`: an A2A
  slot that reads an extension URI other than the default runs only after caller auth succeeded, so a caller with
  a missing or bad credential gets this 422.
- `Inbound identity validation failed: <reason>`: the identity is there but fails the schema or its
  `x-identity` fields.

`protected_identity` (`identity_slots.protected`, or `target.identity_injection` when that slot is unset) and
`external_identity` (`identity_slots.external`) are read from the upstream's answer, so the upstream has already
acted when the caller gets the error. Do not retry a call that changes state until you know whether it ran. When
the request already resolved an identity, a response without one reuses it instead of failing. On MCP, error
responses and incomplete results are not checked. On A2A, the protected agent's identity is read from the
status message first, then from the task's `artifacts`, never from `history`, which holds the caller's own
messages.

Other identity refusals use the `proxy-error` type: 403 `MCP identity validation failed: <reason>` when the
identity fails the surface's extension rules, 422 `Invalid MCP identity presentation` when a presentation in
`_meta` fails verification, 422 `from_jwt_claim could not derive identity: <reason>` when the inbound
`from_jwt_claim` slot's claim is missing, and 500 `from_jwt_claim requires jwt_bearer source auth on this surface`.

## When it fails

| Exact text | Cause | Fix |
| --- | --- | --- |
| a call with no or a bad credential succeeds | no policy requires a method | [Require an API key](#require-an-api-key) |
| a policy on `input.source_auth.subject` denies API-key callers | `subject` is `jwt_bearer` only | test `input.source_auth.method` |
| a policy expecting `api_key_provider` always denies | success reports `api_key` | match `"api_key"` |
| `Missing credential: API key not found in request` | no header, or a different header name | send the `extraction.field` header |
| `Invalid credential: API key not found or inactive` | key not in the secret's list (`api_key`) | compare with the key handed out |
| `Invalid credential: API key not found or revoked` | per-client key (`api_key_provider`) unknown, revoked or for another surface | `fabric agent-gateway api-keys list --agent-id <surface-id>` |
| 500 `Internal source auth error: Authentication configuration error` on every call to an API-key surface | the secret cannot be loaded | recreate it under that `secret_id` |
| 500 `Auth config not found: <id>` on every bearer call | the JWT strategy was deleted | repoint the surface to a strategy that exists |
| 500 `Internal source auth error: JWKS fetch failed: ...` or `... Storage error: ...` | the JWKS cannot be fetched, or the strategy cannot be read | run `validate-jwks-uri`; read the log |
| `missing field audiences` on save | `audiences` has no default | send `"audiences": []` |
| an audience error for a token from the right issuer | the token has no `iss` | fix the token |
| `from_jwt_claim requires jwt_bearer source auth on this surface` | no valid JWT on the call | send a valid token |
| upstream sees `x-caller-did: anonymous` | no `target.policy`, Trust Check or body DID | read the injected VP |
| upstream sees two `x-caller-did` values | the caller sent one | single values only; close the direct path |
| `Workload Binding is enabled but the surface has no managed identity source to sign the VP` | no identity slot | add `identity_slots.inbound` |
| every user consents again after a restart | ephemeral pepper | set `AG_IDENTITY_HASH_PEPPER` |
| problem+json with `code` and `slot` fields | an identity slot did not resolve | [Identity errors](#identity-errors) |
| 422 `Invalid MCP identity presentation` | the presentation in `_meta` fails verification: its proof has expired, a proof is not from the holder's or the issuer's key, or a credential has no proof | [Presentations the gateway verifies](#presentations-the-gateway-verifies) |
| 429 `temporarily_unavailable` from `/api/oauth2/token` | too many failed client authentications | wait for `Retry-After`; check `client_secret_ref` |
| 401 or 403 with `WWW-Authenticate: Bearer resource_metadata=...` from an MCP surface | the surface sets `mcp_http.authorization`, and the call has no valid token from the gateway's MCP issuer or lacks a scope | [MCP client sign-in](#mcp-client-sign-in) |
| 503 with an empty body from a surface with `mcp_http.authorization` | the gateway has no `sts.mcp_issuer`, its `issuer` is not a public inbound origin plus `/oauth2/mcp` under the root or `/api` identity route, or `resource` is not the surface's listener origin plus route; on a Transit Point, also `transit.source_auth` ([surfaces.md](surfaces.md#transit-points)) | fix `sts.mcp_issuer` or `resource`; remove `transit.source_auth` |
| save refused: `MCP resource authorization cannot be combined with legacy source_auth` | the surface has `mcp_http.authorization` and `access_point.caller_authentication` | keep one of them |
| save refused: `mcp_http requires an MCP Access Point` | `mcp_http` is set on a surface whose Access Point is not MCP | remove `mcp_http` |
| save refused: `route '<route>' matches an always-public discovery path, so the surface would skip caller authentication and every policy layer on that path. Choose a different route.` | the route ends in a public path ([Public paths](#public-paths-skip-caller-auth-and-most-policies)) | choose another route |
| `reason` `Invalid credential: Key not found for kid: <kid>` | the token's `kid` is in no key of the strategy's JWKS, even after the gateway fetched it again | sign with a key the JWKS publishes, or fix the strategy's `jwks_uri` |
| 401 `Invalid credential: Surface agent DID is not initialized` | `jwt_bearer.audiences` uses `{{ surface.agent_did }}` and the surface has no agent DID yet; every call is refused | give the surface its identity first, or list the audience literally |
| `reason` `Missing credential: Client certificate not presented` | an `mtls` method, and the connection carried no client certificate: `[tls.client_auth] direct` is `disabled`, or the proxy in front forwarded none | [Per-client API keys, DID Auth and mTLS](#per-client-api-keys-did-auth-and-mtls) |
| update refused: `mTLS CA trust has check_crl=true but CRL checking is not yet implemented` (or `require_ocsp=true ... OCSP stapling is not yet implemented`) | neither check exists | set `check_crl` and `require_ocsp` to false |
| 401 `No pending challenge for this DID` (`code` `challenge_mismatch`) from `<route>/authenticate` | no challenge was requested for that DID, it was already used, or it expired and the gateway's five-minute cleanup dropped it | post to `<route>/authenticate/challenge` again and sign the new challenge |
| 401 `Challenge expired` (`code` `expired`) from `<route>/authenticate` | the challenge expired before the cleanup dropped it | request and sign a new challenge |
| 422 with `required JWT claim '<c>' is missing or not a string in the validated token` | the `from_jwt_claim` slot names a claim the caller's valid token lacks; an inbound slot answers with the `proxy-error` type and the `detail` `from_jwt_claim could not derive identity: ...`, a protected or external slot with `code` `identity_validation_failed` | name a claim every token carries as a string, or have the IdP issue it |
| save refused: `header metadata mapping cannot copy sensitive header '<h>'` | `access_point.header_metadata_mapping` names `Authorization`, `Proxy-Authorization`, `Cookie`, `Set-Cookie` or a header whose name contains `token`, `secret`, `credential`, `api-key` or `apikey` | map only non-secret headers |
| 400 `Header Metadata Mapping failed` | an A2A request on a surface with `access_point.header_metadata_mapping` has no message object to carry the extension; the log line of the same text lists the fields | send a well-formed A2A message |
| 500 `MCP identity binding injection failed` | the identity VP could not be added to the MCP body; on A2A the same failure is only logged, `Failed to inject identity binding VP into request`, and the request goes on without it | send one JSON-RPC object per POST; check `_meta` |
| 500 `MCP metadata injection failed` | `target.custom_metadata` cannot be applied: a `$SECRET:` value that does not resolve, a payload that is not an object, or an invalid header; the log line of the same text says which | fix `target.custom_metadata` or create the secret |

## Known issues here

[KI-01](known-issues.md), [KI-09](known-issues.md), [KI-10](known-issues.md), [KI-14](known-issues.md), [KI-15](known-issues.md),
[KI-27](known-issues.md), [KI-54](known-issues.md), [KI-55](known-issues.md), [KI-57](known-issues.md); see
[known-issues.md](known-issues.md).

Sources: [Caller context binding](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/concepts/caller-context-binding/), [Agent identity and DIDs](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/concepts/identity/), [OPA policies](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/concepts/opa-policies/), [Workload binding](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/concepts/workload-binding/), [Create your first surface](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/get-started/create-first-surface/), [Add identity and access control](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/get-started/secure-a-surface/), [Limit surface access by agent identity](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/how-to-guides/access/limit-surface-access-by-agent-identity/), [Restrict surface access with API key authentication](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/how-to-guides/access/restrict-surface-access-with-api-key/), [Configure GW-to-GW authentication and routing](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/how-to-guides/connections/g2g-authentication-and-routing/), [Configure per-caller Credential Delegation](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/how-to-guides/setup/configure-per-caller-credential-delegation/), [API keys](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/reference/authentication/api-keys/), [JWT Verification Strategies](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/reference/authentication/jwt-verification-strategies/), [Caller Context element](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/reference/surfaces/caller-context/), [Identity element](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/reference/surfaces/identity/), [STS Clients](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/reference/authentication/sts-clients/); gateway source: `src/proxy/handler.rs`, `src/jwt_bearer/models.rs`, `src/source_auth/models.rs`, `src/source_auth/middleware.rs`, `src/config/types.rs`, `src/config/agent_surface.rs`, `src/source_auth/errors.rs`, `src/a2a/errors.rs`, `src/proxy/backend_identity.rs`, `src/protocols/extensions.rs`, `src/identity/ssi/verifier.rs`, `src/identity/handlers/credentials.rs`, `src/sts/handlers.rs`, `src/sts/throttle.rs`, `src/sts/admin.rs`, `src/sts/store.rs`, `src/sts/types.rs`, `src/source_auth/peer_cert/direct.rs`, `src/config/proxy.rs`, `src/didauth/handlers.rs`, `src/identity/credential_identity.rs`, `src/config/header_metadata_mapping.rs`, `src/proxy/paths.rs`, `src/identity/handlers/surfaces.rs`, `src/mcp/resource_server.rs`, `src/sts/mcp_profile.rs`, `src/mcp/meta.rs`, `src/config/pepper_cache_config.rs`, `src/gateways/did_cache.rs`, `src/didauth/sessions.rs`, `src/mcp/modern_http.rs`, `src/identity/didwebvh/identity_manager.rs`, `src/a2a_proxies/runtime.rs`; fabric's `src/commands.rs`, `src/features.rs`.
