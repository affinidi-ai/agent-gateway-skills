# Policies: OPA and Rego on the gateway

Read this before you write or change Rego, and whenever a call gets a 403, a JSON-RPC `-32000` or `-32001`, a
permissive policy still denies, or an A2A rule lets v1.0 callers through. Checked against the reviewed gateway version; where this file
and a running gateway disagree, the gateway wins.

## Contents

- [Before you change anything](#before-you-change-anything)
1. [Where policies attach, and the order they run in](#where-policies-attach-and-the-order-they-run-in)
2. [The package names](#the-package-names)
3. [The four input documents](#the-four-input-documents)
4. [Recipe: capture the real input](#recipe-capture-the-real-input)
5. [Recipe: deny a tool (MCP) or a message (A2A)](#recipe-deny-a-tool-mcp-or-a-message-a2a)
6. [Recipe: allow-list tools with per-tool MCP policies](#recipe-allow-list-tools-with-per-tool-mcp-policies)
7. [Check MCP Tool Gating before you save it](#check-mcp-tool-gating-before-you-save-it)
8. [Recipe: change a policy safely](#recipe-change-a-policy-safely)
9. [Gateway and appliance-wide planes](#gateway-and-appliance-wide-planes)
10. [Fail-closed and fail-open](#fail-closed-and-fail-open)
11. [Rego examples](#rego-examples)
12. [When it fails](#when-it-fails)
- [Known issues here](#known-issues-here)

## Before you change anything

Save the surface (`before.json` is your undo) and derive its data-plane URL: listen address plus route. Add
`http://` if the stored listen address has no scheme.

<!-- e2e: policy-deny-mcp -->
```bash
SURFACE_ID="${SURFACE_ID:?set SURFACE_ID to the surface you will change}"
fabric agent-gateway policies list -o json | jq -c '.[] | {id, policy_type, enabled, version}'
fabric agent-gateway surfaces get "$SURFACE_ID" -o json > before.json
jq -c '{status, inbound: .access_point.inbound_policy, target: .target.policy, tools: .target.mcp_tool_policies}' before.json
echo "data plane: $(jq -r '.access_point.listen_address + .access_point.route' before.json)"
```

`fabric agent-gateway policies impact <id>` counts the surfaces and gateways that use a definition and says whether it is
enforced appliance-wide. It does not count per-tool MCP policies or MCP Tool Gating conditions, so also search
`fabric agent-gateway surfaces list -o json` for the ID.

## Where policies attach, and the order they run in

A definition holds one Rego module. A surface slot holds one reference; the gateway slot (`policy_definition_id` plus
`policy_definition_ids`) and each appliance-wide plane hold a list, and a deny from any member wins, except that an
appliance-wide member set to `monitor_only` only logs.

| Slot | JSON path | Set with | Input |
| --- | --- | --- | --- |
| Gateway | gateway record `opa_policy_config` | `fabric agent-gateway api put /v1/gateways/<id>/policy` | `PolicyInput` subset, or `{sts}` |
| Appliance-wide (2 planes) | `/v1/policy-assignments` | `fabric agent-gateway api put /v1/policy-assignments` | `PolicyInput` |
| Access Point | `access_point.inbound_policy` | `add-feature inbound-policy` | `PolicyInput` |
| Target | `target.policy` | `add-feature policy` | `PolicyInput`; also filters `tools/list`, except on `fabric://` and for a `2024-11-05` request to `proxy://` |
| Response | `target.response_policy` | `add-feature policy --response` | `ResponsePolicyInput` |
| Per MCP tool | `target.mcp_tool_policies[]` | edit the surface JSON | `McpPolicyContext` |
| MCP Tool Gating condition | `target.mcp_tool_gating.gates[].condition_policy_definition_id` | `add-feature mcp-tool-gating` | `PolicyInput` |
| Surface outbound | `transit.opa_policy_definition_id` | edit the surface JSON | `PolicyInput`, outbound |
| Per Transit Point | `transit.points[n].policy`, `.response_policy` | `add-feature policy --transit-point <alias>`, `--response` for the second | `PolicyInput`, outbound; `ResponsePolicyInput` |

A direct inbound request runs these steps in order, and the first deny is final:

1. appliance-wide gateway plane, then the gateway policy (403 problem+json);
2. per-tool MCP policies, on `tools/call` only (HTTP 200, `-32000`);
3. Access Point `inbound_policy`, then the appliance-wide surface plane, then `target.policy` (403 JSON, or HTTP
   200 `-32001` on `tools/call`);
4. MCP Tool Gating on `tools/call`;
5. forward upstream, then the `tools/list` filter and the response policy.

- A `2026-07-28` request to a `proxy://` target runs every step, as for an `http(s)` target. A `2024-11-05` request
  runs step 1, then `inbound_policy` and `target.policy`, then the per-tool policies and MCP Tool Gating on
  `tools/call` and, after the proxy answers, the gating filter on `tools/list` and the response policy: no
  appliance-wide surface plane and no `target.policy` filter on `tools/list`. There `target.policy` sees
  `tools/list` once, with no `tool_name`, so it allows or denies the whole list.
- Across the whole request, a `proxy://` target with a `2024-11-05` request runs routing, caller authentication, the
  rate limit, MCP admission, Metadata Extraction and the gateway policies, skips egress vetting, then runs the
  Trust Check, `inbound_policy`, `target.policy`, the per-tool policies, MCP Tool Gating, target auth and the
  response policy, never the appliance-wide surface plane or delegation. A `2026-07-28` request runs every stage,
  even on `proxy://`, and settles consent (200 `input_required`) and payment after MCP Tool Gating.
- `fabric://` send skips the target policy when no engine is compiled ([KI-11](known-issues.md)); fabric receive
  denies instead. Per-tool MCP policies run before a `fabric://` send too, with the same `-32000` and `-32603`.
- An MCP `GET` notification stream and an MCP `DELETE` are answered after step 1, before any later step, so no
  Access Point, surface-plane or target policy sees them, and a deny-all `target.policy` still lets them through
  ([protocols.md](protocols.md)). One that sends `MCP-Protocol-Version: 2026-07-28` gets 405 before step 1.
- Outbound Transit Point calls run the gateway, surface-outbound and Transit Point policies, then Transit Point
  gating, never the appliance-wide planes.

## The package names

The package line picks the query. `gateway.authz` does not exist.

| Scope | Package | Query | Optional reason |
| --- | --- | --- | --- |
| Every surface slot, per-tool policies, gating conditions, appliance-wide surface plane | `package surface.policy` | `data.surface.policy.allow` | `data.surface.policy.deny_reason` |
| Gateway policy, appliance-wide gateway plane | `package gateway.policy` | `data.gateway.policy.allow` | `data.gateway.policy.deny_reason` |

- `deny_reason` is read only on deny and only when it is a string; otherwise the default is `Policy denied
  request`, `Request blocked by gateway policy` or `Access denied by MCP tool policy`.
- An undefined `allow` (wrong package, no `default allow`) denies, with a reason that starts `Surface policy
  produced no` (`Gateway policy produced no` for a gateway policy, `Policy produced no` from simulate) and names
  the package to declare.
- Create and update check only the package line: the first line that is not blank or a comment must be `package
  surface.policy` for `agent_surface` and `package gateway.policy` for `gateway`, or the answer is 400
  `Invalid policy definition '<id>': Policy package ... does not match ...` (`... Policy must declare ...` when there
  is no package line). An empty body passes the check, and a `target.policy` that uses it then answers `no policy is
  loaded for this channel`. `update` also refuses a changed `policy_type` with 400
  `A policy's type cannot be changed after creation`.
- The engine is regorus, in process, one module per slot: no imports from other definitions.
  Write Rego v1 (`allow if { ... }`): a v0 body fails to compile with `` `if` keyword is required before rule
  body ``. `http.send` always yields undefined: the regorus builtin returns no value. Simulate a draft before you
  rely on a builtin.
- Simulate needs an existing definition ID: `/v1/policy-definitions/<id>/simulate` with an unknown ID answers
  `Policy definition not found: <id>`. The draft in `policy` replaces that definition's text for the run only,
  so test a brand-new draft against any existing definition, with `policy_type` set to the draft's type
  (`agent_surface` or `gateway`) when it differs, or create it unattached first.

## The four input documents

Keys with no value are absent, never `null`, except `error` inside each `trust_check_results` entry and `actor` and
`audience` in `input.sts`. `input.caller.*` does not exist anywhere in `PolicyInput`, and `input.jwt` exists only in
`McpPolicyContext`.

**`PolicyInput`**, per evaluation point:

| Key | Contents | Gateway | `inbound_policy` | `target.policy`, appliance surface plane | Outbound, Transit Point |
| --- | --- | --- | --- | --- | --- |
| `http` | `method`, `path`, `headers` minus sensitive ones | yes | yes | yes | yes, the transit request path |
| `gateway` | `direction`, `source_id`, `target_id` | `inbound` | `inbound` | `inbound` | `outbound`, `target_id` = TP `target_endpoint` |
| `channel` | `config_id` (surface ID), `name`, `variant_alias` | yes | yes | yes | yes |
| `source_auth` | tagged by `method` (below) | yes | yes | yes | only when the Transit Point sets `mcp_http.authorization` |
| `mcp` | `method`, `tool_name`, `params`, more on a `2026-07-28` request (below) | MCP surfaces | MCP surfaces | MCP surfaces | MCP surfaces |
| `a2a` | `method` as the caller spelled it, `method_canonical`, `message` | A2A surfaces | A2A surfaces | A2A surfaces | A2A surfaces |
| `agent` | trust-registry context, `did`, `did_verified`, `did_verification` | yes | yes, `did` as sent | yes, `did` falls back to `extension_identity.did` | the target agent |
| `extension_identity` | `did`, `identity_hash`, `verified`, `verification` (`vp`, `vp_unanchored`, `source_auth` or `unverified`) | no | yes | yes | no |
| `payment`, `identity_binding` | payment and binding results | no | yes | yes | no |
| `trust_check_results` | Trust Check outcomes, as `caller` and `target` lists ([g2g.md](g2g.md#add-a-trust-check-and-act-on-it)) | not set (the Trust Check runs later) | yes | yes | yes |
| `metadata` | never set ([KI-24](known-issues.md)) | | | | |

- For a `2024-11-05` request to a `proxy://` target the input carries only `http`, `gateway`, `channel`,
  `source_auth`, `mcp`, `payment`, `agent` and `trust_check_results`, and `agent` is always built. The `did`
  fallback also applies to gating conditions and the `tools/list` filter.

- `source_auth` is `{"method":"jwt_bearer","subject","claims"}`, `{"method":"api_key","key_name"}`,
  `{"method":"did_auth","did"}`, `{"method":"mtls","principal","fingerprint","subject_dn","issuer_dn","sans"}` or
  `{"method":"failed","attempted_method","reason"}`. Validated JWT claims are `input.source_auth.claims`; an API-key
  caller has no `subject`. On an MCP surface that sets `mcp_http.authorization`, a caller with a valid token from
  the gateway's MCP issuer is `jwt_bearer` with that token's `subject` and `claims`, and a bad token is challenged
  before any policy runs ([identity.md](identity.md#mcp-client-sign-in)).
- `mcp` is built only on MCP surfaces. A `2024-11-05` request needs a JSON-RPC `id`, and its `tool_name` is
  `params.name` for any method, so `prompts/get` puts the prompt's name there. A `2026-07-28` request sets
  `tool_name` only on `tools/call`, `prompt_name` on `prompts/get` and `resource_uri` on `resources/read`, and adds
  `protocol_version`, `client_capabilities` and `client_info`. Both carry the raw `params`, so match a prompt on
  `input.mcp.params.name` and `resources/read` on `input.mcp.params.uri`.
- `a2a.method` and `a2a.message` are the body's `method` and `params.message` exactly as sent. A v0.3 caller
  sends `message/send`, role `user` and parts with `"kind": "text"`; a v1.0 caller sends `SendMessage`, role
  `ROLE_USER` and parts with `text` and no `kind` ([protocols.md](protocols.md) has every method in both
  spellings). `a2a.method_canonical` is the v0.3 spelling of any method the gateway recognises in either era
  (`message/send` for both `message/send` and `SendMessage`) and is absent for any other method. Match the method
  on `input.a2a.method_canonical`, the role in `{"user", "ROLE_USER"}`, and text by `part.text`, never by
  `part.kind`.
- On the direct path the gateway builds `agent` from the request body only when `target.policy` or a caller Trust
  Check is configured; where `did` falls back to `extension_identity.did`, an `agent` holding that `did` appears
  without them too. `agent.did` can come from the caller's own request body, so grant on `source_auth`, or on
  `agent.did` only while `agent.did_verified` is `true`.
- Removed headers: `authorization`, `proxy-authorization`, `cookie`, `set-cookie` and any name containing `token`,
  `secret`, `credential`, `api-key` or `apikey`, except in the fabric-receive gating-condition input.
- The `tools/list` filter evaluates `target.policy` once per listed tool with `mcp` set to
  `{"method":"tools/list","tool_name":"<tool>"}` (a `2026-07-28` request also keeps its `params`, `protocol_version`,
  `client_capabilities` and `client_info`) and with no `trust_check_results`, and drops each tool it denies, so a rule
  that needs a Trust Check result hides every tool.
- `http.path` is the path after the surface's route, `/` for a request to the route itself, so do not match the
  public route in Rego.

**`McpPolicyContext`**, per-tool MCP policies only: `mcp` {`method` always `tools/call`,
`params` with the tool in `params.name`, `protocol`, and on a `2026-07-28` request `protocol_version`,
`client_capabilities` and `client_info`}, `jwt` (claims decoded from any `Authorization: Bearer` header,
**signature not verified**), `channel` {`name`, `id`, `protocol`} and `request`
{`source_ip`, the first `X-Forwarded-For` value when present, `method`, `path`}. `jwt` and `source_ip` are
caller-controlled. The docs' per-tool policy guide says `input.jwt` holds the claims of a token the surface's
JWT bearer caller auth validated, but the gateway does not check that token, with or without caller auth.
Grant on `input.jwt` only when an `inbound_policy` also requires `input.source_auth.method == "jwt_bearer"`
([KI-47](known-issues.md)). The per-tool policy runs first, but the call still needs that allow. A surface that
sets `mcp_http.authorization` removes the `Authorization` header before any policy, so `input.jwt` is absent there:
grant on `input.source_auth` in `inbound_policy` or `target.policy` instead.

**`ResponsePolicyInput`**, response slots: `response` {`status_code`, `body` for JSON bodies, `content_type`,
`is_error`}, `caller` {`did`, `identity_source`, `dna_uai`} and `surface` {`id`, `name`, `protocol`}; no `http`,
`gateway` or `source_auth`.

**`{sts}`**: the gateway policy also authorises STS issuance, with `input.sts` {`grant`, `client_id`, `subject`,
`actor`, `audience`, `scope`, `requested_token_type`, plus `resource` and `issuer` on the MCP issuer's token
endpoint (`sts.mcp_issuer`)} and, when the STS client has a `trust_check_list`, `input.trust_check_results`; nothing
else. So a default-deny gateway policy that grants on `input.http` or `input.source_auth` blocks every STS exchange
unless it also allows on `input.sts` (`GatewayPolicyEvaluator` in `src/sts/policy.rs`).

## Recipe: capture the real input

**Confirm with the user:** while the capture policy is attached, every request to that surface is denied.

**Before.** Use a copy of the surface or one short window, and an anonymous or test caller. The reason leaves out
`http.headers` (the caller's key or JWT) but keeps `source_auth.claims` and the message or tool arguments. On MCP
`tools/call` it goes back to the caller in the `-32001` message; on A2A it goes to the audit log.
Never marshal the whole input.

**Change.**

<!-- e2e-file: opa-input capture.rego -->
```rego
package surface.policy
default allow := false
# Everything except the request headers, which carry the caller's credentials.
deny_reason := json.marshal(object.union(object.remove(input, ["http"]),
	{"http": {"method": input.http.method, "path": input.http.path}}))
```

<!-- e2e: opa-input -->
```bash
CAPTURE_POLICY_ID="${CAPTURE_POLICY_ID:-input-capture}"
fabric agent-gateway policies create --id "$CAPTURE_POLICY_ID" --name "Capture policy input" --policy-file capture.rego -o json
fabric agent-gateway surfaces get "${MCP_SURFACE_ID:?set MCP_SURFACE_ID}" -o json > mcp-before.json
fabric agent-gateway surfaces add-feature "$MCP_SURFACE_ID" policy --policy-id "$CAPTURE_POLICY_ID" -o json > /dev/null
```

**Verify (MCP).** Send one `tools/call` and read the reason out of the error:

<!-- e2e: opa-input -->
```bash
curl -sS "$(jq -r '.access_point.listen_address + .access_point.route' mcp-before.json)" \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"echo","arguments":{"text":"hi"}}}' \
  | jq -r '.error.message | sub("^Tool .* is not allowed by policy: "; "")' | jq .
```

**Verify (A2A).** The caller sees only the fixed 403, so turn on audit with `policy_decision` selected.
`audit_events` is replaced as a whole list ([operations.md](operations.md)), so send it complete:

<!-- e2e: opa-input -->
```bash
fabric agent-gateway settings show -o json > settings-before.json
jq '{audit_enabled: true, audit_events: ((.audit_events // []) + ["policy_decision"] | unique)}' settings-before.json > audit-on.json
fabric agent-gateway settings set --file audit-on.json -o json > /dev/null
fabric agent-gateway surfaces get "${A2A_SURFACE_ID:?set A2A_SURFACE_ID}" -o json > a2a-before.json
fabric agent-gateway surfaces add-feature "$A2A_SURFACE_ID" policy --policy-id "${CAPTURE_POLICY_ID:-input-capture}" -o json > /dev/null
curl -sS -o /dev/null -w '%{http_code}\n' "$(jq -r '.access_point.listen_address + .access_point.route' a2a-before.json)" \
  -H 'Content-Type: application/json' -d '{"jsonrpc":"2.0","id":1,"method":"message/send","params":{"message":
  {"kind":"message","role":"user","messageId":"capture-1","parts":[{"kind":"text","text":"hello"}]}}}'
fabric agent-gateway audit list --category policy_decision --decision deny --filter "$A2A_SURFACE_ID" --limit 1 -o json \
  | jq -r '[.. | objects | select(has("deny_reason")) | .deny_reason][0]' | jq .
```

**Undo.** Detach straight after, restore the audit settings, then delete the definition. Detaching is what stops
enforcement ([KI-10](known-issues.md)). If a surface had a `target.policy` before, re-attach that ID from its
`*-before.json` instead of removing the feature.

<!-- e2e: opa-input -->
```bash
fabric agent-gateway surfaces remove-feature "${MCP_SURFACE_ID:?}" policy -o json > /dev/null
fabric agent-gateway surfaces remove-feature "${A2A_SURFACE_ID:?}" policy -o json > /dev/null
jq '{audit_enabled, audit_events}' settings-before.json > settings-restore.json
fabric agent-gateway settings set --file settings-restore.json -o json > /dev/null
fabric agent-gateway policies delete "${CAPTURE_POLICY_ID:-input-capture}"
```

**If it fails.** Empty audit list: `audit_enabled` is off, or `audit_events` lacks `policy_decision`.
403 `OPA policy enforcement is enabled but no policy is loaded for this channel`, or
`-32001 ... no policy is loaded for this channel` on `tools/call`: the policy did not compile.

## Recipe: deny a tool (MCP) or a message (A2A)

**Confirm with the user:** callers lose the denied tool or message at once.

**Before.** [Before you change anything](#before-you-change-anything); set `SURFACE_URL` to the data-plane URL.

**Change (MCP).** Deny on `input.mcp.tool_name`, which the `tools/list` filter also sets, so the tool disappears
from discovery too; on `fabric://`, and for a `2024-11-05` request to `proxy://`, it stays listed:

<!-- e2e-file: policy-deny-mcp deny-tool.rego -->
```rego
package surface.policy
default allow := false
blocked if input.mcp.tool_name in {"delete_everything"}
allow if not blocked
deny_reason := sprintf("tool %v is blocked on this surface", [input.mcp.tool_name]) if blocked
```

<!-- e2e: policy-deny-mcp -->
```bash
POLICY_ID="${POLICY_ID:-block-dangerous-tools}"
fabric agent-gateway policies create --id "$POLICY_ID" --name "Block dangerous tools" --policy-file deny-tool.rego -o json
fabric agent-gateway surfaces add-feature "${SURFACE_ID:?}" policy --policy-id "$POLICY_ID" -o json | jq -c '.target.policy'
```

**Verify (MCP).** The blocked tool gets HTTP 200 with `-32001` and your reason, `echo` still works, and
`tools/list` omits the blocked tool. A reply the upstream sent as JSON
comes back as one SSE `data:` event when `Accept` allows SSE, so `mcp` keeps only
the JSON lines:

<!-- e2e: policy-deny-mcp -->
```bash
mcp() { { curl -sS "${SURFACE_URL:?set SURFACE_URL}" -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' -d "$1"; echo; } | sed -n -e '/^[{[]/p' -e 's/^data: //p'; }
mcp '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"echo","arguments":{"text":"still here"}}}'
mcp '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"delete_everything","arguments":{}}}'
mcp '{"jsonrpc":"2.0","id":3,"method":"tools/list"}' | jq -c '{listed: [.result.tools[].name]}'
```

**Change (A2A).** Deny on the message text. Match a part by its `text`: a v0.3 part says `"kind": "text"`,
but a v1.0 part has no `kind`, so a rule on `part.kind == "text"` lets every v1.0 caller through:

<!-- e2e-file: policy-deny-a2a deny-refund.rego -->
```rego
package surface.policy
default allow := false
mentions_refund if {
	some part in input.a2a.message.parts
	contains(lower(part.text), "refund")
}
allow if not mentions_refund
deny_reason := "refund requests go to a person, not to this agent" if mentions_refund
```

<!-- e2e: policy-deny-a2a -->
```bash
POLICY_ID="${POLICY_ID:-route-refunds-to-people}"
fabric agent-gateway policies create --id "$POLICY_ID" --name "Route refunds to people" --policy-file deny-refund.rego -o json
fabric agent-gateway surfaces add-feature "${SURFACE_ID:?}" policy --policy-id "$POLICY_ID" -o json | jq -c '.target.policy'
```

**Verify (A2A).** Both refund messages, the v0.3 `message/send` and the v1.0 `SendMessage`, get a fixed 403, and
the other message goes through. The reason is only in the audit log, so turn auditing on as in the capture
recipe:

<!-- e2e: policy-deny-a2a -->
```bash
fabric agent-gateway settings show -o json > settings-before.json
jq '{audit_enabled: true, audit_events: ((.audit_events // []) + ["policy_decision"] | unique)}' settings-before.json > audit-on.json
fabric agent-gateway settings set --file audit-on.json -o json > /dev/null
send() { curl -sS -w '\nstatus %{http_code}\n' "${SURFACE_URL:?set SURFACE_URL}" -H 'Content-Type: application/json' -d \
  '{"jsonrpc":"2.0","id":1,"method":"message/send","params":{"message":{"kind":"message","role":"user","messageId":"'"$1"'","parts":[{"kind":"text","text":"'"$2"'"}]}}}'; }
send_v1() { curl -sS -w '\nstatus %{http_code}\n' "${SURFACE_URL:?}" -H 'Content-Type: application/json' -H 'A2A-Version: 1.0' -d \
  '{"jsonrpc":"2.0","id":2,"method":"SendMessage","params":{"message":{"role":"ROLE_USER","messageId":"'"$1"'","parts":[{"text":"'"$2"'"}]}}}'; }
send deny-1 'I want a refund for order 42'
send_v1 deny-2 'Refund order 42, please'
send allow-1 'Where is order 42?'
fabric agent-gateway audit list --category policy_decision --decision deny --filter "${SURFACE_ID:?}" --limit 1 -o json \
  | jq -c '[.. | objects | select(has("deny_reason")) | {deny_reason, scope, flow}][0]'
```

**Undo.** Detach (or re-attach the previous ID from `before.json`), then restore `settings-before.json` as in the
capture recipe: `fabric agent-gateway surfaces remove-feature <surface-id> policy`.

**If it fails.** Every request denied, `initialize` included: the policy has no path that allows it, or the package
is wrong (the reason says so). The tool is still listed: the Rego tests `input.mcp.params.name`, which the
`tools/list` filter does not set. v0.3 messages are denied but v1.0 ones get through: the Rego tests `part.kind`
or names only `message/send` in `input.a2a.method`; match `part.text`, and the method on `input.a2a.method_canonical`.

## Recipe: allow-list tools with per-tool MCP policies

**Confirm with the user:** every tool not on the list is refused from the next call.

Once `target.mcp_tool_policies` is non-empty it gates every `tools/call`: an exact name match, else the `"*"` entry,
else deny. Entries run in order, the first deny wins, and an entry whose definition is disabled is skipped. The
definition is compiled on every call, so an edit applies at once. There is no
`add-feature` for this field. `target.mcp_tool_policies_enabled`, which surface JSON carries,
has no effect: a non-empty list is the only switch.

**Before.** [Before you change anything](#before-you-change-anything).

**Change.** Bind an allow-all definition to each allowed tool and leave out `"*"`:

<!-- e2e-file: tool-policy-mcp allow.rego -->
```rego
package surface.policy
default allow := true
```

<!-- e2e: tool-policy-mcp -->
```bash
ALLOW_POLICY_ID="${ALLOW_POLICY_ID:-allow-tool}"
fabric agent-gateway policies create --id "$ALLOW_POLICY_ID" --name "Allow this tool" --policy-file allow.rego -o json
fabric agent-gateway surfaces get "${SURFACE_ID:?}" -o json > before.json
jq --arg p "$ALLOW_POLICY_ID" '.target.mcp_tool_policies = [{"tool_name": "echo", "policy_definition_id": $p}]' \
  before.json > surface.json
fabric agent-gateway surfaces update "$SURFACE_ID" --file surface.json -o json | jq -c '.target.mcp_tool_policies'
```

**Verify.** An unlisted tool gets HTTP 200 `-32000` with a fixed message, and the reason goes only to the audit log
(`--scope mcp_tool`). Per-tool policies do not filter `tools/list`, so it is still listed:

<!-- e2e: tool-policy-mcp -->
```bash
mcp() { { curl -sS "${SURFACE_URL:?set SURFACE_URL}" -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' -d "$1"; echo; } | sed -n -e '/^[{[]/p' -e 's/^data: //p'; }
mcp '{"jsonrpc":"2.0","id":7,"method":"tools/call","params":{"name":"delete_everything","arguments":{}}}'
mcp '{"jsonrpc":"2.0","id":8,"method":"tools/call","params":{"name":"echo","arguments":{"text":"allowed"}}}'
mcp '{"jsonrpc":"2.0","id":9,"method":"tools/list"}' | jq -c '{listed: [.result.tools[].name]}'
```

To hide it too, add MCP Tool Gating with `default_effect: "deny"` and an anchored allow pattern such as `^(echo|add)$`
([Check MCP Tool Gating before you save it](#check-mcp-tool-gating-before-you-save-it)), or the `target.policy` of
the previous recipe, which filters `tools/list` except on `fabric://` and for a `2024-11-05` request to `proxy://`.

**Undo.** `jq '.target.mcp_tool_policies = []' before.json > surface.json`, then
`fabric agent-gateway surfaces update <surface-id> --file surface.json`.

**If it fails.** `-32603 Internal error: policy evaluation failed`: an entry names an unknown or empty definition,
its Rego does not load or compile, or evaluation errors; per-tool definitions compile on every call, and the
reason is only in the gateway log, `Failed to evaluate MCP tool policy`. A tool with no entry and no `"*"` is
denied with the audit reason `No MCP tool policy configured for tool '<t>'`, and a `tools/call` with no
`params.name` with `MCP tools/call request is missing params.name`.
A rule on `input.mcp.method == "<tool>"` never matches: the tool is `input.mcp.params.name`.
Never grant on `input.jwt` alone: its signature is not checked ([KI-47](known-issues.md)).

## Check MCP Tool Gating before you save it

MCP Tool Gating (`target.mcp_tool_gating`, feature `mcp-tool-gating`) filters tools by name, both in `tools/list`
and on `tools/call`, on every MCP target, `proxy://` included. It holds `default_effect` (`allow` unless set) and
`gates`, each with an `id`, an optional `name`, an optional `condition_policy_definition_id` and an `action` of
`effect` (`allow` or `deny`) and `patterns`:

- A gate with no condition is always active; one with a condition is active when that surface policy allows the
  request. A condition policy that cannot be resolved, compiled or evaluated keeps a deny gate active and an
  allow gate inactive.
- A tool is allowed when no active deny gate matches it and either an active allow gate matches it or
  `default_effect` is `allow`. Deny always wins, the order of the gates does not matter, and under an `allow`
  default an allow gate changes nothing.
- Patterns are regular expressions that match anywhere in the name unless anchored. With alternatives, anchor
  each one or wrap them, as in `^(?:get_|list_)`.
- A `tools/call` whose `params.name` is missing or not a string is refused with 403 while gating is configured,
  on the Access Point, a Transit Point and the `fabric://` send leg.
- A surface save is refused with 400 when the gating has more than 64 gates, or a gate has no pattern (blank ones
  do not count), more than 64, one longer than 512 bytes or one that does not compile.

For example, this hides every tool whose name starts with `refund_` and leaves the rest alone; save it as
`gates.json`, check it with `tool-gate-preview --gates-file gates.json`, then attach it with
`fabric agent-gateway surfaces add-feature <surface> mcp-tool-gating --file gates.json`:

```json
{"default_effect": "allow", "gates": [{"id": "g-1", "name": "block refunds", "action": {"effect": "deny", "patterns": ["^refund_"]}}]}
```

Source: `CompiledMcpToolGating` in `src/policies/mcp_tool_gating.rs`, `McpToolGatingConfig` in
`src/config/agent_surface.rs`.

`fabric agent-gateway surfaces tool-gate-preview` works out the result on your machine and changes nothing:

- `fabric agent-gateway surfaces tool-gate-preview <surface> --tool delete_user,get_user` reads the gates the
  surface has saved in `target.mcp_tool_gating`, by name or ID. It does not read the gating of variants or
  Transit Points; a note says so when an enabled variant sets its own gating, or is complete and has none,
  because that variant's callers then get other gates.
- `fabric agent-gateway surfaces tool-gate-preview --gates-file gates.json --tool delete_user` checks gates that
  are not saved yet. The file holds the gating object itself, `{"default_effect": ..., "gates": [...]}`, and `-`
  reads standard input. A key the gateway does not know is refused. With a file, fabric reads nothing from the
  gateway and needs no saved connection or token.
- Only the gateway can evaluate a condition for a caller. Say what you know with
  `--condition <policy-id>=met` or `=unmet`, repeatable; a policy no gate names is refused. fabric tries every
  other condition policy both ways, and refuses more than three left open.
- The table is `TOOL  RESULT  DECIDED BY`: `ALLOW` or `DENY`, and the gate that decided (its `name`, else
  `Tool Gate <n>` by position) or `default (allow)` / `default (deny)`. A tool whose answer depends on a
  condition gets one row per case, in an extra `CONDITION` column (`admins met`, `admins not met`; `either way`
  for the other tools). `Assuming:` heads the table when you pinned conditions, and `Warnings` follows it, for
  example for a pattern that also catches a longer name, or an allow gate under an `allow` default.
- `-o json` prints `{default_effect, assumed, tools: [{tool, results: [{conditions, result, decided_by}]}],
  warnings}`, with `decided_by` `null` when the default decided.
- The preview cannot tell whether a condition policy exists: check it with
  `fabric agent-gateway policies get <policy-id> -o json` first.

To add or remove one pattern of a saved gate without resending the gate, use `surfaces update --add` or
`--remove` with the gate in brackets ([surfaces.md](surfaces.md#recipe-change-a-surface-safely)).

## Recipe: change a policy safely

**Confirm with the user:** an update changes every surface that uses the definition at once.

**Before.** `fabric agent-gateway policies impact <policy-id>`. This example starts from an allow-all definition attached as
`target.policy`:

<!-- e2e-file: policy-update-mcp update-allow.rego -->
```rego
package surface.policy
default allow := true
```

<!-- e2e: policy-update-mcp -->
```bash
POLICY_ID="${POLICY_ID:-echo-guard}"
fabric agent-gateway policies create --id "$POLICY_ID" --name "Echo guard" --policy-file update-allow.rego -o json
fabric agent-gateway surfaces add-feature "${SURFACE_ID:?}" policy --policy-id "$POLICY_ID" -o json > /dev/null
curl -sS "${SURFACE_URL:?set SURFACE_URL}" -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"echo","arguments":{"text":"before"}}}'; echo
```

**Change.** Simulate the draft first: it is the only step that reports a compile error. Then update
with the full document from `get -o json`, which carries `id`, `name`, `policy_type` and `created_at`; a field you
leave out falls back to its default, so `enabled` becomes `true`. Every surface that
references the definition is recompiled, with no surface save.

<!-- e2e-file: policy-update-mcp update-deny.rego -->
```rego
package surface.policy
default allow := false
allow if not input.mcp.tool_name == "echo"
deny_reason := "echo is paused" if input.mcp.tool_name == "echo"
```

<!-- e2e: policy-update-mcp -->
```bash
POLICY_ID="${POLICY_ID:-echo-guard}"
jq -n --rawfile rego update-deny.rego '{policy: $rego, input: {mcp: {method: "tools/call", tool_name: "echo"}}}' > sim.json
fabric agent-gateway api post "/v1/policy-definitions/$POLICY_ID/simulate" --file sim.json -o json
fabric agent-gateway policies get "$POLICY_ID" -o json > policy-before.json
jq --rawfile rego update-deny.rego '.policy = $rego' policy-before.json > policy.json
fabric agent-gateway policies update "$POLICY_ID" --file policy.json -o json > /dev/null
fabric agent-gateway policies versions "$POLICY_ID" -o json | jq -c '.[0] | {version, content_hash}'
```

The reply to `policies create` and `policies update` is the document you sent: after a create it has no
`version`, and after an update it still carries the `version` and `content_hash` you read before. Take the stored
version from `policies versions` or `policies get`.

**Verify.** The next call is denied with the new reason:

<!-- e2e: policy-update-mcp -->
```bash
curl -sS "${SURFACE_URL:?}" -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"echo","arguments":{"text":"after"}}}'; echo
```

Two traps. `"enabled": false` does not stop a surface or gateway slot from enforcing it; detach it instead
([KI-10](known-issues.md)):

<!-- e2e: policy-update-mcp -->
```bash
jq '.enabled = false' policy.json > disabled.json
fabric agent-gateway policies update "${POLICY_ID:-echo-guard}" --file disabled.json -o json | jq -c '{enabled}'
curl -sS "${SURFACE_URL:?}" -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"echo","arguments":{"text":"disabled"}}}'; echo
```

And Rego that does not parse is stored behind a valid `package` line: `update` answers as usual, and only the log
says `Failed to recompile OPA policy for channel`. Every surface that uses the definition, other than as a per-tool
policy or a gating condition, then drops all its compiled policy engines (`update_channel_policy` in
`src/policies/surface_manager.rs`), so its `target.policy` answers 403 `OPA policy enforcement is enabled but no
policy is loaded for this channel` (`-32001 ... no policy is loaded for this channel` on `tools/call`) until an
update compiles; `fabric://` send skips the policy instead ([KI-11](known-issues.md)). `policies create` stores
it the same way, as version 1 with no error, and it fails the same way once attached. Simulate catches it; `create`
and `update` do not:

<!-- e2e-file: policy-update-mcp update-broken.rego -->
```rego
package surface.policy
allow if {
```

<!-- e2e: policy-update-mcp expect-fail -->
```bash
jq -n --rawfile rego update-broken.rego '{policy: $rego, input: {}}' > sim-broken.json
fabric agent-gateway api post "/v1/policy-definitions/${POLICY_ID:-echo-guard}/simulate" --file sim-broken.json -o json
```

<!-- e2e: policy-update-mcp -->
```bash
jq --rawfile rego update-broken.rego '.policy = $rego | .enabled = true' policy.json > broken.json
fabric agent-gateway policies update "${POLICY_ID:-echo-guard}" --file broken.json -o json > /dev/null
fabric agent-gateway policies versions "${POLICY_ID:-echo-guard}" -o json | jq -c '.[0] | {version}'
curl -sS "${SURFACE_URL:?}" -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"echo","arguments":{"text":"broken"}}}'; echo
```

The call is denied with `no policy is loaded for this channel`, not `echo is paused`: the surface has no policy
engine until a version that compiles is back.

**Undo.** Put back a known-good version; `versions` lists them newest first:

<!-- e2e: policy-update-mcp -->
```bash
fabric agent-gateway policies versions "${POLICY_ID:-echo-guard}" -o json > versions.json
jq --slurpfile v versions.json '.policy = ([$v[0][] | select(.version == 1)][0].policy) | .enabled = true' \
  policy-before.json > restore.json
fabric agent-gateway policies update "${POLICY_ID:-echo-guard}" --file restore.json -o json > /dev/null
curl -sS "${SURFACE_URL:?}" -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"echo","arguments":{"text":"restored"}}}'; echo
```

**If it fails.** Every call denied with `no policy is loaded for this channel` after an update: the new Rego did not
compile (log `Failed to recompile OPA policy for channel`); simulate it, fix it and update again. No effect after
an update: a gateway lists the id only in `policy_definition_ids`, or a surface uses it only as a gating condition.
A definition you delete and create again under the same ID reaches a surface only when the surface is saved again
(`fabric agent-gateway surfaces update <surface-id> --file surface.json`), because `policies create` recompiles
nothing.
`fabric agent-gateway runtime reload` does not recompile policies ([KI-19](known-issues.md)).

## Gateway and appliance-wide planes

Neither has a `fabric` command; use `fabric agent-gateway api`. Both change every request on the gateway: confirm with the user,
simulate first.

**Gateway policy.** Only the record with `gateway_type: "self"` is enforced ([KI-22](known-issues.md)). Attach with
`fabric agent-gateway api put /v1/gateways/<self-gateway-id>/policy --file gw-policy.json`, the file being
`{"opa_policy_config": {"enabled": true, "policy_definition_id": "<id>", "policy_definition_ids": []}}`. The ID and
then each of `policy_definition_ids` are evaluated, first deny wins; `"enabled": false` or `{"opa_policy_config":
null}` stops enforcement. One member that fails to compile denies everything
([KI-23](known-issues.md)). If it is default-deny, give it an `input.sts` rule, or STS stops issuing tokens.

**Appliance-wide.** `fabric agent-gateway api get /v1/policy-assignments > assign.json`, edit, then
`fabric agent-gateway api put /v1/policy-assignments --file assign.json`. The PUT replaces the whole
`{"assignments": {"gateway": [{"policy_id": "<id>", "monitor_only": true}], "agent_surface": []}}`, and an enforced
entry must be enabled and must parse.

- Start with `"monitor_only": true`. A would-deny shows only as the gateway log line `monitor-only appliance-wide
  policy would deny`; audit records allow. Once enforced, a member that breaks later denies its whole plane with
  `Appliance-wide policy failed to compile`.
- The gateway plane runs on every request to an inbound listener, `proxy://` and `fabric://` send included, and
  on fabric receive, ahead of the self gateway policy. The surface plane runs on direct forwards and on every
  fabric receive, whatever the surface's own OPA setting. Neither runs on outbound calls, or on a direct request
  whose path ends in `/.well-known/agent-card.json` or `/.well-known/agent.json`, which the gateway answers before
  any policy. Both ignore `deny_reason`: the reason is always `Blocked by appliance-wide policy`.
- Both appliance-wide planes deny with 403 problem+json, `detail` `Request blocked by appliance-wide policy`, and
  the self gateway policy with `Request blocked by gateway policy`, on a deny or an evaluation error. The surface
  plane answers a `tools/call` with HTTP 200 `-32001 ... Blocked by appliance-wide policy` instead, on fabric
  receive too. On fabric receive every other deny is a 403 with a plain JSON body.

## Fail-closed and fail-open

| Situation | Result |
| --- | --- |
| `target.policy` set, no engine compiled | 403 `OPA policy enforcement is enabled but no policy is loaded for this channel` (`-32001` on `tools/call`) |
| `inbound_policy` set, no engine | deny; audit reason `No inbound policy engine loaded for surface` |
| Update with Rego that does not parse | stored; every surface that uses it in a surface slot drops its engines and denies (`fabric://` send allows, [KI-11](known-issues.md)), a per-tool entry answers `-32603` from the next call, a gateway member denies everything ([KI-23](known-issues.md)), and an enforced appliance-wide member denies its whole plane |
| Definition disabled or deleted | still enforced in surface and gateway slots; a disabled per-tool definition is skipped, and a tool whose every entry is skipped is allowed; a deleted one denies from the surface's next recompile ([KI-10](known-issues.md)) |
| Undefined `allow` | deny |
| Outbound or Transit Point policy set, not compiled, or evaluation errors | 403 problem+json, `detail` `Request blocked by surface policy`; the cause is only in the log and the audit record |
| Response policy denies, errors or has no engine | 403 `{"error":"Response blocked","code":"response_policy_denied"}`; for a `2024-11-05` request to `proxy://`, HTTP 200 `-32000` with the policy's reason, or `Response blocked by policy` when it errors or gives none |
| A `2024-11-05` MCP request whose upstream answers `text/event-stream` (not `tools/list`) | response policy never runs |
| `fabric://` send, no compiled engine | allowed ([KI-11](known-issues.md)) |
| Fabric receive, surface OPA on, no compiled engine or an evaluation error | 403 `Agent trust policy denied the request`, or HTTP 200 `-32001` `Tool '<t>' is not allowed by policy` on `tools/call`, with no reason |
| Gating condition with the wrong package | counts as false, so a deny gate stops denying |

## Rego examples

Simulate each one with the deny input given with it, and check that `allow` is false.

**R1. Require a validated JWT, block one organisation** (`inbound_policy` or `target.policy`). A token that fails
validation arrives as `source_auth.method == "failed"`. Deny input: `{"source_auth": {"method": "jwt_bearer", "subject": "u1", "claims": {"org": "blocked-org.example"}}}`.

```rego
package surface.policy
default allow := false
blocked_org if input.source_auth.claims.org == "blocked-org.example"
allow if {
	input.source_auth.method == "jwt_bearer"
	not blocked_org
}
deny_reason := "a validated JWT is required" if not input.source_auth.method == "jwt_bearer"
deny_reason := "callers from this organisation are blocked" if blocked_org
```

**R2. Allow listed DIDs only** (`target.policy`). `did_auth` is proof; `input.agent.did` is not, unless
`input.agent.did_verified` is `true`.
Deny input: `{"source_auth": {"method": "api_key", "key_name": "ci"}}`.

```rego
package surface.policy
default allow := false
allowed_dids := {"did:web:agents.example.com:billing"}
allow if {
	input.source_auth.method == "did_auth"
	input.source_auth.did in allowed_dids
}
deny_reason := "caller DID is not on the allow list" if not allow
```

**R3. Allow-list MCP tools in `target.policy`**, covering `tools/call` and the `tools/list` filter. Without the
second `allow`, the `tools/list` request itself is refused with 403. A `fabric://` target, and a `2024-11-05`
request to a `proxy://` target, have no such filter, so hide tools there with MCP Tool Gating.
Deny input: `{"mcp": {"method": "tools/list", "tool_name": "delete_everything"}}`.

```rego
package surface.policy
default allow := false
allowed_tools := {"echo", "add"}
tool_method if input.mcp.method in {"tools/list", "tools/call"}
allow if not tool_method
allow if {
	input.mcp.method == "tools/list"
	not input.mcp.tool_name
}
allow if {
	tool_method
	input.mcp.tool_name in allowed_tools
}
deny_reason := sprintf("tool %v is not allowed on this surface", [input.mcp.tool_name]) if not allow
```

**R4. Restrict egress hosts** (`transit.opa_policy_definition_id` or a Transit Point `policy`). The trailing `/`
stops look-alike hosts. Deny input: `{"gateway": {"direction": "outbound", "target_id": "https://api.partner.example.com.evil.example/"}}`.

```rego
package surface.policy
default allow := false
allowed_prefixes := ["https://api.partner.example.com/"]
allow if {
	input.gateway.direction == "outbound"
	some prefix in allowed_prefixes
	startswith(input.gateway.target_id, prefix)
}
deny_reason := sprintf("egress to %v is not allowed", [input.gateway.target_id]) if not allow
```

**R5. Allow-list A2A methods** (`inbound_policy` or `target.policy`). A v0.3 caller sends `message/send` and
`tasks/get`, a v1.0 caller `SendMessage` and `GetTask`. `input.a2a.method` keeps the caller's spelling, and
`input.a2a.method_canonical` holds the v0.3 spelling of any method the gateway recognises in either era, so one
name covers both. It covers the method only: match the role and the parts as in the refund recipe. A request with
no `input.a2a`, or with a method the gateway does not recognise, is denied too. Deny input:
`{"a2a": {"method": "ListTasks", "method_canonical": "tasks/list"}}`.

```rego
package surface.policy
default allow := false
allowed_methods := {"message/send", "tasks/get"}
allow if input.a2a.method_canonical in allowed_methods
deny_reason := sprintf("A2A method %v is not allowed on this surface", [input.a2a.method]) if not allow
```

## When it fails

| Exact text | Cause | Fix |
| --- | --- | --- |
| HTTP 200 `-32001` `Tool '<t>' is not allowed by policy: <reason>` | `inbound_policy` or `target.policy` denied a `tools/call` | read the reason |
| 403 `{"error":"Forbidden","message":"Agent trust policy denied the request"}` | a surface policy denied another request | `fabric agent-gateway audit list --category policy_decision --decision deny -o json`, field-selected as in [triage.md](triage.md#reading-audit-rows) |
| HTTP 200 `-32000` `Access denied: insufficient permissions for this tool` | per-tool policy denied, or no entry and no `"*"` | `fabric agent-gateway audit list --scope mcp_tool --decision deny -o json`, field-selected as in [triage.md](triage.md#reading-audit-rows) |
| HTTP 200 `-32001` `... not allowed by policy: Tool is not available` | MCP Tool Gating blocked it | `fabric agent-gateway surfaces tool-gate-preview <surface> --tool <tool>` names the gate that decided; patterns are unanchored ([Check MCP Tool Gating](#check-mcp-tool-gating-before-you-save-it)) |
| reason starts `Surface policy produced no` (`Policy produced no` from simulate) | wrong package or no `default allow` | declare `package surface.policy` |
| 400 `Invalid policy definition '<id>': Policy package ...` | package does not match `policy_type` | match them |
| 400 `Policy failed to compile: ...` from simulate | Rego syntax, often a v0 body without `if`; `create` and `update` accept it, and every surface that uses it then denies with `no policy is loaded for this channel` | fix the draft before `create` or `update` |
| `update` rejected for a missing field | `created_at` or another required field left out | start from `fabric agent-gateway policies get <id> -o json` |
| `tools/list` returns fewer tools, or none | `target.policy` denies the per-tool probe, which has no `trust_check_results` | allow each listed tool name on `tools/list`, as R3 does |
| permissive Rego still denies | wrong package, or a path never set (`input.caller.*`, `input.jwt` outside per-tool policies) | capture the real input |
| an A2A rule stops v0.3 or v1.0 callers only | it tests `input.a2a.method` with one spelling, names one role spelling, or tests `part.kind` | match `input.a2a.method_canonical` (R5), both role spellings and `part.text` (the refund recipe) |
| HTTP 200 `-32603` `Internal error: policy evaluation failed` | a per-tool entry's definition is unknown, empty, does not compile or errors | read `Failed to evaluate MCP tool policy` in the log |
| audit reason `No MCP tool policy configured for tool '<t>'` | per-tool policies are set and the tool has no entry and there is no `"*"` | add an entry or a `"*"` default |
| an MCP GET stream or `DELETE` is not denied | those never reach the surface policies | block them at the network, or accept them: neither reaches the upstream |
| every request 403 `Request blocked by gateway policy` after an edit | a gateway policy member failed to compile | simulate, fix, update ([KI-23](known-issues.md)) |
| STS `unauthorized_client` after attaching a gateway policy | a default-deny policy with no `input.sts` rule | add one |
| policy audit list is empty | `audit_enabled` off, or `policy_decision` not in `audit_events` | turn audit on and add the event ([operations.md](operations.md)) |

## Known issues here

[KI-10](known-issues.md), [KI-11](known-issues.md), [KI-19](known-issues.md), [KI-20](known-issues.md), [KI-21](known-issues.md),
[KI-22](known-issues.md), [KI-23](known-issues.md), [KI-24](known-issues.md), [KI-25](known-issues.md), [KI-41](known-issues.md),
[KI-47](known-issues.md).
Details and workarounds: [known-issues.md](known-issues.md).

Sources: [OPA policies](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/concepts/opa-policies/), [OPA policies reference](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/reference/surfaces/opa-policies/), [Apply OPA policies to your gateway and surfaces](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/how-to-guides/policies/apply-opa-policies/), [Apply policy to outbound calls](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/how-to-guides/policies/apply-policy-to-outbound-calls/), [Control MCP tool access with per-tool policies](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/how-to-guides/policies/control-mcp-tool-access-with-per-tool-policies/), [Use JWT claims to control access to a surface](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/how-to-guides/policies/use-jwt-claims-to-control-access-to-a-surface/), [Validate bearer tokens on a surface](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/how-to-guides/access/validate-bearer-tokens-on-a-surface/), [Add identity and access control](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/get-started/secure-a-surface/); gateway source: `src/proxy/handler.rs`, `src/identity/handlers/policy_definitions.rs`, `src/proxy/outbound_handler.rs`, `src/surface_context/mod.rs`, `src/policies/opa.rs`, `src/policies/surface_manager.rs`, `src/policies/gateway_manager.rs`; fabric's `src/commands.rs`, `src/tool_gate_preview.rs`.
