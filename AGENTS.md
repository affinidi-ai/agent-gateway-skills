# AGENTS.md

Instructions for coding agents in this repository. [README.md](README.md) says what the skill does.
[CONTRIBUTING.md](CONTRIBUTING.md) holds the rules, the checks and the layout, and
[docs/upstream-sync.md](docs/upstream-sync.md) is the procedure when the gateway or `fabric` changes.

## What this is

An agent skill, also packaged as a plugin, for operating an Affinidi Agent Gateway with the `fabric` CLI. The
product is the Markdown under `skills/affinidi-agent-gateway/`, which is what users get; the code here only
checks it. `SKILL.md` stays under 500 lines, and its body under 5,000 tokens estimated as characters / 4, as
`make validate` enforces.

## Add or change a fact

1. Fix the prose in every file that states the fact, not only the one you found, and the eval graders that
   restate it.
2. Check it against the gateway or `fabric` CLI source at the baselines in `.github/skill-drift-matrix.json`, a docs page, or an e2e
   case that passed. Mark what the source does not prove as "(inference)".
3. For a settled answer or a known issue, name the upstream file, and the function or type, in the prose. No
   line numbers. The exception is a security row whose Status is `withheld`: it carries no source and no
   Detect step until the gateway's maintainers publish an advisory for it.
4. Keep the page's `Sources:` line and its entry in the matrix in step.

Precedence and format: CONTRIBUTING, "Evidence".

## Recipes

Every recipe has Before, Change, Verify, Undo and If it fails. A step that deletes, replaces or changes what
callers see starts with a **Confirm with the user:** line that says what it affects. Secrets never go on a
command line. Recipe blocks carry `<!-- e2e: NAME -->` markers and run as cases, so a new recipe needs its case
file (CONTRIBUTING, "End-to-end cases").

## Commands

- `make ci` before every commit: the offline checks and unit tests that CI runs.
- `make check FABRIC=...`: adds the command-reference check against the `fabric` binary.
- `make e2e`: the live cases, against a disposable gateway only.
- `make cli-reference FABRIC=...` regenerates `references/commands.md` and `.github/fabric-cli-snapshot.json`;
  never edit either by hand.

When a check fails, fix the content, not the check.

## Hard rules

- Nothing in a tracked file that CONTRIBUTING's "Banned content" lists: no secrets, internal hostnames,
  personal or absolute paths, real UUIDs, ticket keys or test-only gateway hooks.
- Nothing under `skills/` names `tests/`, `scripts/` or a commit ID, except the reviewed public gateway commit
  in `SKILL.md`'s `metadata.gateway_commit`. Gateway and `fabric` versions and review dates appear there only in
  `SKILL.md`'s metadata, its "Reviewed against" line and the generated header of `references/commands.md`.
- British English and the docs' product terms (Agent Surface, Access Point, Transit Point, Trust Check). Code
  spans, field and wire names, commands and quotes stay exactly as they are.
- `SKILL.md` and the references are imperative; only the opening paragraphs of `README.md` take a friendlier,
  benefit-first voice.
- `LICENSE`, `NOTICE.txt`, `SECURITY.md` and the Code of Conduct in CONTRIBUTING follow Affinidi's other public
  repositories, and the README's "Support & feedback", "Contributing" and "License" sections follow their
  shape. Keep them in line with those repositories, but never write "we", "our" or "us" anywhere outside the verbatim licence and `SECURITY.md` text.
- Content over code: no new scripts, parsers or checks unless something is really broken.
- Commits follow CONTRIBUTING, "Commits".
