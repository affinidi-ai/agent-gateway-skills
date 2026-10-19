# MCP and A2A on the wire

What a client sends and receives when it talks to a surface, for both protocols, and what that means
for real clients. Load this when a client cannot connect, when you see `-32022`, `-32009`, `-32602` or 406,
when an agent card looks wrong, when choosing between MCP and A2A or between A2A v0.3 and v1.0, or when a
surface must charge for calls.

## Contents

- [Before you change anything](#before-you-change-anything)
- [Two protocols](#two-protocols)
- [MCP on the wire](#mcp-on-the-wire)
- [MCP client matrix](#mcp-client-matrix)
- [A2A on the wire](#a2a-on-the-wire)
- [Worked example: an A2A agent over HTTPS, end to end](#worked-example-an-a2a-agent-over-https-end-to-end)
- [Worked example: your own MCP server behind the gateway](#worked-example-your-own-mcp-server-behind-the-gateway)
- [Paywalled surfaces](#paywalled-surfaces)
- [Error shapes per protocol](#error-shapes-per-protocol)
- [When it fails](#when-it-fails)
- [Known issues here](#known-issues-here)

## Before you change anything

These read-only commands tell you what a client will reach. No `fabric` command calls a surface;
clients use curl or an MCP or A2A client, as in the recipes below.

| Command | What it tells you |
| --- | --- |
| `fabric agent-gateway runtime show surface-routing -o json` | Inbound listen addresses (`available_listen_addresses`) and channel prefixes (`channel_path_prefix`). A surface is reachable at its listen address plus its route. |
| `fabric agent-gateway surfaces get <SURFACE_ID> -o json` | `access_point.protocol`, `access_point.route`, `access_point.listen_address`, `target.endpoint`, any `target.payment_policy`, and on an MCP surface any `mcp_http` limits (absent means the defaults). |
| `fabric agent-gateway runtime show x402` | The appliance-wide x402 configuration. A 500 means the gateway has no x402 configuration file. |
| `fabric agent-gateway payments list` | Payment records from the x402 and MPP stores. |

## Two protocols

A surface speaks one protocol at both ends: `a2a` (the `fabric agent-gateway surfaces create` default), `mcp`, `ap2`
or `didcomm`, with no translation between them. Choose MCP for a model client
that lists and calls tools, A2A for an agent that sends messages and tracks tasks; a REST API without
an MCP server goes behind an MCP proxy ([proxies.md](proxies.md)). A method of the other protocol
(`message/*`, `tasks/*`, `agent/getAuthenticatedExtendedCard` and the A2A v1.0 names such as `SendMessage`
and `GetTask` are A2A; `tools/*`, `prompts/*` and `resources/*` are MCP) gets 422 problem+json with the
`detail` `Request protocol 'a2a' does not match access point protocol 'mcp'`, or the reverse. Any other method,
`initialize` included, passes this check, and on an MCP surface so does every `2026-07-28` request
(rule 1 below). AP2 is experimental: with the `ap2_experimental` feature flag off, the default, an AP2 POST
with a body gets 501, and with the flag on a request that carries a mandate still gets 501. DIDComm is the gateway-to-gateway transport ([g2g.md](g2g.md)).

Limits added by the extra hop:

- On an MCP surface, every request meets the surface's `mcp_http` limits, whatever its MCP version, before
  any MCP handling: headers over `max_header_bytes` (16 KiB by default) get 431, an `Origin` header that
  names neither the origin of an inbound listener's `external_urls` nor an `allowed_origins` entry gets
  403, and a body over `max_request_bytes` (1 MiB by default) gets 413, each with JSON-RPC `-32600`. A
  request without `Origin` passes, so `allowed_origins` matters only to browser-based clients. Change the
  limits in the surface's `mcp_http` object, for example
  `fabric agent-gateway surfaces update <SURFACE_ID> --set 'mcp_http={"allowed_origins":["https://app.example.com"]}'`;
  each entry must be an exact origin, and fields you leave out keep their values or defaults. A surface whose
  Access Point is not MCP refuses the object with `mcp_http requires an MCP Access Point`.
- On any surface whose target is not `fabric://`, a body over `[a2a] max_body_size`, 10 MiB by default, gets
  413 problem+json; the check does not test the protocol.
- `2024-11-05` POSTs that accept SSE, and MCP GETs that reach the upstream (a `/sse` path, or no SSE
  `Accept`), get a 24 h upstream timeout; plain JSON POSTs keep the surface's request timeout. A
  `2026-07-28` request gets 504 `Modern MCP upstream response headers timed out` when the upstream's
  headers take longer than the surface's request timeout (30 s when unset). A streamed answer on either
  version, a `2024-11-05` `text/event-stream` passthrough included, is cut off after
  `mcp_http.stream_idle_timeout_secs` without data (60 by default) or `stream_max_lifetime_secs` in all
  (3600 by default), so an upstream that is quiet for longer between events needs a larger idle timeout. The
  GET notification stream never reaches the upstream.

## MCP on the wire

The gateway serves MCP `2024-11-05` and `2026-07-28` on every MCP surface, and no setting turns either
off. A request without the `2026-07-28` signals in rule 1 is `2024-11-05` traffic, handled in stateless
session mode: on a direct target every request is forwarded to `target.endpoint`, including one whose
method the gateway does not know. An `initialize` that asks for any other version is forwarded asking for
`2024-11-05` instead (`cap_legacy_initialize` in `src/mcp/request_validation.rs`), and the upstream's
result comes back with its `protocolVersion` untouched, so a client settles on `2024-11-05` whenever the
upstream serves it. These rules decide whether a client gets through:

1. **The version gate.** A POST is checked as a `2026-07-28` request when it has an `MCP-Protocol-Version`
   header other than a single `2024-11-05`, an `Mcp-Method` or `Mcp-Name` header, or an
   `io.modelcontextprotocol/protocolVersion`, `clientCapabilities`, `clientInfo` or `logLevel` key in
   `_meta`. The check runs after caller authentication, the rate limit and the `mcp_http` limits, before
   other MCP handling, on every target, and no setting widens it (`validate_mcp_post` in
   `src/mcp/request_validation.rs`).
   - A version the gateway does not serve, such as `2025-06-18`, gets HTTP 400 with JSON-RPC `-32022`
     "Unsupported protocol version", `data.requested` and `data.supported`: `2024-11-05` and `2026-07-28`,
     or only those of them the upstream listed when a client last ran `server/discover` through the
     surface in the past five minutes, and only `2024-11-05` when the upstream answered that with `-32601`
     (`restrict_unsupported` in `src/mcp/upstream_versions.rs`). A request
     is refused on its header alone; a notification is refused when its header or `_meta` names the version.
   - A complete `2026-07-28` request has the version header, `Mcp-Method`, `Mcp-Name` on `tools/call`,
     `resources/read` and `prompts/get`, and both `io.modelcontextprotocol/protocolVersion` and
     `clientCapabilities` in `params._meta`. It also needs `Content-Type: application/json` (415
     otherwise) and an `Accept` that names both `application/json` and `text/event-stream` (406 otherwise).
     A `proxy://` target answers `server/discover`, `tools/list`, `tools/call` and `subscriptions/listen`
     itself, and any other method with 404 `-32601` `MCP method is not implemented by this proxy`. A direct target gets the
     request without `Mcp-Session-Id` and `Last-Event-ID`, and the gateway checks the answer as a
     `2026-07-28` result: when the upstream answers in the `2024-11-05` shape, without `resultType`, the
     caller gets HTTP 502 `Invalid modern MCP upstream response`.
   - A request whose header names `2026-07-28` but that has no `params._meta` gets `-32602` `Modern MCP
     requests require params._meta`, and so does a `2024-11-05` client that also sends `Mcp-Method` without
     `params._meta`. `-32602` `MCP 2024-11-05 cannot use modern per-request metadata or mirrored headers`
     goes to a complete request that names `2024-11-05` in `params._meta`, and to a notification that
     sends `Mcp-Method` or `Mcp-Name` with `MCP-Protocol-Version: 2024-11-05` (the same notification without
     the version header gets 204). The gate's error texts are in [When it fails](#when-it-fails).
2. **One JSON object per POST, sent as JSON, that every parser reads the same.** With no `2026-07-28` signal
   from rule 1, a POST whose `Content-Type` lacks `application/json`, or whose body has no top-level
   `"jsonrpc": "2.0"`, gets HTTP 200 with JSON-RPC `-32600` `Invalid JSON-RPC request`, and a body that is not
   JSON gets HTTP 200 `-32700` `Invalid JSON` with `data.details`. JSON that is not an object, an object with
   two keys that are equal or differ only in case at any depth, and a field the gateway reads spelled in
   another case (`Method`, `params.Name`) also get HTTP 200 `-32600` `Invalid JSON-RPC request`; a batch
   array gets 422 problem+json `JSON-RPC batches are not supported`. With a `2026-07-28` signal the same
   faults are HTTP 400: `-32700` `Invalid JSON: <e>`, `-32600` `Modern MCP POST body must be one JSON-RPC
   object`, or `-32600` `Invalid JSON-RPC request` for ambiguous keys (`single_object_refusal` in
   `src/mcp/tool_analyzer.rs`). Access Points, Transit Points and fabric receive all apply this.
3. **`2024-11-05` notifications stop at the gateway.** On a direct target, a notification such as
   `notifications/initialized` gets 204 with an empty body and is never forwarded. Any other message
   without an `id` gets the same, a `tools/call` included, unless rule 1 refuses it or admits it as
   `2026-07-28`: it never reaches the upstream, and only the gateway-level policies see it; no surface or
   per-tool policy evaluates it. On a `proxy://` target the same notification gets HTTP 200 with JSON-RPC
   `-32603` `MCP proxy error: Unknown MCP method: <method>`, which clients ignore for a notification. A
   `2026-07-28` notification is forwarded instead, and the upstream's 202 comes back; a `proxy://` target
   answers it with 404 `-32601`.
4. **`Accept` must include `text/event-stream`.** On a `2024-11-05` POST that includes it, the gateway asks
   the upstream for `text/event-stream, application/json`. When it does not, the client's `Accept` goes
   upstream unchanged, and a spec-strict MCP server answers 406, which the gateway relays. A `2026-07-28`
   request whose `Accept` does not name both `application/json` and `text/event-stream` gets 406 from the
   gateway itself.
5. **Sessions.** On `2024-11-05`, if the client accepts SSE and the upstream answers JSON, the reply comes
   back as one SSE `message` event, and an `initialize` reply gets a gateway-minted `Mcp-Session-Id`. With
   `Accept: application/json` alone nothing is wrapped or minted. The gateway never checks the ID later: an
   unknown ID is admitted, and a known one is used only for the gateway's own elicitation. The client's
   `Mcp-Session-Id` and `MCP-Protocol-Version` headers go upstream unchanged, and the upstream's
   `Mcp-Session-Id` comes back, so an upstream that sets one on an SSE-wrapped `initialize` gives the
   client two `Mcp-Session-Id` headers, the upstream's first ([KI-51](known-issues.md)). `tools/list` is
   always buffered so filtering and MCP Tool Gating can run; other SSE replies stream through. A
   `2026-07-28` request has no session: the gateway removes `Mcp-Session-Id` and `Last-Event-ID` before
   forwarding it and mints none.
6. **The GET stream and `DELETE` are the gateway's own.** A `GET` with `Accept: text/event-stream`, on any
   path but `/sse`, opens the gateway's notification stream, and any `DELETE` gets 204. Either one with
   `MCP-Protocol-Version: 2026-07-28` gets 405 with `Allow: POST` instead, and either one with a repeated or
   unreadable `MCP-Protocol-Version` gets 400 `-32020` `MCP-Protocol-Version requires one valid header
   value`. `PUT`, `PATCH` and any method other than `POST`, `GET`, `DELETE`, `HEAD` and `OPTIONS` get 405,
   and a body on any method but `POST` gets 400 `-32600` `Only MCP POST requests may carry a body`. Neither
   the stream nor the `DELETE` reaches the upstream, so a stateful upstream never learns that a session ended. Both
   are answered after the gateway policies and payment but before `inbound_policy`, the appliance-wide
   surface plane and `target.policy`, so a surface policy that denies everything still lets them through
   ([KI-48](known-issues.md)). A `GET` that names an `Mcp-Session-Id` while the stream registry is full
   gets 429 `Too many active SSE sessions` as `text/plain`.
7. **Server-to-client requests cannot be answered.** A `2024-11-05` POST that carries a JSON-RPC response
   (an `id` with `result` or `error` and no `method`) gets 202 and is not forwarded; it only completes an
   elicitation the gateway itself started ([credentials.md](credentials.md)). An upstream's
   `sampling/createMessage`, `roots/list` or `elicitation/create` does reach the client inside a POST's
   SSE stream, but the client's answer never reaches the upstream ([KI-50](known-issues.md)).
8. **HTTP+SSE upstreams.** When a direct upstream answers a `2024-11-05` POST to the surface route
   with 400, 404 or 405, the gateway retries the body over the `2024-11-05` HTTP+SSE transport (`GET
   <target.endpoint>/sse`, then a POST to the endpoint that stream names) and returns the reply as JSON.
   The retry carries no `target.auth` and none of the caller's headers, its reply skips the `tools/list`
   filter and the response policy, and the gateway logs the request body at INFO
   ([KI-49](known-issues.md)). Serve Streamable HTTP at `target.endpoint` instead.

### Recipe: check the version gate on a surface

Run this against a new MCP surface in front of your server: the gateway asks the upstream for
`2024-11-05`, absorbs the notification and refuses a version it does not serve, and a `2026-07-28` request
shows whether the upstream serves that version too. Set `UPSTREAM_URL` to the server's URL.

**Before.** Nothing existing changes: the recipe makes its own surface.

**Change.** **Confirm with the user:** this creates a test surface and deletes it at the end. Create the surface:

<!-- e2e: mcp-version-gate -->
```bash
UPSTREAM_URL="${UPSTREAM_URL:?set UPSTREAM_URL to your MCP server URL}"
SURFACE_NAME="${SURFACE_NAME:-weather-mcp}"
fabric agent-gateway runtime show surface-routing -o json > routing.json
LISTEN_ADDRESS="$(jq -r '.available_listen_addresses[0]' routing.json)"
PREFIX="$(jq -r '.channel_path_prefix[0].prefix' routing.json)"
fabric agent-gateway surfaces create --name "$SURFACE_NAME" --protocol mcp --listen-address "$LISTEN_ADDRESS" \
  --route "$PREFIX/$SURFACE_NAME" --target-endpoint "$UPSTREAM_URL" -o json > surface.json
jq '{surface_id, status, url: (.access_point.listen_address + .access_point.route)}' surface.json
```

**Verify.** Send `initialize` asking for `2025-11-25`, as a client on a later MCP version does. Expect HTTP 200
and `protocolVersion` `2024-11-05`: the gateway asked the upstream for `2024-11-05`. Any other version means
the upstream does not serve `2024-11-05` (see If it fails):

<!-- e2e: mcp-version-gate -->
```bash
URL="$(jq -r '.access_point.listen_address + .access_point.route' surface.json)"
curl -sS -w '\nHTTP %{http_code}\n' "$URL" -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"curl","version":"1"}}}'
```

Send `notifications/initialized`. Expect HTTP 204; the upstream never sees it:

<!-- e2e: mcp-version-gate -->
```bash
URL="$(jq -r '.access_point.listen_address + .access_point.route' surface.json)"
curl -sS -o /dev/null -w 'HTTP %{http_code}\n' "$URL" -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","method":"notifications/initialized"}'
```

Send what a client sends after an upstream negotiated `2025-06-18`, a version the gateway does not serve.
Expect HTTP 400, `-32022` and `data.supported` listing `2024-11-05` and `2026-07-28`:

<!-- e2e: mcp-version-gate -->
```bash
URL="$(jq -r '.access_point.listen_address + .access_point.route' surface.json)"
curl -sS -w '\nHTTP %{http_code}\n' "$URL" -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' -H 'MCP-Protocol-Version: 2025-06-18' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'
```

The same call with `2024-11-05` passes. Expect HTTP 200 and the tool list:

<!-- e2e: mcp-version-gate -->
```bash
URL="$(jq -r '.access_point.listen_address + .access_point.route' surface.json)"
curl -sS -w '\nHTTP %{http_code}\n' "$URL" -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' -H 'MCP-Protocol-Version: 2024-11-05' \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/list","params":{}}'
```

Send a complete `2026-07-28` request. The gateway admits and forwards it: expect the upstream's result with
`resultType` if the upstream serves `2026-07-28`, or HTTP 502 `Invalid modern MCP upstream response` if it
answers only in the `2024-11-05` shape. A `-32602` or `-32020` means the request's shape is wrong, not its
version:

<!-- e2e: mcp-version-gate -->
```bash
URL="$(jq -r '.access_point.listen_address + .access_point.route' surface.json)"
curl -sS -w '\nHTTP %{http_code}\n' "$URL" -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' -H 'MCP-Protocol-Version: 2026-07-28' \
  -H 'Mcp-Method: tools/list' -d '{"jsonrpc":"2.0","id":4,"method":"tools/list","params":{"_meta":
  {"io.modelcontextprotocol/protocolVersion":"2026-07-28","io.modelcontextprotocol/clientCapabilities":{}}}}'
```

**Undo.** Run `fabric agent-gateway surfaces delete <SURFACE_ID>`; it does not ask for confirmation
([KI-34](known-issues.md)).

**If it fails.** If `initialize` comes back with a version other than `2024-11-05`, the upstream does not
serve `2024-11-05`, and a client that echoes that version on its next POST is refused: make the upstream
serve `2024-11-05`, or front the service with an MCP proxy (`proxy://`), whose built-in server answers
`initialize` with `2024-11-05` and serves `2026-07-28` discovery, `tools/list`, `tools/call` and
`subscriptions/listen`. A 502 on
the `2026-07-28` request means this upstream's clients must use `2024-11-05`. A 403 means the request
carried an `Origin` the surface does not allow, and a 413 or 431 that it exceeded the surface's `mcp_http`
limits.

## MCP client matrix

A spec-current client echoes the negotiated version in `MCP-Protocol-Version` on every POST after
`initialize`, starting with `notifications/initialized`, so the version the upstream answers decides. The
gateway asks the upstream for `2024-11-05` on every `initialize`, so a session settles on `2024-11-05`
unless the upstream does not serve it. The gateway-side facts are read from gateway source.
Every client cell is an inference from reading that client's code at the version named: unverified
until a live probe against a gateway confirms it.

| Client (version read) | Direct target, upstream serves `2024-11-05` | Direct target, upstream answers a later version | `proxy://` target | GET stream for `elicit` |
| --- | --- | --- | --- | --- |
| Claude Code 2.1.280 | Connects | Fails at `notifications/initialized` with 400 `-32022` | Connects | Never opened: it waits for a 202 and gets 204 |
| VS Code 1.138.0 | Connects; logs the 204 as unexpected | Connects: it sends no version header | Connects | Opened after the first POST |
| MCP Inspector, `mcp-remote` (TypeScript SDK 1.30.0) | Connects | Fails at `notifications/initialized` | Connects | Never opened |
| GitHub Copilot CLI, Claude Desktop native connectors, Cursor | Not inspected | Not inspected | Not inspected | Not inspected |
| curl or a hand-written client | Works without a version header | Works without a version header | Works | Only with a manual GET and `Mcp-Session-Id` |

What follows for an operator (inference from the table):

- To serve spec-current clients through a direct target, the upstream must serve `2024-11-05`, which the
  gateway asks it for, or the service must sit behind an MCP proxy. The clients listed send both
  `Accept` types, so a 406 points at curl or a hand-written client.
- On `2024-11-05`, `elicit` consent needs a client that opens the GET stream; of the clients read, only
  VS Code does. Which clients handle each consent mode is in [credentials.md](credentials.md).

## A2A on the wire

An A2A surface relays JSON-RPC to the agent at `target.endpoint`. The gateway accepts A2A v0.3 and v1.0 and
never translates between them: the caller and the agent must speak the same version, and the agent card
tells callers which one the agent speaks. Before forwarding to a direct `http(s)` target it runs three
checks, in this order, and a refused request is not forwarded:

1. **Version.** The `A2A-Version` request header names the caller's version. No header, or an empty one,
   means `0.3`, and only major and minor count, so `1.0.1` is `1.0` and a bare `1` is refused. A version
   the gateway does not accept gets HTTP 400 with `id: null` and JSON-RPC `-32009` `Unsupported A2A
   protocol version '<v>'`, with `data.requested` and `data.supported`. This check runs whatever
   `validate_messages` says, and a request that also fails a later check reports only the version.
2. **Envelope.** With `[a2a] validate_messages` on in `config.toml`, which is the default, the body must be
   JSON with `jsonrpc` equal to `"2.0"` and a string `method`. Otherwise the caller gets HTTP 400 with
   `id: null` and `-32700` `Parse error: invalid JSON`, or `-32600` `Invalid JSON-RPC: missing or invalid
   'jsonrpc' field` or `... 'method' field`.
3. **Request shape.** Under the same setting, `params`, when present, must be an object or an array for
   every method, and the methods below are checked for the fields A2A requires in either version. A failure
   is HTTP 400 with `id: null`, JSON-RPC `-32602` `Invalid params`, and one `{field, message}` per problem in
   `error.data.errors[]`, with a dotted `field` such as `params.message.messageId`. The list stops at 20
   entries, and `error.data.truncated` is `true` when there were more. The gateway logs
   `A2A request shape validation failed:`.

| v0.3 method | v1.0 method | Shape check |
| --- | --- | --- |
| `message/send`, `message/stream` | `SendMessage`, `SendStreamingMessage` | `params.message` is an object with a non-empty `messageId` (or `message_id`), a `role` of `user`, `agent`, `ROLE_USER`, `ROLE_AGENT` or `ROLE_UNSPECIFIED`, and non-empty `parts`, each with exactly one of `text`, `file`, `data`, `raw` or `url` and, when it has a `kind`, the member that `kind` names |
| `tasks/get`, `tasks/cancel`, `tasks/resubscribe` | `GetTask`, `CancelTask`, `SubscribeToTask` | a non-empty string `params.id` |
| `tasks/list` | `ListTasks` | `params.status`, when present, is a task state in either spelling, such as `working` or `TASK_STATE_WORKING` |
| `tasks/pushNotificationConfig/set`, `/get`, `/list`, `/delete` | `CreateTaskPushNotificationConfig`, `GetTaskPushNotificationConfig`, `ListTaskPushNotificationConfigs`, `DeleteTaskPushNotificationConfig` | none beyond `params` |
| `agent/getAuthenticatedExtendedCard` | `GetExtendedAgentCard` | none beyond `params` |

A method outside the table is forwarded unchecked, and the agent's own JSON-RPC errors come back to the
caller. The forwarded body and the policy input keep the caller's spelling: a v0.3 caller's
`message/send` reaches `input.a2a.method` as `message/send`, a v1.0 caller's as `SendMessage`. Policy also
gets `input.a2a.method_canonical`: the v0.3 spelling of any method in the table, whichever spelling was sent,
and absent for a method outside it, so one rule on it covers both ([policies.md](policies.md)). A v1.0
message also has `role` `ROLE_USER` and parts with no `kind`, and neither is normalised.

Which targets get which checks:

| Target | Version | Envelope | Shape |
| --- | --- | --- | --- |
| Direct `http(s)` | yes | yes | yes |
| `a2a-proxy://` | yes | yes | no: the proxy runs its own ([proxies.md](proxies.md)) |
| `fabric://`, on the sending or the receiving gateway | no | no | no |
| Transit Point (outbound) | no | no | no |

Every forwarded request carries the gateway's `X-Gateway-Trace-Id` header, which
continues a well-formed ID the caller sent. A caller-sent header is also copied through unchanged, so
the agent can see two values ([KI-09](known-issues.md)).

**v0.3 callers and the legacy flag.** The feature flag `a2a_legacy_compatibility`, in the settings'
`feature_flags` map and on the dashboard's system settings, is read on every request and is on when unset,
so `0.3` and `1.0` are both accepted. Off, only `1.0` is accepted: a caller that sends no `A2A-Version`
is refused with `-32009` too, and the cards the gateway writes itself drop their v0.3 fields
([proxies.md](proxies.md)). The counter `agent_gateway_a2a_protocol_version_total` shows who would
break. It counts every A2A and AP2 request the version check sees, so none on a `fabric://` surface, by
`channel_id` (the surface name), `negotiated_version` (`0.3`, `1.0`, or `rejected` for a request refused with
`-32009`) and `method_era` (`0.3`, `1.0`, `unknown` for a method outside the table, or `none`). The version
and the era can differ, because either spelling is accepted under either version.
[Recipe: refuse A2A v0.3 callers](#recipe-refuse-a2a-v03-callers) turns the flag off.

**`[a2a]` in `config.toml`** ([operations.md](operations.md#configuration-files)). `validate_messages` (default `true`) turns the envelope and shape checks on or
off together. `max_body_size` (10 MiB by default) is the 413 limit (an MCP surface reaches its own
`mcp_http.max_request_bytes`, 1 MiB by default, first) and caps every upstream response the gateway buffers:
a larger one is 502 `Upstream response too large`. `default_version` is the `protocolVersion` of cards the
gateway writes itself, such as A2A proxy cards, while the gateway accepts that version, and otherwise the
first version it does accept, so `0.3` with the legacy flag off gives `1.0`; a managed agent's card keeps its
own. The code default and the example `config.toml` are both `1.0`, but a `config.toml` can pin `0.3`, so
read the file. It is read when the process starts, and a value whose major and minor are not `0.3` or `1.0`
stops the configuration from loading with `a2a.default_version '<v>' is not a supported A2A protocol version
(supported: 0.3, 1.0)`.

**The agent card.** A GET to a path ending in `/.well-known/agent-card.json` or `/.well-known/agent.json`
is answered by the gateway, not proxied. It fetches the card once from `target.endpoint` plus
`/.well-known/agent-card.json`, with no fallback to `agent.json`, rewrites the URLs in it to point at the
gateway, and serves it without running the caller authentication gate. Details:

- The URL written into the card is the first `external_urls` entry of the listener on the surface's port,
  plus the route; with none, `webauthn.external_origin`. It replaces `url`, `endpoint`, `endpoints[].url`,
  and the `url` of every entry in `supportedInterfaces[]` and `additionalInterfaces[]`, camelCase or
  snake_case, keeping their order. A card with none of those fields is served unmodified, so upstream
  URLs leak.
- Every rewritten interface points at the surface's JSON-RPC URL, whatever its `protocolBinding`. A gRPC
  or `HTTP+JSON` interface stays listed but points at a JSON-RPC endpoint, so a client that picks it
  fails (inference). Publish a card whose interfaces are all `JSONRPC`.
- The card keeps the agent's own `protocolVersion`. It is served as `application/a2a+json` when the caller
  sends `A2A-Version: 1.0` or asks for that type in `Accept`, and as `application/json` otherwise. A card
  fetch never answers `-32009`, whatever the header says.
- `securitySchemes` are the agent's own, passed through unchanged: the card does not describe the surface's
  caller authentication. Tell callers the surface's credential another way, and do not publish a scheme
  they cannot use against the gateway.
- The extended card is rewritten the same way: the JSON-RPC `agent/getAuthenticatedExtendedCard` or
  `GetExtendedAgentCard` result, and `GET <route>/extendedAgentCard` (v1.0) or `GET <route>/v1/card` (v0.3), on
  the inbound, fabric and outbound paths. A successful extended-card answer the gateway cannot rewrite, such as
  a non-JSON or SSE body, gets 502 `Failed to process extended agent card`; JSON-RPC errors pass through
  (`EXTENDED_AGENT_CARD_REFUSAL` in `src/a2a/url_rewriter.rs`).
- Push-notification config calls are forwarded unchanged, and the agent then calls the caller's webhook
  directly, so those notifications never pass the gateway's policies or audit (inference).
- `access_point.agent_card_path` fetches the card from the target's origin plus that path instead,
  ignoring the path part of `target.endpoint`.
- The fetch presents the surface's `target.auth` (`agent_card_target_credential` in `src/proxy/handler.rs`).
  With a credential it forwards only the caller's `Accept`, `Accept-Language` and `User-Agent` and follows no
  redirect, so a 3xx is 502 `Upstream redirected`; a secret that cannot be loaded is 502 `Target
  authentication failed` unless `target.auth.fallback` is `passthrough`. Anonymous callers get the card as
  fetched, so keep credential-only content off the card path. The agent's own error status, such as 401 or
  403, reaches the caller as problem+json `Upstream error: <status>`.
- `access_point.supported_extensions` is not published into the card, and the Extension Validation
  element is never enforced. A local x402 policy paywalls the card itself.

**Identity and streaming.** Inbound agent identity travels in `params.message.extensions` and
`params.message.metadata` and is self-asserted by the caller: input for policy, not proof. Its binding
format is in [identity.md](identity.md), and the problem+json it fails with in
[identity.md](identity.md#identity-errors).
`message/stream`, `SendStreamingMessage`, `tasks/resubscribe` and `SubscribeToTask` are not streamed
through; see [operations.md](operations.md).

### Recipe: check the agent card and the relay

Run this against a new A2A surface in front of your agent. Set `UPSTREAM_URL` to the agent's base URL.

**Before.** Nothing existing changes: the recipe makes its own surface.

**Change.** **Confirm with the user:** this creates a test surface and deletes it at the end. Create the surface:

<!-- e2e: a2a-agent-card -->
```bash
UPSTREAM_URL="${UPSTREAM_URL:?set UPSTREAM_URL to your A2A agent base URL}"
SURFACE_NAME="${SURFACE_NAME:-orders-a2a}"
fabric agent-gateway runtime show surface-routing -o json > routing.json
LISTEN_ADDRESS="$(jq -r '.available_listen_addresses[0]' routing.json)"
PREFIX="$(jq -r '.channel_path_prefix[0].prefix' routing.json)"
fabric agent-gateway surfaces create --name "$SURFACE_NAME" --protocol a2a --listen-address "$LISTEN_ADDRESS" \
  --route "$PREFIX/$SURFACE_NAME" --target-endpoint "$UPSTREAM_URL" -o json > surface.json
jq '{surface_id, status, url: (.access_point.listen_address + .access_point.route)}' surface.json
```

**Verify.** Fetch the card at both paths. Expect HTTP 200 twice, a `url` that is the surface's URL, not the
agent's, and an empty list of strings that still name the agent:

<!-- e2e: a2a-agent-card -->
```bash
BASE="$(jq -r '.access_point.listen_address + .access_point.route' surface.json)"
curl -sS -o card.json -w 'agent-card.json HTTP %{http_code}\n' "$BASE/.well-known/agent-card.json"
curl -sS -o card-legacy.json -w 'agent.json HTTP %{http_code}\n' "$BASE/.well-known/agent.json"
jq -r '"url: " + .url' card.json card-legacy.json
jq -c --arg up "${UPSTREAM_URL:?}" '{leaked: [.. | strings | select(contains($up))]}' card.json
```

Send a message. Expect the agent's JSON-RPC `result`:

<!-- e2e: a2a-agent-card -->
```bash
BASE="$(jq -r '.access_point.listen_address + .access_point.route' surface.json)"
curl -sS -w '\nHTTP %{http_code}\n' "$BASE" -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":"req-1","method":"message/send","params":{"message":{"role":"user","messageId":"msg-1","parts":[{"kind":"text","text":"hello"}]}}}'
```

Ask for a task that does not exist. Expect HTTP 200 with the agent's own JSON-RPC error:

<!-- e2e: a2a-agent-card -->
```bash
BASE="$(jq -r '.access_point.listen_address + .access_point.route' surface.json)"
curl -sS -w '\nHTTP %{http_code}\n' "$BASE" -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":"req-2","method":"tasks/get","params":{"id":"no-such-task"}}'
```

Send a body with no `method`. Expect HTTP 400 and `-32600` from the gateway; the agent never sees it:

<!-- e2e: a2a-agent-card -->
```bash
BASE="$(jq -r '.access_point.listen_address + .access_point.route' surface.json)"
curl -sS -w '\nHTTP %{http_code}\n' "$BASE" -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":"req-3","params":{}}'
```

Ask for the card as a v1.0 caller. Expect `application/json`, then `application/a2a+json`:

<!-- e2e: a2a-agent-card -->
```bash
BASE="$(jq -r '.access_point.listen_address + .access_point.route' surface.json)"
curl -sS -o /dev/null -w 'no header: %{content_type}\n' "$BASE/.well-known/agent-card.json"
curl -sS -o /dev/null -w 'A2A-Version 1.0: %{content_type}\n' "$BASE/.well-known/agent-card.json" -H 'A2A-Version: 1.0'
```

Name a version the gateway does not accept. Expect HTTP 400 and `-32009` with `data.supported`; the agent
never sees it:

<!-- e2e: a2a-agent-card -->
```bash
BASE="$(jq -r '.access_point.listen_address + .access_point.route' surface.json)"
curl -sS -w '\nHTTP %{http_code}\n' "$BASE" -H 'Content-Type: application/json' -H 'A2A-Version: 9.9' \
  -d '{"jsonrpc":"2.0","id":"req-4","method":"tasks/get","params":{"id":"no-such-task"}}'
```

Send a v1.0 message with no `messageId` and a part whose `kind` names the wrong member. Expect HTTP 400,
`-32602` and one entry per problem in `error.data.errors`:

<!-- e2e: a2a-agent-card -->
```bash
BASE="$(jq -r '.access_point.listen_address + .access_point.route' surface.json)"
curl -sS -w '\nHTTP %{http_code}\n' "$BASE" -H 'Content-Type: application/json' -H 'A2A-Version: 1.0' \
  -d '{"jsonrpc":"2.0","id":"req-5","method":"SendMessage","params":{"message":{"role":"ROLE_USER","parts":[{"kind":"data","text":"hello"}]}}}'
```

Send a well-formed v1.0 message. It is forwarded as sent: a v1.0 agent replies, and a v0.3-only agent
answers with its own error, such as `-32601`, because the gateway does not translate:

<!-- e2e: a2a-agent-card -->
```bash
BASE="$(jq -r '.access_point.listen_address + .access_point.route' surface.json)"
curl -sS -w '\nHTTP %{http_code}\n' "$BASE" -H 'Content-Type: application/json' -H 'A2A-Version: 1.0' \
  -d '{"jsonrpc":"2.0","id":"req-6","method":"SendMessage","params":{"message":{"role":"ROLE_USER","messageId":"msg-2","parts":[{"text":"hello"}]}}}'
```

**Undo.** Run `fabric agent-gateway surfaces delete <SURFACE_ID>`.

### Recipe: refuse A2A v0.3 callers

**Confirm with the user:** from the next request, every A2A caller on this gateway that sends
`A2A-Version: 0.3` or no header at all is refused, on every surface whose target is not `fabric://`.

**Before.** Any series with `negotiated_version="0.3"` is a caller that will break; a series appears only
after its first request. Save the settings:

<!-- e2e: a2a-legacy-off -->
```bash
fabric agent-gateway metrics scrape | grep '^agent_gateway_a2a_protocol_version_total' \
  || echo 'no A2A request counted yet'
fabric agent-gateway settings show -o json > settings-before.json
jq '.feature_flags' settings-before.json
```

**Change.** `feature_flags` is replaced as a whole map, and `fabric` refuses its runtime-only `terms` entry,
so send the rest of the saved map with the flag added:

<!-- e2e: a2a-legacy-off -->
```bash
jq '{feature_flags: ((.feature_flags // {}) | del(.terms) + {a2a_legacy_compatibility: false})}' \
  settings-before.json > legacy-off.json
fabric agent-gateway settings set --file legacy-off.json -o json | jq '.feature_flags'
```

**Verify.** A request with no `A2A-Version` gets HTTP 400 `-32009`, and `data.supported` lists only `1.0`:

<!-- e2e: a2a-legacy-off -->
```bash
curl -sS -w '\nHTTP %{http_code}\n' "${SURFACE_URL:?set SURFACE_URL to an A2A surface URL}" \
  -H 'Content-Type: application/json' -d '{"jsonrpc":"2.0","id":1,"method":"tasks/get","params":{"id":"probe"}}'
```

**Undo.** Put the saved map back, still without `terms`; a flag that was unset before is unset again:

<!-- e2e: a2a-legacy-off -->
```bash
jq '{feature_flags: ((.feature_flags // {}) | del(.terms))}' settings-before.json > settings-restore.json
fabric agent-gateway settings set --file settings-restore.json -o json > /dev/null
```

**If it fails.** `settings set` refuses the file: it still carries `terms`. The request is forwarded
instead of refused: `SURFACE_URL` names a surface whose target is `fabric://`, which skips the version check;
use one with a direct or `a2a-proxy://` target.

## Worked example: an A2A agent over HTTPS, end to end

One A2A agent, end to end. Do the steps in order and check each before the next.

1. **Routing.** In `fabric agent-gateway runtime show surface-routing -o json`, confirm a channel prefix, and that the
   listener you use has its public URL as `external_urls[0]`: the card is rewritten from it.
2. **Surface.** Create the A2A surface under that prefix, with the agent's `https://` URL as
   `target.endpoint`: the first-surface recipe in [surfaces.md](surfaces.md).
3. **Card.** Run the card recipe above. Every URL in the card must be the gateway's. A 401 or 403 is the
   agent's own answer to the card fetch: give the surface the `target.auth` the agent expects
   ([credentials.md](credentials.md)), or serve a public card and point `agent_card_path` at it.
4. **Variant.** To route some callers to a second agent, add a variant and call `<route>$<alias>`
   ([surfaces.md](surfaces.md)). A card fetched through a variant still names the base route
   (inference).
5. **Caller key.** Require an API key ([identity.md](identity.md)); every later call needs it.
6. **Deny policy.** Attach a `package surface.policy` policy that denies a method or a message, matching
   the method on `input.a2a.method_canonical` and parts by `text`, not `kind`. An A2A deny is HTTP 403, and
   the reason is only in the audit log ([policies.md](policies.md)).
7. **Delegation.** For each user's own token, bind a credential provider with `required_for: "all"` and
   a header injection ([credentials.md](credentials.md)). A missing grant is an HTTP 401 problem+json,
   not an A2A task state.
8. **Direct path.** Make the agent reachable only from the gateway ([identity.md](identity.md)).
9. **Verify.** As the caller, replay the card fetch, one allowed and one denied `message/send`, and the
   same two as `SendMessage` with `A2A-Version: 1.0`.

## Worked example: your own MCP server behind the gateway

The same path for an MCP server you run.

1. **Surface.** Create the MCP surface: the quickstart in [SKILL.md](../SKILL.md).
2. **Version.** Run the version-gate recipe above. If `initialize` comes back with any version other than
   `2024-11-05`, the server ignored the gateway's request for `2024-11-05`: make it serve `2024-11-05` before
   you onboard Claude Code or TypeScript SDK clients ([MCP client matrix](#mcp-client-matrix)).
3. **Caller key.** Require an API key ([identity.md](identity.md)).
4. **Tool allow-list.** Allow only the tools callers need with per-tool policies, and hide the rest
   with MCP Tool Gating ([policies.md](policies.md)). A per-tool deny is HTTP 200 `-32000`; a surface policy
   deny of `tools/call` is HTTP 200 `-32001` with the policy's reason.
5. **Target credential.** If the server needs its own key, store it as a secret and attach target auth
   ([credentials.md](credentials.md)).
6. **Delegation.** For per-user tokens, limit the binding to the tools that need it, so `initialize`
   does not ask for consent ([credentials.md](credentials.md)).
7. **Direct path.** Close it ([identity.md](identity.md)).
8. **Verify.** As the caller: `initialize`, `tools/list`, one allowed and one denied `tools/call`.

## Paywalled surfaces

A surface can charge per call with x402 or MPP. This covers the operator side only: settlement needs a
facilitator and funded wallets, so no recipe here settles a payment.

**Shape.** `target.payment_policy` is `{"type":"x402", ...}` or `{"type":"mpp", ...}`, written with the
`payment` feature. A minimal x402 policy that charges MCP tools whose name
starts with `premium_`:

```json
{
  "type": "x402",
  "payment_requirements": [
    { "scheme": "exact", "network": "eip155:84532", "amount": "10000",
      "asset": "<token-contract>", "recipientId": "<recipient-id>", "maxTimeoutSeconds": 60 }
  ],
  "verification_mode": "local",
  "settlement_mode": "immediate",
  "mcp_payment_triggers": { "mode": "match", "patterns": ["^premium_"] }
}
```

```bash
fabric agent-gateway surfaces add-feature "$SURFACE_ID" payment --file x402.json
```

- `recipientId` must exist in `fabric agent-gateway runtime show x402` with an address for that `network`, or the save
  fails with "Surface payment policy: ... unknown recipient_id".
- Omitted modes default to `verification_mode: local` and `settlement_mode: deferred`. The dashboard's x402
  Payment editor does not use those defaults: when it opens on a policy without a verification mode it fills
  in `"verification_mode": "mock"`, which checks only that the payment names one of the surface's requirements
  and skips every signature, chain and facilitator check, and `"settlement_mode": "none"`, which settles nothing.
  A surface paywalled in the dashboard therefore grants access for unpaid credentials until someone changes both.
- **Requirements bind the payment.** The credential's `accepted` object must repeat one of the requirements the
  402 challenge issued, exactly: `scheme`, `network`, `asset`, `payTo`, `amount`, and in `extra` the transfer
  method (`assetTransferMethod`) and the token's signing-domain `name` and `version`. Otherwise the caller gets 400
  `invalid_payment` `Payment does not match any payment requirement issued for this resource`, in every
  verification mode (`resolve_payment_requirement` in `src/x402/verification.rs`). A surface with an empty
  `payment_requirements` list accepts no payment. For `"verification_mode": "signature"`, give each requirement
  `extra.assetTransferMethod` (`eip3009` or `permit2`), and an `eip3009` one also `extra.name` and
  `extra.version`.
- **What is charged.** On MCP, only `tools/call` is ever charged, and only when `mcp_payment_triggers` is
  set (`all`, `match` or `exclude`); `initialize` and `tools/list` are free. On
  A2A, nothing is charged unless a method filter names a method: for x402, `a2a_method_filters`, or
  `a2a_methods` when `a2a_method_filters` is absent; for MPP, `a2a_method_filters` only.
  Either list matches both spellings of a method, so `message/send` also charges `SendMessage` and
  `tasks/list` also charges `ListTasks`; a method outside the method table matches only as written.
  `message_patterns` are literal substrings of the message text, not
  regular expressions, and x402 reads that text from every part's `text`, whatever its `kind`. While
  `message_patterns` are set, x402 writes the message text it checks to the gateway log at INFO
  (`should_require_payment` in `src/x402/middleware.rs`), so treat that log as holding callers' messages
  ([KI-52](known-issues.md)).
- **When it is charged.** The paywall runs after egress vetting, the body-size limit and, on A2A, the
  version, envelope and shape checks, so a malformed or wrong-version call is refused before it is
  charged. It runs before a `proxy://` target answers, so MCP proxy surfaces are charged too. A
  `2026-07-28` MCP request is charged later, after the surface policies.
- **The challenge.** An unpaid x402 call gets 402 with a base64 `PAYMENT-REQUIRED` header and a body with
  `x402Version: 2` and `accepts`. The payer resends with `PAYMENT-SIGNATURE`. That is the default name:
  the `headers` block of `x402.json` can rename all three headers, and `fabric agent-gateway runtime show
  x402` shows the names in use. The docs' `X-Payment` is not read unless it is configured there. On MCP
  `tools/call` the signature can instead travel as `arguments.payment_signature`, which the gateway
  removes before forwarding. A payment that fails verification gets 400 `invalid_payment`, not 402.
- **MPP.** The policy needs `realm` and `secret_key`; write the key as `$SECRET:<secret_id>` so it lives
  in the secrets store. An unpaid call gets 402 problem+json with one `WWW-Authenticate: Payment`
  challenge per method; the payer answers with `Authorization: Payment <credential>`. The receipt comes
  back in the `PAYMENT-RESPONSE` header. A credential that fails verification gets 402
  `verification-failed` with a fresh challenge and the reason in `detail`; `Invalid challenge ID: HMAC
  binding verification failed` means this surface's `secret_key` did not issue that challenge. A
  `secret_key` reference that does not resolve gets 500 `Payment configuration error`, and a policy with
  no payment method gets 500 `No payment methods configured`.
- **Delegated paywall.** An x402 policy with `"provider": "agent_pay"`, `payment_gateway_id` and
  `payment_surface_id` runs no paywall of its own. Every request is relayed to
  `fabric://<payment_gateway_id>/<payment_surface_id>` after the A2A version, envelope and shape checks and
  before egress vetting and the body-size limit (a `2026-07-28` MCP request after the surface policies): a
  2xx there lets the request through with allow-listed receipt headers, a 402 goes back to the caller with
  allow-listed challenge headers, and anything else is denied, as a 502 for an unexpected status.
- **Records.** `fabric agent-gateway payments list` and `fabric agent-gateway payments get <ID>` read both ledgers; MPP records
  cannot be deleted.

## Error shapes per protocol

Branch on the HTTP status first, then on the body: `-32000` at HTTP 429 is a rate limit, at HTTP 200 a
tool-policy deny, and `-32020` at HTTP 400 on an MCP surface is the gateway's header check, at HTTP 200 on
an A2A surface the A2A proxy.

| Where it came from | HTTP | Body | Where the reason is |
| --- | --- | --- | --- |
| Routing, gateway policy, egress, body size, upstream response limits, agent card, protocol mismatch | 400, 403, 404, 413, 422, 502, 503, 504; a card fetch also relays the agent's own error status | `application/problem+json` of type `https://a2a-protocol.org/errors/proxy-error` | `detail` |
| Caller authentication fault on the gateway's side | 500 | problem+json; `type` `about:blank` on MCP, the `proxy-error` type on A2A | `detail` ([identity.md](identity.md#when-it-fails)) |
| Agent identity slot | 422, 500, 503 | problem+json whose `type` ends in its `code`, with `code`, `slot` and `channel` fields | `code`, `detail` ([identity.md](identity.md#identity-errors)) |
| MCP version gate | 400 | JSON-RPC `-32022`, `data.requested`, `data.supported` | `error.data` |
| MCP modern request shape or headers | 400 | JSON-RPC `-32602`, `-32020`, `-32600` or `-32700` | `error.message` |
| MCP HTTP admission: `Origin`, header or body size, `Accept`, `Content-Type` | 403, 431, 413, 406, 415 | JSON-RPC `-32600` | `error.message` |
| MCP `2026-07-28` reply the gateway cannot pass on | 502 | problem+json `Invalid modern MCP upstream response` | `detail`; the reason is in the log |
| MCP malformed body, no modern header or `_meta` key | 200 | JSON-RPC `-32600` or `-32700` | `error.message`, `error.data.details` |
| MCP client response to the server | 202 | empty | none: dropped |
| MCP per-tool deny | 200 | JSON-RPC `-32000` "Access denied: insufficient permissions for this tool" | Audit only |
| MCP surface policy deny of `tools/call` | 200 | JSON-RPC `-32001` "Tool '...' is not allowed by policy: ..." | In the message |
| MCP rate limit | 429 | JSON-RPC `-32000` "Rate limit exceeded" | `data.retry_after` is a sentence; the `Retry-After` header gives whole seconds ([KI-29](known-issues.md)) |
| MCP `2026-07-28` on `fabric://`, sending gateway's stream cap full | 429, `Retry-After: 5` | JSON-RPC `-32603` "Too many concurrent MCP requests over Fabric" | `error.message`; `Retry-After` header ([g2g.md](g2g.md)) |
| A2A version | 400 | JSON-RPC, `id: null`, `-32009` | `error.data.requested`, `error.data.supported` |
| A2A envelope | 400 | JSON-RPC, `id: null`, `-32700` or `-32600` | `error.message` |
| A2A request shape | 400 | JSON-RPC, `id: null`, `-32602` "Invalid params" | `error.data.errors[]` (`field`, `message`), at most 20; `error.data.truncated` when there were more |
| A2A policy deny | 403 | JSON `{"error":"Forbidden",...}` | Audit only: [policies.md](policies.md) |
| A2A rate limit | 429 | problem+json | `detail` |
| Delegation needs consent, either protocol | 401 | problem+json `consent-required` | `consent_required[].authorization_url`: [credentials.md](credentials.md) |
| x402 unpaid, bad payment | 402, 400 | `PAYMENT-REQUIRED` header and a JSON x402 body; `{"error":"invalid_payment",...}` sent as `text/plain` | Body |
| MPP unpaid or failed | 402 | problem+json of a `paymentauth.org` type, `WWW-Authenticate: Payment` | `detail` |
| AP2 | 501 | "AP2 is experimental and not enabled on this gateway", or with the flag on "AP2 experimental processing failed and request was rejected" | The message |

## When it fails

MCP rows first, then A2A, then the card and payments.

| Exact text | Cause | Fix |
| --- | --- | --- |
| 400 `-32022` "Unsupported protocol version" right after `initialize` | The client echoes a version the gateway does not serve, such as `2025-06-18`, which the upstream answered with although the gateway asked it for `2024-11-05` | Make the upstream serve `2024-11-05`, or use an MCP proxy |
| 400 `-32602` `Modern MCP requests require params._meta`, `Missing io.modelcontextprotocol/protocolVersion`, `Missing io.modelcontextprotocol/clientCapabilities` | A modern header or `_meta` key without the rest of the modern shape | Send a complete `2026-07-28` request, or a `2024-11-05` request with none of them |
| 400 `-32602` `io.modelcontextprotocol/protocolVersion must be a non-empty string`, `io.modelcontextprotocol/clientCapabilities must be an object`, `io.modelcontextprotocol/clientInfo must contain string name and version fields`, `io.modelcontextprotocol/logLevel must be a defined logging level`, `progressToken must be a string or number` | A modern request whose `params._meta` holds a value of the wrong type | Send each key with the type named |
| 400 `-32602` `MCP 2024-11-05 cannot use modern per-request metadata or mirrored headers` | A complete modern request (headers and both `_meta` keys) whose `io.modelcontextprotocol/protocolVersion` is `2024-11-05`, or a notification with `Mcp-Method` or `Mcp-Name` and `MCP-Protocol-Version: 2024-11-05` | Drop the modern headers and `_meta` keys and send a plain `2024-11-05` request |
| 400 `-32602` `Modern MCP metadata must be in params._meta`, `MCP params must be an object`, `MCP params._meta must be an object`, `<method> requires string params.<name>` | A modern request with metadata at the top level, `params` of the wrong type, or no tool, prompt or resource name | Put `_meta` inside an object `params`, with the name the method needs |
| 400 `-32602` `MCP canonical _meta must be a JSON object`, `Conflicting MCP metadata aliases for '<k>'`, `Invalid MCP metadata key '<k>'` | `_meta` the gateway cannot normalise, `2024-11-05` requests included | Send `_meta` as an object with each key once |
| 400 `-32020` `Header <h> must appear exactly once`, `Header <h> contains invalid characters`, `Missing required MCP-Protocol-Version header`, `Missing required Mcp-Method header`, `Mcp-Method header does not match method`, `Missing required Mcp-Name header`, `Mcp-Name header does not match request params`, `MCP-Protocol-Version header does not match params._meta` | A modern request whose headers are missing, repeat or disagree with the body | Send each header once, matching the body |
| 400 `-32700` `Invalid JSON: <e>`; 400 `-32600` `Modern MCP POST body must be one JSON-RPC object`, `Invalid or missing JSON-RPC version`, `Missing or invalid method`, `MCP request id must be a string or integer` | A modern request whose body is not one well-formed JSON-RPC object | Fix the body |
| 200 `-32600` `Invalid JSON-RPC request`; 400 with a `2026-07-28` signal | A `Content-Type` without `application/json`, a body without `"jsonrpc": "2.0"`, JSON that is not an object, or keys that repeat or differ only in case at any depth (`method` and `Method`, `params.Name`) | Send `Content-Type: application/json`, a full envelope, and each key once in its exact spelling |
| 200 `-32700` `Invalid JSON` with `data.details` | No modern header, and a body that is not JSON | Fix the body |
| 403 `-32600` `Origin is not permitted on this MCP endpoint` | The request's `Origin` is neither the origin of an inbound listener's `external_urls` nor in the surface's `mcp_http.allowed_origins`, whatever the MCP version | Add the exact origin to `mcp_http.allowed_origins`; a request with no `Origin` is not checked |
| 413 `-32600` `MCP request body exceeds the configured limit`; 431 `-32600` `MCP request headers exceed the configured limit` | The body is over the surface's `mcp_http.max_request_bytes` (1 MiB by default), or the headers over `max_header_bytes` (16 KiB) | Raise the limit in the surface's `mcp_http` |
| 406 `-32600` `Accept must explicitly permit application/json and text/event-stream`; 415 `-32600` `MCP POST requires one application/json Content-Type with UTF-8 encoding`; 400 `-32600` `Invalid Accept media ranges or quality values` | A `2026-07-28` request without both `Accept` types, or a `2026-07-28` message without one JSON `Content-Type` | Send `Content-Type: application/json` and `Accept: application/json, text/event-stream` |
| 502 `Invalid modern MCP upstream response` | A `2026-07-28` request whose upstream answered with something other than a valid `2026-07-28` reply, such as a `2024-11-05` result without `resultType` | Serve `2026-07-28` at the upstream, or send `2024-11-05` requests |
| 429 `-32603` `Too many concurrent MCP requests over Fabric`, with `Retry-After: 5` | A `2026-07-28` request to a `fabric://` surface while the sending gateway's Fabric stream caps are full | Retry after the delay; see [g2g.md](g2g.md) for the caps |
| 504 `Modern MCP upstream response headers timed out` | The upstream took longer than the surface's request timeout to answer a `2026-07-28` request | Raise the surface's request timeout, or speed up the upstream |
| 405 with `Allow: POST`; 400 `-32020` `MCP-Protocol-Version requires one valid header value` | A `GET` or `DELETE` with `MCP-Protocol-Version: 2026-07-28`, or with that header repeated or unreadable | Send `2026-07-28` requests as POSTs |
| 405 with `Allow: POST, GET, DELETE, HEAD, OPTIONS`; 400 `-32600` `Only MCP POST requests may carry a body` | A `PUT`, `PATCH` or other method an MCP endpoint does not serve; a body on a `GET`, `DELETE`, `HEAD` or `OPTIONS` | Send MCP requests as POSTs, and a `GET` or `DELETE` with no body |
| 404 `-32601` `MCP method is not implemented by this proxy` | A `2026-07-28` notification, or a request other than `server/discover`, `tools/list`, `tools/call` or `subscriptions/listen`, on a `proxy://` surface | Use one of those methods, or `2024-11-05` |
| 422 `JSON-RPC batches are not supported` | A batch array | One object per POST |
| 422 `Invalid MCP identity presentation` | An identity presentation in `_meta` that fails verification | See [g2g.md](g2g.md) for presentations |
| 406 "Not Acceptable", for example `Not Acceptable: Client must accept both ...` | The client's `Accept` lacks `text/event-stream`, and the upstream is strict | Send `Accept: application/json, text/event-stream` |
| The upstream never sees `notifications/initialized` | `2024-11-05` notifications stop at the gateway | Do not make the upstream wait for it before serving requests |
| Upstream server-to-client notifications never arrive on GET | The GET stream is the gateway's own and carries only gateway messages | Stream inside POST responses instead |
| The upstream's `sampling/createMessage`, `roots/list` or `elicitation/create` never gets an answer | The client's reply is a POST that gets 202 and stops at the gateway | Do not rely on server-to-client requests behind the gateway |
| The client receives two `Mcp-Session-Id` headers | The upstream sets its own on `initialize`, and the gateway adds one when it wraps the reply as SSE | Make the upstream stateless, or send `Accept: application/json` |
| 429 `Too many active SSE sessions` (`text/plain`) | The gateway's GET stream registry is full, or it already holds 10,000 HTTP+SSE sessions (`GET <route>/sse` on `proxy://` and `fabric://` surfaces and standalone MCP proxies) | Close idle streams and sessions |
| 404 `SSE session not found or expired` | A `proxy://` surface's HTTP+SSE `POST <route>/mcp/messages?session_id=` names a stream that closed or never opened | Open `GET <route>/sse` again and use its `endpoint` ([proxies.md](proxies.md)) |
| 500 `Invalid MCP HTTP configuration` | The surface's `mcp_http.allowed_origins` holds an entry that is not an exact `http(s)` origin; every MCP request on the surface fails, and the log says `Invalid MCP HTTP configuration: <reason>` | Write each entry as scheme, host and port only, such as `https://app.example.com` |
| 500 `Invalid MCP metadata configuration` | `target.custom_metadata`, `target.response_custom_metadata` or `access_point.response_custom_metadata` is invalid; every MCP POST on the surface fails | Fix that field ([identity.md](identity.md)) |
| 400 `Failed to read request body`, or on an MCP surface 400 `-32600` `Failed to read MCP request body` | The request body could not be read: a client disconnect or broken chunking | Retry; check the client or a proxy in front |
| 422 `Request protocol 'mcp' does not match access point protocol 'a2a'`, or the reverse | An MCP method sent to an A2A surface, or an A2A method (either spelling) to an MCP surface | Use a surface of the caller's protocol |
| A2A 400 `-32009` `Unsupported A2A protocol version '<v>'` | `A2A-Version` names a version the gateway does not accept; with `a2a_legacy_compatibility` off, also `0.3` or no header | Send `A2A-Version: 1.0`, or turn the flag back on for v0.3 callers |
| A2A 400 `-32602` `Invalid params` | A required A2A field is missing, empty or of the wrong kind; `error.data.errors[]` names each, up to 20, and `error.data.truncated` marks more | Fix the named fields; a v1.0 part carries its content member and no wrong `kind` |
| A2A 400 "Invalid JSON-RPC: missing or invalid 'method' field" | The body has no string `method` (or `jsonrpc`) | Send a full JSON-RPC envelope |
| A2A 200 `-32601` from the agent for `SendMessage` or `GetTask` | A v1.0 caller in front of a v0.3-only agent; the gateway does not translate | Match the caller's version to the agent's card |
| 422 `identity_validation_failed`, slot `inbound_identity` | The caller's identity extension fails the surface's inbound identity schema | Fix the caller's extension, or the schema |
| 422 `identity_extension_missing`, `identity_invalid_response` or `identity_validation_failed`, slot `protected_identity` or `external_identity` | The agent's reply, or its card, lacks the identity extension, is not JSON or fails the slot's schema; the agent already answered | Make the agent return a valid identity extension |
| 500 or 503 `identity_did_failed` | The gateway could not create or fetch a DID for the identity slot (503: the identity backend is unavailable) | Retry; check the gateway's identity backend |
| The card shows the agent's own URLs, or the wrong host | No rewritable field, the agent's URL sits in a field the rewrite leaves alone, such as `documentationUrl` or `provider.url`, or the listener on the surface's port has no `external_urls` | Put the URL in `url` or `supportedInterfaces` and keep the agent's host out of other fields; set the listener's `external_urls[0]` |
| A client fails on a card interface that is not `JSONRPC` | The rewrite points every interface at the JSON-RPC surface | Publish only `JSONRPC` interfaces |
| 502 `Failed to process extended agent card` | The agent's extended card came back in a form the gateway cannot rewrite: not JSON, an SSE stream, a card or `result` that is not an object, or both `result` and `error` | Serve the extended card as one JSON object |
| 502 `Failed to rewrite agent card URLs`, `Invalid rewritten agent card JSON` | The gateway fetched the card but could not rewrite it; the log line of the same text has the reason | Serve a plain JSON card at `agent-card.json` or `agent_card_path` |
| Card fetch returns 401 or 403, `Upstream error: <status>` | The agent wants a credential for its card that the surface's `target.auth` does not supply | Give the surface the `target.auth` the agent expects ([credentials.md](credentials.md)), or serve a public card at `agent_card_path` |
| Card fetch returns 502 `Upstream redirected` | The agent redirects its card path, and a fetch that carries `target.auth` follows no redirect | Point `agent_card_path` at the final path |
| Card fetch returns 502 `Target authentication failed` | The `target.auth` secret cannot be loaded and `fallback` is `reject` | Fix the secret ([credentials.md](credentials.md)) |
| The card returns 402 | A local x402 policy is enabled on the surface | Expected: callers pay for the card too |
| An A2A paywall never charges, or `^buy.*` never matches | `a2a_method_filters` is empty, or patterns are literal substrings | Add a filter per method; use a plain substring |
| "Surface payment policy: ... unknown recipient_id" | The recipient is not in the x402 configuration | Pick an ID from `fabric agent-gateway runtime show x402` |
| 400 `invalid_payment` instead of 402 | A payment was sent but failed verification | Check the payload's network, asset and amount |
| 400 `invalid_payment` `Payment does not match any payment requirement issued for this resource` | The credential's `accepted` differs from every issued requirement, or the surface has no `payment_requirements` | Echo one requirement from the 402 challenge unchanged; give the surface its requirements |
| The payer's `X-Payment` header is ignored | The gateway reads `PAYMENT-SIGNATURE` unless `x402.json` renames it | Send the header `fabric agent-gateway runtime show x402` names |
| 402 `verification-failed` with `Invalid challenge ID: HMAC binding verification failed` | The MPP credential answers a challenge this surface's `secret_key` did not issue, or the key changed | Pay the fresh challenge in the same response |
| 500 `Payment configuration error`; 500 `No payment methods configured`; 500 `Failed to generate payment challenges: <e>` | MPP: the `secret_key` reference does not resolve; the policy has no method; a method cannot be built | Fix the secret or the MPP policy |
| The remote gateway's 402 reaches the caller, log `MPP auto-pay failed: Private key address mismatch: ...` | `mpp_auto_pay` on a `fabric://` surface: the stored wallet key does not derive the wallet's address | Store the key that belongs to that address |
| 502 `payment gateway returned unexpected status <n>` | A delegated paywall's payment surface answered neither 2xx nor 402 | Check the payment surface on the remote gateway ([g2g.md](g2g.md)) |

## Known issues here

- [KI-26](known-issues.md): the MCP version gate accepts `2024-11-05` and `2026-07-28` only.
- [KI-27](known-issues.md): MCP OAuth discovery only with `sts.mcp_issuer`, and no authorisation-code sign-in.
- [KI-28](known-issues.md): the A2A proxy speaks only Copilot Direct Line.
- [KI-29](known-issues.md): on an MCP rate-limit 429, `data.retry_after` is a sentence, not seconds.
- [KI-48](known-issues.md): the MCP GET stream and `DELETE` are answered before surface policies.
- [KI-49](known-issues.md): the HTTP+SSE retry drops target auth and logs the body.
- [KI-50](known-issues.md): a client's answer to an upstream's request is dropped.
- [KI-51](known-issues.md): two `Mcp-Session-Id` headers on an SSE-wrapped `initialize`.
- [KI-52](known-issues.md): the x402 message filter logs message text.
- [KI-16](known-issues.md): A2A delegation with `required_for.tools` never matches.

Sources: [A2A protocol](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/concepts/protocols/a2a/), [AP2 protocol](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/concepts/protocols/ap2/), [MCP protocol](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/concepts/protocols/mcp/), [MPP (Machine Payments Protocol)](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/concepts/protocols/mpp/), [Glossary](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/get-started/glossary/), [Payments](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/reference/payments/payments/), [A2A Proxy](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/reference/proxies/a2a-proxy/), [Access Point](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/reference/surfaces/access-point/), [Payment element](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/reference/surfaces/payment/); gateway source: `src/proxy/handler.rs`, `src/mcp/request_validation.rs`, `src/mcp/modern_http.rs`, `src/mcp/upstream_versions.rs`, `src/a2a/version.rs`, `src/a2a/validation.rs`, `src/a2a/url_rewriter.rs`, `src/x402/middleware.rs`, `www/default/src/components/surface-builder/elements/payment/PaymentPanel.tsx`, `src/mcp/tool_analyzer.rs`; fabric's `src/commands.rs`, `src/features.rs`.
