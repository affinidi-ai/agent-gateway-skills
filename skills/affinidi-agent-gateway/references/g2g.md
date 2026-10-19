# Gateway-to-gateway (G2G)

Load this file when a surface must call a surface on another organisation's gateway, when a
`fabric://` target fails, or to connect a trust registry, register an issuer in one or add a Trust Check.
Everything here is read from the gateway source at the reviewed version and from the docs. No recipe here has
been run against that version, and no end-to-end case covers them.

## Contents

- [What a fabric:// target is](#what-a-fabric-target-is)
- [What the mediator needs](#what-the-mediator-needs)
- [Before you change anything](#before-you-change-anything)
- [Recipes](#recipes)
- [Policies across gateways](#policies-across-gateways)
- [When it fails](#when-it-fails)
- [Known issues here](#known-issues-here)

## What a fabric:// target is

Two gateways talk through a DIDComm mediator after an out-of-band (OOB) handshake:

1. The **inviter** (GW-A) creates a **connection point** for its self gateway record. That yields an
   OOB URL. You supply a secret, and both travel to the other operator out of band.
2. The **acceptor** (GW-B) posts the URL and secret to `connect-via-oob` and gets a remote gateway
   record in `pending`. It needs no mediator record of its own, although the docs say both sides do.
3. GW-A gets a record in `awaiting-approval` and must approve it. Both records then go `active`.

Each side of the handshake sends a signed issuer attestation, a JWT that binds its gateway DID to its
connection point DID, and each side refuses a handshake without a valid one: the inviter answers
`Invalid issuer attestation`, the acceptor fails with `Inviter issuer attestation rejected: ...`. For it to
verify, each gateway must resolve the other's gateway DID document, and their clocks must agree: an
attestation lives 300 s, and one dated more than 60 s ahead is refused. The verified DID is stored on the
remote gateway record as `issuer_did`. Once the gateways are paired, the receiving gateway answers a `fabric://`
request dated more than 120 s ahead of its own clock with 403, and one that expired on the way with 504, both
`Envelope refused: ...`.

A surface reaches a surface on the other gateway with the target endpoint
`fabric://<gateway-id>/<surface-id>`. The first segment is the **remote gateway record ID** on the
calling gateway, not a connection point ID. The Gateways concepts page writes
`fabric://CONNECTION_POINT_ID/...`; the save resolves the segment as a gateway record and refuses a connection
point ID with 400 `Gateway reference is not accessible`. The second is the remote
surface's `config_id` from discovery.

`fabric` covers only the CRUD half. `fabric agent-gateway connections create` writes a bare gateway record with no
handshake, and such a record never carries traffic. The handshake, approval,
ping, discovery and publishing go through `fabric agent-gateway api` ([fabric.md](fabric.md)).

## What the mediator needs

The gateway checks no mediator version; the docs ask for 0.17.x or later. A link lives on one mediator, the
inviter's: GW-A's connection points for it use the mediator the invitation was created on, and GW-B's use the
mediator its `oob_url` names. Each gateway sends its messages straight to that mediator, which delivers them
to the other side's account there. With the experimental `mediator_federation` feature flag on (off by
default), `connect-via-oob` also takes `acceptor_mediator_id`, an active mediator GW-B has registered, for
GW-B's own side of the link; each gateway then sends to the other through its own mediator, which forwards the
message (`docs/PER_GATEWAY_MEDIATOR_FEDERATION.md`). Without the flag that field is refused with 400.

- Both gateways must reach the URLs in the mediator's DID document. The accepting gateway also fetches the
  invitation's `oob_url` under its strictest egress rule, which refuses loopback, private (RFC 1918),
  link-local and IPv6 ULA addresses, and a host name that resolves to one: `connect-via-oob` then fails with
  `OOB URL blocked by egress policy`, so the mediator needs a public address.
- Each gateway resolves the mediator's DID, its own and the other side's connection point DIDs, and the other
  side's gateway DID. For `did:web` and `did:webvh` its resolver refuses a host that is, or resolves to, a
  loopback, private-network, carrier-grade NAT or link-local address, and follows no redirects; `did:web` also
  refuses `localhost`, `*.localhost` and `*.local` by name, and `did:webvh` also `*.internal`, `home.arpa` and
  single-label names. A mediator's stored `did_document` stands in only until the resolver's cache expires
  (300 s). When the mediator or the gateways live on such hosts, as on one machine, set
  `allow_private_hosts = true` under `[did_cache]` in each gateway's `config.toml` and restart. It also lets
  these fetches reach cloud metadata addresses, so keep it off wherever one is reachable.
- The inviter's mediator must publish its DID document on the same origin as the `oob_url`:
  `connect-via-oob` tries `/.well-known/did.jsonl` and `/.well-known/did.json`, then `did.jsonl` and
  `did.json` under the URL's path, and fails with 400 `Failed to fetch inviter's mediator DID from URL` when
  none answers. A `did:web` or `did:webvh` mediator publishes one; a `did:peer` mediator does not, so it
  cannot carry an invitation (inference: the mediator's side is not gateway source).
- A gateway deletes a message from the mediator only after processing it, so every `fabric://` request in
  flight stays queued there until it is answered. The mediator caps the messages one sender may have queued
  for one recipient at `[limits] queued_send_messages_per_peer`, 50 by default, and refuses one over the cap
  with `e.p.limits.queue.peer`; the caller then gets 504. Set the cap above the concurrent requests you expect
  between the two gateways and below the mediator's `queued_receive_messages_soft`, 200 by default (from the
  gateway's `docs/FABRIC.md`; the mediator's side is not gateway source).

## Before you change anything

```bash
fabric agent-gateway connections list -o json \
  | jq '[.[] | {id, name, did, gateway_type, status, issuer_did, issuer_did_source, trusted_issuer_dids}]'
fabric agent-gateway connection-points list -o json | jq '[.[] | {id, gateway_id, mediator_id, expires_at, runtime_status}]'
fabric agent-gateway mediators list -o json | jq '[.[] | {id, name, did, status}]'
```

- A remote gateway's `status` is derived from live listeners on every read, so poll it rather than
  trusting a write.
- `issuer_did`, `issuer_did_source` (`handshake` or `exchange`) and `trusted_issuer_dids` are left out of a
  record when unset, so they print as `null`. An active remote record with no `issuer_did` and no trusted issuers, whose peer cannot prove its issuer
  DID, has its incoming `fabric://` requests refused.
- Never print `connection-points get` output in full: it carries the connection secret. Select fields.

## Recipes

### Connect two gateways

**Confirm with the user:** the peer operator gets a secret that lets its gateway connect; once
approved, it can call every active surface you have until you limit it
([Limit what a peer can reach](#limit-what-a-peer-can-reach)).

**Before (GW-A).** A mediator answers a trust-ping; find the self gateway ID.

```bash
MEDIATOR_ID="$(fabric agent-gateway mediators list -o json | jq -r '.[0].id // empty')"
fabric agent-gateway api post "/v1/mediators/$MEDIATOR_ID/trust-ping" -o json
SELF_ID="$(fabric agent-gateway connections list -o json | jq -r '.[] | select(.gateway_type == "self") | .id')"
```

When `MEDIATOR_ID` is empty, register the mediator first, with the DID its operator gives you. The gateway
stores the DID and makes its own `did:peer` and keys for the link. Without `did_document` it later derives the
mediator's https URL from a `did:web` or `did:webvh` DID; for any other method, or a mediator not on https, pass
the mediator's DID document as `did_document`; it does not lift the DID host rules in
[What the mediator needs](#what-the-mediator-needs). A wrong DID is accepted here and fails only at the
trust-ping, so run the trust-ping above again afterwards:

```bash
jq -n --arg d "$MEDIATOR_DID" '{name: "Mediator", description: "", did: $d}' > mediator.json
```

To pass the document, build `mediator.json` with it instead. `MEDIATOR_URL` is the mediator's origin, such as
`https://mediator.example.com`. A `did:webvh` mediator's document is the `state` of the last line of its DID
log; for a `did:web` mediator, fetch `$MEDIATOR_URL/.well-known/did.json` and leave out the `tail` and `jq`:

```bash
curl -sSf "$MEDIATOR_URL/.well-known/did.jsonl" | tail -n 1 | jq '.state' > mediator-doc.json
jq -n --arg d "$MEDIATOR_DID" --slurpfile doc mediator-doc.json \
  '{name: "Mediator", description: "", did: $d, did_document: $doc[0]}' > mediator.json
```

Whichever `mediator.json` you built, create the mediator and keep its ID:

```bash
MEDIATOR_ID="$(fabric agent-gateway mediators create --file mediator.json -o json | jq -r .id)"
fabric agent-gateway mediators get "$MEDIATOR_ID" -o json | jq '{id, did, status}'
```

**Change (GW-A).** Create the invitation. Always use `-o json`: in table mode the command prints only
`Created connection point '<id>'`, without the `oob_url` you need. The create
response carries the secret, so keep only the fields you need, and keep the secret off the command
line by passing it to jq through the environment:

```bash
umask 077
export SECRET="$(od -An -tx1 -N32 /dev/urandom | tr -d ' \n')"
jq -n --arg g "$SELF_ID" --arg m "$MEDIATOR_ID" \
  '{gateway_id: $g, mediator_id: $m, name: "Link to partner", description: "", secret: env.SECRET}' > cp.json
fabric agent-gateway connection-points create --file cp.json -o json | jq '.connection_point | {id, oob_url, expires_at}' > cp-out.json
rm -f cp.json
cat cp-out.json
```

`did_method` in `cp.json` picks the connection point's DID: `web` when left out, `webvh` or `peer`. With `web`
or `webvh`, the mediator and the other gateway fetch each connection point's DID document over HTTPS from the
gateway that made it, so each must reach that gateway at a public address and trust its certificate
([What the mediator needs](#what-the-mediator-needs)); when the mediator cannot, `create` fails with
`Failed to add profile to ATM`. A `did:peer` needs no fetch. When the gateways are not reachable over HTTPS at
a public address with a publicly trusted certificate, add `did_method: "peer"` to `cp.json` here and to
`accept.json` below.

The invitation pairs one gateway. Its connection point accepts one `connection-setup`, and only when the
setup names this invitation; once one succeeds, every later setup on it is refused, even if you reject the
request, so create a new invitation to pair again. The new peer reaches none of this gateway's surfaces until
you expose some ([Limit what a peer can reach](#limit-what-a-peer-can-reach)).

Pass `oob_url` and the secret to GW-B's operator over a channel you trust. Then on **GW-B**, with the
secret exported as `SECRET`:

```bash
umask 077
jq -n --arg u "$OOB_URL" '{oob_url: $u, secret: env.SECRET, name: "Partner gateway", description: ""}' > accept.json
fabric agent-gateway api post /v1/gateways/connect-via-oob --file accept.json -o json | jq '.gateway | {id, status}'
rm -f accept.json
```

Back on **GW-A**, approve the new `awaiting-approval` record within GW-B's pending window,
`[oob_connection] pending_expiry_hours` in GW-B's `config.toml`, one hour by default. Once the window has
passed, GW-B deletes its listener for the approval the next time its listeners start, such as on a restart,
and the approval then cannot reach it. An `oob_connection` block in `gateway.json` is ignored.

```bash
fabric agent-gateway connections list -o json | jq '[.[] | select(.status == "awaiting-approval") | {id, name, did}]'
fabric agent-gateway api post "/v1/gateways/$PEER_ID/approve" --data '{"name":"Partner gateway","description":"Partner"}'
```

**Verify on both sides.** `status` reads `active` and a ping round-trips.

```bash
fabric agent-gateway connections get "$PEER_ID" -o json | jq '{status}'
fabric agent-gateway api post "/v1/gateways/$PEER_ID/ping" -o json | jq '{success, round_trip_ms}'
```

**Undo.** **Confirm with the user:** it cuts the link at once, and on each side it deletes the
record's system-created connection points. Run
`fabric agent-gateway connections delete <peer-id>` on each side, then `fabric agent-gateway connection-points delete <cp-id>` on
GW-A.

**If it fails.** GW-B `pending` with no request on GW-A means GW-A refused the handshake. GW-B records no
reason: its record stays `pending` with an empty `description` ([KI-56](known-issues.md)). When the secrets
differ or GW-B's attestation did not verify, GW-A's log shows
`Failed to process connection-setup as inviter: <reason>`, such as `Invalid connection secret`, and GW-B's log
shows `Connection rejected by inviter: <reason>`. When GW-A cannot use the invitation, it answers nothing and
logs `connection-setup on connection point <cp-id> refused: <reason>`, such as `invitation has expired`,
`connection point is disabled` or `invitation has already been used` (create a new invitation); when GW-A
cannot confirm that GW-B controls its connection point DID, it logs
`connection-setup from <did> refused: control of channel_did <did> not proven: <reason>`.
Other errors: [When it fails](#when-it-fails).

### Route a surface to a remote surface

**Confirm with the user:** this surface's callers will be served through the peer's gateway, and its
policies apply; when the route sets `fabric_delegated_credentials`, the peer also receives callers' delegated
access tokens ([Policies across gateways](#policies-across-gateways)). **Before.** List what the peer publishes, pick
a `config_id`. The list is what this gateway stored at the last discovery, for up to 5 minutes;
`force_refresh=true` asks the peer again.

```bash
fabric agent-gateway api get "/v1/gateways/$PEER_ID/surfaces?force_refresh=true" -o json | jq '[.channels[] | {config_id, name}]'
fabric agent-gateway surfaces get "$SURFACE_ID" -o json > before.json
```

**Change.** Set `target.endpoint`. The save refuses a first segment that is not a gateway record your token
may use with 400 `Gateway reference is not accessible`.
For a new surface, pass the same URL to `surfaces create --target-endpoint` instead.

```bash
fabric agent-gateway surfaces update "$SURFACE_ID" --set target.endpoint="fabric://$PEER_ID/$REMOTE_SURFACE_ID"
```

**Verify.** Send one request through the local surface and read the status. A `2024-11-05` MCP answer with a
complete `result` carries the responding gateway's DID in `result._meta.x-affinidi-fabric-gateway-did`
([Policies across gateways](#policies-across-gateways)); a `2026-07-28` answer carries none. With audit on and
`policy_decision` selected, `fabric agent-gateway audit list --flow fabric --limit 5 -o json`, field-selected as in
[triage.md](triage.md#reading-audit-rows), shows the decisions on this path ([operations.md](operations.md)).
**Undo.** **Confirm with the user:** this replaces the surface with the saved copy.
`fabric agent-gateway surfaces update <surface-id> --file before.json`. **If it fails.** 503, 400, 500 and 504
each have a row in [When it fails](#when-it-fails).

### Limit what a peer can reach

Run this on the exposing gateway, against the **peer's** record. Its `exposure_mode` decides what the peer
reaches: `none`, which every new pairing starts with, reaches no surface; `list` reaches only the surface IDs in
`exposed_channels`; `all` reaches every active surface. The tenant rule applies on top of each mode
(`Gateway::exposes_surface` in `src/gateways/types.rs`). The peer's discovery lists only what it may reach, and
this gateway refuses the rest: 403 `Channel is not exposed to sender`, or, on a `2026-07-28` MCP stream, a
refused stream that the peer's caller sees as 502 `Modern Fabric transport is unavailable`. Narrowing a peer's
access also ends its running streams that the new setting does not allow (`Revocation` in
`src/proxy/fabric_stream/mod.rs`). The request is refused with 400 `Exposure applies only to remote gateways` for
any record that is not a remote gateway.

**Before.** Save what the record holds.

```bash
fabric agent-gateway connections get "$PEER_ID" -o json | jq '{exposure_mode, exposed_channels}' > before.json
```

**Change.** **Confirm with the user:** the peer's callers can then reach only the surfaces listed.

```bash
fabric agent-gateway api put "/v1/gateways/$PEER_ID/exposed-surfaces" \
  --data '{"exposure_mode":"list","exposed_channels":["<surface-id>"]}'
```

`{"exposure_mode":"all"}` exposes every active surface and `{"exposure_mode":"none"}` none. A body without
`exposure_mode` means `list` when the list has entries and `none` when it is empty. The docs' gateway
reference says an empty list exposes every surface; on the reviewed gateway it exposes none.

**Verify from the peer.** `/v1/gateways/<id>/surfaces?force_refresh=true` lists only that surface; without
`force_refresh` the peer still shows what it stored before. A `fabric://` request to another surface is refused.

**Undo.** **Confirm with the user:** the peer can discover and call every surface in `before.json` again.
`fabric agent-gateway api put /v1/gateways/<peer-id>/exposed-surfaces --file before.json`.

**If it fails.** 400 `Surface reference is not accessible` means a listed ID is not a surface on this gateway,
or is one that the peer's record or your token may not use; take the IDs from `fabric agent-gateway surfaces list`.

### Recover a failed connection point

**Before.** Read the `error_code` and fix its cause.

```bash
fabric agent-gateway connection-points get "$CP_ID" -o json | jq '.runtime_status | {status, error_code, error_message}'
```

**Change.** Retry at once instead of waiting: retries back off from 30 seconds, doubling up to 30 minutes
(`[reconnect_policy]` in `config.toml`, [operations.md](operations.md#configuration-files)).

```bash
fabric agent-gateway api post "/v1/connection-points/$CP_ID/reconnect"
```

**Verify.** `runtime_status.status` reads `connected`; it reads `reconnecting` right after the call and between
retries, while the remote gateway record's derived `status` can read `failed`.

**Undo.** Nothing to undo: the call only resets the back-off and restarts the listener.

**If it fails.** `runtime_status` keeps an `error_code` while the cause remains: read it again and look it up in
[When it fails](#when-it-fails).

### Connect a trust registry

Needs `administrator`. The registry administrator gives you its OOB URL, which must be public http or https.
`did_method` picks the DID this gateway makes for the link: `web` (the default), `webvh` or `peer`. With `web`,
the registry's mediator fetches `https://<did domain>/trust-registries/<tr-id>/did.json`, where `<did domain>` is
the gateway's configured `did.domain`, so the gateway must serve that over HTTPS with a certificate the mediator
trusts; otherwise use `peer`.

**Before.** `fabric agent-gateway trust-registries list -o json | jq '[.[] | {id, name, connection_status}]'`.

**Change.**

```bash
jq -n --arg u "$TR_OOB_URL" '{name: "Registry", description: "", oob_url: $u, did_method: "peer"}' > tr.json
TR_ID="$(fabric agent-gateway trust-registries create --file tr.json -o json | jq -r .id)"
fabric agent-gateway trust-registries get "$TR_ID" -o json | jq '{id, connection_status, our_did, main_did}'
```

Give the registry administrator `our_did`, the DID this gateway uses on the link, and ask for two things:
approval of the connection, and a grant for that DID. A registry that approves a link gives the new DID a
deny-all policy of its own, and a deny outweighs every allow, so ask for that policy to be changed to allow
`read`, `list` and `query`, plus `create` and `delete` if you register issuers there. Until then every call fails with
`e.p.msg.unauthorized` (inference: this is how the Affinidi trust registry treats a new link; another
registry may differ).

**Verify.** Poll `trust-registries get <tr-id>` until `connection_status` is `connected` (this enum spells
`awaiting_approval` with an underscore), then
`fabric agent-gateway api post /v1/trust-registries/<tr-id>/list-records -o json | jq '{round_trip_ms}'`
returns a number.

**Undo.** **Confirm with the user:** every Trust Check that names this registry then fails on each request.
`fabric agent-gateway trust-registries delete "$TR_ID"`, and ask the registry administrator to remove the link
and its policy.

**If it fails.** A failed `create` answers 502 `OOB connection failed: ...` and keeps the record with
`connection_status` `failed`; delete it before trying again. The rows under [When it fails](#when-it-fails)
name each message.

### Register an issuer in a trust registry

`trust_registry_did` is the registry's DID (`main_did` on the record), not its record ID. `authority_did` is the DID of the
organisation that vouches for this issuer in that registry; the registry administrator says which one it
expects. Pass both or neither. If you keep that DID as an authority record,
`fabric agent-gateway authorities list -o json | jq '[.[] | {name, did}]'` lists it.

**Before.** The registry is `connected` and its grant includes `create`
([Connect a trust registry](#connect-a-trust-registry)).

**Change.**

```bash
TR_DID="$(fabric agent-gateway trust-registries get "$TR_ID" -o json | jq -r '.main_did // .registry_did')"
jq -n --arg t "$TR_DID" --arg a "$AUTHORITY_DID" \
  '{name: "Sales", description: "Sales agents", trust_registry_did: $t, authority_did: $a}' > issuer.json
fabric agent-gateway issuers create --file issuer.json -o json | jq '{id, did, tr_registered}'
```

The gateway writes two records for the issuer's `did` under `authority_did`: `is` / `registeredDepartment` and
`register` / `agents`. `registeredDepartment` is the default; `[trust_registry] q3_resource_name` in `config.toml`
changes it. In the background the gateway also publishes the issuer's `name` and `description`, and those of the
authority record whose `did` is `authority_did` when there is one, to the registry as reference fields
(`issuer_reference_values` in `src/trust_registries/reference_fields.rs`); a failure there, which a grant that
does not cover these writes may cause (inference: the registry's policy decides), only logs
`Reference field create failed; will retry on the next trigger`.

**Verify.** `tr_registered` is `true`, and `list-records` shows both records.

**Undo.** **Confirm with the user:** the registry then stops recognising the issuer for everyone who asks.
`fabric agent-gateway issuers delete <issuer-id>` also deletes both records from the registry, but only logs
`Failed to deregister issuer from trust registry (non-fatal)` when that fails, so check `list-records` afterwards
and ask the registry administrator to remove any record left.

**If it fails.** `tr_registered` is `false` when the registry refused the write or did not answer; the issuer
itself is kept, and the gateway logs `Failed to register issuer in trust registry (non-fatal)`. Fix the link or
its grant, then `fabric agent-gateway api post /v1/issuers/<issuer-id>/register-trust-registry` and read the
issuer again.

### Add a Trust Check and act on it

A Trust Check only records evidence for policy input; it never blocks by itself. The block comes from a
surface policy that reads the result. `fabric agent-gateway api get /v1/trust-check/predefined-queries -o json`
lists the built-in queries the dashboard offers (is the agent recognised by its provider, is the provider
authorised and recognised by its authority); start from one of those rather than writing the query by hand.

**Before.** Save the surface (`surfaces get <surface-id> -o json > before.json`) and check the registry is
`connected`.

**Change.** **Confirm with the user:** callers the check fails for are refused once the policy is attached.
An element names the registry by its record ID and asks it one TRQP question. `query_type` is `recognition` or
`authorization`. The query fields may hold `{{path}}` placeholders resolved from the request, such as
`{{ input.agent.did }}` in the predefined queries; with literal values, as below, every caller gets the same
answer. `resource` must match what the registering gateway wrote. Save the element as `tc.json`:

```json
{
  "id": "issuer-recognised",
  "name": "Issuer recognised",
  "trust_registry_id": "<tr-id>",
  "query_type": "recognition",
  "query": {"authority_id": "<authority did>", "entity_id": "<entity did>", "action": "is", "resource": "registeredDepartment"},
  "timeout_secs": 3
}
```

```bash
fabric agent-gateway surfaces add-feature "$SURFACE_ID" trust-check --file tc.json -o json \
  | jq '[.access_point.trust_check_list[].id]'
```

Elements on `access_point.trust_check_list` land in `input.trust_check_results.caller`, and those on
`target.trust_check_list`, which `add-feature trust-check --edge ma-tp` appends to, in
`input.trust_check_results.target`. Each entry carries
`id`, `name`, `ok`, `query_resolved`, the resolved query fields and `error`, which is `null` or
`{code, message}`. Then attach a surface policy that refuses the request unless every check passed
([policies.md](policies.md)):

```rego
package surface.policy

default allow := false

failed contains r.id if {
	some r in input.trust_check_results.caller
	not r.ok
}

allow if {
	count(input.trust_check_results.caller) > 0
	count(failed) == 0
}

deny_reason := sprintf("trust check failed: %v", [concat(", ", sort(failed))]) if not allow
```

Requiring at least one result makes the policy refuse, rather than allow, when no check ran.

**Verify.** With an `entity_id` the registry recognises, calls go through; with one it does not know, they are
refused: an MCP `tools/call` with JSON-RPC `-32001` `Tool '<t>' is not allowed by policy: trust check failed: <id>`,
any other request with 403 `Agent trust policy denied the request`, which leaves the reason out; with audit
on and `policy_decision` selected, the audit record carries it ([operations.md](operations.md)).
With a placeholder, the answer follows the caller.

**Undo.** **Confirm with the user:** this replaces the whole surface with the saved copy.
`fabric agent-gateway surfaces update "$SURFACE_ID" --file before.json`.

**If it fails.** `error.code` says why a check is not `ok`:

| `error.code` | meaning |
| --- | --- |
| `NOT_RECOGNIZED` | The registry has no matching record (`Registry returned empty response body — no matching trust record`) |
| `NOT_AUTHORIZED` | An `authorization` query was answered no |
| `QUERY_FAILED` | No answer: without `timeout_secs` the request waits 10 s, then `No response within 10s for thread <id>` |
| `QUERY_TIMEOUT` | No answer within the element's `timeout_secs` (`exceeded <n>s budget`) |
| `TRUST_REGISTRY_PROBLEM_REPORT` | The registry answered with a problem report, such as `e.p.msg.unauthorized` from a missing grant (inference) |
| `TEMPLATE_RESOLUTION_FAILED` | A `{{path}}` did not resolve against the request; nothing was sent |
| `TRUST_REGISTRY_UNREACHABLE` | No usable link to the registry: unknown record, no connection, or a stale one |
| `TRUST_REGISTRY_PARSE_ERROR` | The registry answered in a shape the gateway could not read |
| `AGENT_CARD_UNAVAILABLE` | Target leg only: the target's agent card could not be fetched; nothing was sent |
| `IDENTITY_VP_VERIFICATION_FAILED`, `TARGET_AGENT_IDENTITY_UNAVAILABLE` | Target leg only: the target's agent card carries an identity presentation that does not verify, or none; nothing was sent |
| `TRUST_REGISTRY_METADATA_UNAVAILABLE` | A placeholder names a field the request leaves empty: on the caller leg `input.agent.did`, `provider_did`, `trust_registry_did` or `authority_did`, which come from the caller's identity credential and trust registry extension; on the target leg `provider_did` or `trust_registry_did` from the target's agent card. `error.message` says what is missing; nothing was sent |

A registry that is down delays every request on the surface by the wait, at least 10 s unless `timeout_secs` is
set, and with the policy above refuses them all: when the link to the registry's mediator has dropped, the
gateway reconnects once before the 10 s wait, which adds to it (`send_with_reconnect` in `src/trust_registries/communication.rs`).
`timeout_secs` caps the whole wait. The elements run in parallel, so the wait is the longest one, not the sum.
The save itself fails with 400 `Trust Registry reference is not accessible` when `trust_registry_id` is not a
registry this token may use, with `caller trust_check_list contains duplicate element id '<id>'` when the
`id` is already on the list, and with `caller trust_check_list has <n> elements (max 10)` past ten elements
on a leg. A variant that sets its own list replaces the surface's list whole.

### Manage a connection's issuers

The receiving gateway admits a `fabric://` request only from a paired peer, and attributes an identity
presentation on it to that peer only when the presentation's issuer is one of the connection's issuers: the
attested `issuer_did`, or a DID in `trusted_issuer_dids`. Run these on the receiving gateway, against the
**peer's** record; none has a typed command.

**Before.** Save what the record holds now.

```bash
fabric agent-gateway connections get "$PEER_ID" -o json \
  | jq '{status, issuer_did, issuer_did_source, trusted_issuer_dids}' > issuers-before.json
cat issuers-before.json
```

**Change.** Whichever applies:

- No `issuer_did` (you cleared it, as in **Undo** below): run the issuer exchange now
  rather than on the next `fabric://` request. It answers `{gateway_id, issuer_did}`.

  ```bash
  fabric agent-gateway api post "/v1/gateways/$PEER_ID/issuer" -o json
  ```

- The peer's identity presentations come from an issuer other than its gateway DID, or its issuer DID cannot be
  proven because the exchange fails.
  **Confirm with the user:** identities that DID issues are then attributed to this peer, and the peer's
  requests are admitted even when its own issuer DID cannot be proven. Take the DID from the peer's
  operator: `fabric agent-gateway api get /v1/identity/did-document -o json | jq -r .id` on their gateway
  prints its gateway DID.

  ```bash
  jq -n --arg d "$ISSUER_DID" '{issuer_did: $d}' > trusted-issuer.json
  fabric agent-gateway api post "/v1/gateways/$PEER_ID/trusted-issuers" --file trusted-issuer.json -o json
  ```

**Verify.** Read the record again. After the exchange on a record with no `issuer_did`, `issuer_did_source` is
`exchange`; a record that already holds its handshake DID answers with that DID and keeps `handshake`. After trusting,
`trusted_issuer_dids` lists the DID. Then have the peer send one `fabric://` request. While the peer cannot
answer the exchange, each of its requests waits up to 10 s for it before the trusted DID admits it
(`ensure_peer_issuer_did` in `src/gateways/connection_points/ws_listener.rs` keeps no record of a failed exchange).

**Undo.** **Confirm with the user:** identities that DID issues stop being attributed to this peer.
`fabric agent-gateway api delete "/v1/gateways/$PEER_ID/trusted-issuers/$ISSUER_DID"` removes
a trusted DID. `fabric agent-gateway api delete "/v1/gateways/$PEER_ID/issuer"` forgets the attested DID
and keeps the trusted ones; the gateway runs the exchange again on the peer's next `fabric://` request or
when the listener starts.

**If it fails.** `POST .../issuer` answers 400 `Issuer DID can only be requested for remote gateways` on
the self record, 404 `Gateway not found`, 503 when no listener carries the pairing, 504 when the peer does
not answer within 10 s, and 502 when its attestation does not verify or names another gateway.
`trusted-issuers` answers 400 `issuer_did must be a DID, got "<value>"` unless the value starts with
`did:`, 400 `Issuer DIDs apply to remote gateway connections only` on the self record, and the delete
answers 404 `<did> is not a trusted issuer of this gateway`. All of them need `gateways.edit`, and a
connection update cannot set `issuer_did` directly.

Issuer trust belongs to the connection, never to a surface or the whole gateway, so a peer cannot pass on a
presentation another gateway issued.

## Policies across gateways

| Where | What runs | `input.gateway` |
| --- | --- | --- |
| Calling gateway, `fabric://` send | The surface's target policy, only if an engine is compiled ([KI-11](known-issues.md)) | `direction: "outbound"`, `target_id` = the `did` of the remote record on this gateway |
| Receiving gateway | Appliance-wide gateway policy, then the **self** gateway policy, then the appliance-wide surface policy and the target surface's policy; a surface with OPA on and no compiled policy denies | `direction: "inbound"`, `source_id` = the `did` of the sender's record on this gateway |
| A remote gateway record's policy | Stored and never evaluated ([KI-22](known-issues.md)) | none |

- `target_id` and `source_id` are the `did` on the peer's record once it is `active`: the DID of the connection
  point the peer created for this link during the handshake, not the invitation's connection point, and not its gateway
  DID (`issuer_did`). While the record is `pending` the field holds a temporary DID, so read it only after approval:
  `fabric agent-gateway connections get <peer-id> -o json | jq -r .did`.
- A direct caller of the surface's own listener has no `source_id`; only `direction` is set.
- To stop one peer calling a surface, leave the surface out of that peer's exposed surfaces
  ([Limit what a peer can reach](#limit-what-a-peer-can-reach)): in `list` mode the receiving gateway refuses
  every surface not listed, and in `none` mode every surface, with 403 `Channel is not exposed to sender`. A deny on
  `input.gateway.source_id` in the receiving gateway's self gateway policy or that surface's policy also works;
  confirm the surface policy compiled. To serve only one peer on a surface, attach a surface policy such as this
  one, with the peer's `did` in place of the placeholder:

  ```rego
  package surface.policy

  default allow := false

  allow if {
  	input.gateway.direction == "inbound"
  	input.gateway.source_id == "<did of the peer's record>"
  }

  deny_reason := "this surface serves only the paired gateway" if not allow
  ```

  A direct call to that surface must then be refused (an MCP `tools/call` with JSON-RPC `-32001` carrying the
  policy's `deny_reason`, any other request with 403 `Agent trust policy denied the request`), which shows the
  policy compiled and so also runs on requests from the peer (inference). A peer's request that the receiving
  gateway's surface policy denies gets HTTP 200 with JSON-RPC `-32001`
  `Tool '<t>' is not allowed by policy: <reason>` on an MCP `tools/call`, and otherwise 403
  `Agent trust policy denied the request: <reason>`. When that policy did not compile or fails to evaluate, the
  same answers carry no reason. A surface-policy deny on the calling side is 403
  `Agent trust policy denied the request`.
- To a `2024-11-05` MCP answer with a complete `result`, or an A2A answer, the receiving gateway adds its own
  gateway DID as `x-affinidi-fabric-gateway-did`, for MCP as a string in `result._meta`. When the sending surface
  has an identity slot or `target.identity_injection` other than `static` ([identity.md](identity.md)), the
  calling gateway also adds its gateway DID to the request's MCP `params._meta` or A2A `message.metadata`, as a
  one-element array, and turns the answer's MCP field into an array with its own DID appended
  (`handle_fabric_request` in `src/proxy/handler.rs`); so read that field as a string or an array. A
  `2026-07-28` MCP answer, which crosses as a framed stream, carries neither.
- For MCP and A2A alike, the receiving gateway accepts an identity presentation only when it verifies and
  its issuer is one of the sending connection's issuers
  ([Manage a connection's issuers](#manage-a-connections-issuers)). On MCP any other presentation gets 422
  `Invalid MCP identity presentation`. On A2A the request goes on with the identity unverified and no
  `input.identity_binding`, so a policy that relies on the caller's identity must deny when
  `input.identity_binding` is absent.
- On the direct path, where the caller is not a paired gateway, anyone can send
  `x-affinidi-fabric-gateway-did`, so the gateway does not use it as an anchor: a binding presentation's
  issuer is only reported, as `input.identity_binding.issuer_gateway`. Require the issuer you expect in
  the surface policy.
- Per-tool MCP policies run twice: on the calling gateway before the `fabric://` send, and on the receiving
  gateway for its target surface. On the receiving side `input.jwt` is decoded from the forwarded
  `Authorization` header without any check, so do not grant on it ([KI-47](known-issues.md)).
- A surface's `outbound_credentials` reach a `fabric://` peer only when that route sets
  `fabric_delegated_credentials: true`: `target.fabric_delegated_credentials` for Access Point traffic,
  `transit.points[].fabric_delegated_credentials` for agent-initiated traffic. It is off by default, so with it
  off the peer gets no delegated credential. On the Target only `2026-07-28` MCP requests carry the access token;
  on a Transit Point every protocol does. The refresh token never leaves, and the peer and its upstream can use
  the access token until it expires, so turn the switch on only for peers you would trust with your users'
  tokens. A Transit Point sends only the surface's `outbound_credentials` or its own `transit_credentials`, never
  another Transit Point's (`Target` and `TransitPoint` in `src/config/agent_surface.rs`, `docs/FABRIC.md`).

## When it fails

| Exact text | Cause | Fix |
| --- | --- | --- |
| 503 "Gateway not connected" | No listener for that ID: record made with `connections create`, handshake unfinished, or its connection point deleted | Run [Connect two gateways](#connect-two-gateways) |
| 400 "Gateway reference is not accessible" on the surface save | First `fabric://` segment is not a gateway record your token may use, such as a connection point ID | Use the remote gateway record ID |
| 500 "Gateway DID not found" | A stored surface's first `fabric://` segment is a connection point ID (inference: the save refuses one with 400, so this surface was stored without that check) | Use the remote gateway record ID |
| 400 "Invalid fabric URL format. Expected: fabric://{gateway_id}/{channel_id}" | A segment is missing | Fix `target.endpoint` |
| 404 "Channel <id> not found" / 503 "Channel <id> is not active" | Wrong remote surface ID, or it is inactive on the peer | Re-read `/v1/gateways/<id>/surfaces?force_refresh=true` |
| MCP: HTTP 403 with JSON-RPC `-32001` and `id: null`; A2A: 403 problem+json. The message is `Sender is not a registered gateway` or `Channel is not exposed to sender` | The receiving gateway has no `active` record for the sending connection point; or that record's exposed surfaces are not empty and leave this surface out; or the record belongs to a tenant and the surface to another | On the receiving gateway, add the surface to the peer's exposed surfaces ([Limit what a peer can reach](#limit-what-a-peer-can-reach)) or empty the list; for an unregistered sender, pair again. A tenant-owned peer reaches only its own tenant's surfaces and appliance-wide ones, whatever the list says |
| `"success": false` with `Request timed out - gateway did not respond` from `/v1/gateways/<id>/surfaces` | The peer did not answer discovery within about 5 s | As for the 504 row: [A peer that stops answering](#a-peer-that-stops-answering) |
| 504 "Gateway did not respond in time" | The peer gateway is down; or slower than the surface's `timeout.request_secs`, else `a2a.fabric_gateway_timeout_ms` (60 s by default); or more requests to that peer wait at the mediator than its per-peer queue cap allows ([What the mediator needs](#what-the-mediator-needs)). A down peer's record still reads `active`, and a ping answers `"success": false` with `Gateway ping timed out - no response received` | [A peer that stops answering](#a-peer-that-stops-answering); calls resume as soon as the peer is back. For a slow peer, raise the surface's `timeout.request_secs`, which sets both the wait and the request's expiry at the mediator (the expiry is capped at 3480 s). For many concurrent calls to one peer, ask the mediator's operator to raise `queued_send_messages_per_peer` |
| 503 `{"error":"Gateway dispatch capacity unavailable"}` with `retry-after: 1` | The peer's listener for this link is already running `[a2a] max_inflight_dispatches` requests, 256 by default (`dispatch_slot` in `src/gateways/connection_points/ws_listener.rs`); the sending gateway does not retry | Retry after a second; the peer's operator can raise `max_inflight_dispatches` |
| GW-B stays `pending` with an empty `description` ([KI-56](known-issues.md)), GW-A shows no request, and GW-A's log names the reason | GW-A refused the handshake and logged `Failed to process connection-setup as inviter: <reason>`, with `Invalid connection secret` or `Invalid issuer attestation: ...` as the reason (for the second, also `Issuer attestation rejected for acceptor <did>: <reason>`); or GW-A could not use the invitation and logged `connection-setup on connection point <cp-id> refused: <reason>`, such as `invitation has expired`, `connection point is disabled` or `invitation has already been used` | `Invalid connection secret`: send the secret the connection point was created with. `could not resolve the attestation issuer: ...`: make GW-B's gateway DID document reachable from GW-A on a public host, or set `[did_cache] allow_private_hosts` on a local stack ([What the mediator needs](#what-the-mediator-needs)). `attestation has expired` or `attestation is not yet valid`: the clocks differ; sync both to NTP. An expired, disabled or used invitation: create a new connection point. Then delete GW-B's record and re-run `connect-via-oob`, with a new invitation if `expires_at` has passed |
| GW-B's log shows `Inviter issuer attestation rejected: ...` and its record never goes `active` | GW-A's attestation did not verify, for the same reasons the other way round | Fix it on GW-A, then [Connect two gateways](#connect-two-gateways) again |
| 400 "Gateway is not awaiting approval" / 404 "Pending connection context not found" | Wrong record or approved twice / approval context gone | Approve only `awaiting-approval`; else new invitation |
| 400 "Can only create connection points for self gateway" | `gateway_id` is a remote record | Use the `self` record's ID |
| `Failed to retrieve OOB invitation: "OOB URL blocked by egress policy"` on `connect-via-oob` | The `oob_url` host is a loopback, private, link-local or ULA address | Give the mediator a public address ([What the mediator needs](#what-the-mediator-needs)) |
| 500 "Failed to retrieve OOB invitation" / "Invitation missing 'from' field" | URL truncated, unreachable or not from a connection point | Copy the full `oob_url` |
| 400 "Failed to fetch inviter's mediator DID from URL: Failed to fetch mediator DID document from <url> (tried: ...)" on `connect-via-oob` | The inviter's mediator publishes no DID document at those paths, such as a `did:peer` mediator, or the URL is truncated | Invite through a `did:web` or `did:webvh` mediator ([What the mediator needs](#what-the-mediator-needs)); else copy the full `oob_url` |
| 400 "Failed to extract mediator URL: DID must start with 'did:web:' or 'did:webvh:', got: <did>" on a trust-ping | The mediator was registered with a DID of another method and no `did_document` | Delete it and register it again with `did_document` ([Connect two gateways](#connect-two-gateways)) |
| `Failed to create OOB invitation: Failed to add profile to ATM: ... WebSocket isActive? command timed out` on `connection-points create` | The mediator could not authenticate the new connection point, typically because it cannot fetch its `did:web` document over HTTPS or does not trust GW-A's certificate; the mediator's log shows `did:web resolution error` | Make GW-A's `/connection-points/<cp-id>/did.json` reachable from the mediator, or use `did_method: "peer"` |
| 503 "Cannot resolve inviter's DID document" | GW-B cannot resolve GW-A's connection point DID: it cannot fetch `/connection-points/<cp-id>/did.json` over HTTPS with a certificate it trusts, or the DID's host is, or resolves to, a loopback or private-network address, which GW-B refuses unless its `[did_cache] allow_private_hosts` is `true` | Make that path reachable from GW-B on a public host, or pair with `did_method: "peer"` on both sides |
| 503 "No active connection point listener found for gateway." | Ping before the handshake finished | Finish the handshake |
| `runtime_status.error_code` set, for example `MEDIATOR_UNREACHABLE` or `PEER_GATEWAY_UNAVAILABLE` | Mediator, DID document, auth or peer problem | Fix it, then reconnect; for a vanished peer, handshake again |
| 403 "Request blocked by gateway policy" / "Request blocked by appliance-wide policy" | The receiving gateway's policy denied | Inspect its rules on `input.gateway.source_id` |
| 422 "Invalid MCP identity presentation" | The MCP identity presentation does not verify, or its issuer is not one of the sending connection's issuers | Check the calling gateway's identity binding ([identity.md](identity.md)), then [Manage a connection's issuers](#manage-a-connections-issuers) |
| MCP: HTTP 403 with JSON-RPC `-32001` and `id: null`; A2A: 403 problem+json. The message is `peer issuer DID not established for gateway <id>: ...` | The receiving gateway refused the sender: its connection has no `issuer_did`, trusts no issuer, and the issuer exchange failed. `<id>` is the record ID on the receiving gateway | On the receiving gateway, [Manage a connection's issuers](#manage-a-connections-issuers) |
| MCP: HTTP 403 or 504 with JSON-RPC `-32001` or `-32603`; A2A: problem+json. The message starts `Envelope refused: ` | The receiving gateway refused the request's DIDComm envelope: `envelope expired at <t> (now <t>)` (504) arrived after its expiry; `envelope created_time <t> is more than 120s ahead of now (<t>)` or `envelope expires_time <t> is more than 3600s ahead of now (<t>)` (403) means the two clocks differ | Sync both gateways' clocks to NTP; for an expired envelope, also see the 504 row |
| 502 "Failed to pack message for remote gateway '<id>': ..." / 500 "Failed to send message"; through a Transit Point, 502 `Upstream connection failed: Failed to send message to remote gateway '<id>': ...` | 502 on an Access Point: this gateway could not encrypt the request for the peer, usually because the peer's DID does not resolve from here. 500: it could not hand the request to the link's mediator, for example because the mediator is down. A Transit Point reports either as the 502 | Check that this gateway can resolve the peer record's `did`; one on a loopback or private-network host needs `[did_cache] allow_private_hosts`. Check the mediator with its trust-ping ([A peer that stops answering](#a-peer-that-stops-answering)); calls resume once it is back |
| MCP JSON-RPC `-32603` from a `fabric://` surface, with the remote error as its message; on an HTTP+SSE session, `Fabric forwarding failed: <status> <body>` | Any other error from the receiving gateway | Read the message, then the receiving gateway's log |
| 502 or 504 "Modern Fabric transport is unavailable" on an MCP surface | A `2026-07-28` MCP request, which crosses as a framed stream, failed: 504 when the peer did not answer in time, including when the peer left the refusal unanswered because 16 refusals already await an answer; 502 otherwise, for example when the peer does not expose the surface to this gateway | For 504, as in the 504 row. For 502, ask the peer's operator for its `Rejecting Fabric Open` log lines and its exposure for this gateway ([Limit what a peer can reach](#limit-what-a-peer-can-reach)) |
| 429 with `Retry-After: 5`, JSON-RPC `-32603` `Too many concurrent MCP requests over Fabric`, on an Access Point or Transit Point | A framed-stream cap is full, on this gateway or on the peer, which refuses with `capacity_reached`: 8 request streams and 8 `subscriptions/listen` streams per peer, 16 of each per surface, 128 in each direction (`capacity_response` in `src/proxy/fabric_forward.rs`) | Retry after the interval. A forwarded `subscriptions/listen` can hold its slot for up to an hour, so let long-lived listens end, or spread the callers over more surfaces |
| 502 "OOB connection failed: ..." / 409 "Trust registry connection is not approved yet" | Registry URL bad, blocked or unreachable (record kept, `failed`) / not approved yet | Delete the record, fix the URL and re-create / wait for `connected` |
| 502 "OOB connection failed: ... Failed to enable WebSocket: TransportError(\"WebSocket isActive? command timed out\")" on `trust-registries create` | With `did_method` `web`, the registry's mediator could not fetch `/trust-registries/<tr-id>/did.json` from this gateway over HTTPS (inference) | Serve that path over HTTPS with a certificate the mediator trusts, or re-create with `did_method: "peer"` |
| 502 "Failed to list records: Problem report [e.p.msg.unauthorized]: Unauthorized: DID <did> is denied by authorization policy" | The registry approved the link but its policy for `our_did` still denies | Ask the registry administrator to allow that DID ([Connect a trust registry](#connect-a-trust-registry)) |
| `tr_registered: false` on `issuers create`, and `Failed to register issuer in trust registry (non-fatal)` in the log | The registry refused the write, for example for want of a `create` grant (inference), or did not answer | Fix the grant, then `register-trust-registry` ([Register an issuer](#register-an-issuer-in-a-trust-registry)) |
| 400 "Trust Registry reference is not accessible" on a surface save | A Trust Check names a registry ID this token may not use, or one that does not exist | Use an ID from `trust-registries list` |
| Every request on a surface with a Trust Check takes 10 s or more, and a policy that requires `ok` refuses it | The registry is down; the check waits at least 10 s and records `QUERY_FAILED` | Bring the registry back; set `timeout_secs` on the element to cap the wait |

### A peer that stops answering

Work out whether the fault is this gateway's or the peer's before you change anything. None of these steps
changes a record or anything on the peer. One has a side effect here: when the ping in step 3 times out, the
gateway checks its own mediator account and, if the mediator dropped it or closed its receive list, restarts the
link's connection point or re-opens the list. Every connected connection point also runs that check by itself
every 30 seconds, and logs a repair that fails at `warn` (`ACCOUNT_CHECK_INTERVAL` in
`src/gateways/connection_points/account_watch.rs`).

1. `fabric agent-gateway api post "/v1/mediators/$MEDIATOR_ID/trust-ping" -o json`: this gateway's mediator answers.
2. `fabric agent-gateway connection-points list -o json`: the link's connection point reads `connected`.
3. `fabric agent-gateway api post "/v1/gateways/$PEER_ID/ping" -o json`: a peer that is down answers
   `"success": false` with `Gateway ping timed out - no response received`, after about 10 s.
4. `fabric agent-gateway api get "/v1/gateways/$PEER_ID/surfaces?force_refresh=true" -o json`: a peer that is
   down answers `Request timed out - gateway did not respond` after about 5 s.

When 1 and 2 pass and 3 and 4 fail, the message left this gateway and nothing came back: the fault is on the
peer's side or the mediator's delivery to it. The record's `active` status and the connection point's
`runtime_status` (`connected`, `consecutive_failures` 0) describe this gateway's own link to its mediator, so
they do not show a live peer. `audit list --flow fabric` prints `No matching audit events.` when audit is off
or `policy_decision` is not selected ([operations.md](operations.md)).
Give the peer's operator the time of the first failure, this gateway's DID, the remote surface ID and the ping
result, and ask them to check that their gateway runs, that their connection point for the link is
`connected`, that their record for this gateway is `active` and answers a ping from their side, and that the
surface is still active.

## Known issues here

- [KI-11](known-issues.md): `fabric://` send allows when no target engine is compiled.
- [KI-22](known-issues.md): a remote gateway record's policy is never evaluated.
- [KI-47](known-issues.md): per-tool MCP policies on the receiving gateway see unchecked `input.jwt` claims.
- [KI-56](known-issues.md): a refused handshake can leave GW-B `pending` with no reason.
- Also, not listed as known issues: a disabled connection point refuses only new handshakes on its invitation
  and `2026-07-28` MCP streams that arrive on it, and still carries every other request on its links; a
  mediator's `disabled` status changes nothing; connection point reads expose the connection secret.

Sources: [Gateways](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/concepts/connections/gateways/), [Agent validation via Trust Registry](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/how-to-guides/connections/agent-validation-via-trust-registry/), [Connect two gateways](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/how-to-guides/connections/connect-gateways/), [Connection point](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/reference/gateways/connection-point/), [Gateway reference](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/reference/gateways/gateway/), [Mediator](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/reference/gateways/mediator/), [Trust registries](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/concepts/connections/trust-registry/), [Issuer reference](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/reference/trust-registries/issuer/); gateway source: `src/gateways/handlers.rs`, `src/gateways/connection_points/message_processor.rs`, `src/gateways/connection_points/ws_listener.rs`, `src/proxy/handler.rs`, `src/proxy/fabric_stream/mod.rs`, `src/trust_registries/communication.rs`, `docs/FABRIC.md`, `docs/PER_GATEWAY_MEDIATOR_FEDERATION.md`, `docs/POLICY.md`, `src/gateways/connection_points/account_watch.rs`; fabric's `src/commands.rs`.
