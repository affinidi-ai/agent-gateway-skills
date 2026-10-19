# fabric: getting it, connecting, access and scripting

Read this when `fabric` fails, you need a token for automation, or a task has no command. Checked
against the reviewed fabric version; `--help` wins over this file.

## Contents

[Before you change anything](#before-you-change-anything) · [Get fabric](#get-fabric) ·
[Connect](#connect) · [Access](#access) · [Other resource groups](#other-resource-groups) ·
[Scripting safely](#scripting-safely) ·
[fabric agent-gateway api, and what has no CLI path](#fabric-agent-gateway-api-and-what-has-no-cli-path) ·
[When it fails](#when-it-fails) · [Known issues here](#known-issues-here)

## Before you change anything

Run `fabric --version`, `fabric agent-gateway config list -o json` and `fabric agent-gateway whoami -o json`. `whoami` exits 0
even when the gateway rejects the token, so read `.authenticated`, never the exit code. It reports
`role`, and `scopes` only for a scoped personal access token (PAT); a session token or a full-role
PAT has no `scopes` field. For a PAT it also reports `token_id`, and `token_name` when the token has
`access_tokens.view`. `gateway_version` comes from the gateway's public `/v1/version` route, without a token;
it is `null` (`unknown` in the table) when the gateway gives none, with a `warning:` line on stderr unless the
route answered 404.

## Get fabric

Run `fabric --version`; it prints `fabric <version>`. If there is no `fabric` command, stop and ask
the user to install it: the CLI's README has the steps, with prebuilt binaries for x86_64 and aarch64 Linux
(glibc 2.34 or newer) and for Apple silicon and Intel Macs (macOS 12 or newer); other systems install it with
Cargo. When the version differs from the one [SKILL.md](../SKILL.md) was reviewed against, follow its version
check.

The macOS release binaries are signed with Affinidi's Developer ID and notarized, so a Keychain "Always Allow"
grant lasts across upgrades. If macOS asks for Keychain access again after every new fabric binary, that
binary is unsigned or ad-hoc signed, as a Cargo install is: macOS ties the grant to the binary's code
requirement, and for such a binary that requirement is its content hash. A Cargo copy in `~/.cargo/bin` can
also come first on `PATH` and shadow a release binary; `command -v fabric` shows which one runs.

## Connect

### Sign in

Sign in through the browser for interactive work, and with a personal access token (PAT) for anything
unattended or on a host without a browser. `login` always needs `--host`, even to refresh a saved connection.
Check either with `fabric agent-gateway whoami -o json` and its `.authenticated`.

**Browser.** Run `fabric agent-gateway login --host https://gateway.example.com`. fabric opens the gateway's
`/api/auth/cli/authorize` in a browser (and prints the URL in case it does not open), which sends you through
the dashboard's passkey or SSO sign-in to a page asking **Allow the CLI to sign in as you?**. Choose **Allow**
within 300 seconds. Only an approved account can: a new account, or **Cancel**, ends the login with
`the login callback reported an error: access_denied`. The browser then returns to fabric on `127.0.0.1`, and
fabric exchanges a one-time code for the token (`src/auth/cli_login.rs`). That token is the dashboard's own
session: it carries your whole role, lapses after `session_timeout_minutes` (20 by default) without use, each
request extends it, and there is no refresh. Signing out of the dashboard ends it too. The callback goes to this
machine, so over SSH, or with no browser, use a PAT.

**PAT.** Create one with `fabric agent-gateway tokens create` from a browser login
([Personal access tokens](#personal-access-tokens)), or in the dashboard: **Secrets**, then the
**Access Tokens (PAT)** tab, then **New Access Token**. In the dashboard, pick the scopes the work needs (with
none selected the token holds your whole role) and switch off **Never expires** to set a date; the secret
(`agpat_...`) is shown once. By default only `administrator` can create one ([Roles and approval](#roles-and-approval)).
Then run `fabric agent-gateway login --host https://gateway.example.com --pat`, which prompts for the secret
without echo; without a terminal, pipe it in with `--token-stdin`, or set `FABRIC_PAT`, which fabric reads only
with `--pat` ([CI and other hosts without a keyring](#ci-and-other-hosts-without-a-keyring)).
`--paste`, `--token-stdin` and piped input without `--pat` take a session token, not a PAT.

A plain `http://` host given on the command line (`--host` or `FABRIC_HOST`) is refused before anything is
sent unless it is `localhost` or a loopback address, or you pass the global `--allow-http`: the token would
cross the network unencrypted. With `--allow-http` fabric sends it and warns on stderr
`warning: using plain http with <host>, the session token will be sent unencrypted`. A host already saved in a
connection is not refused again, but fabric gives that warning once per run for a saved plain `http://` host
that is not loopback, adding `log in again with an https host to fix this`.

### Saved connections, overrides and precedence

A login saves a named connection (`default` unless you pass `-c <name>`) and makes it current. The
host goes to `config.toml`, the token to the OS keyring (Keychain, Windows Credential Manager or
Linux Secret Service) under service `affinidi-trust-fabric-cli`. The file is
`~/Library/Application Support/fabric/config.toml` on macOS and `~/.config/fabric/config.toml` on
Linux (under `$XDG_CONFIG_HOME` when set); no flag or variable moves it. Every command that talks to
a gateway resolves the connection (`-c` or `FABRIC_CONNECTION`, else the file's `current`), then the
host (`--host` or `FABRIC_HOST`, else the connection's), then the token (`--token` or
`FABRIC_TOKEN`, which skips the keyring, else the keyring entry). With no connection selected, by `-c`,
`FABRIC_CONNECTION` or the file's `current`, a command needs both a host and a token, uses them as they are,
and never opens the keyring; `whoami` then shows no `connection`. A command given both never opens the keyring
when a connection is selected either, and `whoami` reports `token_stored: false` for a token given that way.
A saved token goes only to the host it was saved for, which the keyring keeps beside it: `--host` or
`FABRIC_HOST` naming another host, or a connection's host edited in `config.toml`, gets
`the token saved for connection '<name>' belongs to <host>, so it was not sent to <other host>` unless you pass
the global `--allow-host-override`, which sends it with a warning; never pass it. A token you give with `--token`
or `FABRIC_TOKEN` goes to whichever host you name, and when both it and the host come from the environment
fabric says so on stderr: `note: sending the token from FABRIC_TOKEN to the host from FABRIC_HOST (<host>)`.
For several gateways, log in once per connection (`-c <name>`) and switch with
`fabric agent-gateway config use <name>`.

### CI and other hosts without a keyring

Set the host and the token in the environment, from your secret store, and run commands with no `login`,
config file or keyring:

```bash
export FABRIC_HOST=https://gateway.example.com
export FABRIC_TOKEN="$PAT"
fabric agent-gateway whoami -o json
```

On Linux, fabric reaches the Secret Service over D-Bus without the system `libdbus` library. A server with no
desktop session has no Secret Service, so `login`, `logout`, `config remove` and any command that reads a saved
token fail there with
`no OS keyring can be reached over D-Bus here, as on a server with no desktop session`, followed by a hint to
set `FABRIC_HOST` and `FABRIC_TOKEN`. A config file that still holds a plaintext `token =` line names the
connection and its saved host in that error: copy that token into `FABRIC_TOKEN`, set `FABRIC_HOST` to that
host, and delete the line. Every command that talks to a gateway also needs the system root
certificates (the `ca-certificates` package), even for a plain `http://` host.

`fabric agent-gateway surfaces features` without a surface and `surfaces tool-gate-preview --gates-file` need no
connection, token or gateway at all.

With `FABRIC_TOKEN` exported, `login --pat`, `--paste` and `--token-stdin` fail as usage errors.
With a keyring, save a PAT once from a secret store, never as an argument:
`printf '%s' "$PAT" | fabric agent-gateway login --pat --token-stdin --host https://gateway.example.com -c ci`.
`login --pat` refuses a value that does not start with `agpat_` before sending anything, and saves the token
only when the gateway's `/v1/token-info` answers 200: a revoked or expired token gets
`validate login: gateway did not accept the bearer token`, and any other answer
`gateway answered <status> when checking the token`.
`fabric agent-gateway logout` deletes the local copy and acts on the gateway when it can reach it: for a session
token it ends the session (`POST /auth/logout`), which signs the browser it came from out too; for a PAT it asks whether to
revoke it, and `--revoke-token` revokes it without asking. Without a terminal and without that flag the PAT
stays valid, and fabric prints how to revoke it. `fabric agent-gateway config remove <name>` deletes only the
local copy.

## Access

### Roles and approval

Three roles, `user`, `poweruser` and `administrator`, each include everything below them.
By default `user` has `surfaces.view`, `gateways.view`, `trust_registries.view`, `issuers.view`,
`authorities.view`, `integrations.view`, `notifications.view`, `metrics.view`, `logs.view` and
`dashboard.view`; `poweruser` adds `mcp_proxies.*`, `a2a_proxies.*`, `mediators.*`, `issuers.edit`,
`issuers.delete`, `notifications.edit`, `notifications.delete`, `surfaces.capture`, `payments.view` and
`payments.retry`; only `administrator` has the rest: `surfaces.edit`, `surfaces.delete`, `gateways.edit`,
`gateways.delete`, `trust_registries.edit`, `trust_registries.delete`, `authorities.edit`,
`authorities.delete`, `integrations.edit`, `integrations.delete`, `payments.edit`, `payments.delete`,
`policies.*`, `secrets.*`, `api_keys.*`, `certificates.*`, `credential_providers.*`, `delegation_vault.*`,
`jwt_verification_strategies.*`, `sts_clients.*`, `access_tokens.*`, `users.*`, `settings.*`, `terms.*`,
`tenant_ownership.manage`, `identity.issue`, `config.reload`, `audit.view` and `storage.admin`.
The map is `rbac.json` on the appliance (the file `[config_files] rbac` in `config.toml` names), merged over
these defaults and read once at startup; `fabric agent-gateway runtime reload` does not re-read it, so a change
needs file access and a restart. An `[rbac]` table in `config.toml` is ignored. The example `rbac.json` is not
these defaults: it lowers `gateways.edit`, `gateways.delete`, `trust_registries.edit`,
`trust_registries.delete` and `payments.edit` to `poweruser`. A file that cannot be loaded leaves the
defaults, with only a warning in the log (`Failed to load RBAC config from <path>`), and a role value other
than the three names (`admin`, say) denies that feature to everyone.
`fabric agent-gateway api get /v1/permissions -o json` shows what the current token may do: `true` or `false`
for each feature name it lists (it leaves out `config.reload`, `storage.admin`, `identity.issue` and
`certificates.edit`), after its role and scopes. Check it before you chase a 403: a role or scope refusal
comes back as a 403 with an empty body.

Sign-in is set by `auth_mode` in `config.toml`: `passkey`, the default and the example `config.toml`'s
setting, or `saml`, which signs users in through the identity provider in `saml.json`.
The first account registered on a new gateway is its approved primary administrator. Later passkey
registrants are `user` with status `new`, and get 401 until an administrator approves them.
SAML users are approved automatically, and each SSO login re-applies the
role from the identity provider, so a role you set with fabric reverts. To
approve (**confirm with the user**: access starts at once), write
`{"status":"approved","role":"poweruser"}` to `approve.json` and run
`fabric agent-gateway users update <user-id> --file approve.json`. Only an administrator can change a role or
status, never their own.

### Personal access tokens

Use a PAT for anything non-interactive. The secret (`agpat_...`) is shown once and only its hash is
stored; the ID is `agat_...`. **Confirm with the user:** the token acts as
them, within its scopes, until it expires or is revoked.
`fabric agent-gateway tokens create --name ci-readonly --scope surfaces.view --expires-at 2027-01-01T00:00:00Z`:
table output is the secret alone on stdout (pipe it into a secret store), with `Created access token '<id>'` and a
`note:` on stderr; `-o json` prints the whole record, `token` and `id` included. Each scope must be a key of
the gateway's permission map; a scope your role lacks is accepted but grants nothing, because every call also
checks the owner's role. `--expires-at` must be in the future and at most 3650 days out. Without it fabric sets one
90 days ahead and says so on stderr, so `tokens create` cannot make a token that never expires. Take scope
names from the roles list above:
`fabric agent-gateway tokens scopes` omits four grantable ones, `config.reload` among them
([KI-42](known-issues.md)).

- **A token needs `--scope`.** Without one, `tokens create` refuses
  (`a token with no scopes would hold your whole role, ...`) unless you pass `--full-role`, and a `--file`
  body needs `scopes` the same way. A full-role token carries the owner's whole role, looked up on every
  request: demoting the owner narrows it, disabling the owner stops it ([KI-07](known-issues.md)). Don't
  create one for anyone or anything to use.
- Scopes narrow the routes behind the per-route feature gate and the handlers that apply them, such as JWT
  verification strategies. Handlers that check only the role (users, settings writes, backup and restore)
  ignore them, and some routes check nothing beyond sign-in ([KI-07](known-issues.md)).
  For real least privilege, create the token as a lower-role user. By default only `administrator` has
  `access_tokens.*` (`RbacConfig::default` in `src/rbac/mod.rs`), so that needs an `rbac.json` change first.
- A PAT can create child tokens with a non-empty subset of its scopes, three levels deep; revoking a
  token revokes its descendants.
- `--resource-pattern` takes `TENANT:${<header>}:<resource-kind>:<id-regex>`, matched against the
  resource's tenant, kind and ID, not the request path, and needs the header
  declared with `--required-header <name>=<regex>`. fabric cannot send
  custom headers: give such a token only to a client that sends the header. A resource's own actions, such
  as a gateway's `issuer` and `trusted-issuers`, are checked against the same ID; a sub-path the gateway does
  not list is refused to a scoped token.
- The tenant header's pattern must match one value only, such as `x-tenant-id=123456789012`; the pattern
  must match the whole value. A broader one, `[0-9]{12}` say, gets 400
  `tenant selector for header '<h>' is broad` unless `config.toml` has a `[tenancy.trusted_tenant_header]`
  table with `header` naming that header and `edge_strips_client_values = true`, which asserts that an
  authenticating proxy in front of the gateway replaces any value a client sends. The table is read at
  startup; without it, a broad token issued earlier gets 403 on every call.
- `fabric agent-gateway tokens rotate <token-id>` replaces the secret and keeps the ID, name, scopes, expiry
  and child tokens. The old secret stops working at once, with no grace period, and the new one is printed
  once, as for `create`; the record then shows `rotation_generation`, `rotated_at` and `rotated_by`. It needs
  `access_tokens.edit`, and rotating another user's token also needs the `administrator` role (403
  `only administrators can rotate another user's access token`); it prompts, and refuses without a terminal
  unless `--yes`. A PAT may rotate only itself
  and its descendants: anything else, an unknown ID included, gets 403
  `an access token may manage only itself or its descendants`. A revoked, expired or inactive token gets
  409, and so does a rotation that races another
  (`access token was rotated concurrently; fetch it and retry`). **Confirm with the user:**
  every client holding the old secret fails until it gets the new one, a saved fabric connection included.
- `fabric agent-gateway tokens` has no update subcommand; editing a PAT through `fabric agent-gateway api` replaces name,
  description, scopes, pattern and headers, and cannot change the expiry.
  Always send `scopes`: an omitted list becomes empty, which grants the owner's full role. A revoked token
  cannot be edited (409 `cannot edit a revoked token`).

**Terms of Use.** When the gateway enforces Terms and you have not accepted the current version,
other calls get 403 `TERMS_ACCEPTANCE_REQUIRED`. A session accepts with
`fabric agent-gateway api post /v1/terms/acceptances --file acceptance.json`. A PAT is refused even there, so its
owner must accept in the dashboard in a browser ([KI-40](known-issues.md)). A session can check first with
`fabric agent-gateway terms status` (must I accept?) and `terms applicable` (which versions are in force).
Your organisation's own customer Terms are set with `terms draft --file draft.json` (`version`, `title`, `url`,
`requires_reconsent`), `terms publish` and `terms deactivate`, which need `terms.edit`, administrator by
default. **Confirm with the user:** after the first publish, and after any version with
`"requires_reconsent": true`, every user must accept it before other calls work.

### Scope a token and prove it

Create a view-only and a full-role token, one hour each, into files only you can read:

<!-- e2e: pat-scope -->
```bash
EXPIRES=$(jq -rn 'now + 3600 | todate')
umask 077
fabric agent-gateway tokens create --name scope-check-view --scope surfaces.view --expires-at "$EXPIRES" -o json > pat-view.json
fabric agent-gateway tokens create --name scope-check-full --full-role --expires-at "$EXPIRES" -o json > pat-full.json
```

Pass a token per command in `FABRIC_TOKEN`; the view-only one shows its scope and can read:

<!-- e2e: pat-scope -->
```bash
PAT=$(jq -r .token pat-view.json)
FABRIC_TOKEN="$PAT" fabric agent-gateway whoami -o json
FABRIC_TOKEN="$PAT" fabric agent-gateway surfaces list -o json > /dev/null
```

It cannot write: the gateway answers 403 with an empty body
(`gateway returned 403 Forbidden: no additional detail from server`):

<!-- e2e: pat-scope expect-fail -->
```bash
PAT=$(jq -r .token pat-view.json)
FABRIC_TOKEN="$PAT" fabric agent-gateway surfaces create --name scope-check-probe --protocol mcp --listen-address "$(fabric agent-gateway runtime show surface-routing -o json | jq -r '.available_listen_addresses[0]')" --target-endpoint http://127.0.0.1:9/mcp
```

The full-role token has no `scopes` field and passes an administrator-only read:

<!-- e2e: pat-scope -->
```bash
PAT=$(jq -r .token pat-full.json)
FABRIC_TOKEN="$PAT" fabric agent-gateway whoami -o json
FABRIC_TOKEN="$PAT" fabric agent-gateway policies list -o json > /dev/null
```

**Undo and verify.** Revoke both with your own login (`--yes` is needed without a terminal);
a revoked token reports `"authenticated": false`. Then delete both files.

<!-- e2e: pat-scope -->
```bash
for f in pat-view.json pat-full.json; do
  fabric agent-gateway tokens revoke "$(jq -r .id "$f")" --yes > /dev/null
done
PAT=$(jq -r .token pat-view.json)
FABRIC_TOKEN="$PAT" fabric agent-gateway whoami -o json
rm -f pat-view.json pat-full.json
```

## Other resource groups

- **Certificates** (mTLS trust anchors and pinned client certificates): [credentials.md](credentials.md#certificates).
  **STS clients**: [identity.md](identity.md).
- **Tenant ownership.** A resource is global or belongs to one tenant. A token bound to a tenant through its
  `--resource-pattern` sees that tenant's resources and global ones, and other callers see all. Such a token
  reads global secrets, policies, credential providers, certificates, STS clients, JWT verification strategies,
  mediators, trust registries, issuers, trust authorities, surface templates and integrations but gets 403 when
  it changes one, and a write to another tenant's resource gets the same 404 as a missing one. A tenant's
  resource may refer to its own tenant's and to global resources, a global one only to global ones. Before a
  move, run `fabric agent-gateway tenant-ownership impact <kind> <id> -o json` for its `tenant_id`,
  `immutable` and the `incoming` and `outgoing` references. **Confirm with the user:**
  `fabric agent-gateway tenant-ownership set <kind> <id> --tenant <tenant>`, or `--clear` for global, changes
  at once who sees it; the answer's `previous_tenant_id` is your undo. It needs `tenant_ownership.manage`
  (administrator). A resource-scoped PAT gets 403
  `Resource-scoped access tokens cannot reassign tenant ownership`, and a move that would break a reference,
  or of a system-owned (`immutable`) resource, gets 409 `tenant_reassignment_blocked` with the `conflicts`.
  `api-keys` and `connection-points` follow their parent and are refused.
- **Integrations** send notifications (`email`, `slack`, `webhook` or `stream`) on gateway events.
  `fabric agent-gateway integrations` creates and edits them; `POST /v1/integrations/test` and
  `/v1/integrations/<id>/trigger` have no typed command. Their `configuration` holds SMTP passwords, API keys
  and webhook URLs in plain text, and every read returns it unmasked, to `user` by default
  ([KI-46](known-issues.md)): never print it.
- **Authorities** are a record book of external DIDs (`name`, `did`, optional `description` and `context`).
  They carry no keys and decide no request. A Trust Recorder that writes records for an authority's DID also
  publishes the authority's `name` and `description` to that trust registry, and the dashboard's Trust Check
  element offers authorities as a query's authority. Any `user` may read them by default; only `administrator`
  may create, change or delete one.

## Scripting safely

- Pass `-o json` to anything you parse, and read a new ID from it, such as
  `fabric agent-gateway surfaces create --file surface.json -o json | jq -r .surface_id`. Table output is for people:
  - a `list` prints one table with a header row and that resource's columns, padded with spaces, not tabs, such
    as `NAME  ID  PROTOCOL  ROUTE  TARGET  TRANSIT POINTS` for surfaces. Long values end in `...`; IDs, DIDs
    and the names of surfaces, secrets and certificates print whole. An empty list prints one line, such as
    `No surfaces yet.`, or `No matching secrets.` after a filter such as `secrets list --tag`;
  - a `get` prints the object as JSON;
  - `create`, `update` and `delete` print one line, such as `Created surface '<id>'`, `Updated policy '<id>'`
    or `Deleted secret '<id>'`; `surfaces create` adds indented `id`, `name`, `route`, `protocol` and `target`
    lines, the target cut to scheme, host and port. With `-o json` they print the gateway's answer, which is
    `null` for the empty body most deletes get;
  - `tokens create` and `rotate`, and `api-keys create` and `rotate`, print the secret alone on stdout and the
    confirmation line and a `note:` on stderr, so `$(...)` captures only the secret.
- `surfaces get`, `update`, `delete`, `features`, `add-feature`, `remove-feature`, `add-transit-point`,
  `remove-transit-point` and `tool-gate-preview` take a surface's name as well as its ID
  ([surfaces.md](surfaces.md#recipe-change-a-surface-safely)), as `secrets`
  and `certificates` `get`, `update` and `delete` take a name; other commands take IDs only.
- Messages on stderr start with `note:`, `warning:` or `error:`, apart from prompts, the confirmation line
  printed beside a secret, and the lines a browser `login` prints. A runtime
  error prints `error: <reason>` and exits 1, and an invalid command line exits 2. Every surface `--dry-run`
  that passes fabric's own check exits 3 with nothing saved, because the gateway runs none of its checks on a
  preview ([surfaces.md](surfaces.md#recipe-change-a-surface-safely)).
- `--file <path>` reads JSON and `--file -` reads stdin. A body that still holds the mask
  `<hidden; pass --reveal to show>` is refused, so a masked `get` can never be replayed; a `--set` or
  `add-feature --json` value is not checked.
  `policies create --policy-file -` reads a file named `-`
  ([KI-41](known-issues.md)).
- Fields you leave out of a `--file` write: `update` for `authorities`, `sts-clients` and `integrations`
  replaces the record and clears them, as do `surfaces update --file` and `policies update`, so start from
  `get -o json`. A Governance Audit integration keeps its `audit_events`, `audit_drop_after_secs` and
  `audit_max_attempts` when the file leaves them out. `surfaces update --file` keeps only the stored
  `mcp_http` (or the `authorization` inside it) and `mcp_legacy_metadata_output` when the file leaves them out
  ([surfaces.md](surfaces.md));
  `jwt-verification-strategies update` replaces `name`, `expected_issuer` and `jwks_source`, so send all
  three. `update` for `users`, `certificates`, `connections`, `connection-points`, `issuers`,
  `trust-registries`, `mediators`, `mcp-proxies`, `a2a-proxies` and `credential-providers` changes only the
  fields you send; read the group's `update --help` for its exceptions.
  `surfaces update --set`/`--unset`/`--add`/`--remove` (not with `--file`), `add-feature`, `remove-feature`,
  `add-transit-point` and `remove-transit-point` send a JSON Merge Patch that leaves other fields alone; a list
  they change is sent whole ([KI-32](known-issues.md), [surfaces.md](surfaces.md)).
  `settings set` keeps them but replaces `feature_flags` and `audit_events` whole; `secrets update` keeps
  them except `description`, which it clears, and refuses a document that sets `value` without an
  `update_value` key; `metrics config set` refuses to drop a stored setting.
- `fabric agent-gateway shell` opens a prompt, `fabric agent-gateway>`, that takes one command per line without
  the `fabric agent-gateway` prefix, such as `surfaces list -o json`, and adds the global flags the shell
  started with. An error is printed and the prompt stays; `exit` or `quit` leaves. Scripts call fabric directly.
- `tokens revoke` and `tokens rotate`, and `api-keys revoke`, `rotate` and `delete`, prompt on stderr and refuse
  without a terminal unless `--yes`; `payments delete`, `metrics truncate` and `logs truncate` need `--yes`;
  `settings reset` needs `--force`. Every other delete, `surfaces delete` included, runs at once with no
  prompt and no undo ([KI-34](known-issues.md)).
- A request gives up after 10 s without a connection or 120 s without data, and every call except
  `logs download` after 5 minutes in all. fabric follows a redirect only to the same scheme, host and port.

## fabric agent-gateway api, and what has no CLI path

`fabric agent-gateway api <get|post|put|patch|delete> <path>` sends one request to `<host>/api<path>` (a path
that already starts with `/api/` is sent as-is) with the connection's token and an optional JSON
body from `--data '<json>'` or `--file <path>` (`-` for stdin). The path must start with `/` and
must not contain `..`, percent-encoded or not, the reply must be JSON, and it cannot add request headers. It sends
`application/json`, except `api patch`, which sends `application/merge-patch+json` and needs `--data` or
`--file`. For a surface prefer `surfaces update --set`, which checks the edit on your machine first.

Every fabric command uses that `/api` prefix. The gateway serves most management routes under the `prefix` of
its `routes` entry of type `identity_api` (`/api` in the example `gateway.json`), but secrets, API keys,
certificates, tokens, credential providers and the delegation vault always under `/api`. With another prefix,
fabric reaches only those. Its other calls miss the management API and get whatever else the listener serves at
that path, which with the example's `fallback` static route is the dashboard's `index.html` (inference).

These tasks have no typed command:

| Need | Path |
| --- | --- |
| Surface Variants, template export and import | `fabric agent-gateway api post /v1/surfaces/<surface-id>/variants --file variant.json`, `fabric agent-gateway api get /v1/surface-templates/<template-id>/export -o json`, `fabric agent-gateway api post /v1/surface-templates/import --file template.json`; see [surfaces.md](surfaces.md) |
| Dry-run a policy | `fabric agent-gateway api post /v1/policy-definitions/<policy-id>/simulate --file simulate.json`; see [policies.md](policies.md) |
| Appliance-wide policy assignments | `fabric agent-gateway api get /v1/policy-assignments -o json`, then `put` the edited document |
| Policy on a remote gateway | `fabric agent-gateway api put /v1/gateways/<gateway-id>/policy --file policy.json`; see [g2g.md](g2g.md) |
| Gateway-to-gateway handshake and approval | `fabric agent-gateway api post /v1/gateways/connect-via-oob --file oob.json`, then `/v1/gateways/<gateway-id>/approve`; see [g2g.md](g2g.md) |
| Edit a PAT | `fabric agent-gateway api put /v1/access-tokens/<token-id> --file token.json` |
| A connection's issuer DIDs | `fabric agent-gateway api post /v1/gateways/<gateway-id>/issuer`, `fabric agent-gateway api post /v1/gateways/<gateway-id>/trusted-issuers --data '{"issuer_did":"<did>"}'`; see [g2g.md](g2g.md) |
| Trust Check query templates | `fabric agent-gateway api get /v1/trust-check/predefined-queries -o json` |
| What the current token may do | `fabric agent-gateway api get /v1/permissions -o json` |
| `gateway.json` as stored | `fabric agent-gateway api get /v1/gateway/config -o json`, which needs `settings.view` (administrator by default); like the routing view, it shows the file, not what is running |
| Accept Terms | session: `fabric agent-gateway api post /v1/terms/acceptances --file acceptance.json`; PAT owner: browser only |
| Backup and restore | `curl` with a bearer token, because `fabric agent-gateway api` is JSON-only; see [operations.md](operations.md) |
| Live payload capture, live log stream | dashboard only (WebSocket); see [operations.md](operations.md) |
| Listeners, channel prefixes, TLS, `rbac.json` | edit the files on the appliance and restart; see [operations.md](operations.md) |

## When it fails

| Exact text | Cause | Fix |
| --- | --- | --- |
| `no gateway connection configured; run \`fabric agent-gateway login --host <URL>\`, or set both FABRIC_HOST and FABRIC_TOKEN` | No connection selected, and not both a host and a token given | Log in, or set both ([CI and other hosts without a keyring](#ci-and-other-hosts-without-a-keyring)) |
| `no OS keyring can be reached over D-Bus here, as on a server with no desktop session` | Linux with no D-Bus session or no Secret Service, for a command that uses the keyring | Set `FABRIC_HOST` and `FABRIC_TOKEN`; for a plaintext `token =` line, follow the error's steps |
| `build HTTP client: builder error: unexpected error: No CA certificates were loaded from the system` | The system root certificates are missing, as on a slim container image | Install `ca-certificates` |
| `warning: could not read the gateway version: <reason>` | `whoami` could not read the gateway's version: a network error, an answer other than 200 or 404, or no version in the answer | Read `<reason>`; `gateway_version` is `null` and the rest of `whoami` stands |
| `--host is required for login` | Refreshing without a host | Add `--host https://<gateway>` |
| `timed out waiting for the browser login to complete` | No **Allow** within 300 seconds, or the browser could not reach `127.0.0.1` on this machine (SSH, a remote desktop) | Run `login` again and choose **Allow**; on a host without a local browser use `--pat` ([Sign in](#sign-in)) |
| `the login callback reported an error: access_denied` | **Cancel** on the consent page, or the account is not approved yet | Run `login` again; an administrator approves the account first ([Roles and approval](#roles-and-approval)) |
| `code exchange failed (400 Bad Request)` with `invalid_grant` | The one-time code is older than two minutes or was used, or the gateway runs as several instances and the exchange reached another one: codes live in one instance's memory | Run `login` again; behind several instances use `--pat` |
| `personal access token must start with 'agpat_'` | `login --pat` was given something else, such as the token's ID (`agat_...`) | Pass the secret shown when the token was created |
| `cannot be used with '--token <TOKEN>'` | `FABRIC_TOKEN` exported during `login` | `unset FABRIC_TOKEN` |
| `validate login: gateway did not accept the bearer token` | Expired session token, a revoked or expired PAT, or a PAT without `--pat` | A fresh session token, a new PAT, or add `--pat` |
| `validate login: gateway answered <status> when checking the token` | `login --pat` got neither 200 nor 401 from `/v1/token-info`: `--host` is not the gateway, or the gateway is unhealthy | Check `--host` and the gateway's health |
| `the token saved for connection '<name>' belongs to <host>, so it was not sent to <other host>` | `--host` or `FABRIC_HOST` names another host than the saved token's, or the connection's host was edited in `config.toml` | Select the connection for that host with `-c`, or log in there |
| `gateway rejected the bearer token: no additional detail from server` (401) | Session lapsed, the PAT is revoked or expired, or its owner is not approved yet or is disabled | Log in again or create a new PAT; an administrator approves the account |
| `TERMS_ACCEPTANCE_REQUIRED` (403), or for a PAT `Sign in to Agent Gateway as this access token's owner, accept the required Terms and Conditions, then retry.` | Terms not accepted | Accept (see Terms of Use above); a PAT's owner accepts in the dashboard |
| `gateway returned 403 Forbidden: no additional detail from server` | The account's role is below the feature's minimum, the PAT lacks that scope, or its `resource_pattern` or required header refused the call | Check `fabric agent-gateway api get /v1/permissions -o json`; use an account with the role or a PAT with the scope, and from fabric a PAT without a pattern or required header |
| `Insufficient permissions` (403) | A handler that checks the role itself (users, settings writes, backup and restore), or a JWT verification strategy route refusing the role or the PAT's scope | Use an account with the role, and for JWT verification strategies a PAT with the scope |
| `gateway returned 404 Not Found: no additional detail from server`, object exists | Resource-scoped PAT; the ID is outside its pattern | Use a PAT whose pattern covers the ID |
| `unknown scope: <scope> (see \`fabric agent-gateway tokens scopes\`)` | Not a key of the permission map (`departments.*` included) | Take the name from the roles list |
| `refusing to revoke '<id>'`, `refusing to rotate '<id>'` or `refusing to delete '<id>'` `without confirmation in a non-interactive session` | `tokens revoke` or `rotate`, or `api-keys revoke`, `rotate` or `delete`, without a terminal | Confirm with the user, then add `--yes` |
| `a token with no scopes would hold your whole role, ...` | `tokens create` with no `--scope`, or a `--file` body with no `scopes` | Add `--scope` |
| `refusing to use plain http for a non-local host (<host>)` | An `http://` host that is not loopback | Use `https://`, or pass `--allow-http` on a network you trust |
| `cannot rotate a revoked token`, `cannot rotate an expired token`, `access token is inactive or its parent token is no longer valid` (409) | The token, or its parent, is no longer active | Create a new token |
| `access token was rotated concurrently; fetch it and retry` (409) | Two rotations at once | Read the token again; use the secret the winning rotation printed |
| `an access token may manage only itself or its descendants` (403) | A PAT acting on a token outside its own lineage, or an unknown ID | Use the owner's session or the parent token |
| `only administrators can rotate another user's access token` (403) | `tokens rotate` on another user's token without the `administrator` role | An administrator, or the token's owner, rotates it |
| `cannot edit a revoked token` (409) | `api put /v1/access-tokens/<token-id>` on a revoked token | Create a new token |
| `non-empty resource pattern must use TENANT:${header}:<resource-kind>:<resource-id-pattern>` (400) | `--resource-pattern` is not in the `TENANT:${<header>}:<kind>:<id-regex>` form | Rewrite it in that form |
| `tenant selector for header '<h>' is broad` (400) | The tenant header's pattern admits more than one value | An exact value, or `[tenancy.trusted_tenant_header]` behind a proxy that strips the header |
| `Resource-scoped access tokens cannot reassign tenant ownership` (403) | `tenant-ownership set` with a resource-scoped PAT | An administrator session, or a token without `--resource-pattern` |
| `tenant_reassignment_blocked` (409) | The move would break a reference, or the resource is system-owned | Read `conflicts`, move or detach the other side first |
| `gateway returned non-JSON content` | Wrong `--host`, or a route that returns HTML or binary | Check `--host`; use `curl` for binary routes |

## Known issues here

In [known-issues.md](known-issues.md): [KI-07](known-issues.md), [KI-34](known-issues.md),
[KI-40](known-issues.md), [KI-41](known-issues.md),
[KI-42](known-issues.md), [KI-46](known-issues.md).

Sources: [Deploy Agent Gateway appliance](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/get-started/deploy-agent-gateway-appliance-portal/), [Settings](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/reference/configuration/settings/); gateway source: `src/auth_manager/middleware.rs`, `src/access_tokens/handlers.rs`, `src/access_tokens/store.rs`, `src/rbac/mod.rs`, `src/auth_manager/resource_scope.rs`, `src/identity/router.rs`, `src/auth/cli_login.rs`, `www/default/src/pages/SecretsPage.tsx`; fabric's `src/commands.rs`, `src/config.rs`, `src/credentials.rs`, `src/client.rs`, `src/browser_login.rs`, `src/tables.rs`.
