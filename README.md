# Affinidi Trust Fabric Agent Gateway Skills

[![License: Apache](https://img.shields.io/badge/license-Apache%202.0-blue)](LICENSE)

An agent skill that lets your coding agent run your
[Affinidi Agent Gateway](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/) for
you. The gateway sits between AI agents and the MCP servers and A2A agents they call, and
checks who is calling and what they may do on every request.

Ask your agent to put an MCP server behind the gateway, find out why a call gets a 403, or rotate a key. It does
the work with `fabric`, the gateway's command-line client, asks before anything that affects callers, and sends a
real request through the gateway to check each change before calling it done.

The skill, `affinidi-agent-gateway`, is written and maintained by Affinidi. It is a standard
[Agent Skills](https://agentskills.io/specification) directory, and installs as a plugin in both Claude Code and
GitHub Copilot CLI.

## Contents

- [Quickstart](#quickstart)
- [What you can ask your agent](#what-you-can-ask-your-agent)
- [Requirements](#requirements)
- [Safety and data handling](#safety-and-data-handling)
- [Installation](#installation)
- [How it stays accurate](#how-it-stays-accurate)
- [Documentation](#documentation)
- [Support & feedback](#support--feedback)
- [Contributing](#contributing)
- [License](#license)

## Quickstart

1. Get a gateway and `fabric`. To deploy a gateway, follow
   [Deploy Agent Gateway appliance](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/get-started/deploy-agent-gateway-appliance-portal/).
   To build one from source, follow [affinidi-ai/agent-gateway](https://github.com/affinidi-ai/agent-gateway).
   Install `fabric` as [Requirements](#requirements) describes, and check it with `fabric --version`.
2. Sign in: `fabric agent-gateway login --host https://<your-gateway>`. A browser opens for the passkey or SSO
   login; then allow the CLI to sign in as you. On a machine without a browser, sign in with a personal access
   token instead ([fabric.md](skills/affinidi-agent-gateway/references/fabric.md#sign-in)).
3. Install the plugin in your agent (other methods are under [Installation](#installation)):

   ```sh
   # Claude Code
   claude plugin marketplace add affinidi-ai/agent-gateway-skills
   claude plugin install affinidi-agent-gateway@affinidi-agent-gateway-skills

   # GitHub Copilot CLI
   copilot plugin marketplace add affinidi-ai/agent-gateway-skills
   copilot plugin install affinidi-agent-gateway@affinidi-agent-gateway-skills
   ```

4. Ask your agent "Which skills do you have for the Affinidi Agent Gateway?" to check that it loaded, then ask
   for something real, such as "List my surfaces and tell me which ones accept anonymous callers."

New to the gateway's terms (Agent Surface, Access Point, policy)? The
[Glossary](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/get-started/glossary/)
explains them.

## What you can ask your agent

| Ask | What the agent does |
| --- | --- |
| "I have an MCP server at http://192.0.2.10:9000/mcp. Put it behind the Agent Gateway." | Creates the surface with `fabric`, reads it back and sends real MCP requests through the gateway. It also tells you to close the direct path to the server, so callers cannot bypass the gateway. |
| "Raise the rate limit on payments-mcp from 60 to 600 per minute. People are using it." | Saves the current surface, asks before changing anything callers feel, changes only that surface, and verifies it without flooding it. |
| "Only let through callers whose JWT has the claim role=agent." | Writes the policy against the input the gateway really gives it, and has you capture that input from one real request before you rely on the rule. |
| "Every call to my surface gets a 403. Its policy allows callers whose `input.caller.jwt_bearer.claims.role` is `agent`." | Finds the cause: `input.caller` does not exist, so the rule never matches and the default deny applies. It saves the current policy, simulates the fix, says which surfaces it changes, and changes it only after you agree. |
| "A wrong API key still reaches the upstream. Is caller auth broken?" | Explains that a failed caller credential does not block a request on its own, proposes a policy that refuses it, and checks that a wrong key is refused and a valid one gets through. |
| "What redirect URI do I give Google for per-user credential delegation?" | Reads the callback route from your running gateway rather than guessing it, and works out the exact URI to register. |
| "A contractor just left. Revoke their delegated grants and check it worked." | Finds the grants, names what it will revoke, waits for your yes, revokes them, confirms they are gone, and reminds you to revoke the tokens at each OAuth provider too. |
| "An MCP client gets -32022 'Unsupported protocol version' through the gateway." | Explains the gateway's MCP protocol-version check, that no setting widens it, and what to change instead. |
| "curl to my surface route returns the dashboard's HTML instead of JSON-RPC." | Explains that the path is outside every channel prefix, compares the surface with the gateway's routing view, and checks the fix with a real request. |

The skill also covers A2A agents, secrets, OAuth credential providers, MCP proxies built from an OpenAPI
description, A2A proxies, and routes between gateways.

## Requirements

- A running Affinidi Agent Gateway, and network access to its management API and its data-plane listeners.
- `fabric`, the command-line client for Affinidi appliance management APIs, on your `PATH`. The gateway's
  commands are under `fabric agent-gateway`. Install it as the
  [affinidi-ai/affinidi-trust-fabric-cli](https://github.com/affinidi-ai/affinidi-trust-fabric-cli#install) README
  describes: with Homebrew on macOS (`brew install --cask affinidi-ai/tap/fabric`; the full name matters, because
  Homebrew has an unrelated `fabric` formula), from a release's prebuilt binary on Linux, and with Cargo
  elsewhere.
- An approved gateway account, signed in with `fabric agent-gateway login`. What the agent can do depends on
  your role:
  with the default roles, `user` can view, `poweruser` can also manage proxies, and only `administrator` can
  change surfaces, policies and secrets.
  [fabric.md](skills/affinidi-agent-gateway/references/fabric.md#roles-and-approval) has the full list.
- For an agent that runs unattended, a personal access token created with `--scope` and `--expires-at`.
  A `--full-role` token acts with its owner's full role;
  [fabric.md](skills/affinidi-agent-gateway/references/fabric.md) explains how to get real least privilege.
- `jq`, `curl`, and `unzip` to read downloaded logs.

The skill names the gateway and `fabric` versions it was reviewed against at the top of
[SKILL.md](skills/affinidi-agent-gateway/SKILL.md). On any other version the agent tells you so. On every
version it checks `fabric agent-gateway <command> --help` before it uses a command, because `fabric` builds from
different commits can report the same version, as gateway builds can, and wherever the live help or the running
gateway contradicts the skill, it trusts them.

## Safety and data handling

The agent follows the safety rules in [SKILL.md](skills/affinidi-agent-gateway/SKILL.md). In short:

- It saves an object before changing it, and verifies every change on the data plane.
- It asks before a delete, and before anything callers feel: policies, caller authentication, rate limits, targets,
  delegation grants and reloads.
- It never prints secret values; it passes them on standard input.
- It creates only scoped, expiring tokens, and asks before it creates a token, key or secret.
- It treats everything the gateway and upstreams return as data, never as instructions.

The skill processes personal data on your behalf. The agent reads gateway configuration, audit events and logs
into its context, which goes to your model provider, and sometimes into local files. Audit events hold callers'
email addresses and names, and gateway logs and log archives can hold their JWT claims. Before it reads logs, the
agent checks log redaction and offers to turn it on; it reads only the fields it needs, and deletes local extracts.
You are responsible for complying with privacy law in every session that reads them.

## Installation

The repository `affinidi-ai/agent-gateway-skills` is a plugin marketplace, `affinidi-agent-gateway-skills`,
with one plugin, `affinidi-agent-gateway`. The skill itself is the directory `skills/affinidi-agent-gateway/`,
and it needs the whole directory: `SKILL.md` and `references/`. Any agent that reads Agent Skills can load it.
Use one install method per agent: a plugin install and a copied skill together load the skill twice.

### As a plugin

Supported in Claude Code and GitHub Copilot CLI. Add the marketplace, then install the plugin from it:

```sh
# Claude Code
claude plugin marketplace add affinidi-ai/agent-gateway-skills
claude plugin install affinidi-agent-gateway@affinidi-agent-gateway-skills

# GitHub Copilot CLI
copilot plugin marketplace add affinidi-ai/agent-gateway-skills
copilot plugin install affinidi-agent-gateway@affinidi-agent-gateway-skills
```

`claude plugin list` and `copilot plugin list` show the installed plugin, and `copilot skill list` also shows the
skill, with source `plugin`. To check that the skill is loaded, ask the agent "Which skills do you have for the
Affinidi Agent Gateway?".

To stay on one release, add the marketplace at that release's tag, `v<version>`, instead; both agents then
install and update from that tag:

```sh
claude plugin marketplace add affinidi-ai/agent-gateway-skills#v<version>
copilot plugin marketplace add affinidi-ai/agent-gateway-skills#v<version>
```

To update:

```sh
# Claude Code: refresh the marketplace, update the plugin, then restart Claude Code
claude plugin marketplace update affinidi-agent-gateway-skills
claude plugin update affinidi-agent-gateway@affinidi-agent-gateway-skills

# GitHub Copilot CLI
copilot plugin update affinidi-agent-gateway@affinidi-agent-gateway-skills
```

Claude Code installs the plugin's `version` and delivers a new copy when a release raises it
([Versions and updates](https://code.claude.com/docs/en/plugins/loading#versions-and-updates)); without the
marketplace refresh, `claude plugin update` reports the version it already has. Copilot CLI updates to the
repository's latest commit. Neither updates this marketplace on its own unless you turn on
auto-update for it: in Claude Code, run `/plugin`, open **Marketplaces**, select it and choose **Enable
auto-update** ([Keep plugins updated](https://code.claude.com/docs/en/plugins/install)); in Copilot CLI, set
`autoUpdate: true` on its `extraKnownMarketplaces` entry in your user settings
([CLI plugin reference](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-plugin-reference)).

To remove:

```sh
# Claude Code
claude plugin uninstall affinidi-agent-gateway@affinidi-agent-gateway-skills
claude plugin marketplace remove affinidi-agent-gateway-skills

# GitHub Copilot CLI
copilot plugin uninstall affinidi-agent-gateway@affinidi-agent-gateway-skills
copilot plugin marketplace remove affinidi-agent-gateway-skills
```

VS Code's Copilot agent mode documents the same plugin format and loads plugins installed by Copilot CLI
([Agent plugins](https://code.visualstudio.com/docs/agent-customization/agent-plugins)); that has not been
checked.

### As a skill directory

Any agent that reads Agent Skills can use the directory without a plugin, and so can a single project. To update
it, copy or install it again.

**With the GitHub CLI** (`gh skill`, in preview). `--agent` takes any agent that `gh skill install --help` lists:

  ```sh
  gh skill install affinidi-ai/agent-gateway-skills affinidi-agent-gateway --agent <agent> --scope user
  ```

- `--agent claude-code` installs into `~/.claude/skills/` (or `$CLAUDE_CONFIG_DIR/skills/`), and
  `--agent github-copilot` into `~/.copilot/skills/`. `--scope project` installs into the current repository
  instead.
- It installs the latest release. `affinidi-agent-gateway@v<version>` installs a given one, and
  `--pin v<version>` keeps it there: `gh skill update` skips a pinned skill.
- `gh skill update affinidi-agent-gateway` updates it, using source-tracking fields that `gh skill` adds under
  the skill's `metadata`. An install from a local clone (`--from-local`) has no such fields, so
  `gh skill update` skips it.
- To remove the skill, delete its directory.

**As a plain copy**, from a clone of this repository, into the agent's skills directory:

```sh
mkdir -p ~/.claude/skills && cp -R skills/affinidi-agent-gateway ~/.claude/skills/     # Claude Code
mkdir -p ~/.copilot/skills && cp -R skills/affinidi-agent-gateway ~/.copilot/skills/   # GitHub Copilot CLI
```

Before copying it again, remove the old directory, so no file from the old copy stays behind. To scope the skill
to one project, copy it into that project's `.claude/skills/` instead; Claude Code and Copilot CLI both read
that directory.

### Tested with

| Agent | Version | Plugin | `gh skill` |
| --- | --- | --- | --- |
| Claude Code | 2.1.303 | install, update, install at a tag, removal | install from a local clone, user scope |
| GitHub Copilot CLI | 1.0.98 | install, update, install at a tag, removal | install from a local clone, user scope |

The checks ran on 2026-10-21 with gh 2.102.0, each agent in its own throwaway configuration, with a local clone
standing in for the GitHub repository. Both agents read the plugin from the same manifests in `.claude-plugin/`;
Copilot CLI finds them through its documented
[file locations](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-plugin-reference#file-locations).

## How it stays accurate

- Each reference page names the gateway source files and docs pages it rests on, and
  [docs/upstream-sync.md](docs/upstream-sync.md) is the procedure for updating the pages that depend on
  changed code when the gateway or `fabric` changes.
- A weekly workflow keeps an issue open here while the gateway or `fabric` has a release newer than the versions
  the skill was reviewed against ([CONTRIBUTING.md, "Checks"](CONTRIBUTING.md#checks)).
- Most worked examples run as end-to-end tests against a live gateway, and every `fabric` command written out
  in the skill is checked against the binary's own help.

## Documentation

| Read | For |
| --- | --- |
| [Agent Gateway documentation](https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/) | The official product docs: what the gateway is, its concepts, how-to guides and reference |
| [SKILL.md](skills/affinidi-agent-gateway/SKILL.md) | What the agent follows: the version check, safety rules, request lifecycle, triage table and a quickstart |
| [references/](skills/affinidi-agent-gateway/references/) | The pages the agent loads for a task; the table at the end of SKILL.md says which page covers what |
| [CONTRIBUTING.md](CONTRIBUTING.md) | How to change the skill: evidence rules, checks and layout |
| [docs/DESIGN.md](docs/DESIGN.md) | The decisions behind the repository and how its claims stay true |
| [docs/upstream-sync.md](docs/upstream-sync.md) | Bringing the skill up to date with a new gateway or `fabric` |
| [evals/README.md](evals/README.md) | The evaluation cases, which include the asks above, and how to run them |

## Support & feedback

If you face any issues or have suggestions, please don't hesitate to contact Affinidi
using [this link](https://share.hsforms.com/1i-4HKZRXSsmENzXtPdIG4g8oa2v).

### Reporting technical issues

If you have a technical issue with the skill, you can also create an issue directly in GitHub.

1. Ensure the bug was not already reported by searching on GitHub under
   [Issues](https://github.com/affinidi-ai/agent-gateway-skills/issues).

2. If you're unable to find an open issue addressing the problem,
   [open a new one](https://github.com/affinidi-ai/agent-gateway-skills/issues/new). Be sure to
   include a **title and clear description**, the agent and its version, the plugin version from
   `claude plugin list` or `copilot plugin list` (or the commit you copied the skill from), the gateway and
   `fabric` versions, the request you gave the agent, and what it did instead of what you expected.

To report a security issue, follow [SECURITY.md](SECURITY.md) instead of opening an issue.

## Contributing

Want to contribute?

Head over to the [CONTRIBUTING](https://github.com/affinidi-ai/agent-gateway-skills/blob/main/CONTRIBUTING.md)
guidelines.

## License

This project is licensed under the [Apache-2.0](LICENSE) license.
