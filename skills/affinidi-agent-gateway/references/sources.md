# Official sources

The Agent Gateway documentation pages this skill was checked against, and when to read one live instead of
answering from the skill. The pages change with the product; this skill describes the reviewed version named in
[SKILL.md](../SKILL.md).

## Contents

- [When to read a page live](#when-to-read-a-page-live)
- [Order of trust](#order-of-trust)
- [If a page cannot be read](#if-a-page-cannot-be-read)
- [Pages by topic](#pages-by-topic)
- [Gateway repository documents](#gateway-repository-documents)

## When to read a page live

Fetch the page with your web tool when:

- the user asks about something this skill does not cover;
- the live gateway or `fabric agent-gateway <command> --help` contradicts this skill;
- the user asks for the latest or current behaviour.

Otherwise answer from the reference pages. Every reference page except commands.md and this one ends with a Sources line naming the docs pages and gateway
files it was checked against, so that line tells you which page below to read for a given topic. A gateway file
such as `src/proxy/handler.rs` is a path in the gateway's source repository,
[affinidi-ai/agent-gateway](https://github.com/affinidi-ai/agent-gateway); the `fabric` files those lines name
are not published.

Every docs page also serves itself as Markdown: add `index.md` to its URL, after the trailing slash. Read that
version when you fetch a page; it holds the same text without the site's navigation.

## Order of trust

1. The running gateway: its responses, and `fabric agent-gateway <command> --help`.
2. The gateway source, and the documents in its `docs/` directory ([Gateway repository documents](#gateway-repository-documents)).
3. These docs pages.

This skill was checked against the source and the docs at the reviewed version. Where a docs page disagrees with
the skill, the skill follows the source. Where the running gateway disagrees with either, the gateway wins: tell
the user which claim looks stale.

## If a page cannot be read

Answer from the reference pages, tell the user the answer reflects the reviewed version, and give them the page's
URL to check.

## Pages by topic

### Getting started

| Page | Read it for |
| --- | --- |
| [Deploy Agent Gateway appliance](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/get-started/deploy-agent-gateway-appliance-portal/) | Deploying a gateway appliance from the portal |
| [Create your first surface](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/get-started/create-first-surface/) | The documented first-surface walkthrough |
| [Add identity and access control](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/get-started/secure-a-surface/) | The walkthrough's next step: a payload identity and a policy that requires it |
| [Monitor your surface](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/get-started/monitor-your-surface/) | A surface's Monitoring tab, Capture and logs in the dashboard |
| [Glossary](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/get-started/glossary/) | The product's terms and what each one means |

### Surfaces and routing

| Page | Read it for |
| --- | --- |
| [Surfaces](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/concepts/surfaces/) | What an Agent Surface is and the parts it has |
| [Surface routing model](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/concepts/surface-routing-model/) | How listeners, channel prefixes and routes pick a surface |
| [Surface reference](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/reference/surfaces/surface-reference/) | The fields of a surface document |
| [Access Point](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/reference/surfaces/access-point/) | The Access Point: listen address, route and protocol |
| [Networking elements](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/reference/surfaces/networking/) | `target.networking`: timeouts, retry and circuit breaker |
| [Variants](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/reference/surfaces/variants/) | Surface Variants and the default variant |
| [Transit Points](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/reference/surfaces/transit-points/) | Transit Points for outbound calls from a managed agent |
| [Target](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/reference/surfaces/target/) | The Target element: the upstream a surface forwards to |
| [Managed Agent](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/reference/surfaces/managed-agent/) | The Managed Agent element and the identity presentation it sends to the target |
| [Outbound binding elements](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/reference/surfaces/outbound-binding/) | The Credential Delegation and Workload Binding elements |
| [MCP Tool Gating element](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/reference/surfaces/mcp-tool-gating/) | Allowing or hiding MCP tools on a surface |
| [Trust elements](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/reference/surfaces/trust-element/) | The Trust Check and Trust Recorder elements |
| [Protocol extension elements](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/reference/surfaces/protocol-extensions/) | Extension Validation and Extension Rules on A2A surfaces |
| [Metadata elements](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/reference/surfaces/metadata/) | Injecting and extracting custom metadata |

### Caller identity and access

| Page | Read it for |
| --- | --- |
| [Agent identity and DIDs](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/concepts/identity/) | How the gateway models identity |
| [Caller context binding](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/concepts/caller-context-binding/) | Binding the caller's context to a request |
| [Caller Context element](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/reference/surfaces/caller-context/) | The `caller_context` settings on a surface ([KI-01](known-issues.md)) |
| [Workload binding](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/concepts/workload-binding/) | Passing caller context to the upstream in a signed presentation |
| [API keys](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/reference/authentication/api-keys/) | Surface API keys: create, rotate, revoke |
| [JWT Verification Strategies](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/reference/authentication/jwt-verification-strategies/) | How a caller's JWT is verified |
| [Restrict surface access with API key authentication](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/how-to-guides/access/restrict-surface-access-with-api-key/) | Requiring an API key on a surface |
| [Limit surface access by agent identity](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/how-to-guides/access/limit-surface-access-by-agent-identity/) | Allowing only callers with a given agent identity |
| [Validate bearer tokens on a surface](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/how-to-guides/access/validate-bearer-tokens-on-a-surface/) | Requiring a JWT from the caller's identity provider |
| [Identity element](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/reference/surfaces/identity/) | Identity slots and how each one derives an agent DID |
| [Token exchange and ID-JAG](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/concepts/token-exchange/) | Exchanging a token at the gateway's STS, and ID-JAG grants |
| [STS Clients](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/reference/authentication/sts-clients/) | STS client fields: audiences, scopes, subject token types, ID-JAG and impersonation |

### Policies

| Page | Read it for |
| --- | --- |
| [OPA policies](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/concepts/opa-policies/) | Where OPA policies apply and how they decide |
| [OPA policies reference](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/reference/surfaces/opa-policies/) | Policy definitions, packages and the policy input |
| [Per-tool policy bindings](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/reference/surfaces/mcp-proxy-tool-policies/) | Per-tool policies on MCP surfaces |
| [Apply OPA policies to your gateway and surfaces](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/how-to-guides/policies/apply-opa-policies/) | Attaching gateway and surface policies |
| [Apply policy to outbound calls](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/how-to-guides/policies/apply-policy-to-outbound-calls/) | Policies on a managed agent's outbound calls |
| [Control MCP tool access with per-tool policies](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/how-to-guides/policies/control-mcp-tool-access-with-per-tool-policies/) | The how-to for per-tool MCP policies |
| [Use JWT claims to control access to a surface](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/how-to-guides/policies/use-jwt-claims-to-control-access-to-a-surface/) | Policies on the claims of a caller's JWT |

### Credentials and secrets

| Page | Read it for |
| --- | --- |
| [Credentials](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/concepts/credentials/) | Target credentials, credential providers and delegation |
| [Secrets concepts](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/concepts/secrets/) | How the gateway stores and uses secrets |
| [Secrets reference](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/reference/authentication/secrets/) | Secret fields and secret references |
| [Configure per-caller Credential Delegation](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/how-to-guides/setup/configure-per-caller-credential-delegation/) | Setting up per-user OAuth delegation |

### Protocols and payments

| Page | Read it for |
| --- | --- |
| [MCP protocol](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/concepts/protocols/mcp/) | MCP surfaces |
| [A2A protocol](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/concepts/protocols/a2a/) | A2A surfaces and agent cards |
| [AP2 protocol](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/concepts/protocols/ap2/) | AP2 surfaces |
| [MPP (Machine Payments Protocol)](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/concepts/protocols/mpp/) | MPP payments |
| [x402 payment protocol](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/concepts/protocols/x402/) | x402 payments |
| [Payments concepts](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/concepts/payments/) | How the gateway verifies and settles x402 and MPP payments |
| [Payments](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/reference/payments/payments/) | x402 and MPP payments |
| [Payment element](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/reference/surfaces/payment/) | The payment settings on a surface |

### Proxies

| Page | Read it for |
| --- | --- |
| [MCP Proxy](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/reference/proxies/mcp-proxy/) | MCP proxies built from an OpenAPI spec |
| [Expose a REST API as MCP tools](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/how-to-guides/setup/expose-a-rest-api-as-mcp-tools/) | The how-to for an MCP proxy |
| [A2A Proxy](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/reference/proxies/a2a-proxy/) | A2A proxies and their backends |
| [Enable A2A communication with a Copilot Studio agent](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/how-to-guides/setup/enable-a2a-communication-with-a-copilot-studio-agent/) | Fronting a Copilot Studio agent over A2A |

### Gateway to gateway

| Page | Read it for |
| --- | --- |
| [Gateways](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/concepts/connections/gateways/) | Connections between gateways |
| [Connect two gateways](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/how-to-guides/connections/connect-gateways/) | The handshake between two gateways |
| [Configure GW-to-GW authentication and routing](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/how-to-guides/connections/g2g-authentication-and-routing/) | Authenticating and routing `fabric://` calls |
| [Agent validation via Trust Registry](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/how-to-guides/connections/agent-validation-via-trust-registry/) | Checking agents against a trust registry |
| [Connection point](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/reference/gateways/connection-point/) | Connection point fields |
| [Gateway reference](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/reference/gateways/gateway/) | Remote gateway records |
| [Mediator](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/reference/gateways/mediator/) | DIDComm mediator records |
| [Trust registries](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/concepts/connections/trust-registry/) | Issuers, trust registries over DIDComm, and Trust Checks |
| [Trust registry reference](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/reference/trust-registries/trust-registry/) | Trust registry record fields |
| [Issuer reference](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/reference/trust-registries/issuer/) | Issuer record fields |

### Operations and observability

| Page | Read it for |
| --- | --- |
| [Settings](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/reference/configuration/settings/) | Gateway-wide settings, including VP Auditing and feature flags |
| [Audit log](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/concepts/audit-log/) | What the audit log records |
| [Observability](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/concepts/observability/) | Observing a running gateway |
| [Metrics reference](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/reference/observability/metrics/) | Gateway metrics and their export |
| [Tasks](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/reference/observability/tasks/) | Runtime status of listeners, connection points and MCP proxies |
| [Integrations reference](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/reference/configuration/integrations/) | Email, Slack, webhook and stream integration fields |
| [Set up event notifications](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/how-to-guides/connections/set-up-event-notifications/) | Sending gateway events to an integration |
| [Echo server](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/reference/configuration/echo-server/) | A local test upstream that prints what the gateway forwards to it |

## Gateway repository documents

The gateway's source repository, [affinidi-ai/agent-gateway](https://github.com/affinidi-ai/agent-gateway), keeps
documents that describe its source exactly, limitations included. They follow its `main` branch, which can be
newer than the version this skill describes. Read one for implementation detail the docs pages above do not give.

| Document | Read it for |
| --- | --- |
| [Capabilities](https://github.com/affinidi-ai/agent-gateway/blob/main/docs/CAPABILITIES.md) | What the gateway can do, in detail |
| [Architecture](https://github.com/affinidi-ai/agent-gateway/blob/main/ARCHITECTURE.md) | How the gateway is built, and the module map: where in `src/` each part lives |
| [Build from source](https://github.com/affinidi-ai/agent-gateway/blob/main/docs/development/GETTING_STARTED.md) | Building and running a gateway locally, such as a disposable one for testing |
| [Configuration files](https://github.com/affinidi-ai/agent-gateway/blob/main/docs/CONFIGURATION_REFERENCE.md) | What each configuration file controls and the effect of its fields |
| [Configuration reload](https://github.com/affinidi-ai/agent-gateway/blob/main/docs/CONFIGURATION_RELOAD.md) | Reloads, the listener lifecycle, server mode and the `[a2a]` settings |
| [Example configuration](https://github.com/affinidi-ai/agent-gateway/blob/main/config/examples/README.md) | The example configuration files and what each one maps to |
| [Source auth and managed identity](https://github.com/affinidi-ai/agent-gateway/blob/main/docs/SOURCE_AUTH.md) | Caller authentication methods, agent DID derivation and the Trust Recorder |
| [Policy planes and egress](https://github.com/affinidi-ai/agent-gateway/blob/main/docs/POLICY.md) | OPA packages, policy versions, appliance-wide enforcement and egress controls |
| [Protocol behaviour](https://github.com/affinidi-ai/agent-gateway/blob/main/docs/PROTOCOLS.md) | The protocol revisions the gateway serves, what it validates, and its limitations |
| [MCP tool gating](https://github.com/affinidi-ai/agent-gateway/blob/main/docs/MCP_TOOL_GATING.md) | MCP metadata handling and the tool-gating firewall |
| [MCP metadata](https://github.com/affinidi-ai/agent-gateway/blob/main/docs/MCP_METADATA.md) | MCP metadata keys, MCP `2026-07-28` admission and `mcp_http` |
| [Credential delegation](https://github.com/affinidi-ai/agent-gateway/blob/main/docs/CREDENTIAL_DELEGATION.md) | Credential providers, bindings, consent modes, the OAuth flow and the delegation vault |
| [Security Token Service](https://github.com/affinidi-ai/agent-gateway/blob/main/docs/STS.md) | Token exchange, ID-JAG issuance and redemption, and their checks |
| [Fabric internals](https://github.com/affinidi-ai/agent-gateway/blob/main/docs/FABRIC.md) | Gateway-to-gateway listeners, the receive pipeline and peer issuer DIDs |
| [Integrations](https://github.com/affinidi-ai/agent-gateway/blob/main/docs/INTEGRATIONS.md) | Integration senders, the event catalogue, triggers and template variables |
| [Observability internals](https://github.com/affinidi-ai/agent-gateway/blob/main/docs/OBSERVABILITY.md) | Dashboard events, request correlation and audit forwarding |
| [Management RBAC](https://github.com/affinidi-ai/agent-gateway/blob/main/docs/RBAC.md) | How the management API enforces roles and permissions |
| [Management access tokens](https://github.com/affinidi-ai/agent-gateway/blob/main/docs/ACCESS_TOKENS.md) | Personal access tokens, their resource patterns and tenant ownership |
| [Terms and consent](https://github.com/affinidi-ai/agent-gateway/blob/main/docs/TERMS_AND_CONSENT.md) | Terms of Use documents, who must accept them, and acceptance records |
| [Onboarding capture](https://github.com/affinidi-ai/agent-gateway/blob/main/docs/AGENT_ONBOARDING_CAPTURE.md) | The temporary capture endpoint behind the dashboard's surface onboarding |
