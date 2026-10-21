# Contributing

When contributing to this repository, please first discuss the change you wish to make by creating
a new [GitHub issue](https://github.com/affinidi-ai/agent-gateway-skills/issues/new).

The skill is only useful if what it says is true of a real gateway. Everything below exists to keep
it that way, and `make ci` enforces what [Checks](#checks) says it checks; the rest is checked by hand.

## Your first change

1. Clone the repository and run `make ci` once, so you know the checks pass before you start.
2. Find every file that states the fact you are changing (`git grep` helps), including the eval graders under
   `evals/` that restate it, and fix each one.
3. Back the new statement with evidence ([Evidence](#evidence)), and keep the page's `Sources:` line and its
   entry in `.github/skill-drift-matrix.json` in step.
4. If you changed a recipe, run its end-to-end case against a disposable gateway
   ([End-to-end cases](#end-to-end-cases)), or say in the pull request that you could not.
5. Run `make ci` again and commit ([Commits](#commits)).

## Evidence

Every behavioural statement in the skill (what a command does, what the gateway answers, what a
field means, what a default is) rests on at least one of:

- **Source**: the Agent Gateway source code and the `fabric` CLI source at the commits in
  `.github/skill-drift-matrix.json`.
- **Docs**: a page under `https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/`.
- **Observed**: behaviour seen on a running gateway built from the baseline commit, such as an end-to-end case in
  `tests/e2e/cases/` that passed, a known issue's Detect step that showed the symptom, or a run by hand that the
  page describes.

If you cannot check a statement against the source, back it with Docs or Observed evidence and say so in
the pull request; a maintainer checks it against source.

When they disagree, Observed beats Source and Source beats Docs. Write the skill to match the winner,
and where a reader could meet the other version, say which one the skill follows and why.

Record the evidence where a reader can check it:

- The settled answers in `SKILL.md` and every row of `references/known-issues.md` name the upstream
  file, and the function or type where there is one. No line numbers: they move.
- Each reference page except the generated `commands.md` and the docs index `sources.md` ends with a
  one-line `Sources:` paragraph: the docs pages it was checked against, then at most about six gateway
  source files.
- `.github/skill-drift-matrix.json` lists, per page, every gateway source path and docs URL the page
  relies on. Update a page's entry in the same change that makes it rely on something new.
  `make validate` fails when a page the skill ships has no entry and when an entry names no shipped
  page. Whether a page's `Sources:` line agrees with its entry is checked by hand.

## Checks

Requirements: Python 3.9 or later (standard library only), `git`, `make`, `bash` and `jq`. The
standard validators need `claude` and `gh`, and the end-to-end cases also need `curl`, a `fabric`
binary and a gateway.

```sh
make help                                    # list the targets
make ci                                      # what CI's check job runs
make check FABRIC=path/to/fabric             # ci, plus the command reference against the binary
```

What each part checks:

- **Sources.** Each reference page except `commands.md` and `sources.md` ends with a `Sources:` line, and the settled answers and known
  issues name the file and function they rest on. `.github/skill-drift-matrix.json` lists every source
  path and docs page each page relies on, so an upstream change points at the pages to re-read. Its
  `baseline` records the reviewed Agent Gateway commit, the gateway and `fabric` versions and the day
  the docs were read; `SKILL.md`'s metadata and its "Reviewed against" line carry the same versions for
  users, and `metadata.gateway_commit` the first 12 characters of the gateway commit.
- **Commands.** `.github/fabric-cli-snapshot.json` and `references/commands.md` are generated from the
  `fabric` binary. `make validate` checks every `fabric ...` invocation in the skill's shell blocks and inline code,
  with its options, against that snapshot, so a renamed command or flag there fails the checks; an option
  named in prose or a call through `$FABRIC` is not checked.
- **Recipes.** The skill's worked examples carry `e2e` markers, apart from those in `references/g2g.md`, the
  listener-change and backup-and-restore recipes in `references/operations.md`, and the live part of the
  Copilot Studio recipe in `references/proxies.md`, which needs a published Copilot Studio agent. `make e2e` runs
  them against a live gateway ([End-to-end cases](#end-to-end-cases)).
- **Triggering and task quality.** `evals/` holds `claude plugin eval` cases: task prompts, requests
  that should load the skill and near-misses that should not ([evals/README.md](evals/README.md)).
  They are advisory and never run in CI.

CI (`.github/workflows/check.yml`) runs on Ubuntu 24.04, the newest runner image with Python 3.9 builds. It runs
`make ci` on Python 3.9 and 3.13, and the standard validators: the marketplace checks of the shared
validate-plugins action from `anthropics/claude-plugins-community`, run as its scripts at a pinned commit;
`claude plugin validate --strict` on the marketplace, the plugin manifest and the skill, which fails on any
error or warning; and `gh skill publish --dry-run`. The command-reference check
and the end-to-end cases need a `fabric` binary or a live gateway, so they run outside CI with `make check` and
`make e2e`.

### Make targets

| Target | What it does | Needs |
| --- | --- | --- |
| `make help` | Lists the targets | |
| `make validate` | Offline checks the standard validators lack: size, links, anchors, links out of the skill, the drift matrix against the shipped pages, banned content, maintainer material and reviewed-version literals in the skill, `fabric` commands, generated files | |
| `make unit` | Unit tests for every script and the e2e runner | |
| `make ci` | `validate` and `unit`; what CI's `check` job runs | |
| `make cli-reference` | Regenerates `.github/fabric-cli-snapshot.json` and `references/commands.md` | `FABRIC`, or `fabric` on PATH |
| `make cli-check` | Fails when the generated files differ from what the binary prints | `FABRIC` |
| `make e2e` | Runs every case with blocks under `skills/` and a case file, except `# priority: P2` ones, against a live gateway (`E2E_PRIORITY=all` for all) | `FABRIC_E2E_HOST`, `FABRIC_E2E_TOKEN`, and `FABRIC` or `fabric` on PATH |
| `make check` | `ci` and `cli-check` | `FABRIC` |
| `make all` | `check` and `e2e` | As above |

In any Markdown table row, `make validate` reads `\|` inside inline code as `|` when it checks
`fabric` commands, so write a pipe in a table's code that way.

`PYTHON` selects the interpreter (default `python3`). A missing input is an error, never a skip.
Pass the e2e token through the environment rather than on the `make` command line.

Never edit `references/commands.md` or `.github/fabric-cli-snapshot.json` by hand; `make validate` fails when the
reference is not the generator's output.

## Layout

| Path | What it is |
| --- | --- |
| `skills/affinidi-agent-gateway/SKILL.md` | The skill: version check, safety rules, change contract, request lifecycle, triage table, quickstart, settled answers |
| `skills/affinidi-agent-gateway/references/` | Reference pages, one level deep, loaded when a task needs them; `commands.md` is generated and `sources.md` lists the docs pages |
| `.claude-plugin/` | Plugin and marketplace manifests |
| `.github/skill-drift-matrix.json` | The reviewed baseline, and the source paths and docs pages each skill page relies on |
| `.github/fabric-cli-snapshot.json` | The `fabric` command tree, generated from the binary |
| `.github/workflows/check.yml` | CI: `make ci` and the standard validators |
| `evals/` | `claude plugin eval` cases for triggering and task quality |
| `scripts/validate.py` | Offline checks over the whole repository |
| `scripts/gen-cli-reference.py` | Generates the command snapshot and `references/commands.md` from the `fabric` binary |
| `scripts/drift-report.sh` | Lists, per page, the upstream source files that changed since the baseline |
| `tests/unit/` | Unit tests for every script and for the end-to-end runner |
| `tests/e2e/` | The literate end-to-end runner (`run.sh`, `lib.sh`, `extract.py`, `redact.py`), its test upstreams (`targets.py`), its cases and fixtures |
| `docs/DESIGN.md` | Decisions, sources of truth and how the skill stays true |
| `docs/upstream-sync.md` | How the skill is brought up to date when the gateway or `fabric` changes |
| `AGENTS.md` | Instructions for coding agents working in this repository; `.claude/CLAUDE.md` imports it for Claude Code |

## End-to-end cases

The skill's worked examples are the tests. A marker on the line directly before a fenced code block
in the skill's Markdown puts that block into a case:

```markdown
<!-- e2e: surface-basics -->
<!-- e2e: surface-basics expect-fail -->
<!-- e2e-file: surface-basics surface.json -->
```

The first appends the block to the case's script. The second does the same for a block that
demonstrates an error: the block must exit non-zero. The third writes the block's content to a file
in the case's work directory, for JSON payloads and Rego policies that the recipe then passes with
`--file`. Script blocks are `bash`, `sh`, `shell` or untagged, and have no `$ ` prompts. All of a
case's blocks are in one Markdown file, and they run in document order.

### A gateway to run against

Use a gateway you can throw away, built from the baseline commit of
[affinidi-ai/agent-gateway](https://github.com/affinidi-ai/agent-gateway). Its local environment, which its
`docs/development/GETTING_STARTED.md` sets up, is the usual one; on macOS that setup adds its self-signed
certificate to the System keychain with `sudo`. The first account you register there is the gateway's
administrator.

`FABRIC_E2E_TOKEN` is an administrator personal access token for that gateway: sign in as the
administrator with `fabric agent-gateway login`, which opens a browser, then create the token with
`fabric agent-gateway tokens create --name e2e --full-role --expires-at <a few hours ahead>` (the cases need
your whole role, and without `--expires-at` the token lasts 90 days). Keep it in a file and read it into the
environment when you run `make e2e`; an unattended run needs a token made this way in advance. Cases create,
change and delete surfaces, policies and secrets, and every `pat-scope` run leaves two revoked tokens behind,
because the API cannot delete a token.

Set `FABRIC_E2E_HOST` to one of the gateway's own listen addresses, spelled exactly as
`fabric agent-gateway runtime show surface-routing` lists it in `available_listen_addresses`: a surface
created on `http://localhost:8080` is not reached through `http://127.0.0.1:8080`.

A case that starts a target with `--lan` needs this machine to reach its own LAN address. Where it
cannot, the case is reported `REFUSED`, not `FAIL`, and its recipe stays untested. The test servers
approve every request, and the `idp` server issues a token to any client, so run `--lan` cases only on a
network you trust. Each run picks a random secret that the test servers ask for before they return or
clear the requests they recorded, and the servers start without `FABRIC_TOKEN`.

The delegation cases can run on loopback instead, against a gateway configured for testing to accept exact
loopback URLs as OAuth endpoints; without that configuration, leave `E2E_LOOPBACK_TARGETS` unset so `--lan`
uses the LAN address. Set `E2E_LOOPBACK_TARGETS` to comma-separated `KIND:PORT`
entries, such as `idp:18101`: `start_target KIND --lan` then listens on `127.0.0.1` on the next port
listed for that kind and exports `LAN_HOST=127.0.0.1`. The gateway must accept
`http://127.0.0.1:PORT/authorize` and `http://127.0.0.1:PORT/token` for each `idp` port, and the
callback URL `http://127.0.0.1:<gateway port><oauth_callback_route>/e2e-idp-<run id>`, so set
`E2E_RUN_ID` to the run ID that URL names. When a case's cleanup fails, its provider stays behind
and the next run with the same run ID cannot create it. List only kinds the gateway accepts on
loopback: an MCP proxy's `base_url` never is, so `mcp-proxy-rest` still needs the LAN address.

### Case files

Each case also has a file `tests/e2e/cases/<name>.sh`, named after the case and sourced after
`tests/e2e/lib.sh`, which may define:

- `setup`: runs before the blocks.
- `verify`: runs after every block succeeded. Use `expect_block N REGEX`,
  `expect_fail_block N REGEX` and `expect_json N EXPR [WHAT]`, plus `pass` and `fail`. EXPR is a
  Python expression limited to the grammar in `tests/e2e/expr.py`.
- `cleanup`: always runs, even after a failure, and must remove everything the case created.

It may have:

- `E2E_SERIAL=1`, for a case that changes appliance-wide settings. The runner saves
  `fabric agent-gateway settings show -o json` before `setup` and fails the case when any top-level setting
  differs after `cleanup`, naming the settings that differ.
- `# priority: P2`, for a case that needs more than the usual rig. `make e2e` leaves it out and
  prints `EXCLUDED <name>` and the reason for each case left out; `E2E_PRIORITY=all` includes
  them, and a case named on the command line (`tests/e2e/run.sh NAME...`) always runs.

Blocks run with `bash -euo pipefail` in the case's work directory, one at a time, with standard
input from `/dev/null`, the saved connection `e2e`, `GATEWAY` set to the gateway URL and the
administrator token in `FABRIC_TOKEN`. Every block is its own process, so `setup` must `export`
anything a block reads. Case files and blocks also have:

| Helper | What it does |
| --- | --- |
| `fab ARGS...` | Runs `fabric` through the sandbox wrapper ([The keychain guard](#the-keychain-guard)). Blocks call `fabric` or `$FABRIC`, which is the same wrapper. |
| `unique NAME` | Prints `NAME-$E2E_RUN_ID`. `E2E_RUN_ID` is lowercase letters and digits, random per run unless set. |
| `json_get FILE EXPR` | Prints the Python expression EXPR over the JSON in FILE, with the document as `doc` and the environment as `env`: a string as it is, anything else as JSON. |
| `start_target KIND [VAR] [--lan]` | Starts `tests/e2e/targets.py KIND` (`mcp`, `a2a`, `a2a1`, `idp` or `rest`) on a free port and exports its URL as VAR (default `MCP_URL`, `A2A_URL`, `A2A1_URL`, `IDP_URL` or `REST_URL`). `a2a` is an A2A 0.3 agent; `a2a1` also speaks A2A 1.0. It listens on `127.0.0.1`, or with `--lan` on this machine's non-loopback IPv4 address, exported as `LAN_HOST`; the case is refused when that address does not answer a request from this machine. When `E2E_LOOPBACK_TARGETS` lists KIND, `--lan` listens on `127.0.0.1` on a listed port instead ([A gateway to run against](#a-gateway-to-run-against)). Call it in `setup`; the runner stops the target when the case ends. |
| `target_requests VAR` | Prints the JSON list of requests the target at `$VAR` received. |
| `clear_target VAR` | Forgets the requests the target at `$VAR` received. |

`E2E_CASE`, `E2E_CASE_DIR` (the work directory, where block N's output is `block-N.out`),
`E2E_CASES_DIR` and `PYTHON` are set too.

### The keychain guard

A run never reads or writes an OS keychain other than the one throwaway keychain it creates for
itself. The runner gives every run a fresh work directory with its own `HOME`, `XDG_CONFIG_HOME` and
fabric config holding only the connection `e2e`, and refuses a case when that `HOME` has
`Library/Keychains`. Before the first case:

- On macOS, it checks that `security` under the sandbox `HOME` reports only keychains inside the
  sandbox. It then creates the throwaway keychain there and checks at once that the keychain search
  list and default keychain under your real `HOME` did not change, and only then makes it the
  sandbox's search list and default keychain. After the last case it deletes the keychain and
  compares the real state again; any difference fails the run. The real `HOME` is used for these
  reads only and never reaches a case. When the real state changed, the runner prints the state it
  saved before the run and the `security list-keychains -d user -s ...` and
  `security default-keychain -d user -s ...` commands that put it back. It never runs them.
- On every system, `DBUS_SESSION_BUS_ADDRESS` names a socket that does not exist, `XDG_RUNTIME_DIR`
  is a private directory in the sandbox, and `DISPLAY` and `WAYLAND_DISPLAY` are unset, so fabric's
  keyring on Linux has no Secret Service to reach. Everywhere but macOS, `dbus-send --session` then
  probes the bus twice, with that address and with none (where libdbus looks in
  `$XDG_RUNTIME_DIR` and tries to autolaunch a bus). The run is refused when either probe gets an
  answer, and when there is no `dbus-send` to probe with.

Before any of a case runs, and after `extract.py` writes its blocks and files, the runner greps the
case file, every block and every file an `e2e-file` marker writes for
`\blog(in|out)\b|config[[:space:]]+remove|agent-gateway[[:space:]]+shell\b`, and refuses the case on
a match. Comments and resource names count too, so keep those words out of case files and recipes.

At run time, `fabric` on `PATH`, `$FABRIC` and `fab` are a short wrapper. It refuses a call with an
argument `login` or `logout`, with `remove` after `config`, with `FABRIC_TOKEN` empty, with a `HOME`
or `XDG_CONFIG_HOME` other than the sandbox's, or while the sandbox config holds a `token =` line.
It also refuses `fabric agent-gateway shell`, fabric's interactive shell, which reads commands from
standard input; a call with no subcommand after `agent-gateway` and its global options (`-c`,
`--host`, `--token`, `--allow-http`, `-o` and their values), in case the
binary starts that shell for such a call; and a call with an option it does not know before the
subcommand, or with any option before `agent-gateway` other than `--help` and `--version`. A refused
call exits 3 and is logged, and a case with a logged refusal is reported `REFUSED`, even when the
block that made the call was expected to fail.

The wrapper is one layer, not the whole guard. The real binary's directory stays on `PATH`, because
it usually holds other tools the cases use, such as `jq` and `curl`, so a block that names the real
binary by its path skips the wrapper. The other layers still hold then: the grep above, run before
any of the case; the token passed as `FABRIC_TOKEN`, which fabric uses instead of reading a
keychain; the sandbox `HOME` and `XDG_CONFIG_HOME`; on macOS the throwaway keychain as the only
keychain and the default one under the sandbox `HOME`, and the before and after comparison of the
real state; on Linux the D-Bus session address that reaches no bus; and the check after every block
that the sandbox `HOME` has no `Library/Keychains`.

Everything the runner prints, including the last lines of a failed block, passes through
`tests/e2e/redact.py`, which replaces the administrator token, personal access tokens, JWTs, the
values of `Authorization` headers and headers whose name ends in `-token`, `-key` or `-secret`,
the value after `Bearer` or `Basic`, a UUID after a session key, and the values of JSON members
and `key=value` pairs named `token`, `secret`, `api_key`, `key` or `password` or ending in one of
them after `_` or `-`. Bare UUIDs are resource IDs and are kept. Saved block output is not
rewritten while the case runs, because the checks read it; `E2E_KEEP=1` keeps the work directory
under `.e2e-work/`, redacted in place.

### Fixture cases

Two fixture cases, driven by `tests/e2e/fixtures/`, prove the runner itself:

```sh
E2E_DOCS_ROOT=tests/e2e/fixtures FABRIC=path/to/fabric FABRIC_E2E_HOST=http://localhost:8080 \
    FABRIC_E2E_TOKEN="$(cat path/to/token-file)" tests/e2e/run.sh fixture-sample fixture-login-guard
```

`fixture-sample` must pass, and `fixture-login-guard` must be refused. The unit tests in
`tests/unit/` run the runner, the guard and the redaction against a fake `fabric`, `security` and
`dbus-send`, with no gateway and no keychain.

## Keeping up with upstream

When the gateway or `fabric` changes, follow [docs/upstream-sync.md](docs/upstream-sync.md). It is the
only procedure for moving the baseline in `.github/skill-drift-matrix.json`, and it ends with a pull
request.

## Checking an install

CI validates the manifests and the skill (`.github/workflows/check.yml`, job `plugin-validate`), but
it does not install the plugin. After any change to `.claude-plugin/` or to the skill's frontmatter,
run the same checks and then an install by hand.

On macOS, `claude` looks up its credentials in the keychain when it starts, even for `validate`, and
`gh` can keep its token there. So run every command in this section with a throwaway `HOME` and
configuration directories, never your own:

```sh
sandbox=$(mktemp -d) && mkdir -p "$sandbox/home" "$sandbox/claude" "$sandbox/gh"
HOME="$sandbox/home" security list-keychains -d user   # macOS: lists nothing outside $sandbox
(
  export HOME="$sandbox/home" CLAUDE_CONFIG_DIR="$sandbox/claude" GH_CONFIG_DIR="$sandbox/gh"
  claude plugin validate .                            # the marketplace manifest
  claude plugin validate .claude-plugin/plugin.json   # the plugin manifest
  claude plugin validate skills --strict              # the skill itself
  gh skill publish --dry-run < /dev/null              # the Agent Skills name rules
)
```

The manifest checks pass with no errors and no warnings; CI runs them with `--strict`.

Under a `HOME` with no keychain preferences, `security` finds no keychain, so the lookups find
nothing. `gh skill publish --dry-run` needs no login: without one, its repository lookups find
nothing and only the local checks run.

Then install from a clean clone of the commit into throwaway configuration directories, never your
own. Each agent has an official variable for this: `CLAUDE_CONFIG_DIR` for Claude Code, and
`COPILOT_HOME` with `COPILOT_CACHE_HOME` for Copilot CLI. Give both the sandbox `HOME` too, so that no
command reads your real credentials; a command that needs a keychain gets a throwaway one, as in
[The keychain guard](#the-keychain-guard). Then run:

```sh
claude plugin marketplace add ./clone
claude plugin install affinidi-agent-gateway@affinidi-agent-gateway-skills
claude plugin list --json          # version is the one in plugin.json
copilot plugin marketplace add "$PWD/clone"   # an absolute path: Copilot CLI reads ./clone as a GitHub repository
copilot plugin install affinidi-agent-gateway@affinidi-agent-gateway-skills
copilot skill list --json          # affinidi-agent-gateway, source "plugin", enabled
```

In each installed copy, check that `skills/affinidi-agent-gateway/` holds `SKILL.md` and all of
`references/`. Copilot CLI loads a marketplace added from a local path in place, without copying it.
To test the copy and update path that users get, serve a bare clone in place of the GitHub
repository: in the sandbox's git config, point `url.<bare-clone>.insteadOf` at the repository's
HTTPS URL and at its scp-style SSH URL, each with and without `.git`.
Claude Code may clone over SSH and Copilot CLI clones over HTTPS, so an unmapped form reaches the
real remote. Then
check an update: push a new commit to the clone, and run the update commands from
[README.md](README.md#installation).

## Banned content

`make validate` scans every tracked file, and every untracked file that git does not ignore, and
fails on content that must not be published: absolute paths from someone's machine, test-only
gateway hooks and their token files, internal hostnames, IP addresses other than loopback, the
unspecified address and the documentation ranges, issue tracker keys, real UUIDs, secrets of any
kind (tokens, private keys, cloud access keys, JWTs), email addresses outside the reserved example
domains and other than `security@affinidi.com`, and
authorship or tool attribution: co-author trailers, phrases such as "generated by" or "written
with" an assistant, an assistant's model IDs and its noreply addresses. Naming a vendor or a tool
in prose is fine. The exact patterns and their allow-lists are constants in `scripts/validate.py`;
only that file, its unit test and `tests/unit/fixtures/` may contain samples of them.

Use `localhost`, `gateway.example.com`, the documentation IP ranges, all-zero UUIDs and
`example.com` addresses in examples.

Everything under `skills/` is what users get, so it also must not name this repository's `tests/`
or `scripts/`, or commit IDs. The one exception is `SKILL.md`'s `metadata.gateway_commit`, the reviewed
commit of the public gateway, which `make validate` checks against the matrix. Describe evidence in user
terms, such as "reproduced on a running gateway". The reviewed gateway and fabric versions, and dates in the
review month, appear only in `SKILL.md` metadata, its one "Reviewed against" line and the generated header of
`references/commands.md`; elsewhere, say "the reviewed version". The plugin descriptions carry no
versions either.

## Commits

Conventional Commits subjects (`feat:`, `fix:`, `docs:`, `test:`, `chore:`), at most 72 characters,
with no attribution and no issue tracker keys. Sign every commit. Every change reaches `main` through a
pull request that passes CI and CodeQL, with every review thread resolved, and that two people approve after
its last push, one of them a code owner other than its author; no person pushes to `main` directly.

Only a fix that cannot wait for two reviews goes another way, and only after Affinidi Security is told: Affinidi's
release automation, the one actor allowed past the review rules, pushes it once CI has passed on the commit.

## Releases

The `version` in `.claude-plugin/plugin.json`, and the same value on the plugin's entry in
`.claude-plugin/marketplace.json`, is the release. Claude Code installs and updates the plugin by that
version, so a change reaches its users only in a new version. To release `<version>`:

1. In a pull request, set both to `<version>`, following [Semantic Versioning](https://semver.org/spec/v2.0.0.html):
   a new recipe or rule is a minor version, a correction a patch.
2. After the merge, a maintainer tags the merge commit with a signed tag and pushes it:

   ```sh
   git fetch origin main
   git tag -s v<version> -m v<version> <merge commit>
   git push origin v<version>
   ```

3. Publish a GitHub Release for that tag. `gh skill install` and `gh skill update` take the latest release
   when no version is given, and the default branch only when the repository has no release:

   ```sh
   gh release create v<version> --verify-tag --generate-notes
   ```

## Code of Conduct

### Pledge

In the interest of fostering an open and welcoming environment,
contributors and maintainers pledge to make participation in this project
and its community a harassment-free experience for everyone, regardless of
age, body size, disability, ethnicity, gender identity and expression,
level of experience, nationality, personal appearance, race, religion, or
sexual identity and orientation.

### Standards

Examples of behavior that contributes to creating a positive environment
include:

- Using welcoming and inclusive language.
- Being respectful of differing viewpoints and experiences.
- Gracefully accepting constructive criticism.
- Focusing on what is best for the community.
- Showing empathy towards other community members.
- Avoiding obvious comments about things like code styling and indentation.
  If you see yourself wanting to do that more than once, open an issue to
  update the lint/formatter config to address the concern once and for all.
  **Code reviews should be about logic, not indenting or adding more
  newlines.**

Examples of unacceptable behavior by participants include:

- The use of sexualised language or imagery and unwelcome sexual attention or
  advances.
- Trolling, insulting/derogatory comments, and personal or political attacks.
- Public or private harassment.
- Publishing others' private information, such as a physical or electronic
  address, without explicit permission.
- Other conduct which could reasonably be considered inappropriate in a
  professional setting.
