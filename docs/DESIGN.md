# Design

What this repository is, the decisions behind it, and how its claims stay true.

## What it is

An agent skill for operating an Affinidi Agent Gateway. An agent that loads it can explain how a
gateway works and can also change one, because the skill is written around `fabric`, the gateway's
command-line client: it creates, inspects, updates and debugs surfaces, policies, proxies, secrets,
credential providers, identities and gateway-to-gateway connections instead of describing dashboard
clicks.

## Decisions

| Question | Decision | Why |
| --- | --- | --- |
| Where it lives | Its own repository | It changes independently of the gateway and installs as a plugin. The Agent Gateway source repository's own agent instructions, its `AGENTS.md`, are for people editing gateway code, a different audience. |
| Who it is for | Anyone operating a gateway through an agent: customers and Affinidi engineers alike | The CLI is operator tooling. Gateway internals appear only where they explain behaviour an operator sees. |
| Distribution | A public GitHub repository that is both a plugin marketplace and an Agent Skills directory | The same tree installs as a plugin and as a plain Agent Skills directory. |
| Packaging | The marketplace entry's plugin `source` is `"./"`, the repository root, and the skill is `skills/affinidi-agent-gateway/` | The layout of anthropics/skills and obra/superpowers. The skill folder holds only what the user's agent needs, nothing in it links outside it, and maintainer files stay at the root. |
| Relation to third-party skills | Independent | Nothing is copied from other skills. No check compares its coverage with a third-party skill's. |
| Runtime truth | `SKILL.md` opens with a version check (`fabric --version`, the gateway's `/v1/version`) against its one "Reviewed against" line, and `fabric agent-gateway <command> --help` before any flag it names | When the live system and the skill disagree, the live system wins, then gateway source, then the docs. `references/sources.md` lists the docs pages and when to read one live. |
| Generated command reference | `references/commands.md` stays, next to the rule to check `fabric agent-gateway <command> --help` before using a command, which wins when the two differ | No eval run has compared agents with and without it: a sandboxed run needs a credential other than a login ([evals/README.md](../evals/README.md#run)), and none has been done. |
| Page owners | The drift matrix has no owner field | The repository's owners own every page. A per-page owner would need team names that nothing here defines, and an invented one would mislead. |
| Evidence | A `Sources:` line on each reference page, `.github/skill-drift-matrix.json`, the `fabric` command snapshot (`.github/fabric-cli-snapshot.json`) and the live e2e cases. Settled answers and known issues name the upstream file and function, never a line; a security row marked `withheld` names neither until the gateway publishes an advisory | Page-level sources say what to re-read when upstream changes and stay valid when code moves within a file. Citations by line would break whenever code moved, whether or not behaviour changed. |
| Validation | The standard validators in CI (`claude plugin validate`, the shared plugin validator action, `gh skill publish --dry-run`); `scripts/validate.py` keeps only the checks they lack | See [Staying true](#staying-true). |
| Staying current | By runbook: [upstream-sync.md](upstream-sync.md), run by hand or by any agent. Who starts a run when [upstream-sync.md](upstream-sync.md#when-to-run-it)'s conditions hold, and whether a scheduled job does, is still to be decided | A scheduled job would also need clones of the Agent Gateway and `fabric` CLI sources, a `fabric` binary built from the CLI's new ref and a disposable gateway for the end-to-end step. |

## Format

- [Agent Skills specification](https://agentskills.io/specification), read 2026-10-19: `name` is
  lowercase letters, digits and single hyphens, at most 64 characters, equal to the directory name;
  `description` is 1 to 1024 characters and says what the skill does and when to use it;
  `SKILL.md` stays under 500 lines; references are one level deep from `SKILL.md`.
- Claude Code plugin: `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json`, whose one entry
  has the repository root (`./`) as its source. From the plugins reference, read 2026-10-19: the plugin
  `name` is kebab-case, and skills are discovered at `skills/<name>/SKILL.md` under the plugin root. The
  reference makes `version` and `description` optional. This repository sets `description`, `homepage`,
  `repository` and `version`, and the same `version` on the plugin's marketplace entry: it is the release
  ([CONTRIBUTING.md, "Releases"](../CONTRIBUTING.md#releases)). From the plugin loading reference, read
  2026-10-19, a manifest that sets `version` keeps users on that version until it changes, so a change
  reaches users only in a new release. `homepage` must parse as a URL or the plugin fails to load.
  `claude plugin validate --strict` checks both manifests and fails on any warning.
- Because the plugin root is the repository root, anything at a default component location there
  would load for every plugin user. The plugin reference, read 2026-10-19, lists `commands/`,
  `agents/`, `hooks/hooks.json`, `.mcp.json`, `.lsp.json`, `output-styles/`, `workflows/`, `themes/`,
  `monitors/monitors.json`, `bin/` and `settings.json`. Copilot CLI's plugin reference, read 2026-10-19,
  adds `hooks.json`, `.github/mcp.json`, `lsp.json`, `.github/lsp.json` and `lsp-config/servers.json` for a
  plugin with a `.claude-plugin/` manifest such as this one, and `mcp.json` and `com.github.copilot/` for an
  Agent Plugins one. Keep the root free of all of them.
- GitHub Copilot CLI reads the same two manifests. Its plugin reference, read 2026-10-19, looks
  for a plugin manifest at `<root>/.plugin/plugin.json`, `<root>/plugin.json`,
  `<root>/.github/plugin/plugin.json` and then `.claude-plugin/plugin.json`. It looks for a
  marketplace at `<root>/marketplace.json`, `<root>/.plugin/marketplace.json`,
  `<root>/.github/plugin/marketplace.json` and then `.claude-plugin/marketplace.json`. The repository
  has no manifest at the earlier paths. Claude Code does not read them, and a second copy would have
  to be kept in sync with the first. A manifest at an earlier path would also take precedence over
  `.claude-plugin/` in Copilot CLI and VS Code. Copilot's documented skill frontmatter is `name`,
  `description`, `license` and `allowed-tools`. The skill sets no `allowed-tools`, so it pre-approves no tool.
  Copilot CLI 1.0.98 loads this skill with `compatibility` and `metadata` present too, which
  was observed with `copilot skill list`.
- Maintainer instructions are in `AGENTS.md`, and `.claude/CLAUDE.md` imports it for Claude Code.
  A `CLAUDE.md` at the plugin root is not loaded by an installed plugin, and
  `claude plugin validate --strict` fails on one.

## Sources of truth

In order of authority; every statement rests on at least one:

1. **Observed**: behaviour seen on a running gateway built from the baseline commit. When written
   guidance and a running gateway disagree, the gateway wins.
2. **Source**: the Agent Gateway source code and the `fabric` CLI source at their baseline commits, cited
   by file, and by function or type where there is one.
3. **Docs**: the official documentation at docs.affinidi.com, cited by URL.

Where two sources disagree, the skill follows the higher one and, where a reader could meet the
other, says so. The versions and the commit the skill was reviewed against are recorded once, in the
matrix's `baseline`, and repeated for users only in `SKILL.md`'s metadata (the gateway commit as
`metadata.gateway_commit`), its "Reviewed against" line and the generated header of `references/commands.md`;
everywhere else under `skills/` says "the reviewed version".

## Staying true

A check fails only when something a reader relies on is broken: a command that does not exist, a
link that is gone, content that must not be published, a recipe
that fails on a live gateway. It never fails because code moved or a page was reworded. Checks that
need a gateway, the `fabric` binary or another repository's content stay out of CI, so a change here
is judged only on this repository. The tooling stays this size: prefer content to code, and add a
check only when its failure would mean a reader is misled.

- `make ci` is what CI's `check` job runs (`.github/workflows/check.yml`, on Python 3.9 and 3.13). It runs
  `scripts/validate.py` and the unit tests, with no network. `validate.py` keeps only the checks the
  standard validators lack: the skill's size, links and heading anchors, no link out of the skill,
  the drift matrix's pages against the shipped pages, banned content, maintainer
  material and reviewed-version literals in the skill, every `fabric ...` invocation in the skill's shell blocks and inline code against
  the recorded snapshot (`.github/fabric-cli-snapshot.json`), and that the command reference is the
  generator's unedited output.
- CI's `plugin-validate` job runs the standard validators: the marketplace checks of the shared plugin
  validator from claude-plugins-community, which claude-plugins-official also runs, from a checkout pinned
  by commit; `claude plugin validate --strict` on the marketplace, the plugin manifest and `skills/`, with
  the CLI at a pinned version; and `gh skill publish --dry-run` for the Agent Skills name rules.
- `make check` is `make ci` plus `make cli-check FABRIC=...`, which regenerates the command
  reference from the `fabric` binary (`scripts/gen-cli-reference.py`) and fails when the checked-in
  copy does not match. It fails, never skips, when the binary is missing.
- Gateway source and docs are not checked automatically. `.github/skill-drift-matrix.json` names, per
  page, the source paths and docs pages to re-read when upstream changes, and
  `scripts/drift-report.sh` lists the pages whose paths changed between the baseline and a new ref.
  It is a report, never a gate. The comparison is one diff from the baseline to the new ref that
  [upstream-sync.md](upstream-sync.md#when-to-run-it) picks, never commit by commit: most commits touch the files many pages rely on, so a per-commit diff would flag most
  pages every time. [upstream-sync.md](upstream-sync.md) is the procedure that acts on the report.
- `make e2e` needs a live gateway (`FABRIC_E2E_HOST`, `FABRIC_E2E_TOKEN`, and `FABRIC` or `fabric` on `PATH`) and never runs
  in CI. It runs the skill's own marked code blocks, in document order, in a sandbox with its own
  HOME and `fabric` config, and prints every `# priority: P2` case it leaves out. Each run has one
  throwaway keychain on macOS and no reachable D-Bus session bus, and compares the real keychain
  state before and after. Before a case runs, a grep refuses it when its case file, blocks or
  `e2e-file` files name a call that could reach a keychain or start fabric's interactive shell; at run
  time `fabric` on `PATH` and `$FABRIC` are a short wrapper that refuses such calls
  ([CONTRIBUTING.md](../CONTRIBUTING.md#the-keychain-guard) lists both). The wrapper is one layer: a call to the real binary by its
  path skips it, and the other layers still hold. The token reaches the CLI as an environment
  override, so it never opens a keychain. Output is redacted before it is printed.
  [CONTRIBUTING.md](../CONTRIBUTING.md#end-to-end-cases) has the details.
- `make all` is `make check` plus `make e2e`.
- `evals/` holds `claude plugin eval` cases. They cost tokens and need a model, so they never run in CI
  and are advisory.
