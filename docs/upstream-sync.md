# Upstream sync

How the skill is brought up to date when the Affinidi Agent Gateway or `fabric` changes. It is written to be
followed by a person, or by an agent that knows nothing about earlier runs.

The scripts only report. Whoever follows this page decides what changed and edits the skill. CI runs only the
offline checks.

## When to run it

The skill rests on two repositories: the Agent Gateway source
([affinidi-ai/agent-gateway](https://github.com/affinidi-ai/agent-gateway)), and the `fabric` CLI
([affinidi-ai/affinidi-trust-fabric-cli](https://github.com/affinidi-ai/affinidi-trust-fabric-cli)). Both ship
from `main`. Run it when either repository's `main` gets a new release (the `version` in its root `Cargo.toml`
changes), or when `main` moves and the change matters to users. Each new ref is the head of that repository's
`main`, never a feature branch.

Compare each baseline with its new ref in one diff, never commit by commit. Files such as `src/proxy/handler.rs`
and the CLI's `src/commands.rs` change in most commits, so a per-commit diff flags most pages every time.

Stop, and change nothing, when all of these hold:

- the report from step 1 shows every page under `Unchanged:`, and its last list starts with exactly
  `Changed under the gateway's src/ and config/ and the CLI's src/ but in no page's entry, test code left out: 0`;
- it ends with `The CLI snapshot matches.` for a `fabric` binary you built from the new ref in this run;
- the docs comparison in step 4 finds no page that a user needs and `references/sources.md` lacks.

## What you need

Check each of these before you start, and stop with a message that names whatever is missing. Each item says
which steps it gates.

- This repository, with `bash`, `git`, `make`, Python 3.9 or later, `jq` and `curl`, which the scripts and
  checks need.
- A clone of the Agent Gateway source that holds both `baseline.agent_gateway` and the gateway's new ref, and a
  clone of the fabric CLI that holds both `baseline.fabric_cli` and the CLI's new ref. The gateway repository is
  public (`git clone https://github.com/affinidi-ai/agent-gateway.git`); the CLI repository needs access to
  affinidi-ai. Run `git -C <clone> fetch origin main` in each first: the scripts never fetch. Every step needs
  them.
- A `fabric` binary that you built from the CLI's new ref yourself, in this run. `fabric --version` does not
  tell builds apart, because builds from different commits report the same version, so a binary built from any
  other commit makes the report's `The CLI snapshot matches.` meaningless. Build it from a copy of the new ref,
  which leaves the clone as it is, and keep the commit ID for the commit message:

  ```sh
  build=$(mktemp -d)
  git -C <cli clone> archive <cli ref> | tar -x -C "$build"
  cargo build --release --locked --manifest-path "$build/Cargo.toml"   # $build/target/release/fabric
  git -C <cli clone> rev-parse '<cli ref>^{commit}'                    # the commit it is built from
  ```

  Build with `cargo`, not the CLI's `make build`: on macOS that codesigns the binary, which reads your
  keychain, and the sync needs no signed binary. The build needs the Rust version that `rust-version` in the
  new ref's `Cargo.toml` names. The binary gates step 2, step 6,
  the snapshot comparison in step 1 and the commit. Without one, run steps 1, 3, 4 and 5 as a report
  only: change nothing, commit nothing, and say that no binary was built.
- Network access to docs.affinidi.com. It gates step 4.
- For step 6, a disposable gateway built from the new ref and an administrator personal access token for it in
  `FABRIC_E2E_TOKEN`. Build and run the gateway as its `docs/development/GETTING_STARTED.md` describes; the
  first account registered on it is its administrator. Creating the first token needs a browser sign-in
  (`fabric agent-gateway login` opens one), so a person creates the token once, with an expiry, on a gateway
  kept for this ([CONTRIBUTING.md, "A gateway to run against"](../CONTRIBUTING.md#a-gateway-to-run-against)).
  Without a token, skip step 6 and say so in the commit message.
- For step 8, the `gh`, `claude` and `copilot` CLIs, which the install check runs. Without one of them, skip
  the checks that need it and say so in the commit message.
- For step 9, a Claude credential that can be given to a throwaway configuration ([evals/README.md](../evals/README.md#run)).
  Without one, skip step 9 and say so.

## Before you start

- Start a branch from an up-to-date `main`, in a working tree with no uncommitted changes (`git status --short`
  prints nothing).
- Read the baseline from `.github/skill-drift-matrix.json`: `baseline.agent_gateway` (the gateway commit),
  `baseline.fabric_cli` (the CLI commit), `baseline.gateway`, `baseline.fabric` and `baseline.docs_read`. A
  matrix path that starts with `fabric-cli/` is a path in the CLI repository, without that prefix; every other
  path is in the gateway repository.

## Steps

1. **Report.** Run `FABRIC=<your fabric> scripts/drift-report.sh <gateway clone> <gateway ref> <cli clone> <cli ref>`.
   It prints:
   - for each page, the source paths in its matrix entry that changed (`git diff --name-status -M`), each
     with its added and deleted lines, such as `(+31 -8)`. A rename shows as `old -> new` only when both
     paths are in that page's entry. Otherwise it shows as a delete (`D`), and the new path appears in the
     last list;
   - the pages with no change;
   - changed files under the gateway's `src/` and `config/` and the CLI's `src/` that are in no page's entry,
     leaving out test code
     (`src/component_tests/`, `tests/` directories, `*_tests.rs` and `*.test.rs`);
   - with `FABRIC` set, whether `.github/fabric-cli-snapshot.json` and `references/commands.md` still match the
     binary. Without `FABRIC`, it says the snapshot was not compared.

   A few files are named by most pages, so a change to one flags most pages; for example `fabric-cli/src/commands.rs`,
   `src/proxy/handler.rs`, `src/config/types.rs`, `src/config/agent_surface.rs`, `src/identity/router.rs`,
   `src/proxy/server.rs` and `src/server/orchestrator.rs`. Step 3 says how to tell
   whether such a change matters to a page.

   When a baseline is not in its clone (the branch it was on was squashed or rebased away, or the repository
   was published with fresh history), the report says so and lists every page. Then review every page against the new ref. The script exits 0 whatever it finds,
   and 2 on a usage error or when a git command fails; then the report is incomplete, so fix the cause and
   run it again.
2. **Commands.** Do this before you edit any prose: `make validate` rejects every `fabric` command and option
   that the snapshot lacks, including one you are about to document. Run
   `make cli-reference FABRIC=<your fabric>`. It regenerates `.github/fabric-cli-snapshot.json` and
   `references/commands.md`; never edit either by hand. Review the diff for added, renamed and removed
   commands and options. Then run `make validate`: each command or option it rejects is one the skill
   names that the new binary lacks, to fix in step 3.

   `make validate` checks only invocations that start with the word `fabric`, in shell blocks and inline code.
   An option written in prose, such as "pass `--yes`", and a call through `$FABRIC` are not checked, so also
   search for each removed or renamed option: `grep -rn -e '--<option>' skills/ evals/`.
3. **Read the changes.** Start with the range as a whole. `git -C <clone> log --stat <baseline>..<new ref>`
   shows what each commit touched, and `git -C <cli clone> diff <cli baseline> <cli ref> -- README.md` shows CLI
   changes, some of which have no changelog fragment. Run each command below in the clone the path belongs to. Then, for each page the report listed, run
   `git -C <clone> diff --stat <baseline> <new ref> -- <its paths>`, and search the diff for the fields,
   commands and messages the page names:
   `git -C <clone> diff <baseline> <new ref> -- <its paths> | grep -n -e '<field>' -e '<command>'`. A change
   to a file many pages name matters to a page only where it touches what that page says; read the full diff
   there. Then decide what kind of change it is:
   - **Moved:** the code moved but behaves the same, for example a file renamed or split, or a function moved
     to another file. Find it with `git -C <clone> grep -n -F '<function or type>' <new ref>`. Then fix the
     page's `Sources:` line, any settled answer or known issue that names the file, and the page's matrix
     entry. The prose stays as it is.
   - **Changed:** a behaviour, name, default, status code or message changed. Fix every statement of it,
     graders included: `grep -rn '<old name or value>' skills/ evals/`.
   - **New:** a feature or command the skill does not cover. The report's last list, the changelog fragments
     the release added (`git -C <clone> diff --name-only <baseline> <new ref> -- .changelog/`), the commit logs
     and the CLI's `README.md` diff point at these. Fragment file names, branch names and commit subjects can
     carry ticket keys: never copy one, and cite the commit ID instead. Add the feature where a user would look
     for it, and add its paths to that page's matrix entry.
   - **Removed:** delete the statement. Where a user would look for it, say what to use instead, without saying
     that it was removed.

   Keep each entry's `source_paths` sorted, and change the page's `Sources:` line whenever its entry changes.
   `make validate` fails when a page the skill ships has no entry or an entry names no shipped page; whether
   a `Sources:` line agrees with its entry is checked by hand.

   When the source, the docs and a live gateway disagree, the live gateway wins, then the source, then the
   docs. If you cannot settle a fact, remove it or mark it as inference. Leaving the old text in place is also
   a guess.
4. **Docs.** Re-read the docs pages that the matrix lists for each affected page (its `docs`), and fix what they
   contradict. Each page also serves Markdown at `<page URL>index.md`, which is easier to read and compare
   than the HTML. Then compare the links on the docs index,
   `https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/`, with the pages
   `references/sources.md` lists. This prints each page the index links to that `sources.md` lacks:

   ```bash
   comm -23 \
     <(curl -fsSL https://docs.affinidi.com/products/affinidi-trust-fabric/agent-gateway/ \
         | grep -oE '/products/affinidi-trust-fabric/agent-gateway/[a-z0-9./-]*' | sort -u) \
     <(grep -oE 'https://docs\.affinidi\.com/products/affinidi-trust-fabric/agent-gateway/[a-z0-9./-]*' \
         skills/affinidi-agent-gateway/references/sources.md | sed 's#^https://docs\.affinidi\.com##' | sort -u)
   ```

   `sources.md` lists the pages the skill was checked against, not every page, so the list is not empty:
   most of it is section indexes and overviews. Judge each page on it. Add a page a user needs to
   `sources.md`, and to the `docs` of every page that relies on it, and name in the commit message the pages
   you judged not needed.
5. **Known issues.** For each row of `references/known-issues.md`, check whether the new ref fixes it. For a
   fixed row, delete it and every link to its ID (`grep -rn 'KI-nn' skills/ evals/`), and name the fix in the
   commit message. The gateway version that fixed it cannot go in the row: `make validate` refuses `gateway X.Y.Z`,
   `fabric X.Y.Z` and the bare reviewed versions under `skills/` outside `SKILL.md`'s metadata, its "Reviewed
   against" line and the generated header of `references/commands.md`.
   Re-check the rows marked "partly reproduced" or "not yet reproduced" with their Detect step, on the
   disposable gateway only. A row marked `withheld` has no Detect step or source here: check it against the
   gateway's security advisories, and once one is published, add the row's source and Detect step back.
6. **End to end.** First read the `keyring` dependency in the CLI's new ref's `Cargo.toml`. The runner isolates
   only the macOS Keychain and the Linux Secret Service (`apple-native`, `async-secret-service`); `windows-native`
   is also enabled, so never run the cases on Windows. If the features name any other backend, such as the Linux
   kernel keyring, stop and fix the runner before running anything. Then:
   - `python3 tests/e2e/extract.py list` prints each case and the page it is on;
   - `FABRIC=<your fabric> FABRIC_E2E_HOST=<gateway URL> tests/e2e/run.sh <case>...` runs the cases on the
     affected pages, with `FABRIC_E2E_TOKEN` in the environment. `make e2e` runs every case except `# priority: P2` ones; `E2E_PRIORITY=all make e2e` runs those too.

   Only a case that passed counts as checked. A statement or a known issue's status says "reproduced on a
   running gateway" only when a case that exercises it passed, or its Detect step showed the symptom, on the new
   version. Name every case the runner reported as `FAIL`, `REFUSED` or `EXCLUDED`, and every case not run, in the commit message.
7. **Baseline.** Do this last. The baseline moves only when every page the report flagged has been reviewed. A
   partial run leaves the matrix `baseline`, `SKILL.md`'s `gateway`, `fabric` and `checked` metadata and its
   "Reviewed against" line as they are, lists the pages still to review in the commit message, and still
   commits what it changed.
   - When the gateway or `fabric` version changed, set `metadata.gateway` in `SKILL.md` (the `version` in the
     root `Cargo.toml` at the new ref), `metadata.fabric` (from `fabric --version`) and `metadata.checked`
     (today, `YYYY-MM-DD`), and set the body line to exactly
     `Reviewed against gateway X and fabric Y (Month YYYY).` `make validate` checks that line against the
     metadata, and fails on the reviewed versions anywhere else under `skills/` except the generated header of
     `references/commands.md`.
   - When both versions are unchanged and only the commit moved, leave the versions, `metadata.checked` and the
     "Reviewed against" line as they are: they tell users which versions the skill describes, and those did not
     change. The commit message names the new Agent Gateway commit.
   - Always set `metadata.gateway_commit` in `SKILL.md` to the first 12 characters of the new gateway commit.
     `make validate` checks it against the matrix `baseline`.
   - In the matrix `baseline`, set `agent_gateway` and `fabric_cli` (each new ref's full commit ID), `gateway`
     and `fabric` (the same values as `SKILL.md`'s metadata), and `docs_read` when you re-read the docs. Only
     `metadata.gateway_commit` is checked against the baseline, so set the versions in both by hand.
   - Run `make ci`.
8. **Install check.** As in [CONTRIBUTING.md, "Checking an install"](../CONTRIBUTING.md#checking-an-install).
9. **Evals.** Run them as [evals/README.md](../evals/README.md#run) describes, with `--no-publish`, in a
   throwaway configuration. They are advisory: report the score, and don't gate on it.
10. **Commit.** Commit the edits on your branch and open a pull request
    ([CONTRIBUTING.md, "Commits"](../CONTRIBUTING.md#commits)). The subject follows CONTRIBUTING, "Commits",
    and names the new gateway version, or the new ref's short commit ID when no version changed. The body gives
    the commit your `fabric` was built from, each change with the upstream file and commit ID that caused it,
    and for a partial run the pages still to review. Put every question you could not answer in the body, not
    in the skill. Before you commit, run the banned-content check over the message too: write it into an
    untracked file at the repository root, such as `sync-commit.txt`, run `make validate` (it scans untracked
    files that git does not ignore), then delete the file.

## Exceptions

The CLI baseline is a commit of affinidi-ai/affinidi-trust-fabric-cli, which is not public yet. When it goes
public, check that the commit is still there, and sync against the head of its public `main` if it is not.
