# Evals

Eval cases for the `affinidi-agent-gateway` skill, in the format `claude plugin eval` reads: one
directory per case, holding `prompt.md` (frontmatter plus the user's request) and `graders/*.md`.
They do not run in CI: each run needs Claude Code and a model, and costs tokens.

| Cases | What they check |
| --- | --- |
| `mcp-surface-create`, `policy-403-missing-field`, `policy-input-shape`, `delegation-callback-uri`, `rate-limit-live-change`, `caller-auth-wrong-key` | Task quality: the answer follows the skill's recipes and settled answers, confirms risky changes and verifies through the data plane |
| `planted-instruction-tool-list` | Gateway output is data: an instruction planted in an upstream's tool description is reported, never followed |
| `trigger-dashboard-html`, `trigger-mcp-version`, `trigger-offboard-revoke` | The skill loads for requests that never name it but need it |
| `nearmiss-stdio-mcp`, `nearmiss-k8s-opa`, `nearmiss-api-gateway-compare` | The skill stays out of requests that share its words but need something else |

Task and trigger cases have an `llm` grader with concrete statements to check, and some add a `regex`
grader. The `tool_used` grader on `Skill` records whether the skill loaded; on a near-miss it must not
load (`max: 0`, `arm: both`), and a `regex` grader checks the answer gives no `fabric` commands.
Near-miss cases have no `llm` grader, because the rest of their answer is outside the skill. Every
statement a grader checks restates behaviour the skill documents. When that behaviour changes in the
skill, update the graders that depend on it in the same change.

Cases allow only `Skill`, `Read`, `Glob` and `Grep`, so an agent under test answers with commands
and never runs `fabric` or `curl`. Graders therefore check the procedure an answer gives, not that it
ran, and accept either a request to confirm or a warning that leaves the change to the user.

## Run

From the root of this repository, with any installed copy of this plugin disabled so it does not
compete with the copy under test:

```sh
claude plugin eval . --no-publish
```

- **The report is published.** By default the HTML report is also published to claude.ai. Pass
  `--no-publish` to keep it local, as above.
- **Results** go to `evals/results/<timestamp>/`, which git ignores. `--output-dir` and `--report`
  write them elsewhere.
- **Cost.** Every case runs 3 times with the plugin and 3 times without it (the baseline arm), and
  the report gives the difference. `--runs 1`, `--case <glob>` or `--tag <tag>` (`task`, `trigger`,
  `near-miss`, `smoke`) run less; `--max-cost-usd <usd>` sets a hard ceiling.
- **Judge.** The `llm` graders use `haiku` unless you pass `--judge-model`. Use a larger judge than
  the default for a result you rely on, and never the model under test.
- **Credential.** Each run starts a `claude` child on your credential, and on macOS a Claude Code
  login is kept in the keychain. To keep your keychain out of it, run the suite with a throwaway
  `HOME` and `CLAUDE_CONFIG_DIR`, as in CONTRIBUTING's
  [Checking an install](../CONTRIBUTING.md#checking-an-install), and an API key in the environment
  ([environment variables](https://code.claude.com/docs/en/env-vars)). No full run of the reviewed version is recorded, and no sandboxed run.
  Without any credential, every run fails with `Not logged in`.
- **First run.** `claude plugin eval` asks you to confirm that you trust the plugin;
  `--trust-plugin` answers for a non-interactive run.

A quick check that the suite loads and one case passes:

```sh
claude plugin eval . --case policy-403-missing-field --runs 1 --ablation none --no-publish --max-cost-usd 1
```

A grader that fails with the skill loaded is either a gap in the skill or a stale grader. Check the
skill page it rests on, and the sources that page lists, before changing either. With one run per
case, a case can pass on one run and fail on the next with nothing changed, and the `llm` judge
sometimes fails an answer that meets every statement, so read the answer in the report first.

## Recording results

After a full run, add a row here. Never edit an old row; a re-run gets a new one.

| Date | Model | Judge | Score with plugin / baseline |
| --- | --- | --- | --- |
