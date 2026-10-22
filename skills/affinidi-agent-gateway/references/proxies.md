# MCP and A2A proxies

An **MCP proxy** turns a REST API with an OpenAPI spec into MCP tools. An **A2A proxy** turns a Microsoft
Copilot Studio agent (Direct Line) into an A2A agent. Callers reach either one through a surface.

## Contents

- [Before you change anything](#before-you-change-anything)
- [When to use an MCP proxy](#when-to-use-an-mcp-proxy)
- [Recipe: MCP proxy from OpenAPI](#recipe-mcp-proxy-from-openapi)
- [How proxy:// differs](#how-proxy-differs)
- [Recipe: A2A proxy for Copilot Studio Direct Line](#recipe-a2a-proxy-for-copilot-studio-direct-line)
- [Delete order](#delete-order)
- [When it fails](#when-it-fails)
- [Known issues here](#known-issues-here)

## Before you change anything

`mcp-proxies list` returns every proxy's full OpenAPI spec, so reduce it with `jq`. Both kinds need the
`poweruser` role or above by default.

```bash
fabric agent-gateway runtime show surface-routing -o json
fabric agent-gateway mcp-proxies list -o json | jq '[.[] | {id, name, endpoint_path, direct_access, status}]'
fabric agent-gateway a2a-proxies list -o json | jq '[.[] | {id, name, status, backend: .backend.kind}]'
```

## When to use an MCP proxy

| You have | Target to use |
| --- | --- |
| An MCP server, or an HTTPS A2A agent | A direct target; no proxy ([surfaces.md](surfaces.md)) |
| A REST API with an OpenAPI 3.0 spec that agents should call as MCP tools | An MCP proxy behind a surface on `proxy://<proxy-id>` |
| A Copilot Studio agent that A2A callers should reach | An A2A proxy behind an A2A surface on `a2a-proxy://<proxy-id>` |

Each operation becomes one tool, named by its `operationId`, else by method and path.
Give every operation an `operationId` (tool policies match names exactly) and inline parameters: a `$ref`
parameter is left out of the tool.

## Recipe: MCP proxy from OpenAPI

**Confirm with the user:** which API the gateway will call, and who may call the surface. Until it has caller
auth ([identity.md](identity.md)), anyone who reaches the listener can call every tool.

**Before.** `REST_API_URL` is the API's base URL as the gateway reaches it. The save refuses loopback,
`localhost` and metadata hosts and resolves the name by DNS at that moment; private (RFC 1918) addresses are
allowed.

<!-- e2e: mcp-proxy-rest -->
```bash
REST_API_URL="${REST_API_URL:?set REST_API_URL to the REST API base URL, reachable from the gateway}"
fabric agent-gateway runtime show surface-routing -o json > routing.json
jq '{listen: .available_listen_addresses, channels: .channel_path_prefix, mcp: .mcp_proxy_path_prefix}' routing.json
```

**Change, step 1: the spec, as YAML.** This one has a GET with a path parameter and a POST with a body:

<!-- e2e-file: mcp-proxy-rest weather.yaml -->
```yaml
openapi: 3.0.0
info: {title: Weather, version: v1}
paths:
  /forecast/{city}:
    get:
      operationId: getForecast
      parameters:
        - {name: city, in: path, required: true, schema: {type: string}}
      responses:
        '200': {description: Forecast, content: {application/json: {schema: {type: object}}}}
  /alerts:
    post:
      operationId: createAlert
      requestBody: {required: true, content: {application/json: {schema: {type: object}}}}
      responses:
        '201': {description: Created}
```

**Step 2: build the body and dry-run it.** The spec goes in as one string, and the `description` key is
required even when empty. `"direct_access": false` serves the proxy only through surfaces, never on its own
route ([How proxy:// differs](#how-proxy-differs)). Other optional fields: `id`, your own ID of 1 to 128 ASCII
letters, digits, `-` or `_`, starting with a letter or digit (a UUID otherwise), and `flatten_post_params`, which
when `true` lists a request body's properties as top-level tool arguments instead of under `request_body`.
`validate` answers `"valid": true` or an `error` text; its `tools_count` is 0 on a valid spec and null
otherwise, so do not read it.

<!-- e2e: mcp-proxy-rest -->
```bash
PROXY_NAME="${PROXY_NAME:-weather-api}"
REST_API_URL="${REST_API_URL:?set REST_API_URL}"
MCP_PREFIX="$(jq -r '.mcp_proxy_path_prefix[0].prefix // "/mcp"' routing.json)"
jq -n --arg name "$PROXY_NAME" --arg base "$REST_API_URL" --arg prefix "$MCP_PREFIX" \
  --arg path "/$PROXY_NAME" --rawfile spec weather.yaml \
  '{name: $name, description: "", base_url: $base, channel_prefix: $prefix, endpoint_path: $path,
    openapi_spec: $spec, direct_access: false}' > proxy.json
jq '{openapi_spec, base_url}' proxy.json | fabric agent-gateway api post /v1/mcp-proxies/validate --file - -o json
```

A loopback `base_url` fails the save, even when the API runs on the gateway host:

<!-- e2e: mcp-proxy-rest expect-fail -->
```bash
jq '.base_url = "http://localhost:8080"' proxy.json | fabric agent-gateway mcp-proxies create --file - -o json
```

**Step 3: create the proxy and list its tools.** Create builds the tool server, so a bad spec fails here.
A spec that only the `2026-07-28` tool server can load still saves, and the reply's `warnings` then says
`OpenAPI spec is unavailable to the MCP 2024-11-05 tool catalog, so 2024-11-05 clients cannot use this proxy:`;
fix the spec unless every caller sends `2026-07-28`.
`discover-tools` answers `{"tools":[{"name":...}]}` and needs `secrets.view` (`administrator` by default) as well
as `mcp_proxies.edit`; neither endpoint has its own `fabric` subcommand.

<!-- e2e: mcp-proxy-rest -->
```bash
fabric agent-gateway mcp-proxies create --file proxy.json -o json > proxy-created.json
fabric agent-gateway mcp-proxies get "$(jq -r .id proxy-created.json)" -o json | jq '{id, name, status, endpoint_path}'
jq '{mcp_proxy_id: .id}' proxy-created.json | fabric agent-gateway api post /v1/mcp-proxies/discover-tools --file - -o json
```

**Step 4: a surface in front of it.** The target is `proxy://<proxy-id>` with nothing after the ID.
Take the listen address and channel prefix from the routing view: a route outside
every channel prefix never serves ([surfaces.md](surfaces.md)).

<!-- e2e: mcp-proxy-rest -->
```bash
SURFACE_NAME="${SURFACE_NAME:-weather-mcp}"
PROXY_ID="$(jq -r .id proxy-created.json)"
LISTEN_ADDRESS="${LISTEN_ADDRESS:-$(jq -r '.available_listen_addresses[0]' routing.json)}"
PREFIX="$(jq -r '.channel_path_prefix[0].prefix' routing.json)"
fabric agent-gateway surfaces create --name "$SURFACE_NAME" --protocol mcp --listen-address "$LISTEN_ADDRESS" \
  --route "$PREFIX/$SURFACE_NAME" --target-endpoint "proxy://$PROXY_ID" -o json > surface.json
jq '{surface_id, status, endpoint: .target.endpoint}' surface.json
```

**Step 5: per-tool policies, in the surface's `target.mcp_tool_policies`.** Once the list has an entry, a tool
with no entry of its own and no `"*"` entry is **denied**. The Per-tool policy bindings reference page says such a tool is allowed; the per-tool
policies how-to and the gateway agree that it is denied.
A tool policy is an ordinary surface policy (`package surface.policy`, rule `allow`) that sees the tool as
`input.mcp.params.name` ([policies.md](policies.md)). This allows `getForecast` and,
by leaving it out, blocks `createAlert`:

<!-- e2e-file: mcp-proxy-rest allow.rego -->
```rego
package surface.policy

default allow = true
```

<!-- e2e: mcp-proxy-rest -->
```bash
POLICY_ID="${POLICY_ID:-weather-forecast-allow}"
SURFACE_ID="$(jq -r .surface_id surface.json)"
fabric agent-gateway policies create --id "$POLICY_ID" --name "Allow getForecast" --policy-file allow.rego -o json > policy.json
fabric agent-gateway surfaces get "$SURFACE_ID" -o json > before.json
jq --arg proxy "$(jq -r .id proxy-created.json)" --arg pol "$POLICY_ID" \
  '.target.mcp_proxy_id = $proxy
   | .target.mcp_tool_policies = [{tool_name: "getForecast", policy_definition_id: $pol}]' before.json > tools.json
fabric agent-gateway surfaces update "$SURFACE_ID" --file tools.json -o json | jq '{surface_id, tools: .target.mcp_tool_policies}'
```

**Verify on the data plane.** `initialize` answers protocol `2024-11-05` with the proxy's name as
`serverInfo.name`, and `tools/list` has both tools. Send `Accept: application/json`:
with `text/event-stream` in it, a `proxy://` surface wraps the reply in SSE.

<!-- e2e: mcp-proxy-rest -->
```bash
LISTEN_ADDRESS="$(jq -r .access_point.listen_address surface.json)"
case "$LISTEN_ADDRESS" in http://*|https://*) BASE="$LISTEN_ADDRESS" ;; *) BASE="http://$LISTEN_ADDRESS" ;; esac
printf '%s%s\n' "$BASE" "$(jq -r .access_point.route surface.json)" > surface-url.txt
curl -sS "$(cat surface-url.txt)" -H 'Content-Type: application/json' -H 'Accept: application/json' -d \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"curl","version":"1"}}}'
echo
curl -sS "$(cat surface-url.txt)" -H 'Content-Type: application/json' -H 'Accept: application/json' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}'
```

The allowed tool reaches the API, which receives `GET /forecast/paris`: expect `result.content` and
`"isError": false`. The tool with no entry is refused before the API sees it:
HTTP 200, `"code":-32000`, `Access denied: insufficient permissions for this tool`.

<!-- e2e: mcp-proxy-rest -->
```bash
curl -sS "$(cat surface-url.txt)" -H 'Content-Type: application/json' -H 'Accept: application/json' \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"getForecast","arguments":{"city":"paris"}}}'
echo
curl -sS "$(cat surface-url.txt)" -H 'Content-Type: application/json' -H 'Accept: application/json' -d \
  '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"createAlert","arguments":{"request_body":{"city":"paris"}}}}'
```

**Undo.** **Confirm with the user:** callers lose the tools, and the policy and proxy are deleted. In this order: `fabric agent-gateway surfaces delete <surface_id>`,
`fabric agent-gateway policies delete <policy-id>`, `fabric agent-gateway mcp-proxies delete <proxy-id>`. To change the spec later, send only
the fields that change: `update` keeps the fields you leave out. An update whose spec does not load changes
nothing. Surface calls use the new spec on their next request.

**If it fails.** [When it fails](#when-it-fails).

## How proxy:// differs

- **Two MCP versions.** A `2026-07-28` request ([protocols.md](protocols.md#mcp-on-the-wire)) runs the same
  policy and credential stages as a request to an `http(s)` target, the appliance-wide surface plane, MCP Tool
  Gating and `outbound_credentials` included, and the proxy answers it in place of the upstream. It may use
  `server/discover`, `tools/list`, `tools/call` and `subscriptions/listen`; the proxy answers other methods with
  HTTP 404 `-32601` `MCP method is not implemented by this proxy`. Unless a bullet says otherwise, the rest of
  this section and the recipe above describe a `2024-11-05` request.
- **Fewer policy slots.** A `2024-11-05` request runs the appliance-wide gateway plane, the gateway policy, the
  inbound, surface, per-tool and response policies and MCP Tool Gating, which also filters `tools/list`, but not
  the appliance-wide surface plane, so a deny there does not cover it. Its `outbound_credentials` are never
  resolved: no consent prompt and no delegated token ([credentials.md](credentials.md)). A payment policy does
  apply: it runs before the proxy answers ([protocols.md](protocols.md#paywalled-surfaces)).
- **The HTTP+SSE transport as well.** Besides Streamable HTTP POSTs, the surface serves the
  `2024-11-05` HTTP+SSE transport. `GET <route>/sse` runs `inbound_policy` and `target.policy`, then opens a
  stream whose first `endpoint` event names the surface route. A `POST <route>/mcp/messages?session_id=<id>`
  gets 202, and its reply arrives on that stream; an unknown or closed session gets 404 problem+json `SSE
  session not found or expired`, and a body that is not JSON gets 400 `Invalid JSON-RPC request`. The gateway
  holds at most 10,000 such sessions; past that, after dropping those whose client has gone, a `GET` gets 429
  `Too many active SSE sessions`.
- **The proxy's own route.** When `gateway.json` has a top-level `mcp_proxies` prefix list
  (`mcp_proxy_path_prefix` in the routing view), a proxy whose `direct_access` is `true`, the default, is also
  served under those prefixes with no surface or gateway policy, and with no caller auth
  ([identity.md](identity.md)) unless the proxy's `mcp_http.authorization` demands a resource token. A
  `2024-11-05` request on that route forwards the caller's headers to the REST API, `Authorization` included
  when no token is demanded. Create a proxy with `"direct_access": false` unless a caller needs that route: the
  route then answers as if no proxy had that path.
- **Backend credentials come from the surface:** `target.auth` with a stored secret's `secret_id`
  ([credentials.md](credentials.md)). A secret that does not resolve gives HTTP 502
  `Target authentication configuration error` under the default `fallback: reject`, or
  `Target authentication failed: <detail>` for a `2026-07-28` request.
- **Tools only.** For a `2024-11-05` request the built-in server answers `initialize`, `tools/list` and
  `tools/call`, and tool-layer failures come back as HTTP 200, code -32603, `MCP proxy error: <detail>`. A
  `2026-07-28` request gets its JSON-RPC error with an HTTP error status, and a REST call that cannot be sent, or
  whose reply cannot be read, gives a result with `"isError": true`. The tools come from the rmcp-openapi crate.

## Recipe: A2A proxy for Copilot Studio Direct Line

Copilot Studio's Direct Line is the only backend ([KI-28](known-issues.md)). The proxy takes only the send method,
`message/send` or its A2A v1.0 spelling `SendMessage`, with text parts only (a part with `kind: "text"`, or a v1.0
part with `text` and no `kind`), and opens a new Direct Line conversation for every call, so the bot keeps no
context between messages. The gateway checks `A2A-Version` and the JSON-RPC envelope first
([protocols.md](protocols.md#a2a-on-the-wire)) but never the A2A request shape, so a malformed message gets the
proxy's own `-32602`. A surface whose target is an A2A proxy has fixed versions in its `access_point.a2a`:
`["1.0"]` when it is created or its target moves to an A2A proxy, and what is stored after that. So the callers of
a new one send `A2A-Version: 1.0`; one that sends no header counts as `0.3` and gets `-32009`. A save that names
other versions is refused. A surface that already had an A2A proxy target before per-surface settings was given
both versions when it was first loaded, or `["1.0"]` where the retired `a2a_legacy_compatibility` flag was `false`
([protocols.md](protocols.md#a2a-surface-settings)), so it keeps serving `0.3` callers, and a save that asks it
for `["1.0"]` gets 400 `... are fixed at [0.3, 1.0]`. A live check needs a published Copilot Studio agent; without
one you can check the save.

In front of an A2A proxy the gateway always checks only the envelope, so `validation` applies only to a variant
that points the target at something other than an A2A proxy. Without such a variant, a save that sets a level
other than `envelope` and other than the stored one is refused, and an edit that removes the last such variant
resets the stored level to `envelope`.

**Confirm with the user:** the agent is published, and its Direct Line secret may be stored on the gateway.
**Before.** `fabric agent-gateway a2a-proxies list -o json`, and `fabric agent-gateway secrets list -o json` for the secret's `secret_id`.

**Change.** `backend.secret_id` is a stored secret's `secret_id`, not its UUID and not the value. The gateway
checks it before any other field, so a wrong reference fails with `A2A proxy secret is not accessible` and
nothing is saved:

<!-- e2e: a2a-proxy-validation expect-fail -->
```bash
A2A_PROXY_NAME="${A2A_PROXY_NAME:-copilot-hr}"
jq -n --arg name "$A2A_PROXY_NAME" \
  '{name: $name, backend: {kind: "copilot_direct_line", secret_id: "no-such-direct-line-secret"}}' > a2a-bad.json
fabric agent-gateway a2a-proxies create --file a2a-bad.json -o json
```

<!-- e2e: a2a-proxy-validation -->
```bash
A2A_PROXY_NAME="${A2A_PROXY_NAME:-copilot-hr}"
fabric agent-gateway a2a-proxies list -o json | jq --arg n "$A2A_PROXY_NAME" '{name: $n, saved: ([.[] | select(.name == $n)] | length)}'
```

With the Direct Line secret stored as `copilot-direct-line` ([credentials.md](credentials.md)), create the proxy
and an A2A surface under a channel prefix; `a2a-proxy://` is refused on MCP surfaces:

```bash
jq -n '{name: "copilot-hr", backend: {kind: "copilot_direct_line", secret_id: "copilot-direct-line"}}' |
  fabric agent-gateway a2a-proxies create --file - -o json > a2a-created.json
fabric agent-gateway surfaces create --name copilot-hr --protocol a2a --listen-address "<listen-address>" \
  --route "<channel-prefix>/copilot-hr" --target-endpoint "a2a-proxy://$(jq -r .id a2a-created.json)" -o json
```

Optional `backend` fields: `credential_mode`, `base_url` (private, loopback and link-local
IP literals and `localhost` are refused at save; another hostname that resolves into those ranges saves and then
fails on each call),
`timeout_secs`, `poll_interval_ms`, `max_poll_attempts`. `timeout_secs` bounds the
polling, not the total: each Direct Line call has its own `timeout_secs` limit, so a reply can take about two to
three times as long. Without `agent_identity` the API uses the proxy-managed subject,
not the dashboard's Entra default.

**Verify.** The gateway writes the agent card. `name` is the card override or the **surface** name.
`supportedInterfaces[]` has one entry per version the surface accepts, so only `1.0` on a new surface, each with
`protocolBinding` `JSONRPC`, its `protocolVersion` and a `url` ending in `<route>/rpc`. The first entry is the
preferred version: `[a2a] default_version` when the surface accepts it, else the first version it does accept
([protocols.md](protocols.md#a2a-surface-settings)). While the surface accepts `0.3`, the card also carries the v0.3
fields `protocolVersion`, `url` (the same `<route>/rpc`), `preferredTransport`, `agentProvider` and
`supportsAuthenticatedExtendedCard`. `capabilities.extendedAgentCard`, `streaming` and `pushNotifications` are
`false`. Fetch `<listen-address><route>/.well-known/agent-card.json`, then POST a `SendMessage` with
`A2A-Version: 1.0` and one text part to `<listen-address><route>/rpc`. The docs' test sends `message/send` with
no `A2A-Version` header, which a new A2A proxy surface refuses with 400 `-32009`. Expect the A2A 1.0 reply:
`result.message`, with `role` `ROLE_AGENT` and parts without `kind`. The reply follows the spelling of the send
method, not the `A2A-Version` header: a `message/send` gets the v0.3 reply, the message itself as `result`, with
`kind` `message` and `role` `agent`. A rejected secret is JSON-RPC -32020 in HTTP 200, not an HTTP 401.

**Undo.** **Confirm with the user:** A2A callers of the route stop being served. Delete the surface, then
`fabric agent-gateway a2a-proxies delete <proxy-id>`, then the secret if nothing else uses
it. Rotating the secret needs no proxy change: it is read on every call.

**If it fails.** [When it fails](#when-it-fails).

## Delete order

Delete or re-point the surfaces first. A proxy delete runs at once, checks no references, and leaves its surfaces
pointing at nothing ([KI-34](known-issues.md)). Find them with:

```bash
fabric agent-gateway surfaces list -o json | jq --arg id "<proxy-id>" \
  '[.[] | select(.target.endpoint == "proxy://\($id)" or .target.endpoint == "a2a-proxy://\($id)") | .surface_id]'
```

## When it fails

| Exact text | Cause | Fix |
| --- | --- | --- |
| `URL host '<h>' is blocked: cloud-provider metadata services and loopback addresses`, `URL host '<h>' resolves to blocked address`, `DNS resolution failed for '<host>'` | MCP `base_url` is loopback or metadata, resolves to one, or does not resolve on the gateway | A host the gateway resolves to a non-loopback address |
| `Endpoint path must start with '/'`, `Failed to create MCP Server:` (such as `Failed to create MCP Server: Failed to load modern tool routing:`), `Failed to reload MCP Server:` | No leading slash, or the spec does not load; a failed update changes nothing | Fix the path; run `validate`, fix the spec, send it again |
| `MCP proxy reference is not accessible` | Surface save: the `proxy://` ID is unknown or in another tenant | An ID from `fabric agent-gateway mcp-proxies list` |
| HTTP 404 `MCP proxy '<id>' not found` (`MCP proxy was not found` for `2026-07-28`); -32603 `MCP proxy is disabled` (HTTP 503 `MCP proxy is unavailable` for `2026-07-28`) | Proxy deleted, a path after the ID, or `status` `disabled` | Re-point the surface, or update the proxy with `{"status":"active"}` |
| -32603 `MCP proxy error: Unknown MCP method: <m>`; on the proxy's own route, 400 `Unknown MCP method: <m>`; for `2026-07-28`, 404 `-32601` `MCP method is not implemented by this proxy` | A method the proxy does not serve, notifications included (the proxy's own route answers `notifications/initialized` with 204) | Expected for notifications; otherwise call a tool |
| -32603 `MCP proxy error: Tool execution timed out after <d>`; for `2026-07-28`, 504 `MCP proxy execution timed out` or `MCP tool execution timed out` | The REST API did not answer in time: within `timeout.request_secs`, or 30 s for `2026-07-28` when that is unset | Check the API from the gateway host |
| 404 `SSE session not found or expired` on a surface; `SSE session '<id>' not found or expired`, 410 `SSE session disconnected`, 400 `Missing session_id query parameter` on the proxy's own route | An HTTP+SSE `POST .../mcp/messages` whose `GET .../sse` stream closed, never opened, or is not named | Open the stream again and POST to the `endpoint` it names |
| 404 `No MCP proxy configured for path: <p>`; 500 `MCP server not initialized` | The proxy's own route: no proxy with `direct_access` on has that `endpoint_path` under an `mcp_proxy_path_prefix` prefix, or its `2024-11-05` tool server did not load (its save gave a `warnings` entry) | Check `endpoint_path` and `direct_access`; run `validate` on the spec and update the proxy |
| -32603 `MCP proxy error: Tool '...' not found`, `MCP proxy error: Tool execution failed:`; for `2026-07-28`, 400 `-32602` `Tool was not found` or `Invalid tool arguments`, or a result with `"isError": true` and `Tool execution failed` | Wrong tool name or arguments, or the REST API is unreachable from the gateway | Names from `tools/list`; check `base_url` from the gateway host |
| -32000 `Access denied: insufficient permissions for this tool` | Tool policy denied, or no entry and no `"*"` | Add an entry or a `"*"` default |
| -32001 `Tool '<name>' is not allowed by policy: Tool is not available` | MCP Tool Gating hides the tool | Check `target.mcp_tool_gating` ([policies.md](policies.md#check-mcp-tool-gating-before-you-save-it)) |
| -32000 with a policy reason, or `Response blocked by policy` | The response policy denied or errored after the API answered | Fix the response policy |
| HTTP 502 `Target authentication configuration error` (`Target authentication failed: <detail>` for `2026-07-28`) | `target.auth` names a secret that does not resolve | Create the secret or fix `secret_id` |
| `A2A proxy secret is not accessible` | `backend.secret_id` is a UUID, a name, blank, or another tenant's | The `secret_id` from `fabric agent-gateway secrets list` |
| `backend.base_url is not a permitted egress target` | Private, loopback or metadata IP literal, or `localhost`, as the Direct Line URL | The public endpoint |
| -32020 `A2A proxy target blocked by egress policy:` | The Direct Line hostname resolves to a private, loopback or metadata address | The public endpoint |
| `target A2A Proxy configuration is invalid` | `a2a-proxy://` on an MCP surface | Protocol `a2a` or `ap2` |
| -32601 `Unsupported A2A method` | Not `message/send` or `SendMessage`: streaming, task and extended-card methods included | Send `message/send` or `SendMessage` |
| -32602 `A2A proxy supports text parts only`, `Missing params.message`, `Missing message parts`, `message parts must not be empty`, `Text part is missing text` | A non-text part, or a message without text | One or more text parts |
| HTTP 400 -32700 `Parse error: invalid JSON`; HTTP 200 -32700 `Parse error` for an empty body | The body is not JSON | Send a JSON-RPC body |
| HTTP 400 -32009 `Unsupported A2A protocol version '0.3'` with `"supported": ["1.0"]` | The caller sent no `A2A-Version` header, or `0.3`, to a surface that accepts `1.0` only | Send `A2A-Version: 1.0` |
| HTTP 400 `the accepted A2A versions of a surface whose Target is an A2A proxy are fixed at [...]` | A surface save named other versions for an A2A proxy target | Leave `accepted_versions` out, or send the fixed ones |
| HTTP 400 `an A2A proxy target always checks the JSON-RPC envelope only, ...` | A surface save set `validation` other than `envelope` where every target is an A2A proxy | Set `access_point.a2a.validation` to `envelope` |
| -32020 `A2A proxy not found`, `A2A proxy is disabled` | The `a2a-proxy://` ID is deleted, or the proxy's `status` is `disabled` | Re-point the surface, or set the proxy's `status` back to `active` |
| -32020 `Direct Line secret not found` | `backend.secret_id` does not resolve | Store the secret again under that `secret_id` |
| -32020 `A2A proxy target DNS resolution failed:` | The Direct Line host does not resolve from the gateway | Fix `base_url`, or the gateway's DNS |
| -32603 `A2A proxy request failed` | An unexpected failure in the proxy; the gateway log has the cause | Read the log |
| -32020 `Direct Line conversation creation failed:` | Direct Line refused the secret or is unreachable | Rotate the secret; try `credential_mode: generate_token` |
| -32021 `A2A proxy target timed out` | No bot reply within `timeout_secs` | Raise `timeout_secs`; check the agent is published |

## Known issues here

- [KI-28](known-issues.md): the A2A proxy speaks only Copilot Direct Line.
- [KI-34](known-issues.md): deletes have no prompt, and a proxy delete does not check references.

Sources: [Enable A2A communication with a Copilot Studio agent](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/how-to-guides/setup/enable-a2a-communication-with-a-copilot-studio-agent/), [Expose a REST API as MCP tools](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/how-to-guides/setup/expose-a-rest-api-as-mcp-tools/), [A2A Proxy](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/reference/proxies/a2a-proxy/), [MCP Proxy](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/reference/proxies/mcp-proxy/), [Per-tool policy bindings](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/reference/surfaces/mcp-proxy-tool-policies/); gateway source: `src/mcp_proxies/handlers.rs`, `src/mcp_proxies/types.rs`, `src/proxy/handler.rs`, `src/identity/handlers/surfaces.rs`, `src/mcp/request_validation.rs`, `src/a2a_proxies/runtime.rs`, `src/a2a_proxies/agent_card.rs`, `src/url_validation.rs`; fabric's `src/commands.rs`.
