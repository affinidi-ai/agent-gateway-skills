<!-- Generated from the help of fabric 0.1.2 by make cli-reference. Do not edit by hand. -->

# fabric command reference

An index of every `fabric` command and its options, taken from the help of fabric 0.1.2. It is a snapshot of `fabric --help` at the reviewed version: where the installed fabric's `fabric agent-gateway <command> --help` says otherwise, the live help wins. `fabric agent-gateway <command> --help` is the authoritative detail: what each option means, its default and the values it accepts. This file only lists them.

Every command is under an appliance group: `fabric agent-gateway`. Before the group, `fabric` takes only `-h, --help` and `-V, --version`.

## Global options

Every command accepts these after its appliance group, `fabric agent-gateway`, and after any subcommand, but not before the group, so the tables below leave them out.

| Option | What it does |
| --- | --- |
| `-c, --connection <CONNECTION>` | Named gateway connection. |
| `--host <HOST>` | Gateway host for this command. |
| `--token <TOKEN>` | Bearer token for this command. |
| `--allow-http` | Allow a plain http:// host other than this machine, typed with --host or set in FABRIC_HOST. |
| `--allow-host-override` | Send the saved token to a --host other than the one it was saved for. |
| `-o, --output <OUTPUT>` | Output format for commands that return data |
| `-h, --help` | Print help |

## login

Authenticate and save a named gateway connection.

| Command | What it does | Options |
| --- | --- | --- |
| `fabric agent-gateway login` | Authenticate and save a named gateway connection. | `--token-stdin`, `--paste`, `--pat` |

## logout

Sign out and remove a saved gateway connection.

| Command | What it does | Options |
| --- | --- | --- |
| `fabric agent-gateway logout` | Sign out and remove a saved gateway connection. | `--revoke-token` |

## config

Manage local gateway profiles.

| Command | What it does | Options |
| --- | --- | --- |
| `fabric agent-gateway config list` | List saved gateway profiles, with their hosts and which one is current |  |
| `fabric agent-gateway config use` | Select the default gateway profile. | `<NAME>` |
| `fabric agent-gateway config remove` | Remove a gateway profile and its saved token, without contacting the gateway. | `<NAME>` |

## runtime

Inspect and reload the gateway's own runtime configuration.

| Command | What it does | Options |
| --- | --- | --- |
| `fabric agent-gateway runtime show` | Show one of the gateway's read-only runtime configuration views | `<VIEW>` |
| `fabric agent-gateway runtime reload` | Reload surface configuration from the configured source. | `--surface` |

## settings

Manage appliance-wide settings

| Command | What it does | Options |
| --- | --- | --- |
| `fabric agent-gateway settings show` | Show the appliance-wide settings. |  |
| `fabric agent-gateway settings set` | Apply a partial update from a JSON document. | `--file` |
| `fabric agent-gateway settings reset` | Overwrite the whole document with the built-in defaults and show them. | `--force` |

## user-settings

Manage the signed-in user's own settings overrides

| Command | What it does | Options |
| --- | --- | --- |
| `fabric agent-gateway user-settings show` | Show this user's settings. | `--overrides` |
| `fabric agent-gateway user-settings set` | Apply a partial update from a JSON document. | `--file`, `--force` |
| `fabric agent-gateway user-settings reset` | Clear every personal override and show the resulting settings. |  |

## terms

Inspect and publish Terms of Use.

| Command | What it does | Options |
| --- | --- | --- |
| `fabric agent-gateway terms show` | Show the Terms of Use definitions |  |
| `fabric agent-gateway terms applicable` | Show the terms that apply to this gateway |  |
| `fabric agent-gateway terms status` | Show whether the signed-in principal has accepted the current terms |  |
| `fabric agent-gateway terms provider-health` | Show the health of the upstream terms provider |  |
| `fabric agent-gateway terms draft` | Save the customer Terms of Use draft from a JSON document. | `--file` |
| `fabric agent-gateway terms publish` | Publish the saved customer Terms of Use draft as a new version. |  |
| `fabric agent-gateway terms deactivate` | Deactivate the published customer Terms of Use. |  |

## notifications

Manage welcome notifications.

| Command | What it does | Options |
| --- | --- | --- |
| `fabric agent-gateway notifications welcome-template show` | Show the welcome notification template |  |
| `fabric agent-gateway notifications welcome-template set` | Replace the welcome notification template from a JSON document. | `--file` |
| `fabric agent-gateway notifications send-welcome` | Send a welcome notification to a user. | `--user-id`, `--title`, `--message` |

## whoami

Show the current login session and connected gateway.

| Command | What it does | Options |
| --- | --- | --- |
| `fabric agent-gateway whoami` | Show the current login session and connected gateway. |  |

## surfaces

Manage Agent Surfaces

| Command | What it does | Options |
| --- | --- | --- |
| `fabric agent-gateway surfaces list` | List Agent Surfaces |  |
| `fabric agent-gateway surfaces get` | Get an Agent Surface by ID or name | `<SURFACE_ID>` |
| `fabric agent-gateway surfaces create` | Create an Agent Surface using flags or a complete JSON document. | `--name`, `--description`, `--file`, `--listen-address`, `--route`, `--protocol`, `--target-endpoint`, `--tags` |
| `fabric agent-gateway surfaces update` | Update an Agent Surface's fields, or replace it from a JSON document. | `<SURFACE_ID>`, `--file`, `--set`, `--unset`, `--add`, `--remove`, `--dry-run` |
| `fabric agent-gateway surfaces delete` | Delete an Agent Surface by ID or name. | `<SURFACE_ID>` |
| `fabric agent-gateway surfaces features` | List the features a surface can have, or the ones a given surface has. | `<SURFACE_ID>` |
| `fabric agent-gateway surfaces add-feature` | Add a feature to an Agent Surface. | `<SURFACE_ID>`, `<FEATURE>`, `--edge`, `--transit-point`, `--response`, `--policy-id`, `--json`, `--file`, `--dry-run` |
| `fabric agent-gateway surfaces remove-feature` | Remove a feature from an Agent Surface. | `<SURFACE_ID>`, `<FEATURE>`, `--edge`, `--transit-point`, `--response`, `--dry-run` |
| `fabric agent-gateway surfaces add-transit-point` | Add a transit point to an Agent Surface from its alias and endpoint. | `<SURFACE_ID>`, `--alias`, `--endpoint`, `--dry-run` |
| `fabric agent-gateway surfaces remove-transit-point` | Remove a transit point from an Agent Surface by its alias or id. | `<SURFACE_ID>`, `<TRANSIT_POINT>`, `--dry-run` |
| `fabric agent-gateway surfaces tool-gate-preview` | Preview which tools a set of MCP tool gates would allow or deny. | `<SURFACE_ID>`, `--gates-file`, `--tool`, `--condition` |

## connections

Manage connections, the Gateway records of this gateway and its peers.

| Command | What it does | Options |
| --- | --- | --- |
| `fabric agent-gateway connections list` | List connections |  |
| `fabric agent-gateway connections get` | Get a connection by ID. | `<ID>` |
| `fabric agent-gateway connections create` | Create a connection from a JSON document. | `--file` |
| `fabric agent-gateway connections update` | Update a connection from a JSON document. | `<ID>`, `--file` |
| `fabric agent-gateway connections delete` | Delete a connection by ID. | `<ID>` |

## connection-points

Manage connection points, the DIDComm endpoints other appliances use to connect to this one.

| Command | What it does | Options |
| --- | --- | --- |
| `fabric agent-gateway connection-points list` | List connection points |  |
| `fabric agent-gateway connection-points get` | Get a connection point by ID. | `<ID>` |
| `fabric agent-gateway connection-points create` | Create a connection point from a JSON document. | `--file` |
| `fabric agent-gateway connection-points update` | Update a connection point from a JSON document. | `<ID>`, `--file` |
| `fabric agent-gateway connection-points delete` | Delete a connection point by ID. | `<ID>` |

## policies

Manage the Rego policy definitions the gateway enforces on traffic

| Command | What it does | Options |
| --- | --- | --- |
| `fabric agent-gateway policies list` | List policy definitions |  |
| `fabric agent-gateway policies get` | Get a policy definition by ID | `<POLICY_ID>` |
| `fabric agent-gateway policies create` | Create a policy definition from a Rego file. | `--id`, `--name`, `--description`, `--policy-type`, `--policy-file` |
| `fabric agent-gateway policies update` | Replace a policy definition from a JSON document. | `<POLICY_ID>`, `--file` |
| `fabric agent-gateway policies delete` | Delete a policy definition. | `<POLICY_ID>` |
| `fabric agent-gateway policies versions` | List the saved versions of a policy definition. | `<POLICY_ID>` |
| `fabric agent-gateway policies impact` | Show how many surfaces and gateways use a policy definition. | `<POLICY_ID>` |

## issuers

Manage issuers, the DID-carrying units that own surfaces

| Command | What it does | Options |
| --- | --- | --- |
| `fabric agent-gateway issuers list` | List issuers |  |
| `fabric agent-gateway issuers get` | Get an issuer by ID. | `<ID>` |
| `fabric agent-gateway issuers create` | Create an issuer from a JSON document. | `--file` |
| `fabric agent-gateway issuers update` | Update an issuer from a JSON document. | `<ID>`, `--file` |
| `fabric agent-gateway issuers delete` | Delete an issuer by ID. | `<ID>` |

## authorities

Manage authorities, external DIDs recorded as trust anchors.

| Command | What it does | Options |
| --- | --- | --- |
| `fabric agent-gateway authorities list` | List authorities |  |
| `fabric agent-gateway authorities get` | Get an authority by ID. | `<ID>` |
| `fabric agent-gateway authorities create` | Create an authority from a JSON document. | `--file` |
| `fabric agent-gateway authorities update` | Update an authority from a JSON document. | `<ID>`, `--file` |
| `fabric agent-gateway authorities delete` | Delete an authority by ID. | `<ID>` |

## trust-registries

Manage the trust registries this gateway connects to for Trust Checks

| Command | What it does | Options |
| --- | --- | --- |
| `fabric agent-gateway trust-registries list` | List trust registries |  |
| `fabric agent-gateway trust-registries get` | Get a trust registry by ID. | `<ID>` |
| `fabric agent-gateway trust-registries create` | Create a trust registry from a JSON document. | `--file` |
| `fabric agent-gateway trust-registries update` | Update a trust registry from a JSON document. | `<ID>`, `--file` |
| `fabric agent-gateway trust-registries delete` | Delete a trust registry by ID. | `<ID>` |

## mediators

Manage DIDComm mediator records

| Command | What it does | Options |
| --- | --- | --- |
| `fabric agent-gateway mediators list` | List mediators |  |
| `fabric agent-gateway mediators get` | Get a mediator by ID. | `<ID>` |
| `fabric agent-gateway mediators create` | Create a mediator from a JSON document. | `--file` |
| `fabric agent-gateway mediators update` | Update a mediator from a JSON document. | `<ID>`, `--file` |
| `fabric agent-gateway mediators delete` | Delete a mediator by ID. | `<ID>` |

## mcp-proxies

Manage MCP proxies, the services a surface Target can route MCP traffic through

| Command | What it does | Options |
| --- | --- | --- |
| `fabric agent-gateway mcp-proxies list` | List MCP proxies |  |
| `fabric agent-gateway mcp-proxies get` | Get an MCP proxy by ID. | `<ID>` |
| `fabric agent-gateway mcp-proxies create` | Create an MCP proxy from a JSON document. | `--file` |
| `fabric agent-gateway mcp-proxies update` | Update an MCP proxy from a JSON document. | `<ID>`, `--file` |
| `fabric agent-gateway mcp-proxies delete` | Delete an MCP proxy by ID. | `<ID>` |

## a2a-proxies

Manage A2A proxies, which expose a managed agent that does not speak A2A as an A2A endpoint

| Command | What it does | Options |
| --- | --- | --- |
| `fabric agent-gateway a2a-proxies list` | List A2A proxies |  |
| `fabric agent-gateway a2a-proxies get` | Get an A2A proxy by ID. | `<ID>` |
| `fabric agent-gateway a2a-proxies create` | Create an A2A proxy from a JSON document. | `--file` |
| `fabric agent-gateway a2a-proxies update` | Update an A2A proxy from a JSON document. | `<ID>`, `--file` |
| `fabric agent-gateway a2a-proxies delete` | Delete an A2A proxy by ID. | `<ID>` |

## sts-clients

Manage STS clients, the OAuth clients allowed to exchange tokens with the gateway's Security Token Service.

| Command | What it does | Options |
| --- | --- | --- |
| `fabric agent-gateway sts-clients list` | List STS clients |  |
| `fabric agent-gateway sts-clients get` | Get an STS client by ID. | `<ID>` |
| `fabric agent-gateway sts-clients create` | Create an STS client from a JSON document. | `--file` |
| `fabric agent-gateway sts-clients update` | Update an STS client from a JSON document. | `<ID>`, `--file` |
| `fabric agent-gateway sts-clients delete` | Delete an STS client by ID. | `<ID>` |

## credential-providers

Manage credential providers, the OAuth 2.0 and API-key providers used for outbound credential delegation.

| Command | What it does | Options |
| --- | --- | --- |
| `fabric agent-gateway credential-providers list` | List credential providers |  |
| `fabric agent-gateway credential-providers get` | Get a credential provider by ID. | `<ID>` |
| `fabric agent-gateway credential-providers create` | Create a credential provider from a JSON document. | `--file` |
| `fabric agent-gateway credential-providers update` | Update a credential provider from a JSON document. | `<ID>`, `--file` |
| `fabric agent-gateway credential-providers delete` | Delete a credential provider by ID. | `<ID>` |

## certificates

Manage TLS certificates and their private keys

| Command | What it does | Options |
| --- | --- | --- |
| `fabric agent-gateway certificates` | Manage TLS certificates and their private keys | `--reveal` |
| `fabric agent-gateway certificates list` | List certificates | `--reveal` |
| `fabric agent-gateway certificates get` | Get a certificate by its id or name | `<CERTIFICATE>`, `--reveal` |
| `fabric agent-gateway certificates create` | Create a certificate from a JSON document | `--file`, `--reveal` |
| `fabric agent-gateway certificates update` | Update a certificate from a JSON document. | `<CERTIFICATE>`, `--file`, `--reveal` |
| `fabric agent-gateway certificates delete` | Delete a certificate by its id or name. | `<CERTIFICATE>`, `--reveal` |

## secrets

Manage secrets

| Command | What it does | Options |
| --- | --- | --- |
| `fabric agent-gateway secrets` | Manage secrets | `--reveal` |
| `fabric agent-gateway secrets list` | List secrets. List responses never carry secret values | `--tag`, `--reveal` |
| `fabric agent-gateway secrets get` | Get a secret by its id, secret_id or name. The value is masked unless --reveal is given | `<SECRET>`, `--reveal` |
| `fabric agent-gateway secrets create` | Create a secret using flags or a complete JSON document. | `--name`, `--secret-id`, `--value`, `--value-stdin`, `--description`, `--reveal`, `--type`, `--tag`, `--file` |
| `fabric agent-gateway secrets update` | Update a secret from a JSON document. | `<SECRET>`, `--file`, `--reveal` |
| `fabric agent-gateway secrets delete` | Delete a secret by its id, secret_id or name. | `<SECRET>`, `--reveal` |

## delegation-vault

Inspect and revoke delegated credential grants

| Command | What it does | Options |
| --- | --- | --- |
| `fabric agent-gateway delegation-vault list` | List delegated credential grants |  |
| `fabric agent-gateway delegation-vault get` | Get a grant by ID | `<ID>` |
| `fabric agent-gateway delegation-vault revoke` | Revoke a single grant by ID. | `<ID>` |
| `fabric agent-gateway delegation-vault revoke-user` | Revoke every grant held for one user identity hash (sha256:...). | `<USER_HASH>` |

## integrations

Manage integrations, such as the email, Slack or webhook senders the gateway notifies through.

| Command | What it does | Options |
| --- | --- | --- |
| `fabric agent-gateway integrations list` | List integrations |  |
| `fabric agent-gateway integrations get` | Get an integration by ID. | `<ID>` |
| `fabric agent-gateway integrations create` | Create an integration from a JSON document. | `--file` |
| `fabric agent-gateway integrations update` | Update an integration from a JSON document. | `<ID>`, `--file` |
| `fabric agent-gateway integrations delete` | Delete an integration by ID. | `<ID>` |

## users

Manage gateway users.

| Command | What it does | Options |
| --- | --- | --- |
| `fabric agent-gateway users list` | List users |  |
| `fabric agent-gateway users get` | Get a user by ID. | `<USER_ID>` |
| `fabric agent-gateway users update` | Update a user's role, status, or profile from a JSON document. | `<USER_ID>`, `--file` |
| `fabric agent-gateway users delete` | Delete a user by ID. | `<USER_ID>` |

## identities

Manage did:webvh identities

| Command | What it does | Options |
| --- | --- | --- |
| `fabric agent-gateway identities list` | List did:webvh identities |  |
| `fabric agent-gateway identities get` | Get an identity by ID. | `<ID>`, `--reveal` |
| `fabric agent-gateway identities create` | Create an identity, optionally from a JSON document. | `--file` |
| `fabric agent-gateway identities update` | Update an identity's DID document from a JSON document. | `<ID>`, `--file` |
| `fabric agent-gateway identities rotate-keys` | Rotate an identity's signing keys. | `<ID>`, `--file` |
| `fabric agent-gateway identities transfer` | Transfer an identity to a new controller. | `<ID>`, `--file` |
| `fabric agent-gateway identities history` | Show an identity's version history | `<ID>` |
| `fabric agent-gateway identities trust-policy get` | Get an identity's trust-score policy. | `<ID>` |
| `fabric agent-gateway identities trust-policy set` | Set an identity's trust-score policy from a JSON document. | `<ID>`, `--file` |
| `fabric agent-gateway identities deactivate` | Deactivate an identity. | `<ID>` |

## api-keys

Manage the API keys an Agent Surface authenticates callers with

| Command | What it does | Options |
| --- | --- | --- |
| `fabric agent-gateway api-keys list` | List API keys across every Agent Surface, or for one of them | `--agent-id` |
| `fabric agent-gateway api-keys get` | Get an API key's metadata. The secret is never returned | `<KEY_ID>`, `--agent-id` |
| `fabric agent-gateway api-keys create` | Create an API key for an Agent Surface. | `<AGENT_ID>`, `--client-id`, `--label`, `--file` |
| `fabric agent-gateway api-keys revoke` | Revoke an API key without removing its record. | `<KEY_ID>`, `--agent-id`, `--actor`, `--yes` |
| `fabric agent-gateway api-keys rotate` | Replace an API key's secret, keeping its id, client_id and labels. | `<KEY_ID>`, `--agent-id`, `--actor`, `--yes` |
| `fabric agent-gateway api-keys delete` | Delete an API key. | `<KEY_ID>`, `--agent-id`, `--yes` |

## tenant-ownership

Inspect and reassign which tenant owns a resource

| Command | What it does | Options |
| --- | --- | --- |
| `fabric agent-gateway tenant-ownership impact` | Report what reassigning a resource would affect. | `<KIND>`, `<ID>` |
| `fabric agent-gateway tenant-ownership set` | Assign a resource to a tenant, or clear its tenant ownership. | `<KIND>`, `<ID>`, `--tenant`, `--clear` |

## jwt-verification-strategies

Manage JWT verification strategies.

| Command | What it does | Options |
| --- | --- | --- |
| `fabric agent-gateway jwt-verification-strategies list` | List JWT verification strategies |  |
| `fabric agent-gateway jwt-verification-strategies get` | Get a JWT verification strategy by ID. | `<ID>` |
| `fabric agent-gateway jwt-verification-strategies create` | Create a JWT verification strategy from a JSON document. | `--file` |
| `fabric agent-gateway jwt-verification-strategies update` | Update a JWT verification strategy from a JSON document. | `<ID>`, `--file` |
| `fabric agent-gateway jwt-verification-strategies delete` | Delete a JWT verification strategy by ID. | `<ID>` |
| `fabric agent-gateway jwt-verification-strategies validate-jwks-uri` | Check that a JWKS URI is reachable and serves a parseable key set. | `<URI>` |

## tokens

Manage personal access tokens for non-interactive gateway access

| Command | What it does | Options |
| --- | --- | --- |
| `fabric agent-gateway tokens list` | List personal access tokens. |  |
| `fabric agent-gateway tokens get` | Get a personal access token by ID | `<ID>` |
| `fabric agent-gateway tokens create` | Create a personal access token using flags or a complete JSON document. | `--name`, `--description`, `--scope`, `--full-role`, `--expires-at`, `--resource-pattern`, `--required-header`, `--file` |
| `fabric agent-gateway tokens revoke` | Revoke a personal access token. | `<ID>`, `--yes` |
| `fabric agent-gateway tokens scopes` | List the scopes your role holds, which you can give a new token. |  |
| `fabric agent-gateway tokens rotate` | Replace a personal access token's secret, keeping its ID, name, and scopes. | `<ID>`, `--yes` |

## audit

Read the gateway audit log

| Command | What it does | Options |
| --- | --- | --- |
| `fabric agent-gateway audit list` | List audit events, newest first. | `--limit`, `--page`, `--filter`, `--category`, `--flow`, `--scope`, `--decision`, `--all`, `--reveal` |

## payments

Inspect x402 and MPP payment records

| Command | What it does | Options |
| --- | --- | --- |
| `fabric agent-gateway payments list` | List payment records from both stores, newest first. | `--store`, `--surface`, `--status`, `--limit` |
| `fabric agent-gateway payments get` | Get one payment record. | `<ID>`, `--store`, `--reveal` |
| `fabric agent-gateway payments stats` | Show x402 settlement counters | `--sync` |
| `fabric agent-gateway payments delete` | Delete a finalised x402 transaction. MPP records cannot be deleted. | `<ID>`, `--yes` |

## metrics

Scrape metrics and check metrics export health

| Command | What it does | Options |
| --- | --- | --- |
| `fabric agent-gateway metrics config show` | Show the metrics configuration |  |
| `fabric agent-gateway metrics config set` | Replace the whole metrics configuration from a JSON document. | `--file`, `--force` |
| `fabric agent-gateway metrics status` | Report OpenTelemetry export health |  |
| `fabric agent-gateway metrics scrape` | Fetch the Prometheus exposition. | `--username`, `--password`, `--output-file` |
| `fabric agent-gateway metrics test-endpoint` | Check whether the gateway can reach an OTLP endpoint. | `<URL>` |
| `fabric agent-gateway metrics truncate` | Delete metrics older than the configured retention period. | `--yes` |

## logs

Download and truncate gateway log files

| Command | What it does | Options |
| --- | --- | --- |
| `fabric agent-gateway logs download` | Download every log file as one ZIP archive. | `--output-file` |
| `fabric agent-gateway logs truncate` | Delete every rotated log file, keeping the current one. | `--yes` |

## api

Call any authenticated management API endpoint.

| Command | What it does | Options |
| --- | --- | --- |
| `fabric agent-gateway api` | Call any authenticated management API endpoint. | `<METHOD>`, `<PATH>`, `--data`, `--file` |

## shell

Open the interactive shell.

| Command | What it does | Options |
| --- | --- | --- |
| `fabric agent-gateway shell` | Open the interactive shell. |  |
