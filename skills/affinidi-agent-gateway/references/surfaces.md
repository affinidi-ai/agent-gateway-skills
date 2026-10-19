# Agent Surfaces

Read this before you create, change, disable or delete an Agent Surface, and when a surface answers 404, dashboard
HTML or a variant error. It also covers Transit Points (the managed agent's outbound calls) and where each
feature lands in the surface document. Every command here is in [commands.md](commands.md).

## Contents

- [The model](#the-model)
- [Before you create](#before-you-create)
- [Recipe: first surface, A2A](#recipe-first-surface-a2a)
- [Recipe: change a surface safely](#recipe-change-a-surface-safely)
- [Recipe: disable or delete with a backup](#recipe-disable-or-delete-with-a-backup)
- [Why a saved surface is not serving](#why-a-saved-surface-is-not-serving)
- [Variants](#variants)
- [Transit Points](#transit-points)
- [Feature placements](#feature-placements)
- [When it fails](#when-it-fails)
- [Known issues here](#known-issues-here)

## The model

A surface is one JSON document with two required parts:

- the **Access Point**: `listen_address` (a listener's external URL), `route` (the path callers use) and `protocol`
  (`a2a`, `ap2`, `mcp` or `didcomm`, lowercase);
- the **target**: `endpoint`, the managed agent's URL; policies, networking and the rest are optional.

Optional parts: `transit` ([Transit Points](#transit-points)), `variants` ([Variants](#variants)), `identity_slots`
and `outbound_credentials`. `status` is `active` (the default), `disabled` or `deleted`; only `active` surfaces are
loaded on reload. Unknown keys, such as a typo or a dashboard-only key, fail the save at
the top level and in `access_point` and `target`. Inside `transit`, `transit.points[]` and `target.auth` they are
dropped without an error, so read the saved document back. The save runs many validators. It refuses with 400 a
route that ends like a public discovery path, such as `/discovery`, `/agent.json` or `/agent-card.json`:
`route '<r>' matches an always-public discovery path`. It never tests that the listen address maps to a listener
or that the route sits under a prefix, and it accepts private and loopback targets, so review target URLs
yourself.

Pick the target scheme by what sits behind the surface:

| `target.endpoint` | Use it for | Read |
| --- | --- | --- |
| `https://…` or `http://…` | Your own MCP server or A2A agent | this file, [protocols.md](protocols.md) |
| `proxy://<mcp-proxy-id>` | A REST API exposed as MCP tools | [proxies.md](proxies.md) |
| `a2a-proxy://<a2a-proxy-id>` | A Copilot Studio agent (A2A or AP2 surfaces only) | [proxies.md](proxies.md) |
| `fabric://<gateway-id>/<surface-id>` | A surface on another organisation's gateway | [g2g.md](g2g.md) |

Any other scheme, no scheme, or a `did:<method>:…` endpoint gets 403 `Request blocked by egress policy`. Only
`did://…` reaches a stub, which answers 200 `text/plain` `Routing to DID: <endpoint> (path: <path>)` and forwards
nothing; do not use it.

The docs, the surface document and the code name the same things differently:

| Docs term | In the surface document or the routing view | In code, policy input and errors |
| --- | --- | --- |
| Agent Surface | the whole document | channel: `input.channel.config_id` is the surface ID |
| Access Point | `access_point` | AP |
| Target | `target` | target |
| Transit Point | an entry in `transit.points` | TP, keyed by its `alias` |
| Surface Variant | an entry in `variants` | virtual channel, selected by a variant alias (`input.channel.variant_alias`) |
| Channel Route (the dashboard's Entry point URL) | `listen_address` plus `route` | a route under a channel prefix (`channel_path_prefix`) |
| Caller Context | `access_point.caller_authentication` | source auth: `input.source_auth` |

The other dashboard elements map to the keys in [Feature placements](#feature-placements).

## Before you create

Run `fabric agent-gateway runtime show surface-routing -o json` and `fabric agent-gateway surfaces list -o json` first, and copy values from
them, never from docs or memory. The routing view has five fields:

| Field | What it is | What you do with it |
| --- | --- | --- |
| `available_listen_addresses` | External URLs of the inbound listeners | Copy one verbatim into `access_point.listen_address` |
| `available_outbound_listen_addresses` | External URLs of the outbound listeners | Copy one into `transit.outbound_listen_address` |
| `channel_path_prefix` | List of `{id, name, prefix}` | Start every `route` with one `prefix` |
| `mcp_proxy_path_prefix` | Prefixes for MCP proxies | Not a surface route |
| `oauth_callback_route` | Delegation callback base path | [credentials.md](credentials.md) |

The rules the save does not check:

- **The listen address must equal a listener's external URL**, compared with `http://` or `https://` stripped. The
  save accepts any non-empty value, and the failed apply falls back to a full reload that rebinds every listener,
  so a mis-addressed save is not free on a shared gateway; the surface is then skipped
  with only a log line. The `--listen-address` default `0.0.0.0:8080` matches no listener in the example
  configuration.
- **The route must start with a channel prefix.** Only `<prefix>` and `<prefix>/…` are routed to surfaces, plus
  `<prefix>/…` of any `type: proxy` entry in `routes`, which the routing view does not show. Any other path falls
  through to the other `routes` entries, then the static fallback (the dashboard in the example configuration). The
  `--route` default is `/` plus a URL-safe form of the name (`Sales Agent` gives `/sales-agent`), with no prefix.
- **Longest route wins.** Routes in a prefix are tried longest first; a route of `/` matches every path.
- **One route per listener.** Two active surfaces on the same listener port and route are refused with
  `access_point.route '<r>' on <listener> is already in use by surface '<name>'`. A disabled surface reserves no
  route.
- **No placeholder targets.** A target host that does not resolve from the gateway gets 403
  `Request blocked by egress policy`. For an endpoint containing `example.com`, `placeholder.` or `your-domain.com`,
  any other send failure is 503 instead of 502, with that failure's text. The `uses a placeholder domain` text
  needs a send-time DNS error, which a direct target does not reach (inference).

`runtime show surface-routing` reads `gateway.json` on every call, so it shows what the file says, not what the
listeners serve ([KI-36](known-issues.md)).

## Recipe: first surface, A2A

This puts an A2A agent behind the gateway and proves it with the agent card and one `message/send`. The MCP version
is in [SKILL.md](../SKILL.md). `GATEWAY` is the gateway URL fabric is connected to; `UPSTREAM_URL` is your agent's
base URL, the one that serves `/.well-known/agent-card.json`.

**Change.** Create the surface with a listen address and prefix from the routing view. The `jq` line prefers the
address equal to `GATEWAY`, else the first; pick another if your callers reach the gateway elsewhere.

<!-- e2e: quickstart-a2a -->
```bash
UPSTREAM_URL="${UPSTREAM_URL:?set UPSTREAM_URL to your A2A agent base URL}"
SURFACE_NAME="${SURFACE_NAME:-orders-a2a}"
fabric agent-gateway runtime show surface-routing -o json > routing.json
LISTEN_ADDRESS="$(jq -r --arg gw "${GATEWAY%/}" '.available_listen_addresses | (map(select(. == $gw)) + .)[0]' routing.json)"
PREFIX="$(jq -r '.channel_path_prefix[0].prefix' routing.json)"
fabric agent-gateway surfaces create --name "$SURFACE_NAME" --protocol a2a --listen-address "$LISTEN_ADDRESS" \
  --route "$PREFIX/$SURFACE_NAME" --target-endpoint "$UPSTREAM_URL" -o json > surface.json
jq '{surface_id, status, route: .access_point.route}' surface.json
jq -r '.access_point.listen_address + .access_point.route | if test("^https?://") then . else "http://" + . end' \
  surface.json > surface-url.txt
```

**Verify.** A 201 means stored, not serving. Fetch the card through the gateway, then send
one message. The gateway answers the card request itself: it fetches `<target.endpoint>/.well-known/agent-card.json`
and rewrites `url` to the listener's first external URL plus the route, so callers never see the upstream URL.

<!-- e2e: quickstart-a2a -->
```bash
SURFACE_URL="$(cat surface-url.txt)"
curl -sS -f "$SURFACE_URL/.well-known/agent-card.json" | jq '{name, url}'
curl -sS -f "$SURFACE_URL" -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":"1","method":"message/send","params":{"message":{"role":"user","messageId":"m-1","parts":[{"kind":"text","text":"hello"}]}}}'
```

Expect the card with the gateway's URL, then the agent's JSON-RPC `result`. Wire format, card fields and the
identity extension: [protocols.md](protocols.md). **Undo.** **Confirm with the user:** the delete runs at once and the route stops serving
([KI-34](known-issues.md)). `fabric agent-gateway surfaces delete <surface_id>`.

**If it fails.** 404 `No route configured for path`: [Why a saved surface is not
serving](#why-a-saved-surface-is-not-serving). Dashboard HTML, or 405 on a POST (inference): the route is outside
every prefix. 422 `Request protocol … does not match access point protocol`: an MCP body
on an A2A surface or the reverse. 502: the gateway cannot reach `UPSTREAM_URL`; 403
`Request blocked by egress policy`: its host does not resolve from the gateway. Next: [identity.md](identity.md), [credentials.md](credentials.md).

## Recipe: change a surface safely

**Confirm with the user:** what callers will notice; a new target, policy or limit applies to live traffic at once.
**Before.** `fabric agent-gateway surfaces get "$SURFACE_ID" -o json > before.json`. This file is your undo.
`fabric agent-gateway surfaces features "$SURFACE_ID"` shows which features the surface has and where
([Feature placements](#feature-placements)).

**Name or ID.** `surfaces get`, `update`, `delete`, `features`, `add-feature`, `remove-feature`,
`add-transit-point`, `remove-transit-point` and `tool-gate-preview` take the surface's `name` wherever they take
its ID. fabric lists the surfaces first, so:

- A name that picks one surface prints `note: using surface <id> (<name>)` on standard error, and the command acts
  on that ID.
- A name several surfaces share is refused with `'<name>' matches more than one surface; pass one of these ids
  instead:` and their IDs. A name or ID that matches nothing gets `surface not found: no surface has the ID or name
  '<x>'`, and the command sends nothing more.
- The lookup needs `surfaces.view`. A token without it must pass the ID, a UUID, which goes to the gateway
  unchecked.
- Other commands that take a surface, such as `runtime reload --surface`, `api-keys --agent-id` and
  `tenant-ownership`, take only the ID.

**Preview it.** Add `--dry-run` to the `update`, `add-feature`, `remove-feature`, `add-transit-point` or
`remove-transit-point` you are about to run. fabric reads the surface, merges the change on your machine and
checks the required fields, prints the patch and each changed field as `path: before -> after` under
`Changes (checked on this machine only):`, then `Dry run: nothing was saved.`, and sends no change to the gateway.
The gateway runs none of its checks on a preview: referenced policies, secrets and credential providers, route
collisions and the rest run only on the real save, so read the gateway's answer to that save too.

- It exits 1 when fabric's check refuses the change, with that error, such as `access_point.route is required`.
- Otherwise it exits 3 and prints, on standard error,
  `error: dry run incomplete: only the checks on this machine ran, and nothing was saved`, after a
  `warning: the gateway's checks did not run …` line in table output. Every preview that passes fabric's check
  ends this way, so do not run one under `set -e`.
- With `-o json` it prints one object, `{"dry_run": true, "checked": "local", "patch", "before", "after"}`, plus
  `warning` when fabric's check passed and `error` when it refused the change.
- A Transit Point added without an `id` has none in the preview; the real save gives it one.
- `--dry-run` cannot be combined with `--file`.

**Change single fields.** `update --set <path>=<value>` and `--unset <path>`, each repeatable, send one JSON
Merge Patch that changes only the fields named:

```bash
fabric agent-gateway surfaces update "$SURFACE_ID" --set description='Orders agent, v2' -o json | jq '{surface_id, description}'
```

- Without `-o json`, `update`, `add-feature` and `remove-feature` print only `Updated surface '<id>'`; with
  `--dry-run` they print the preview instead.
- fabric reads the surface first, merges the change and refuses it before sending anything when `name`,
  `access_point.listen_address`, `access_point.route` or `target.endpoint` would end up empty, with the
  gateway's own message, such as `access_point.route is required`. `update --file` checks its file the same way.
  A token without `surfaces.view` cannot read the surface: `--set` and `--unset` then warn
  `could not read the surface to check the edit first (needs surfaces.view), sending it unchecked` and send the
  edit anyway.
- A path is object keys joined by dots, such as `access_point.rate_limit.requests`. A path with a list position in
  it, such as `transit.points.0.policy`, is refused: change list items with `--add` and `--remove`.
- A value is read as JSON when it parses and as text otherwise, and one with leading or trailing spaces is always
  text: `5` is a number, `'"1.0"'` forces text and `'{"requests":100,"window_secs":60}'` is an object. An object
  merges into the stored one, so keys it leaves out stay; a list replaces the stored list.
- `null`, alone or inside an object, is refused: use `--unset`. So are a path given twice and a path inside
  another one.
- The merged document must still be a whole surface: `--set access_point.rate_limit.requests=5` on a surface with
  no rate limit gets 400 `Merged surface failed to deserialise: …`, naming the missing field `window_secs`.

**Change one list item.** `update --add <path>=<item>` and `--remove <path>=<item>`, each repeatable and
combinable with `--set` and `--unset`, change one item of a list and keep the rest:

```bash
fabric agent-gateway surfaces update "$SURFACE_ID" --add tags=beta -o json | jq '{surface_id, tags}'
```

- `<path>` is the list's own path, such as `tags`, `transit.points` or `access_point.trust_check_list`. An item
  is read the same way as a `--set` value. For one Transit Point, `add-transit-point` and `remove-transit-point`
  are simpler ([Transit Points](#transit-points)).
- `--remove` names a text item by its value and an object by its `id`, else its `alias`, else some of its fields as
  JSON, such as `outbound_credentials='{"credential_provider_id":"<provider-id>"}'`.
- Removes run before adds. An added item takes a removed item's place when it has the same `id` or `alias`, or,
  having neither, holds the fields you gave to `--remove`; it then keeps the removed item's `id`. Any other added
  item is appended, and the removed one is gone.
- An item already in the list is refused with `already has`, and an item that is not there with `has no item`. A
  `--remove` that fits several items fails with `matches more than one item`: give its `id` or more fields.
- Both need `surfaces.view`, because fabric reads the list and sends it whole with only these items changed. A
  change someone else makes to that list between the read and the write is lost ([KI-32](known-issues.md)).
- To add or remove one MCP Tool Gating pattern without resending its gate, name the gate in square brackets and
  quote the flag so the shell leaves the brackets alone:
  `--add 'target.mcp_tool_gating.gates[<gate>].action.patterns=<regex>'`, or
  `transit.points[<point>].mcp_tool_gating.gates[<gate>].action.patterns` for a gate on a Transit Point. A gate
  is picked by `id`, else `name`, and a point by `id`, else `alias`. The pattern is always text, with surrounding
  spaces trimmed. fabric sends the whole gates list, or the whole `transit.points` list, with only that pattern
  changed ([KI-32](known-issues.md)). Before sending anything it refuses a pattern that is blank, over 512 bytes
  or not valid regex, a gate or point the surface lacks, a pattern the gate already has or does not have, and a
  removal that would leave the gate with no pattern. `--set` and `--unset` refuse brackets. Preview the gates with
  `tool-gate-preview` ([policies.md](policies.md#check-mcp-tool-gating-before-you-save-it)).

**Or change the whole document.** `update --file` is a PUT of the whole document, for many fields at once; it
cannot be combined with `--set`, `--unset`, `--add` or `--remove`. When the file leaves out `mcp_http` (on the
surface, or on a Transit Point with the same `id`), the `authorization` inside it, or `mcp_legacy_metadata_output`,
the PUT keeps the stored value; remove one from the surface with `--unset`, such as `--unset mcp_http`. Edit a
copy and keep `surface_id` or drop it:

```bash
jq '.description = "Orders agent, v2"' before.json > after.json
fabric agent-gateway surfaces update "$SURFACE_ID" --file after.json -o json | jq '{surface_id, description}'
```

**Or add one feature**, for example
`fabric agent-gateway surfaces add-feature "$SURFACE_ID" policy --policy-id "$POLICY_ID"`. `add-feature` reads the
surface and patches one place ([Feature placements](#feature-placements)):

- An object or policy value replaces what is there, including keys the new value leaves out. A value that is
  `null` or holds `null` is refused, because a merge patch reads `null` as a removal.
- A list feature (`trust-check`, `credential-delegation`) appends the value and sends the whole list.
- A Transit Point feature sends the whole `transit.points` list with that point changed.

`--policy-id` builds `{"policy_definition_id": "<id>", "require_agent_context": false}`. Other values take
`--json` or `--file` (`-` reads standard input). fabric works out the place from the feature's name, so most
features need no flag; add `--response` for the response leg or `--transit-point <alias>` for one Transit
Point ([Feature placements](#feature-placements)).

`remove-feature` clears the place and fails with `is not set at` when nothing is there. **Confirm with the user:**
on a list feature it removes every entry, every Trust Check or every credential binding at that place; to drop one
entry, use `update --remove <list path>=<id>`, or its fields as JSON for a credential binding, which has no `id`. `add-feature` and `remove-feature` run the same required-field check
as `update`, need `surfaces.view` to read the surface, and take `--dry-run`.

- Every write here runs the same validators and reload as `update --file`, and none checks a version, so a
  whole-list or whole-surface write can lose a concurrent edit ([KI-32](known-issues.md)).
- fabric refuses the mask `<hidden; pass --reveal to show>` in `--file`, `-` and `--data` bodies; `--set` and
  `add-feature --json` values are not checked. Edit a fresh document and set secret references, not values.
- `create` skips the caller-auth and workload-binding validators that `update` runs. After creating from a file,
  re-save with `update` so every validator runs.
- `fabric agent-gateway api patch /v1/surfaces/<id>` sends a JSON Merge Patch without the checks `update` runs on
  your machine. Use `update --set`.
- A serde error naming a field is an unknown key. The stored name of the dashboard's agent identity setting is
  `identity_injection`.

**Verify.** `fabric agent-gateway surfaces get "$SURFACE_ID" -o json`, then one real request. A 200 from `update` does not prove
the runtime applied it. A reload never compiles a surface's policies; a save and
`fabric agent-gateway policies update` do ([policies.md](policies.md)). **Undo.**
`fabric agent-gateway surfaces update "$SURFACE_ID" --file before.json`.

## Recipe: disable or delete with a backup

**Confirm with the user:** callers of this route stop being served. **Before.**
`fabric agent-gateway surfaces get "$SURFACE_ID" -o json > before.json`. **Change.**

- Disable: set `"status": "disabled"` and update. The surface stays stored but leaves the runtime, so its route
  answers 404 `No route configured for path`, not the 503 the docs describe (inference from source).
- Delete: `fabric agent-gateway surfaces delete "$SURFACE_ID"`. No prompt, no soft delete
  ([KI-34](known-issues.md)). fabric prints `Deleted surface '<id>'`; with `-o json` it prints the gateway's
  answer, `{"success":true,"message":"Surface '<id>' deleted"}`.

Disabling, and any save of a surface with variants or Transit Points, runs a full in-process reload that rebinds
every listener; expect a brief connection-refused window ([operations.md](operations.md)).

**Verify.** The route answers 404 `No route configured for path`; after a delete, `fabric agent-gateway surfaces get` fails with
`surface not found: no surface has the ID or name '<id>'`. **Undo.** Disabled: set `"status": "active"` and update. Deleted:
`fabric agent-gateway surfaces create --file before.json`, which keeps the `surface_id` from the file.

## Why a saved surface is not serving

A surface can be stored and active and still get 404. Check in this order:

1. **The answer.** 404 `application/problem+json` `No route configured for path: <path>` means no surface matched.
   Dashboard HTML, or 405 on a POST (inference), means the path is outside every prefix.
2. **The listen address** equals an `available_listen_addresses` entry, scheme aside.
3. **The route** starts with a `channel_path_prefix` value, and no route on the same prefix that is longer than it catches the path first.
4. **The status.** A `disabled` surface gets the same 404. Never run
   `fabric agent-gateway runtime reload --surface <id>` on one: the single reload does not check the status and puts the surface back
   into service until the next full reload (inference).
5. **The runtime's own answer.** For an active surface, `fabric agent-gateway runtime reload --surface <id>` reloads that one
   surface and reports the mapping error the save hid: `Could not map channel listen_address to internal port: <addr>`.
   An unknown ID gets a 500 that fabric rewords as not found ([KI-43](known-issues.md)). Never
   run a bare `fabric agent-gateway runtime reload` for this: it rebinds every listener ([KI-35](known-issues.md)).

**Worked example.** Store a surface with the flag default listen address, see the 404, let the runtime name the
cause, fix it. **Confirm with the user:** the first save cannot apply the surface, so it runs a full in-process reload
that rebinds every listener. Run it only on a gateway nobody else is using.
`UPSTREAM_URL` is your MCP server's URL.

<!-- e2e: route-not-serving -->
```bash
UPSTREAM_URL="${UPSTREAM_URL:?set UPSTREAM_URL to your MCP server URL}"
SURFACE_NAME="${SURFACE_NAME:-orders-mcp}"
fabric agent-gateway runtime show surface-routing -o json > routing.json
PREFIX="$(jq -r '.channel_path_prefix[0].prefix' routing.json)"
# The mistake: no --listen-address, so the default 0.0.0.0:8080 is stored.
fabric agent-gateway surfaces create --name "$SURFACE_NAME" --protocol mcp --route "$PREFIX/$SURFACE_NAME" \
  --target-endpoint "$UPSTREAM_URL" -o json > surface.json
jq '{surface_id, status, listen_address: .access_point.listen_address}' surface.json
BASE="$(jq -r --arg gw "${GATEWAY%/}" '.available_listen_addresses | (map(select(. == $gw)) + .)[0]' routing.json)"
for _ in 1 2 3 4 5 6 7 8 9 10; do curl -s -o /dev/null "$BASE/" && break; sleep 1; done
curl -sS -w '\nHTTP %{http_code} %{content_type}\n' "$BASE$(jq -r .access_point.route surface.json)" \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

<!-- e2e: route-not-serving expect-fail -->
```bash
fabric agent-gateway runtime reload --surface "$(jq -r .surface_id surface.json)"
```

<!-- e2e: route-not-serving -->
```bash
SURFACE_ID="$(jq -r .surface_id surface.json)"
LISTEN_ADDRESS="$(jq -r --arg gw "${GATEWAY%/}" '.available_listen_addresses | (map(select(. == $gw)) + .)[0]' routing.json)"
fabric agent-gateway surfaces get "$SURFACE_ID" -o json > before.json
jq --arg listen "$LISTEN_ADDRESS" '.access_point.listen_address = $listen' before.json > fixed.json
fabric agent-gateway surfaces update "$SURFACE_ID" --file fixed.json -o json | jq '{surface_id, listen_address: .access_point.listen_address}'
curl -sS -w '\nHTTP %{http_code}\n' "$LISTEN_ADDRESS$(jq -r .access_point.route fixed.json)" \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}'
```

Expect 404 problem+json, then the mapping error from the reload, then 200 with the upstream's tools.

## Variants

A variant is a named set of overrides on one surface, selected by an alias in the path:
`<listen-address><route>$<alias>[/<rest>]`, with `%24` accepted for `$` and no slash before it. It works on any
route under a prefix.

| Request | Surface without variants | Surface with variants |
| --- | --- | --- |
| no alias | base surface | the `default_variant_id` variant; the base surface when that is unset |
| known alias | alias ignored, base surface | that variant; 503 `Virtual channel variant '<a>' is disabled` if disabled |
| unknown alias | alias ignored, base surface | 400 `Virtual channel alias '<a>' not found for this channel` |

On a surface without variants, a `2026-07-28` MCP request ([protocols.md](protocols.md)) that names an alias
gets 404 with JSON-RPC `-32603` `MCP surface variant is unavailable` instead, and one without an alias gets 503
with the same error when the surface sets `default_variant_id` (`VariantResolveError` in
`src/config/agent_surface_variants.rs`).

Variants have no fabric commands; use `fabric agent-gateway api`:

| Do | Call | Body |
| --- | --- | --- |
| Create | `fabric agent-gateway api post /v1/surfaces/<id>/variants` | `alias` (`^[a-z0-9-]{1,32}$`), `name`; optional `description`, `source_alias` |
| Change | `fabric agent-gateway api put /v1/surfaces/<id>/variants/<variant-id>` | any of `alias`, `name`, `description`, `enabled`, `overrides` |
| Make default | `fabric agent-gateway api post /v1/surfaces/<id>/variants/<variant-id>/promote-to-default` | none |
| Inspect | `fabric agent-gateway api get /v1/surfaces/<id>/variants/<alias>/resolved` | none |
| Delete | `fabric agent-gateway api delete /v1/surfaces/<id>/variants/<variant-id>` | none |

- A new variant is enabled, copies the overrides of `source_alias` or else of the default variant, and does not
  become the default. PUT keeps the fields you leave out and replaces `overrides` whole.
- The API refuses to delete the only variant or the default one. To drop the last one,
  update the surface with `"variants": []` and no `default_variant_id`.
- Never disable the default variant. Nothing stops you, and every alias-less call then gets 503
  ([KI-31](known-issues.md)). Promote another variant first.

**Worked example: a beta upstream.** **Confirm with the user:** callers who use `$beta` reach a different agent,
and every variant write here, the undo included, runs a full in-process reload that rebinds every listener.
Run it only on a gateway nobody else is using.
`UPSTREAM_URL` is the current A2A agent, `BETA_UPSTREAM_URL` the beta one. The first block creates the starting
surface; for an existing one, write its `get -o json` to `surface.json` instead.

<!-- e2e: variant-a2a -->
```bash
UPSTREAM_URL="${UPSTREAM_URL:?set UPSTREAM_URL to the current A2A agent base URL}"
SURFACE_NAME="${SURFACE_NAME:-orders-a2a}"
fabric agent-gateway runtime show surface-routing -o json > routing.json
LISTEN_ADDRESS="$(jq -r --arg gw "${GATEWAY%/}" '.available_listen_addresses | (map(select(. == $gw)) + .)[0]' routing.json)"
fabric agent-gateway surfaces create --name "$SURFACE_NAME" --protocol a2a --listen-address "$LISTEN_ADDRESS" \
  --route "$(jq -r '.channel_path_prefix[0].prefix' routing.json)/$SURFACE_NAME" --target-endpoint "$UPSTREAM_URL" \
  -o json > surface.json
jq '{surface_id, route: .access_point.route}' surface.json
```

<!-- e2e: variant-a2a -->
```bash
BETA_UPSTREAM_URL="${BETA_UPSTREAM_URL:?set BETA_UPSTREAM_URL to the agent the beta variant should reach}"
SURFACE_ID="$(jq -r .surface_id surface.json)"
fabric agent-gateway surfaces get "$SURFACE_ID" -o json > before.json
fabric agent-gateway api post "/v1/surfaces/$SURFACE_ID/variants" --data '{"alias":"beta","name":"Beta upstream"}' -o json > variant.json
jq -n --arg endpoint "$BETA_UPSTREAM_URL" '{overrides: {target: {endpoint: $endpoint}}}' > beta.json
fabric agent-gateway api put "/v1/surfaces/$SURFACE_ID/variants/$(jq -r .id variant.json)" --file beta.json -o json \
  | jq '{alias, enabled, overrides}'
```

**Verify.** Each variant save runs a full reload, so wait for the route first. Then call
with the alias, without it, and with an alias that does not exist:

<!-- e2e: variant-a2a -->
```bash
SURFACE_URL="$(jq -r '.access_point.listen_address + .access_point.route' surface.json)"
for _ in 1 2 3 4 5 6 7 8 9 10; do curl -s -o /dev/null "$SURFACE_URL/.well-known/agent-card.json" && break; sleep 1; done
for alias in '$beta' '' '$nope'; do
  curl -sS -w '\nHTTP %{http_code}\n' "$SURFACE_URL$alias" -H 'Content-Type: application/json' \
    -d "{\"jsonrpc\":\"2.0\",\"id\":\"1\",\"method\":\"message/send\",\"params\":{\"message\":{\"role\":\"user\",\"messageId\":\"m-1\",\"parts\":[{\"kind\":\"text\",\"text\":\"via ${alias:-base}\"}]}}}"
done
```

Expect the beta agent to answer `$beta`, the current agent the alias-less call, and 400 `Virtual channel alias
'nope' not found for this channel` for `$nope`. **Undo.** `fabric agent-gateway surfaces update "$SURFACE_ID" --file before.json`
(the variant DELETE refuses the only variant). Per-variant policies: [policies.md](policies.md).

## Transit Points

A Transit Point (TP) is a named outbound destination that the managed agent calls through the gateway, so the
gateway's policy, limits and credentials also cover that call. TPs live in `transit.points`.

- **URL.** The managed agent calls `<outbound-listen-address>/outbound<route>/<tp-alias>[/<rest>]`, or
  `/outbound<route>$<variant>/<tp-alias>[/<rest>]` (`%24` accepted for `$`) for one of the surface's variants. A
  call through a disabled variant is served by the base surface, except a `2026-07-28` MCP request
  ([protocols.md](protocols.md)), which gets 503 `MCP Transit Point variant is unavailable`. A TP with a
  `listen_path` is also served at `<listen_path>` and `<listen_path>$<variant>`. The prefix is `/outbound`. The
  docs say `/outgoing`, which no route serves, and so does the gateway's own rewrite of an agent card fetched
  through a TP without a `listen_path` (`build_transit_point_proxy_endpoint` in `src/a2a/url_rewriter.rs`), so an
  agent that follows that card gets 404 (inference). Only configured aliases have routes, so a wrong alias gets
  a plain 404 (inference).
- **Listener.** A TP is served only on an outbound listener, at its own `listen_address` or else
  `transit.outbound_listen_address`. Otherwise it is skipped with the log line
  `has no resolvable outbound listen address - skipping`.
- **Shared hostname.** When an outbound listener has an external URL with the same hostname as an inbound
  listener's, whatever the ports, that inbound listener also serves `/outbound` and `/outbound/…` and forwards
  them, `X-Transit-Token` included, to the outbound listener. One reverse-proxy hostname then reaches both, and so
  does anyone who can reach the inbound listener. An outbound listener that does not answer gives an empty 502.
  The inbound listener logs this when it starts:
  `Shared-domain detected: registering outbound transit-point proxy on inbound listener -> outbound listener`.
- **Token.** On the inbound leg the gateway adds `X-Transit-Token` to each request it forwards to the managed agent,
  which copies it onto its outbound call: an HS256 JWT valid for 300 seconds for every TP alias of the surface.
  Without it the call gets 401 problem+json
  `Transit token missing or invalid: missing X-Transit-Token header`. A `GET` of a discovery path, such as one
  ending in `/.well-known/agent-card.json`, needs no token, and `require_transit_token: false` on the TP turns
  the check off. The token is not authentication: anyone who knows the gateway's
  `did.domain` can mint one ([KI-08](known-issues.md)). Keep the outbound listener off public networks, and give
  it a hostname that no inbound listener uses.

| TP field | Rule |
| --- | --- |
| `alias` | Required, `^[a-z][a-z0-9-]{0,62}$`, unique per surface; the API does not derive it from `name` |
| `target_endpoint` | Required: the destination URL |
| `protocol` | `a2a` (default), `ap2`, `mcp` or `http`; a request of another protocol gets 422 |
| `require_transit_token` | Default `true`. Other optional fields include `name`, `listen_address`, `listen_path`, `agent_card_path`, `target_auth`, `policy`, `response_policy`, `networking`, `rate_limit`, `mcp_tool_gating`, `payment_policy` and `transit_credentials` |

**Add or remove one TP** on a saved surface:
`fabric agent-gateway surfaces add-transit-point "$SURFACE_ID" --alias orders --endpoint "$DOWNSTREAM_URL"` sets
`alias` and `target_endpoint`, gives the TP the surface's own `protocol`, as `update --add transit.points=...`
does for an item without one, and leaves every other field at its default, and
`fabric agent-gateway surfaces remove-transit-point "$SURFACE_ID" orders` takes the alias or the `id`. Before
sending anything, `add-transit-point` refuses a blank alias or endpoint, an alias the table above does not allow,
and one the surface already has; `remove-transit-point` lists the TPs there are when none matches. Both send the
whole `transit.points` list ([KI-32](known-issues.md)) and take `--dry-run`. **Confirm with the user:** a save
that leaves the surface with any TP runs a full reload.

`transit_token_mode`, `transit.transit_policy`, `sign_requests` and `transit.source_auth` are stored but not
enforced ([KI-20](known-issues.md)). The one effect of `transit.source_auth` is a failure: every call to an MCP TP
that sets `mcp_http.authorization` gets an empty 503. Outbound policy goes in `transit.opa_policy_definition_id`
(every TP) or per TP with
`fabric agent-gateway surfaces add-feature <id> policy --transit-point <alias> --policy-id <policy-id>`; a deny is
403 `Request blocked by surface policy`. There is no per-TP Trust Check list: `add-feature trust-check --edge ma-tp`
appends to `target.trust_check_list`, which applies to every TP, and fabric refuses `trust-check --transit-point`.
Delegation through a TP: [credentials.md](credentials.md).

**Worked example: an MCP agent that calls an A2A agent.** **Confirm with the user:** the save runs a full reload.
`UPSTREAM_URL` is the managed MCP agent, `DOWNSTREAM_URL` the A2A agent it calls, and
`OUTBOUND_ADDRESS` an outbound listen address the managed agent can reach (default: the first).

<!-- e2e: transit-a2a -->
```bash
UPSTREAM_URL="${UPSTREAM_URL:?set UPSTREAM_URL to the managed MCP agent URL}"
DOWNSTREAM_URL="${DOWNSTREAM_URL:?set DOWNSTREAM_URL to the A2A agent the managed agent calls}"
SURFACE_NAME="${SURFACE_NAME:-orders-mcp}"
fabric agent-gateway runtime show surface-routing -o json > routing.json
OUTBOUND_ADDRESS="${OUTBOUND_ADDRESS:-$(jq -r '.available_outbound_listen_addresses[0] // empty' routing.json)}"
jq -n --arg name "$SURFACE_NAME" --arg route "$(jq -r '.channel_path_prefix[0].prefix' routing.json)/$SURFACE_NAME" \
  --arg listen "$(jq -r --arg gw "${GATEWAY%/}" '.available_listen_addresses | (map(select(. == $gw)) + .)[0]' routing.json)" \
  --arg target "$UPSTREAM_URL" --arg outbound "${OUTBOUND_ADDRESS:?no outbound listener in the routing view}" \
  --arg downstream "$DOWNSTREAM_URL" '{name: $name, target: {endpoint: $target},
    access_point: {listen_address: $listen, route: $route, protocol: "mcp"},
    transit: {outbound_listen_address: $outbound,
      points: [{alias: "orders", name: "Orders agent", target_endpoint: $downstream, protocol: "a2a"}]}}' > new-surface.json
fabric agent-gateway surfaces create --file new-surface.json -o json > surface.json
jq '{surface_id, points: [.transit.points[] | {alias, protocol, require_transit_token}]}' surface.json
```

Send one inbound call; the managed agent receives it with `X-Transit-Token`. Then call the TP without the token:

<!-- e2e: transit-a2a -->
```bash
SURFACE_URL="$(jq -r '.access_point.listen_address + .access_point.route' surface.json)"
OUTBOUND_URL="$(jq -r '.transit.outbound_listen_address + "/outbound" + .access_point.route + "/orders"' surface.json)"
for _ in 1 2 3 4 5 6 7 8 9 10; do curl -s -o /dev/null -X POST "$SURFACE_URL" && break; sleep 1; done
curl -sS "$SURFACE_URL" -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"echo","arguments":{"text":"order 42"}}}'
curl -sS -w '\nHTTP %{http_code}\n' "$OUTBOUND_URL" -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":"1","method":"message/send","params":{"message":{"role":"user","messageId":"m-1","parts":[{"kind":"text","text":"status"}]}}}'
```

**Verify.** The tokenless call gets 401 `missing X-Transit-Token header`. The managed agent's own call, with `-H
"X-Transit-Token: <value it received>"`, returns the destination agent's `result`; a wrong alias gets 404
(inference). **Undo.** **Confirm with the user:** callers and the managed agent's TP calls stop being served.
`fabric agent-gateway surfaces delete <surface_id>`, or update the surface without `transit`.

## Feature placements

`fabric agent-gateway surfaces add-feature <surface> <key>` writes these places, and `remove-feature` clears
them. fabric works out the place from the key, so a flag is needed only to pick another place:

- With no flag it uses the place on the whole surface, and the request place when the feature has both.
- `--response` picks the response place, and `--transit-point <alias>` the place on that Transit Point (add
  `--response` for its response place).
- `--edge` names a pipeline edge: `ap-ma` (caller to managed agent), `ma-external` (managed agent to external
  services) or `ma-tp` (managed agent to a Transit Point). It picks the target leg of `trust-check` and the
  slots of `identity`, and fabric refuses `identity --response` until you add one. Flags that name a place
  explicitly still work.

"List" keys append to an array; the others replace. `fabric agent-gateway surfaces features` prints the catalogue
from the binary you have, with each place's edge and direction; with `-o json` each entry has `feature`,
`aliases`, `description` and `placements[]` of `edge`, `direction`, `pointer` and `kind`.

| Key (aliases) | Flags → JSON pointer | Kind |
| --- | --- | --- |
| `policy` (`opa`) | none → `/target/policy`; `--response` → `/target/response_policy`; `--transit-point <alias>` → `/transit/points/{tp}/policy`, with `--response` `/transit/points/{tp}/response_policy` | PolicyRef |
| `inbound-policy` (`access-point-policy`) | none → `/access_point/inbound_policy` | PolicyRef |
| `caller-auth` (`authentication`, `source-auth`) | none → `/access_point/caller_authentication` | object |
| `rate-limit` (`throttling`, `network.throttling`) | none → `/access_point/rate_limit` | object |
| `networking` (`timeout`, `retry`, `circuit-breaker`) | none → `/target/networking`; `--transit-point <alias>` → `/transit/points/{tp}/networking` | object |
| `payment` (`x402`, `mpp`) | none → `/target/payment_policy` | object |
| `extension-validation` | none → `/access_point/extension_validation` | object |
| `extension-rules` | none → `/target/extension_rules` | object |
| `custom-metadata` (`metadata-injection`) | none → `/target/custom_metadata`; `--response` → `/target/response_custom_metadata` | object |
| `header-metadata` (`metadata-extraction`, `header-mapping`) | none → `/access_point/header_metadata_mapping` | object |
| `trust-check` | none → `/access_point/trust_check_list` (caller leg); `--edge ma-tp` → `/target/trust_check_list` (target leg, every Transit Point) | list |
| `trust-recorder` | none → `/access_point/trust_recorder`, a response place | object |
| `identity` (`identity-slot`) | none → `/identity_slots/inbound`; `--edge ma-external` → `/identity_slots/external`; `--edge ap-ma --response` → `/identity_slots/protected` | object |
| `mcp-tool-gating` (`tool-gating`) | none → `/target/mcp_tool_gating`; `--transit-point <alias>` → `/transit/points/{tp}/mcp_tool_gating` | object |
| `credential-delegation` (`outbound-credentials`) | none → `/outbound_credentials` | list |
| `workload-binding` | none → `/target/workload_binding` | object |

An unknown key fails with `unknown feature '<f>'`, and a flag the feature has no place for with
`feature '<f>' cannot use <flags>; use one of: <flags>`, or `has no response place` for `--response`.
`identity --response` alone gets `can go in more than one place; add one of these flags:` with both choices.
`--transit-point` on a feature with no Transit Point place gets `cannot go on a transit point`, on
`trust-check` `has no place per transit point alias`, and `--edge ma-tp` on a per-point feature
`goes on one transit point, so use --transit-point <alias> instead of --edge ma-tp`. An alias the surface lacks
fails with `transit point '<alias>' not found on surface`. The values are described in the file for each domain,
such as [policies.md](policies.md).

**What a surface has.** `fabric agent-gateway surfaces features <surface>` reads one surface and prints
`FEATURE  ON  WHERE`: every feature, `on` or `off`, and each place it is set with the flags `remove-feature` needs
there, such as `access point: rate_limit (remove with no flags)`. A place holding `{}` counts as on, an empty list
as off. It reads the surface itself, not its variants: a `Notes` section under the table names each enabled
variant that sets a feature, says that Transit Point features may not match when a variant changes the Transit
Points, and for a complete variant names the blocks it replaces, whose features the variant leaves out are off
for the gateway even when the table shows them on. With `-o json` it prints a list of `{feature, on,
placements}`; each placement has `edge`, `direction`, `pointer`, `kind`, `place`, `field`, `transit_point` (the
alias, or `null`), `index` (the point's position, or `null`) and `remove_flags`, which is `""` when no flag is
needed and `null` when `remove-feature` cannot pick that place: a Transit Point with no alias, or one whose alias
an earlier point also has. A feature a note concerns also has `variant_notes`.

## When it fails

| Exact text | Cause | Fix |
| --- | --- | --- |
| 201 or 200 from the save, then 404 `No route configured for path` | Listen address maps to no listener, route outside a prefix, or surface disabled | [Why a saved surface is not serving](#why-a-saved-surface-is-not-serving) |
| `Could not map channel listen_address to internal port: <addr>` | Listen address is not a listener's external URL | Copy one from `available_listen_addresses` and update |
| Dashboard HTML, or 405 on POST (inference) | Route outside every channel prefix | Put the route under a `channel_path_prefix` |
| `name is required`, `access_point.listen_address is required`, `access_point.route is required`, `target.endpoint is required` | Missing field; fabric refuses an edit that would leave one empty before sending it | Add it |
| `target.endpoint: URL host '<h>' is blocked` | Cloud metadata host | Use the real upstream |
| `surface_id in body does not match URL parameter` | Wrong ID in the PUT body | Keep or drop the stored ID |
| `access_point.route '<r>' on <listener> is already in use by surface '<n>'`, or `listen_path '<p>' on <listener> is already in use by surface '<n>'` | Route collision on that listener, or a Transit Point `listen_path` that another surface's TP uses on that outbound listener | Another route or `listen_path`, or disable the other surface |
| `route '<r>' matches an always-public discovery path` | A route ending in a discovery path, such as `/agent.json`, `/agent-card.json`, `/.well-known/ucp` or `/discovery` | Another route |
| A serde error naming an `unknown field` | Key the model does not have | Remove it; send stored names |
| 400 `Merged surface failed to deserialise: …` | `update --set` or `add-feature` left a document that is not a surface: a required field missing, a wrong type, or an unknown field | Set the whole object, quote text as `'"…"'`, or drop the key |
| `--set <path>=null would remove the field: use --unset <path> instead`, or `would remove <path>` | `null` in a `--set` value | `--unset <path>` |
| `the request body still carries the masked placeholder <hidden; pass --reveal to show>` | A `--file`, `-` or `--data` body copied from a masked `get` | Re-read with `--reveal`, or remove the masked field to keep the stored credential |
| `points at a list item by position` | `--set`, `--unset`, `--add` or `--remove` path with a list position in it | `--add` or `--remove` on the list's own path |
| `'<path>' already has <item>: remove it first to replace it` | `--add` of an item the list holds | `--remove` it and `--add` the new one in the same command |
| `'<path>' has no item '<item>'` | `--remove` of an item the list lacks | Read the list with `surfaces get`; name an object by its `id` or `alias` |
| `matches more than one item` | `--remove` fields that fit several objects | Give its `id`, or more of its fields |
| `'<path>' is not a list: use --set <path>=<value> to change it` | `--add` or `--remove` on a field that is not a list | `--set` |
| `could not read the surface to check the edit first (needs surfaces.view), sending it unchecked` | Token without `surfaces.view` on `--set`/`--unset`; `--add`, `--remove`, `--dry-run` and the feature commands fail instead | A token with `surfaces.view` |
| `dry run incomplete: only the checks on this machine ran, and nothing was saved`, exit 3 | Every `--dry-run` that passes fabric's check: the gateway runs none of its checks on a preview | Read the printed change, then run the command without `--dry-run`; the gateway's own checks run on that save |
| 415 `Content-Type must be application/merge-patch+json` | A PATCH to a surface sent with another content type, such as `application/json` from `curl` | `surfaces update --set` |
| `surface not found: no surface has the ID or name '<x>'` | No surface has that ID or name, or it was deleted | `fabric agent-gateway surfaces list` |
| `'<name>' matches more than one surface; pass one of these ids instead:` | Several surfaces share the name | Pass one of the IDs it lists |
| `if the token lacks surfaces.view, the CLI can't look names up` | A name given with a token that cannot list surfaces | Pass the surface ID, or use a token with `surfaces.view` |
| `unknown feature '<f>'` | Key typo | `fabric agent-gateway surfaces features` |
| `feature '<f>' cannot use <flags>`, `has no response place`, `can go in more than one place`, `cannot go on a transit point` | A flag the feature has no place for, or `identity --response` without `--edge` | A flag the error lists ([Feature placements](#feature-placements)) |
| `feature '<f>' is not set at <pointer>` | `remove-feature` with nothing there | `fabric agent-gateway surfaces features <surface>` shows where it is set and the flags to remove it |
| `has no tool gate '<g>'`, `already has the pattern`, `has no pattern`, `would leave gate '<g>' ... with no patterns` | A bracketed tool-pattern edit that names a missing gate, adds a pattern twice, removes one the gate lacks, or removes its last pattern | Read the gates with `surfaces get`; remove a whole gate with `--remove <path to gates>=<gate>` |
| `can't use brackets in '<path>'` | Brackets on `--set` or `--unset` | `--add` or `--remove` on the gate's patterns |
| 403 on create before anything is saved | Appliance surface limit reached | Delete unused surfaces or raise the limit |
| 403 on a surface write or `runtime reload` | Token below administrator | Administrator token |
| 422 `Request protocol '<d>' does not match access point protocol '<e>'` | MCP body on an A2A surface, or the reverse | Fix the protocol or the client |
| 503 with a send-failure text, such as `Connection failed to target endpoint` | `example.com` or a placeholder in the endpoint, and the send failed | Set the real endpoint |
| 400 `Virtual channel alias '<a>' not found for this channel` | Alias typo on a surface with variants | Check `.variants[].alias` |
| 503 `Virtual channel variant '<a>' is disabled` | Disabled variant selected, including the default, for calls with no alias | Enable it or promote another |
| TP call to `/outgoing/…` gets 404 (inference) | The docs' `/outgoing` prefix, or the one in the gateway's rewritten agent card | `/outbound<route>/<alias>` |
| 401 `Transit token missing or invalid: missing X-Transit-Token header` / `...: transit token validation failed` | Agent did not copy the header / the token is past 300 s or not this gateway's | Forward the header from the current inbound request |
| 403 `Request blocked by surface policy` on a TP | Outbound or per-TP policy denied | [policies.md](policies.md) |
| Behaviour unchanged after a 200 update; the log has `Surface <action> for '<id>' persisted to storage but in-process reload failed: <e>` | The save was stored but not applied | For an active surface, `fabric agent-gateway runtime reload --surface <id>`; after a disable or delete, a full `fabric agent-gateway runtime reload` ([KI-35](known-issues.md)). If that fails too, recover per [operations.md](operations.md) |

## Known issues here

[KI-08](known-issues.md), [KI-20](known-issues.md), [KI-31](known-issues.md), [KI-32](known-issues.md),
[KI-34](known-issues.md), [KI-35](known-issues.md), [KI-36](known-issues.md), [KI-43](known-issues.md). Details and workarounds:
[known-issues.md](known-issues.md). Anything else: [triage.md](triage.md).

Sources: [Surface routing model](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/concepts/surface-routing-model/), [Surfaces](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/concepts/surfaces/), [Create your first surface](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/get-started/create-first-surface/), [Glossary](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/get-started/glossary/), [Surface reference](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/reference/surfaces/surface-reference/), [Transit Points](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/reference/surfaces/transit-points/), [Variants](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/reference/surfaces/variants/), [Target](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/reference/surfaces/target/), [Managed Agent](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/reference/surfaces/managed-agent/); gateway source: `src/identity/handlers/surfaces.rs`, `src/config/agent_surface.rs`, `src/proxy/handler.rs`, `src/proxy/outbound_handler.rs`, `src/proxy/server.rs`, `src/proxy/paths.rs`, `src/identity/handlers/config.rs`, `src/a2a/url_rewriter.rs`, `src/config/agent_surface_variants.rs`; fabric's `src/commands.rs`, `src/features.rs`, `src/surface_patch.rs`, `src/surface_validate.rs`, `src/tool_gate_preview.rs`.
