# Operations

Reloads and restarts, outages and standby nodes, latency, 429 / 502 / 503 / 504, audit settings, moving
config, health, and the startup configuration files.

## Contents

- [Before you change anything](#before-you-change-anything)
- [What is applied when](#what-is-applied-when)
- [Recipe: change a listener or prefix](#recipe-change-a-listener-or-prefix)
- [Outage and standby](#outage-and-standby)
- [The extra hop](#the-extra-hop)
- [Traffic management](#traffic-management)
- [Audit, logs and metrics](#audit-logs-and-metrics)
- [Moving config between gateways; backup and restore](#moving-config-between-gateways-backup-and-restore)
- [Health](#health)
- [Configuration files](#configuration-files)
- [When it fails](#when-it-fails)
- [Known issues here](#known-issues-here)

## Before you change anything

All read-only. Run the ones that match the change first.

| Question | Command |
| --- | --- |
| Which listeners, channel prefixes and callback route does the config file name? | `fabric agent-gateway runtime show surface-routing -o json` |
| What does this surface carry now (rate limit, networking)? | `fabric agent-gateway surfaces get <surface-id> -o json`; `fabric agent-gateway surfaces features <surface-id>` lists which features are on and where |
| Is audit on, and which categories? | `fabric agent-gateway settings show -o json` |
| Is this process up, and is it active and ready? | `fabric agent-gateway api get /v1/alive`, then `fabric agent-gateway api get /v1/health` |
| Which gateway version answers? | `fabric agent-gateway api get /v1/version` |
| How much headroom is left before an appliance limit? | `fabric agent-gateway api get /v1/limits` |
| Is OTLP export healthy? | `fabric agent-gateway metrics status` |

## What is applied when

Read the "how to confirm" column before you tell the user a change is live.

| Change | Applied by | How to confirm |
| --- | --- | --- |
| Surface create or update of an active surface with no variants and no Transit Points; delete of a running surface without variants | A fast path swaps or removes that one surface in place; when it fails, the full reload below runs. The API answers success even when the apply fails; the failure is only logged | Send a real request through the surface |
| Surface save that leaves it disabled, leaves it with variants or Transit Points, or removes its variants; delete of a surface that has variants or is not running | A full in-process reload: every inbound listener, the management API included, and every outbound listener that serves a Transit Point is aborted and rebound. An outbound listener that serves none is left unbound | Real request; expect a short window of refused connections |
| Policy definition update | Recompiles every surface that references it, at once. The update still answers 200 when a surface fails to compile: the gateway logs `Failed to recompile OPA policy for channel` and drops that surface's compiled policies, so its direct traffic is denied until a recompile succeeds (`fabric://` send skips it instead, [KI-11](known-issues.md)). `policies create` and `fabric agent-gateway runtime reload` recompile nothing | Send a request. On that log line, fix the Rego and update again |
| Policy definition delete | Removes it from appliance-wide assignments at once. Surfaces that reference it are not refused and not recompiled: they keep enforcing the compiled copy until their next recompile (restart, promotion), which finds no definition and denies their direct traffic. Saving such a surface fails with 400 `Policy definition reference is not accessible` until it names another definition | Before deleting, `fabric agent-gateway policies impact <policy-id>` must count no surfaces; move any it counts to another definition first |
| `fabric agent-gateway runtime reload --surface <surface-id>` | Reloads one surface from storage into its inbound listener without rebinding it; when the surface has or had Transit Points, its outbound listener is aborted and rebound | The response's `is_fallback` is `false` |
| `fabric agent-gateway runtime reload` (all surfaces) | The full reload above, which also re-reads `gateway.json` from disk | Real request; never run it with an unvalidated `gateway.json` on disk ([KI-35](known-issues.md)) |
| `settings set`, `metrics config set` | Live, on write | `fabric agent-gateway settings show -o json`; `fabric agent-gateway metrics status` |
| Listeners, ports, `external_urls`, channel prefixes | Restart (the documented path); a full reload also rebinds them from the file | A real request to the new port or prefix |
| `config.toml` and the files it names other than `gateway.json` and `metrics.json`: `rbac.json`, `limits.json`, `saml.json`; also mTLS client auth, log level, the trace allow-list, payload capture (`[extension_inspection]`), the Terms switch | Restart only | Behaviour after the restart |

`fabric agent-gateway runtime show surface-routing` re-reads `gateway.json` on every call: it shows what the file
says, never what is bound ([KI-36](known-issues.md)).

## Recipe: change a listener or prefix

**Confirm with the user:** every caller of every surface on this gateway, and every `fabric` session,
loses its connection while the listeners rebind. Plan a window. (Not tried on a running gateway: it
rebinds the management API that `fabric` itself uses.)

1. **Before.** `fabric agent-gateway runtime show surface-routing -o json > routing-before.json`, and keep a copy of
   the current `gateway.json`. Parse the edited file (`jq . gateway.json`) before anything reads it.
   A file that fails to load during a full reload leaves the process with no listeners at all, the
   management API included, until a restart.
2. **Change.** Restart the process. `fabric agent-gateway runtime reload` also rebinds from the file, but a restart
   is the path the docs support and the only one that reloads RBAC and limits.
3. **Verify.** Send a real request to a surface on the new port or prefix. Do not use
   `runtime show surface-routing` as proof.
4. **Undo.** Put the saved `gateway.json` back and restart.
5. **If it fails.** Nothing answers at all: the file did not load. Fix it and restart; a second
   `fabric agent-gateway runtime reload` cannot reach a process with no listeners.

## Outage and standby

| Situation | What callers see |
| --- | --- |
| Process stopped or crashed | Nothing answers: surfaces, API and dashboard are one process. Connection refused, or whatever a front proxy returns. No path bypasses the gateway to the upstream |
| Process restarting | In-flight requests are cut: there is no graceful HTTP drain |
| Inside a full-reload window | New connections refused for at least 200 ms plus the rebind, on every listener |
| Upstream host does not resolve from the gateway | 403 problem+json `Request blocked by egress policy` on every call, from the egress check before the send |
| Boot refused | The process exits: a `backup_encryption_key` that is missing, empty or does not resolve, a surface store that cannot be read at all, caller authentication that cannot be set up, a broken `gateway.json`, missing TLS files, an OTLP `auth.secret_id` naming a secret that does not exist, or a bad value in `config.toml` ([Configuration files](#configuration-files)) |
| Surface missing after a restart | One surface file that fails to load is skipped and the gateway boots without it; the log says `Encountered N error(s) loading agent_surface(s)` |
| Standby node | It serves direct surface traffic but records no audit events: only an active node runs the audit journal. `fabric://` targets and Trust Checks need an active node (below). Only `GET /api/v1/health` changes, to 503. The load balancer's health check decides who gets traffic |

- A node starts active unless `config.toml` sets `server_mode = "standby"`. It is a top-level key: written
  after a `[table]` header it belongs to that table and does not set the mode. `SIGUSR1` promotes a node
  and `SIGUSR2` steps it down; nothing else changes the mode. The gateway elects no active node, so send the
  signals from whatever runs your nodes; nothing stops two nodes being active at once (inference).
- A standby node keeps its HTTP listeners, whatever the example configuration's comment says: in standby,
  `run_axum_proxy` (`src/server/orchestrator.rs`) deactivates only the connection-point and trust-registry
  listeners, and nothing on the request path checks the mode (not tried on a running gateway). It has no
  DIDComm or trust-registry links until it is promoted, so `fabric://` targets and Trust Checks work only on an
  active node.
- Promotion re-reads surfaces, gateways, policy definitions and the appliance-wide policy set from storage,
  runs a full reload (every listener rebinds, as in [What is applied when](#what-is-applied-when)) and
  recompiles every policy; only then does `GET /api/v1/health` answer 200, and the links reconnect after
  that. `SIGUSR1` to a node that is already active does the same. A node that is starting answers 503 there
  until its startup finishes.
- `metrics config set` saves an OTLP `auth` block naming a missing secret, answers success with
  "saved, but applying it live failed", and the next boot fails.
- Unverified: whether an HTTPS keep-alive connection keeps the pre-reload surface state after a reload.

State held per process, so it is lost on restart and not shared between nodes:

| State | Consequence |
| --- | --- |
| Rate limiters and circuit breakers | They reset; with N reachable nodes the effective limit is N times the configured one (inference) |
| MCP GET notification streams, pending MCP elicitations | Clients must reopen; an elicitation answered on the other node never resumes the call |
| Pending `2026-07-28` MCP consent, when `[mcp.continuations]` uses the `embedded` storage backend | It must finish on the node that started it; nodes that use one `dynamodb` table share it (inference) |
| `fabric` browser-login codes (two minutes), passkey and DID-Auth challenges, outstanding SAML requests | A sign-in must finish on the node that started it |
| SAML and CLI login throttles | Each node counts on its own |
| STS replay cache (default `in_process`) | A replay is not detected across nodes |

Nodes that share one storage directory see each other's writes only when `config.toml` sets
`cache_refresh_interval_secs` above 0 (default 0, off). Each node then re-reads its cached stores on that
interval and applies another node's surface changes as if they were saved locally. Policy definitions and
the appliance-wide policy set are re-read only at startup and on promotion, and the other stores refresh
what they read but rebuild nothing already compiled. Run the same gateway version on every node that shares
storage: a newer node can write a field an older one rejects, and the older node's refresh then drops that
record from its cache while it is still serving. While two versions share storage, set
`cache_refresh_interval_secs` to 0 on the older node.

| Dependency | Behaviour |
| --- | --- |
| Appliance-wide policy fails to compile | An enforced member makes its plane deny every request the plane evaluates until it is fixed; outbound calls and direct agent-card requests are never evaluated, and a monitor-only member that fails is dropped |
| Enforced gateway policy fails to compile | That gateway's traffic is denied |
| Trust registry unreachable | Reported to the policy as `TRUST_REGISTRY_UNREACHABLE`; the policy decides |
| Mediator link breaks | Reconnect with backoff from 30 s, doubling, capped at 1800 s (`[reconnect_policy]`) |
| `limits.json` missing or malformed | The gateway starts with no appliance limits |
| `settings.json` corrupt at boot | Replaced with defaults and saved, with only a warning: audit and Prometheus auth are off again |

## The extra hop

- The dashboard latency series, the average-latency card and Prometheus
  `agent_gateway_request_duration_seconds` measure the upstream round trip only, retries and
  backoff included. Gateway work (auth, policy, identity, VP minting) is not in them, whatever the docs
  call "end-to-end". A `2026-07-28` MCP request is the exception: it records the whole time from arrival
  to the end of its answer.
- Gateway overhead per request is `total_latency_ms - latency_ms` in the datapoints of
  `fabric agent-gateway api get /v1/dashboard/metrics/hierarchical`, kept `metrics_retention_minutes` (default 360);
  for a `2026-07-28` MCP request the two are equal.
  No overhead figure has been measured; compute it on your own traffic.
- The access log's INFO line per request carries the gateway-side total in ms, and with OTel traces
  on, the span `Send Request & Await Response` is the upstream leg.
- Upstream client: every direct forward resolves the host in a blocking task and builds a new client pinned to
  that address, so it opens a new TCP and TLS connection with no reuse between requests (inference), follows no
  redirects and has no separate connect timeout. Only `proxy://` targets, mirrors and the HTTP+SSE fallback
  ([KI-49](known-issues.md)) send through the pooled client, with its 10 s connect timeout and 10 idle
  connections per host for 30 s. Payload capture (`[extension_inspection] enabled`, on by default) runs
  inline before the response returns, so it adds latency, whatever the docs say; how much has not been
  measured.
- Streaming: a `2024-11-05` MCP answer in `text/event-stream` passes through as it arrives, except a
  `tools/list`, which is buffered so it can be filtered. An MCP GET, or a `2024-11-05` POST that accepts
  `text/event-stream`, gets a 24 h upstream timeout. A `2026-07-28` MCP answer streams until
  `mcp_http.stream_idle_timeout_secs` (default 60) pass with no event or `mcp_http.stream_max_lifetime_secs`
  (default 3600) pass in all. Every other response, A2A `message/stream` and `tasks/resubscribe`
  (`SendStreamingMessage` and `SubscribeToTask` in A2A 1.0) included, is buffered and delivered in one burst
  when the upstream finishes, so a stream must finish inside the request timeout, with no pause longer than
  `timeout.idle_secs`.

## Traffic management

On the direct path the rate limit runs after caller authentication, which hands a failed credential to the
policy instead of refusing it, and before every policy gate, target auth and the upstream send. So a 429
says nothing about the caller's credentials or policy, unless the surface sets `mcp_http.authorization`,
whose bearer-token check refuses a bad token before the limiter.

| Setting | Where | Default when the block is absent |
| --- | --- | --- |
| `rate_limit` `{requests, window_secs, burst?}` | `access_point.rate_limit` (feature `rate-limit`) | Off |
| `timeout` `{request_secs, idle_secs}` | `target.networking` (feature `networking`) | `request_secs`: `[a2a] timeout_seconds` in `config.toml`, default 30; `idle_secs`: 60 |
| `retry` `{max_attempts, initial_backoff_ms, max_backoff_ms, backoff_multiplier, retryable_status_codes}` | `target.networking` | Off: one send |
| `circuit_breaker` `{failure_threshold, success_threshold, timeout_secs, window_secs}` | `target.networking` | Off |
| `mirror` `{endpoint, percentage, wait_for_response, timeout_secs}` | `target.networking` | Off |

`add-feature networking --json` writes the whole `target.networking` object: adding a circuit
breaker with only `circuit_breaker` in the JSON drops an existing `timeout`, `retry` or `mirror`.
Always pass the complete object, built from `fabric agent-gateway surfaces get <surface-id> -o json`.
Two edits to `target.networking` at once lose one of them ([KI-32](known-issues.md)).

### Rate-limit a surface

**Confirm with the user:** callers over the limit get HTTP 429 until the bucket lets their next request
through.

The limit is a token bucket per surface, per process: it holds `burst` requests (default `requests`)
and refills one every `window_secs / requests` seconds. Each surface save installs a fresh bucket.
**Before.** `fabric agent-gateway surfaces get <surface-id> -o json > before.json` keeps any current
`access_point.rate_limit`. **Change.**

<!-- e2e: rate-limit-mcp -->
```bash
SURFACE_ID="${SURFACE_ID:?set SURFACE_ID to the surface to limit}"
REQUESTS="${REQUESTS:-100}"; WINDOW_SECS="${WINDOW_SECS:-60}"
fabric agent-gateway surfaces add-feature "$SURFACE_ID" rate-limit \
  --json "{\"requests\":$REQUESTS,\"window_secs\":$WINDOW_SECS}" -o json > after.json
jq '.access_point.rate_limit' after.json
```

**Verify.** Send one request more than the limit, at once. On MCP the last is HTTP 429 with JSON-RPC
`-32000` `Rate limit exceeded`, `id: null`, and `error.data.retry_after` holding a sentence such as
`Rate limit exceeded. Retry after 151.881319ms`, not a number ([KI-29](known-issues.md)). The `Retry-After`
header gives the same wait in whole seconds, rounded up. The wait is until the next single request is allowed
(the bucket refills one request every `window_secs / requests`), not until the window resets. Every caller of
the surface shares the bucket, so on a surface with live callers this test empties it for them too: there,
read `access_point.rate_limit` back and send one request that must succeed, and keep the overflow test for a
test surface.

<!-- e2e: rate-limit-mcp -->
```bash
LISTEN="$(jq -r .access_point.listen_address after.json)"; ROUTE="$(jq -r .access_point.route after.json)"
case "$LISTEN" in http://*|https://*) URL="$LISTEN$ROUTE" ;; *) URL="http://$LISTEN$ROUTE" ;; esac
N="$(( $(jq -r .access_point.rate_limit.requests after.json) + 1 ))"
for i in $(seq 1 "$N"); do
  curl -sS -o last-body.json -D last-headers.txt -w "call $i: HTTP %{http_code}\n" "$URL" \
    -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
    -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"curl","version":"1"}}}'
done
cat last-body.json; echo
grep -i '^retry-after:' last-headers.txt || echo "no Retry-After header"
```

On an A2A surface the change is the same command, and the 429 is problem+json with
`detail: "Rate limit exceeded"` and the same `Retry-After` header:

<!-- e2e: rate-limit-a2a -->
```bash
LISTEN="$(jq -r .access_point.listen_address after.json)"; ROUTE="$(jq -r .access_point.route after.json)"
case "$LISTEN" in http://*|https://*) URL="$LISTEN$ROUTE" ;; *) URL="http://$LISTEN$ROUTE" ;; esac
N="$(( $(jq -r .access_point.rate_limit.requests after.json) + 1 ))"
for i in $(seq 1 "$N"); do
  curl -sS -o last-body.json -D last-headers.txt -w "call $i: HTTP %{http_code}\n" "$URL" -H 'Content-Type: application/json' \
    -d '{"jsonrpc":"2.0","id":"rl-1","method":"message/send","params":{"message":{"kind":"message","role":"user","messageId":"rl-1","parts":[{"kind":"text","text":"ping"}]}}}'
done
cat last-body.json; echo
grep -i '^retry-after:' last-headers.txt || echo "no Retry-After header"
```

- **Undo.** `fabric agent-gateway surfaces update <surface-id> --file before.json` restores the previous limit. When there
  was none, `fabric agent-gateway surfaces remove-feature <surface-id> rate-limit` does the same.
- **If it fails.** A 429 on the first call means other traffic drained the bucket. Every call 200 means
  the save did not apply: read the gateway log, then re-save the surface.

### Timeouts, retry and circuit breaker

- **Timeout.** `request_secs` bounds the whole exchange, the read of a buffered response body included.
  `idle_secs` (default 60, `0` turns it off) bounds each pause while a buffered body arrives. `connect_secs`
  is accepted and ignored, and connecting counts against the request timeout ([KI-30](known-issues.md)).
  Without a `timeout` block, `[a2a] timeout_seconds` stands in for `request_secs` and the 60 s idle bound
  still applies. An MCP GET, or a POST that accepts `text/event-stream`, gets a 24 h upstream timeout either
  way, unless it is a `2026-07-28` request, which must start its answer within `request_secs` (30 without a
  `timeout` block). A slow upstream then gets 502 `Request timeout to target endpoint ...`; a buffered body
  that stalls or runs late gets 504 `Upstream response timed out`, and a late `2026-07-28` answer 504
  `Modern MCP upstream response headers timed out`.
- **Retry.** `max_attempts` counts retries, so the default 3 means four sends. Backoff starts at
  100 ms, doubles and stops at 5000 ms. It retries transport errors and the statuses 408, 429, 500,
  502, 503 and 504, and it retries **POST** too: turn it on only for an idempotent upstream. After the
  last attempt the upstream's own response is relayed. A `2026-07-28` MCP request is never retried.
- **Circuit breaker.** It counts only transport failures (refused, timed out). An upstream 5xx is a
  successful send and never trips it. After `failure_threshold` (default 5) consecutive failures
  inside `window_secs` (60), callers get 503 `Service temporarily unavailable. Retry after <duration>`,
  with no `Retry-After` header, until `timeout_secs` (60) pass; a success, or the window running out,
  resets the count. Then it half-opens: every request passes, `success_threshold` (2) successes close
  it and one failure reopens it. The dashboard's defaults differ (3 and 30).
- **Upstream errors** are gateway-built problem+json with `type`
  `https://a2a-protocol.org/errors/proxy-error`. A 502 or 503 that is not problem+json came from the
  upstream and was relayed (inference).
- **Mirror.** It sends to `endpoint` exactly as written, without the request path, with the caller's
  headers minus its credential plus `X-Mirrored-Request: true` and a trace ID ending `-mirror`.
  `percentage` defaults to 100 and `wait_for_response` to `false`, fire-and-forget, the opposite of
  the dashboard toggle's default. It never runs on outbound transit calls, and the endpoint gets no
  URL check, neither when the surface is saved nor when the mirror is sent.

### Rehearse an upstream outage

On a throwaway A2A surface pointed at a port nothing listens on: see what callers get, and prove a
breaker trips before you rely on it.

<!-- e2e: upstream-down-a2a -->
```bash
UPSTREAM_URL="${UPSTREAM_URL:-http://127.0.0.1:9}"; SURFACE_NAME="${SURFACE_NAME:-outage-drill}"
fabric agent-gateway runtime show surface-routing -o json > routing.json
LISTEN="$(jq -r '.available_listen_addresses[0]' routing.json)"; PREFIX="$(jq -r '.channel_path_prefix[0].prefix' routing.json)"
fabric agent-gateway surfaces create --name "$SURFACE_NAME" --protocol a2a --listen-address "$LISTEN" \
  --route "$PREFIX/$SURFACE_NAME" --target-endpoint "$UPSTREAM_URL" -o json > drill.json
case "$LISTEN" in http://*|https://*) URL="$LISTEN" ;; *) URL="http://$LISTEN" ;; esac
printf '%s%s\n' "$URL" "$(jq -r .access_point.route drill.json)" > drill-url.txt
printf '%s\n' '{"jsonrpc":"2.0","id":"d-1","method":"message/send","params":{"message":{"kind":"message","role":"user","messageId":"d-1","parts":[{"kind":"text","text":"ping"}]}}}' > drill-body.json
jq '{surface_id, status, networking: .target.networking}' drill.json
```

With no breaker configured, every call is a 502 whose `detail` starts
`Connection failed to target endpoint`:

<!-- e2e: upstream-down-a2a -->
```bash
for i in 1 2 3 4 5 6; do
  curl -sS -o last-body.json -w "call $i: HTTP %{http_code}\n" "$(cat drill-url.txt)" \
    -H 'Content-Type: application/json' --data @drill-body.json
done
cat last-body.json; echo
```

Add a breaker. The JSON is the whole networking object:

<!-- e2e: upstream-down-a2a -->
```bash
SURFACE_ID="$(jq -r .surface_id drill.json)"; FAILURE_THRESHOLD="${FAILURE_THRESHOLD:-5}"
fabric agent-gateway surfaces add-feature "$SURFACE_ID" networking --json \
  "{\"timeout\":{\"request_secs\":30},\"circuit_breaker\":{\"failure_threshold\":$FAILURE_THRESHOLD,\"success_threshold\":2,\"timeout_secs\":60,\"window_secs\":60}}" \
  -o json > drill.json
jq .target.networking drill.json
```

**Verify.** The first `failure_threshold` calls are 502, the next is 503.

<!-- e2e: upstream-down-a2a -->
```bash
N="$(( $(jq -r .target.networking.circuit_breaker.failure_threshold drill.json) + 1 ))"
for i in $(seq 1 "$N"); do
  curl -sS -o last-body.json -w "call $i: HTTP %{http_code}\n" "$(cat drill-url.txt)" \
    -H 'Content-Type: application/json' --data @drill-body.json
done
cat last-body.json; echo
```

- **Undo.** `fabric agent-gateway surfaces delete <surface-id>` for the drill surface (no prompt,
  [KI-34](known-issues.md)).
- **If it fails.** A 503 with a send-failure text means the endpoint contains a placeholder host such as
  `example.com`; a 403 `Request blocked by egress policy` means the host does not resolve from the
  gateway.

## Audit, logs and metrics

A settings update changes only the fields the document holds, but `audit_events` and `feature_flags` are
each replaced whole. An event you leave out stops being recorded, and a flag you leave out returns to its
default, such as `ap2_experimental`, which is off when absent ([protocols.md](protocols.md)). `settings set`
and `settings reset` need `settings.edit` (administrator by default).

Every audit destination records only the events selected for it, and nothing is selected by default. The VP
Audit Log, which `audit list` reads, keeps the events named in the settings' `audit_events` while
`audit_enabled` is on. Each Governance Audit integration receives the events in its own `audit_events`,
independently of the log ([Logs and metrics](#logs-and-metrics)). An event is recorded only from the moment it
is selected. The catalog lists every event name with its group (policies, trust, identity, trace, auth,
delegation, payments and requests), and a name outside it gets 400
`Audit events must be names from the audit event catalog`:

<!-- e2e: audit-settings-replace -->
```bash
fabric agent-gateway api get /v1/settings/audit-events -o json | jq -r '.[] | "\(.group)\t\(.event)"'
```

`auth_failed`, `rate_limited` and `request_rejected` are recorded for each request they apply to, with no
sampling, so a flood of unauthenticated or unroutable requests writes one record per request.

The docs' Settings and Audit log pages describe three audit categories instead; the gateway ignores an
`audit_categories` field. Policy decision records are plain JSON lines and no VP carries them, although the
Audit log page says each one is attested in a signed VP.

### Turn on audit events without switching others off

**Confirm with the user:** audit rows hold raw caller email and name, and the file grows without bound.

**Before.** Save what is on now; this file is also your undo.

<!-- e2e: audit-settings-replace -->
```bash
fabric agent-gateway settings show -o json | jq '{audit_enabled, audit_events}' > audit-before.json
cat audit-before.json
```

**Change.** Write back every event already selected, with `policy_decision` added.

<!-- e2e: audit-settings-replace -->
```bash
jq '{audit_enabled: true, audit_events: ((.audit_events // []) + ["policy_decision"] | unique)}' \
  audit-before.json > audit-on.json
fabric agent-gateway settings set --file audit-on.json -o json | jq '{audit_enabled, audit_events}'
```

**Verify.** `audit_enabled` is `true`, and `audit_events` holds `policy_decision` and every event it held before.

<!-- e2e: audit-settings-replace -->
```bash
fabric agent-gateway settings show -o json | jq '{audit_enabled, audit_events}'
```

- Then send one request through a surface with a policy, and read the decision without the caller's fields:

  ```bash
  fabric agent-gateway audit list --category policy_decision --limit 5 -o json \
    | jq '[.events[] | {timestamp, trace_id, surface_id, decision: .event.policy_decision | {decision, scope, flow, policy_name}}]'
  ```

- **Undo.** `fabric agent-gateway settings set --file audit-before.json`.
- **If it fails.** An empty `audit list` is ambiguous: the gateway answers 200 with no events when the
  file cannot be read, records nothing from before an event was selected, and records nothing while its audit
  pipeline is not running (a standby node, or `agent_gateway_audit_pipeline_started` at 0). A 400
  `Audit events must be names from the audit event catalog` means a misspelled event: compare it with the
  catalog above. Never pipe a whole `settings show` document back: `fabric agent-gateway settings set` refuses
  `feature_flags.terms`, and `feature_flags` would be replaced.

### Turn on log redaction

Do this before the first log read on a gateway that serves real callers. **Confirm with the user:** it edits
`gateway.json` and needs a restart, which drops every caller's connection
([Recipe: change a listener or prefix](#recipe-change-a-listener-or-prefix)).

**Before.** Keep a copy of `gateway.json`, and read the redaction settings in the file on disk. Redaction is on
only when `enabled` is `true` and `rules` is above 0, and only since the process last started.

<!-- e2e: log-redaction -->
```bash
fabric agent-gateway api get /v1/gateway/config -o json \
  | jq '.logging.redaction | {enabled, rules: (.rules // [] | length)}'
```

**Change.** In `gateway.json`, set `logging.redaction` to `{"enabled": true, "rules": [...]}`, starting from the
rules in the gateway's example configuration (`config/examples/gateway.example.json`). They replace JWTs,
authorisation header values, tokens, passwords, email addresses, IP addresses, DIDs and similar patterns in every
line written to the log file and standard error, and in exported OTLP spans. Leave out its `Phone numbers` rule
if you search logs by UUID ([KI-45](known-issues.md)). Parse the file (`jq . gateway.json`), then restart.

**Verify.** Run the Before block again and send one request through a surface with a policy. Then, with the
user's go-ahead for the download, count the markers; the count is above 0.

<!-- e2e: log-redaction -->
```bash
umask 077
fabric agent-gateway logs download --output-file gw-logs.zip
unzip -p gw-logs.zip | grep -ci 'redacted' || true
rm -f gw-logs.zip
```

**Undo.** Put the saved `gateway.json` back and restart.

**If it fails.** A rule whose pattern does not compile is skipped, and standard error shows
`Skipping invalid redaction rule '<name>': <error>` at start; fix the pattern and restart.

Each rule is a pattern, so a value no rule matches, such as a person's name in a JWT claim, is still written.
Lines written before the restart, and archives taken before it, stay as they were.

### Logs and metrics

| Topic | Behaviour |
| --- | --- |
| Audit file | One append-only `delegation-audit.jsonl`, never rotated, read whole on every `audit list`; `--limit` is clamped to 1-500. Treat audit reads as expensive. `audit list` redacts callers' email and name and each `vp_jwt` unless you pass `--reveal` |
| Delegation audit | `fabric agent-gateway api get "/v1/delegation-audit?page_size=100" -o json` reads the same file without policy decisions, Trust Checks, trace terminations and the request events (`auth_failed`, `rate_limited`, `request_rejected`, `identity_binding_verified`, `identity_binding_failed`), in pages of at most 100 with `category_counts`; it needs `audit.view` |
| Main log | `agent-gateway.log` in `[logging] log_directory`, never rotated; every line also goes to standard error, the only local copy when no directory is set. Rotate it outside the gateway |
| `fabric agent-gateway logs download` | Builds a ZIP of every log file in memory, and needs `audit.view` (administrator by default). Treat the archive as a secret ([KI-05](known-issues.md)). Any signed-in account still reads the last log lines through the dashboard ([KI-59](known-issues.md)) |
| `fabric agent-gateway logs truncate --yes` | Deletes rotated `agent-gateway*.log*` files and keeps the current one; download first |
| Log redaction | Off unless `gateway.json` carries `logging.redaction` with `enabled: true` and rules, whatever the docs say. The example configuration's phone rule also rewrites parts of UUIDs ([KI-45](known-issues.md)) |
| OTLP export | `metrics config set --file` replaces the whole metrics config and applies it live; with `protocol: http`, `/v1/traces`, `/v1/metrics` or `/v1/logs` is appended to `endpoint`; `traces.enabled` is ignored |
| Who can change telemetry | `metrics config show`, `metrics config set` and `metrics test-endpoint` need `settings.edit` (administrator by default). `metrics truncate` and `logs truncate` have no permission check, so any signed-in user can run them, whatever `rbac.json` says ([KI-05](known-issues.md)) |
| Prometheus scrape | `/api/v1/metrics/prometheus` is open to anyone who reaches the port unless `prometheus_auth_enabled` is set; then HTTP Basic |
| Event notifications | `fabric agent-gateway integrations` manages email, Slack, webhook and stream (Kafka, Kinesis, Pulsar, Redis Streams) integrations that fire on gateway events such as connection point, mediator, trust registry, secret and user changes. A user event carries only the user's `user_id`, `role`, `status`, `is_primary`, `created_at` and `updated_at`, and never reaches an integration a tenant owns. The settings' `appliance_id` fills `${APPLIANCE_ID}` in every template. Sending a test notification has no typed command |
| Audit forwarding | An active Governance Audit integration (category `audit`) owned by no tenant, of any type, receives the events in its own `audit_events`, independently of the VP Audit Log, and nothing while that list is empty. Set them with `fabric agent-gateway integrations update <id> --file integration.json`, starting from `integrations get <id> -o json`; a name outside the catalog gets 400 `Unknown audit event: "<name>"`. Each record arrives as the event type `audit.<event>`, such as `audit.policy_decision`, at least once: receivers deduplicate on its `event_id`. Without limits a record is retried until delivered; `audit_drop_after_secs` skips records older than that, and `audit_max_attempts` skips a record after that many failed deliveries. Disabling an integration lets go of what it has not received, and once enabled again it receives only new records. Listing, reading, creating, changing, deleting or triggering one also needs `audit.view`. Email and Slack send one message per record, without the record itself or its VP, so use a stream or webhook integration on a busy gateway. `agent_gateway_audit_forward_total` counts deliveries by `result`: `delivered`, `failed` or `not_receiving` |
| Audit journal | Every selected record is written first to `journal/` next to the audit file, readable by the gateway's user only, and each destination reads it from its own position, so a slow or unreachable integration falls behind instead of losing records, and delivery resumes after a restart. `agent_gateway_audit_journal_bytes` gives its size; above 256 MiB the gateway logs a warning, and above 1 GiB the destinations holding back its oldest part are moved past it. Only an active node runs it. Alert when `agent_gateway_audit_pipeline_started` is 0, and when `agent_gateway_audit_records_lost_total` or `agent_gateway_audit_sink_skipped_total` grows |
| A2A protocol versions | `agent_gateway_a2a_protocol_version_total` counts the A2A requests the version check sees by `channel_id`, `negotiated_version` (`0.3`, `1.0`, or `rejected` for a request refused with `-32009`) and `method_era`; read it before you remove `0.3` from a surface's accepted versions ([protocols.md](protocols.md#a2a-surface-settings)) |
| `fabric agent-gateway settings reset --force` | Turns audit and Prometheus auth off; the password cannot be restored from a saved `settings show`, because reads blank its hash |

Before enabling OTLP `auth`, create the secret and confirm it with `fabric agent-gateway secrets list -o json`. The
response must read "Metrics configuration updated and applied."; anything else means do not restart.

## Moving config between gateways; backup and restore

Not tried on a running gateway: a restore overwrites the whole store and restarts the process. **Backup and restore
clone one gateway; they do not migrate between gateways.** A restore replaces all of `_storage`, users
and passkeys included, and refuses a backup whose manifest names another domain. To move
surfaces to a different gateway, copy objects one by one.

### Move surfaces to another gateway

1. **Before.** On the source, save `fabric agent-gateway surfaces get <surface-id> -o json`,
   `fabric agent-gateway policies get <policy-id> -o json` and every provider, JWT strategy, certificate and proxy the
   surface names. Secret values never leave the gateway; record each `secret_id` only.
2. **Change.** **Confirm with the user:** this creates the surfaces and every object they name on the new
   gateway, secrets included. On the new gateway, create in dependency order. A surface save that names a
   policy, secret, issuer, certificate, JWT strategy, credential provider, MCP or A2A proxy, trust registry or
   peer gateway the gateway does not have is refused with 400 `<kind> reference is not accessible`, such as
   `Policy definition reference is not accessible`:
   - secrets, same `secret_id`, values from where you keep them
     (`printf %s "$VALUE" | fabric agent-gateway secrets create --secret-id <secret-id> --name <name> --value-stdin`);
   - policies, same `--id` (`fabric agent-gateway policies create --id <policy-id> --name <name> --policy-file <file.rego>`);
   - providers, strategies, certificates and A2A proxies: they get **new** server IDs, so map old to new; an
     MCP proxy keeps its `id` when the JSON you create it from carries one;
   - surfaces last, with those IDs and the listen addresses replaced by the new gateway's values, then
     `fabric agent-gateway surfaces create --file <surface>.json`, which keeps `surface_id`.
3. **Verify.** Diff `fabric agent-gateway surfaces get <surface-id> -o json` across the two gateways (only remapped
   IDs and addresses differ), then send a real request.
4. **Undo.** **Confirm with the user:** this deletes what the recipe created on the new gateway. Delete there in
   reverse order: surfaces, proxies, providers, policies, secrets.
5. **If it fails.** A credential provider's callback URL follows the new gateway's `oauth_callback_route`
   and is fixed when the provider is created: register the new URL with the OAuth provider.

Surface templates are the lighter alternative for sharing one shape:
`fabric agent-gateway api get /v1/surface-templates/<template-id>/export -o json > t.json`, then
`fabric agent-gateway api post /v1/surface-templates/import --file t.json`. The embedded surface is neither
validated nor remapped.

### Back up and restore the same gateway

1. **Before.** You need `storage.admin` (administrator). The archive holds all of `_storage` except
   logs and system metrics, including private keys and user data, and it is capped at 64 MiB.
   `fabric agent-gateway api` cannot carry a binary body, so use curl.
   Keep the operator bearer token off the command line, where the process
   list shows it: write the header to a file only you can read, and pass the file.

   ```bash
   umask 077
   printf 'Authorization: Bearer %s\n' "$(cat <token-file>)" > auth.hdr
   curl -sS -X POST -H @auth.hdr "$GATEWAY/api/v1/admin/backup-storage" -o backup.agbak
   ```

2. **Change.** **Confirm with the user:** the restore replaces every user, passkey, key, surface and
   setting on this gateway with the backup's, and takes the gateway down while it restarts. Check that
   a supervisor restarts the process on exit and that `did.domain` is unchanged, then
   `curl -sS -X POST -H @auth.hdr -F backup=@backup.agbak "$GATEWAY/api/v1/admin/restore-storage"`.
   Expect 200, then the process exits with code 1; at the next start it applies the backup and exits
   with code 1 again, so it restarts twice.
3. **Verify.** Sign in again; users, passkeys and surfaces are the backup's. Then `rm -f auth.hdr`.
   **Undo.** **Confirm with the user:** this again replaces every user, passkey, key, surface and setting and
   restarts the gateway. Restore the previous backup the same way.
4. **If it fails.** 400 `Backup validation failed` means a wrong domain, a wrong key or a damaged
   manifest; the cause is only in the server log. Restore needs the `backup_encryption_key` the backup
   was made with, or that key listed in `legacy_backup_encryption_keys`
   ([Configuration files](#configuration-files)).

## Health

| Endpoint | Answer | Use it for |
| --- | --- | --- |
| `GET /api/v1/alive` | Always `200 {"status":"OK"}`, no session needed | Liveness |
| `GET /api/v1/health` | 503 with an empty body while the node is in standby, and while it starts or is being promoted, until its surfaces and policies are loaded; otherwise 200 `{"status":"OK"}`. It checks no dependency (vault, mediator, trust registry, OTLP; use `fabric agent-gateway metrics status` for OTLP) | Readiness, and whether this node is active |
| `GET /api/v1/version` | `{"version": "..."}`, no session needed | Which build answers |
| `GET /api/v1/limits` | `{id, name, description, limit, current}` per dimension | Headroom before bulk creates; a create over a limit gets 403 `Appliance limit reached for '<kind>': <n> of <max> in use` |
| `GET /alive` on an outbound listener's port | `200 {"status":"OK"}`; that listener has no `/api`. After a full reload, an outbound listener that serves no Transit Point is left unbound and answers nothing until a restart or a reload that gives it one | Liveness of the listener Transit Points use |

These answer without a sign-in on the management prefix (`/api` in the example configuration):
`/v1/alive`, `/v1/health`, `/v1/version`, `/v1/permissions/public`, `/v1/metrics/prometheus` (unless
Prometheus auth is on), `/v1/terms/applicable`, `/v1/terms/provider-health`, the DID lookups
`/v1/identity/resolve-did` and `/v1/resolve`, the STS under `/oauth2/` (it checks client credentials
itself), the sign-in flows under `/auth/` and `/saml/`, `/v1/auth/mode`, the DIDComm endpoint `/didcomm`,
the temporary onboarding agents under `/onboard/`, `/agents-api/v1/onboard` (mints a managed DID for any
identity fields and returns the DID but no key) and `/agents-api/v1/verify-jwt`, `/ws` (see
`websocket_require_auth` below) and `/avatars/`. At the root, DID documents answer too: the gateway's
under `/.well-known/`, each managed agent DID (`...:surface:<id>`) under `/surface/<id>/`, each connection
point's under `/connection-points/<cp-id>/`, and did:webvh logs under `/dids/`. Decide at the edge which of these the
internet may reach.

## Configuration files

The gateway reads `config.toml` at startup, and the files it names under `[config_files]`: `gateway`
(`gateway.json`: listeners, prefixes, routes), `metrics`, `rbac`, `limits`, `saml`, `x402`, `x402_proxy` and
`agent_surface_templates_dir`, whose starter templates are seeded at startup. What each change needs
to apply is in [What is applied when](#what-is-applied-when). `fabric agent-gateway api get /v1/gateway/config -o json`
prints `gateway.json` as it is on disk. It needs `settings.view`, administrator-only by default.

Keys in `config.toml` that change behaviour in ways the example file does not show:

| Key | What to know |
| --- | --- |
| `backup_encryption_key` | Required: `env://VAR`, `file://path` or 64 hex characters. Boot stops when it is missing, empty or does not resolve. `legacy_backup_encryption_keys` names up to four earlier keys, comma-separated, tried after it when a restore needs one; remove it after a fresh backup |
| `auth_mode` | `passkey` by default and in the example. `saml` needs a readable `saml.json` (IdP entity ID, SSO URL and certificate), or boot stops with `Failed to load SAML configuration`. The IdP posts to `<api prefix>/saml/acs` and reads `<api prefix>/saml/metadata` |
| `websocket_require_auth` | Keep `true`, the default. With `false`, `<api prefix>/ws` and `/ws/dashboard` stream live log lines, captured request and response payloads and identity events to anyone who reaches the port ([KI-05](known-issues.md) says what the log lines hold) |
| `secrets_backend` | `filesystem` (default) or `aws`; any other value falls back to `filesystem` with only a warning. On `filesystem` with encryption at rest off, secrets are plaintext JSON ([KI-03](known-issues.md)) |
| `[oob_connection] pending_expiry_hours` | How long an acceptor waits for the other gateway to approve a handshake; 1 by default and absent from the example ([g2g.md](g2g.md)) |
| `[reconnect_policy]` | `initial_backoff_seconds` (30), `max_backoff_seconds` (1800) and `backoff_multiplier` (2.0) for connection point links |
| `[did_cache]` | DID documents for gateway-to-gateway links. An entry is used without resolving again until it is `stale_threshold_percent` (80) of `ttl_seconds` old: 86400 (24 hours) by default and in the example. When resolving again fails, the cached copy stays in use, so a peer's key change can take that long to be seen. Other lookups, such as presentation checks, use a separate one-hour cache. `did:web` and `did:webvh` resolution refuses a host that is, or resolves to, a loopback, private-network, carrier-grade NAT or link-local address, and names such as `localhost`. `allow_private_hosts = true` (default `false`, read at startup) lifts that for every DID lookup, cloud metadata addresses included: use it only for a local stack, such as one whose mediator is on `localhost`, and never where a metadata service is reachable |
| `server_mode` | `active` by default; `standby` answers 503 on `/api/v1/health` and keeps the connection-point and trust-registry links down until `SIGUSR1` promotes it. Write it before any `[table]` header ([Outage and standby](#outage-and-standby)) |
| `[storage_paths]` | A relative path resolves against the folder that holds `config.toml`, except `policy_definitions`, `global_policies`, `issuers`, `authorities`, `credential_providers` and `delegation_vault`, which resolve against the working directory, and `backup_restore`, which the startup restore check resolves against `--base-folder` when it is set and the restore API against the working directory. Write absolute paths in a deployment |
| `cache_refresh_interval_secs` | 0, off, by default. Set it above 0 when nodes share one storage directory, so each re-reads the shared stores on that interval ([Outage and standby](#outage-and-standby)) |
| `[a2a] default_version` | The preferred A2A version on the agent cards the gateway builds, such as an A2A proxy card, among the versions the card lists: `1.0` by default and in the example configuration. A value whose major and minor are not 0.3 or 1.0 stops boot with `a2a.default_version '<v>' is not a supported A2A protocol version`. Accepted versions and validation are set per surface ([protocols.md](protocols.md#a2a-surface-settings)) |
| `[logging]` | `level`, `json` and `log_directory` are read from here only; an unknown `level` stops boot with `Cannot parse log level` |
| `[rbac]` | Parsed and ignored: roles come from the file `[config_files] rbac` names. When that file cannot be loaded the gateway logs a warning and runs with the built-in permissions |
| `[mcp]` | Only the `[mcp.continuations]` table is read: gateway-originated consent for MCP `2026-07-28` callers, credential delegation included, needs it together with `sts.mcp_issuer` in `gateway.json`, and a table that fails validation stops boot with `Invalid [mcp.continuations] config`. The other fields are inert: the MCP version check is built in, and `fabric://` waits use `[a2a] fabric_gateway_timeout_ms`, so the example's 5000 ms here does nothing |
| `[tls] verify_upstream` | Nothing reads it; `false` changes nothing |

Keys in `gateway.json` to check before a first start:

| Key | What to know |
| --- | --- |
| `routes.api.prefix` | The management API prefix, `/api` in the example. `fabric` always calls `/api/...`, so keep it ([fabric.md](fabric.md)) |
| `routes.dashboard` | The static route with `fallback: true`: every path nothing else matches answers the dashboard's HTML with 200 |
| `routes.<name>` with `type: "proxy"` | Serves surfaces under `<prefix>/...` like a `channels` entry, but not at the bare prefix and with no `$<variant>` routes |
| `listeners[].bind_address` | An inbound listener accepts connections on every network interface whatever this says; only outbound listeners use it. Restrict who reaches inbound ports with a host firewall or the container's port publishing ([KI-58](known-issues.md)) |
| `listeners[].external_urls` | When an outbound listener shares a hostname with an inbound one, as the example's `localhost` URLs do, the inbound port forwards every `/outbound/...` request to the outbound listener, `X-Transit-Token` included, so Transit Points answer on the inbound port too. To keep them off it, give the two listeners no hostname in common |
| `webauthn.rp_id`, `webauthn.external_origin` | Passkey sign-in: `rp_id` is the host users open the dashboard on (or a parent domain) and `external_origin` that origin; passkey sign-in fails when they do not match |
| `cors` | Browser origins allowed to call surfaces and the management API. Empty, as in the example, allows none, except that public discovery paths on surfaces answer any origin |
| `facilitator_mode.enable_test_endpoints` | Keep `false`: `true` mounts unauthenticated x402 test endpoints on the inbound listener |
| `facilitator_mode.facilitator_via_http` | Mounts the x402 facilitator at `/api/x402/verify`, `/settle` and `/supported`, outside the management API's sign-in check, so anyone who reaches the port can call them |
| `cli_login_throttle`, and `login_throttle` in `saml.json` | Per-client-IP limits on the `fabric` browser login and on SAML sign-in, off by default (20 requests per 60 s when on). Over the limit gets 429 with `Retry-After` |
| `client_ip.trusted_proxies` | Proxy CIDRs whose `X-Forwarded-For` (or `Forwarded`) names the caller for those two limits. Empty by default, so behind a load balancer every caller counts as the balancer and shares one limit; startup logs a warning when a limit is on and the list is empty |
| `logging` | Only `logging.redaction` is read from this file. `logging.level` and `logging.json` here are ignored, so the example's `"level": "debug"` does nothing |
| `oob_connection` | Ignored; the key that counts is in `config.toml` |

## When it fails

| Exact text | Cause | Fix |
| --- | --- | --- |
| 429 `Rate limit exceeded` | Per-surface limiter | Retry after the `Retry-After` seconds |
| 502 `Connection failed to target endpoint` | Upstream refuses connections from the gateway host | Fix the upstream or the network path |
| 403 `Request blocked by egress policy` | The upstream host does not resolve from the gateway, or is a cloud metadata address | Fix the endpoint or the gateway's DNS |
| 502 `Request timeout to target endpoint` | Upstream slower than the request timeout | Raise `timeout.request_secs` or fix the upstream |
| 504 `Upstream response timed out` | The upstream's response body paused for longer than `timeout.idle_secs` (60 by default), or reading it ran past the request timeout | Raise `idle_secs` or `request_secs`, or fix the upstream |
| 504 `Modern MCP upstream response headers timed out` | A `2026-07-28` MCP upstream did not start its answer within `timeout.request_secs` (30 without a `timeout` block) | Raise `request_secs` or fix the upstream |
| 502 `Upstream response too large` | The upstream's response is larger than `[a2a] max_body_size` in `config.toml` (10 MiB by default) | Make the response smaller, or raise `max_body_size` and restart |
| 502 `Connection timeout to target endpoint '<url>'` | The upstream did not accept the connection in time: a host that is down, or a firewall that drops packets | Check the network path from the gateway; connecting counts against the request timeout ([KI-30](known-issues.md)) |
| 502 `DNS resolution failed for target endpoint '<url>'` | The connection failed on name resolution; on the usual path an unresolvable host is refused earlier, with 403 `Request blocked by egress policy` | Fix the hostname or the gateway's DNS |
| 403 `Appliance limit reached for '<kind>': <n> of <max> in use` | A create would pass the appliance limit for that kind | Delete unused objects; `GET /api/v1/limits` shows the headroom |
| 500 `Failed to load network configuration: <e>` from `runtime show surface-routing` or a reload | `gateway.json` on disk cannot be read or parsed | Fix the file, then restart; everything that re-reads it fails until then ([KI-36](known-issues.md)). A surface save or delete still answers success, but its apply runs a full reload that fails the same way after aborting every listener ([KI-35](known-issues.md)) |
| 503 `Service temporarily unavailable. Retry after` | Circuit breaker open | Fix the upstream; it half-opens after `timeout_secs` |
| Duplicate side effects at the upstream | Retry is on and resends POST | Turn retry off or make the upstream idempotent |
| Saved with 200, behaviour unchanged | The apply failed and was only logged, or `fabric://` send skipped a policy that did not compile ([KI-11](known-issues.md)) | Read the log; fix the cause, then save again |
| Saved with 200, then every direct request to the surface gets 403 `OPA policy enforcement is enabled but no policy is loaded for this channel` | Its policy did not compile, so the gateway dropped the surface's compiled policies | Read the log for the compile error, fix the Rego, then update the definition or save the surface again |
| Connection refused everywhere after `fabric agent-gateway runtime reload` | `gateway.json` failed to load after the listeners were aborted | Fix the file, restart |
| Boot stops: `Failed to resolve OTLP exporter authentication` | OTLP `auth.secret_id` names a missing secret | Create the secret, or remove `auth` from `metrics.json` on disk |
| Boot stops: `backup_encryption_key is required` | The key is empty, not 64 hex characters, or its `env://` variable or `file://` path is missing. With no `backup_encryption_key` line at all, boot stops earlier with `Failed to load bootstrap config from <path>` | Supply the key the gateway's backups use ([Configuration files](#configuration-files)) |
| Boot stops: `Failed to load SAML configuration from <path>` | `auth_mode = "saml"` with no readable `saml.json` | Set `auth_mode = "passkey"`, or provide `saml.json` |
| Boot stops: `Failed to load surfaces from local storage` | The surface store cannot be read, or `gateway.json` cannot be read for the duplicate-route check; the error under it says which | Fix the storage directory's permissions or the file |
| Boot stops: `Invalid [a2a] config: <reason>` | An `[a2a]` value fails its check: an unsupported `default_version`, `message_expires_seconds` not above `fabric_gateway_timeout_ms`, a zero `max_inflight_dispatches`, `sdk_inbound_cache_count` or `sdk_inbound_cache_bytes`, or `fabric_stream_max_envelope_bytes` outside 64 KiB to 1 MiB or above `sdk_inbound_cache_bytes` | Fix the field the reason names |
| Boot stops: `Invalid [mcp.continuations] config: ...` | The `[mcp.continuations]` table fails validation | Fix the table, or remove it |
| `audit list` empty | Audit is off, the event is not selected, the audit pipeline is not running, or the file is unreadable | `fabric agent-gateway settings show -o json`, then the log |
| Restore answers 413 | Archive over 64 MiB | Trim storage before the backup |
| Restore answers 200 and the gateway stays down | No supervisor restarted it after the exit | Run it under systemd or a container restart policy |
| `fabric agent-gateway runtime reload --surface <surface-id>` answers 500 | Unknown surface ID | Check `fabric agent-gateway surfaces list` ([KI-43](known-issues.md)) |

## Known issues here

- [KI-05](known-issues.md): the log archive holds policy input with JWT claims, and `logs truncate` and `metrics truncate` need no role.
- [KI-19](known-issues.md): `runtime reload` never recompiles policies.
- [KI-29](known-issues.md): on MCP, `data.retry_after` is a sentence, not seconds.
- [KI-30](known-issues.md): `timeout.connect_secs` is accepted and ignored.
- [KI-32](known-issues.md): concurrent surface edits lose one update.
- [KI-34](known-issues.md): deletes have no prompt.
- [KI-35](known-issues.md): a full reload rebinds every listener, and a broken `gateway.json` downs them all.
- [KI-36](known-issues.md): `runtime show surface-routing` re-reads the file.
- [KI-43](known-issues.md): `runtime reload --surface <unknown>` returns 500.
- [KI-58](known-issues.md): inbound listeners ignore `bind_address` and accept on every interface.
- [KI-59](known-issues.md): any signed-in account reads the last log lines through the dashboard.

Sources: [Audit log](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/concepts/audit-log/), [Observability](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/concepts/observability/), [Surface routing model](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/concepts/surface-routing-model/), [Surfaces](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/concepts/surfaces/), [Settings](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/reference/configuration/settings/), [Metrics reference](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/reference/observability/metrics/), [Networking elements](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/reference/surfaces/networking/), [Integrations reference](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/reference/configuration/integrations/); gateway source: `src/proxy/handler.rs`, `src/proxy/upstream_body.rs`, `src/policies/rate_limiter.rs`, `src/config/types.rs`, `src/main.rs`, `src/server/orchestrator.rs`, `src/server/mode.rs`, `src/proxy/server.rs`, `src/proxy/surface_manager.rs`, `src/identity/handlers/surfaces.rs`, `src/identity/handlers/surface_tenancy.rs`, `src/auth_manager/middleware.rs`, `src/identity/handlers/config.rs`, `src/identity/router.rs`, `src/observability/log_redact.rs`, `src/config/network.rs`, `src/config/bootstrap.rs`, `src/backup_restore/encryption.rs`, `src/backup_restore/handlers.rs`, `src/policies/surface_manager.rs`, `src/identity/handlers/policy_definitions.rs`, `src/observability/payload_capture.rs`, `src/auth/cli_login.rs`, `src/auth/auth_config.rs`, `src/auth/saml/pending_requests.rs`, `src/source_auth/client_ip.rs`, `src/gateways/did_cache.rs`, `src/integrations/audit_integration_triggers.rs`, `src/delegation_vault/audit.rs`, `src/audit/catalog.rs`, `src/audit/sources.rs`, `src/audit/journal.rs`, `src/audit/dispatch.rs`, `src/integrations/stream_publishers/mod.rs`, `src/metrics/backends/metric_names.rs`, `src/a2a/version.rs`, `src/config/limits_config.rs`, `src/x402/middleware.rs`, `src/integrations/user_integration_triggers.rs`, `src/surfaces/store.rs`; fabric's `src/client.rs`, `src/commands.rs`, `src/features.rs`.
