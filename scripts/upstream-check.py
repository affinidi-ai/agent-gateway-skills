#!/usr/bin/env python3
"""Keep one issue open while the Agent Gateway or fabric has a release newer than the reviewed versions.

The reviewed versions are `baseline.gateway` and `baseline.fabric` in .github/skill-drift-matrix.json, each
X.Y.Z with an optional pre-release such as 1.1.0-rc.1, which comes before 1.1.0. A repository's release is its
highest tag of the form vX.Y.Z, read with `git ls-remote`, which needs no token: affinidi-ai/agent-gateway for
the gateway and affinidi-ai/affinidi-trust-fabric-cli for fabric.

The issue is one that the workflow opened (gh shows its author as app/github-actions) with a title that starts
with "Upstream sync: ". While a release is newer, the check gives one such open issue the title and description
that name the newer releases: the one that already has that title, or else the oldest. It opens one when none is
open, checks that gh shows the new issue's author as the workflow (and closes it again when not, so the next run
does not open another), and closes any other such issue as superseded.
Once no release is newer, it closes each such issue that is still open. Issues anyone else opened are never
changed, whatever their title.

It changes issues only when GitHub Actions runs it (GITHUB_ACTIONS=true) on main (GITHUB_REF=refs/heads/main),
as .github/workflows/upstream.yml does every Monday with GH_TOKEN set. Anywhere else, and with --dry-run, it reads
the same sources and prints what it would change; gh then reads the issues with whatever login it has.
GITHUB_REPOSITORY names the repository for the issue unless --repo does.

Exit status: 0 when it finished, whatever it changed or would change; 1 when git or gh fails or answers in a way
this script does not expect; 2 when the arguments or the drift matrix are wrong.
"""

import argparse
import json
import os
import re
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DRIFT_MATRIX = ".github/skill-drift-matrix.json"
RUNBOOK = "docs/upstream-sync.md"
# (name in the issue, baseline version field, baseline commit field, upstream repository)
UPSTREAMS = (
    ("gateway", "gateway", "agent_gateway", "affinidi-ai/agent-gateway"),
    ("fabric", "fabric", "fabric_cli", "affinidi-ai/affinidi-trust-fabric-cli"),
)
TITLE_PREFIX = "Upstream sync: "
# How gh shows the author of an issue opened with the workflow's GITHUB_TOKEN. No account can have this login.
WORKFLOW_AUTHOR = "app/github-actions"
ISSUE_LIMIT = 1000
TIMEOUT = 120
NUMBER = r"(0|[1-9][0-9]*)"
# Semantic Versioning: X.Y.Z, an optional pre-release and optional build metadata, which never orders.
VERSION_RE = re.compile(r"%s\.%s\.%s(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?" % (NUMBER, NUMBER, NUMBER))
TAG_RE = re.compile(r"refs/tags/(v%s\.%s\.%s)" % (NUMBER, NUMBER, NUMBER))
COMMIT_RE = re.compile(r"[0-9a-f]{40}")
REPOSITORY_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")


class UpstreamError(Exception):
    """git or gh failed, or answered in a way this script does not expect."""


class UsageError(Exception):
    """The arguments or the drift matrix are wrong."""


def run(args, what, stdin=None):
    """Run a command and return its standard output; any failure is an UpstreamError that names what it did."""
    # No terminal prompt and no askpass program, so git can never ask anyone for credentials.
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_ASKPASS="")
    try:
        proc = subprocess.run(args, input=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
                              universal_newlines=True, timeout=TIMEOUT)
    except FileNotFoundError:
        raise UpstreamError("%s: %s is not installed" % (what, args[0]))
    except OSError as exc:
        raise UpstreamError("%s: %s cannot be run: %s" % (what, args[0], exc))
    except subprocess.TimeoutExpired:
        raise UpstreamError("%s did not finish within %d seconds" % (what, TIMEOUT))
    if proc.returncode != 0:
        raise UpstreamError("%s: %s exited %d: %s" % (what, args[0], proc.returncode, proc.stderr.strip()))
    return proc.stdout


def order(numbers, prerelease):
    """A version key that orders a pre-release before the X.Y.Z it leads to."""
    return tuple(int(n) for n in numbers) + (0 if prerelease else 1,)


def read_baseline(path):
    """Return {name: (order key, version as written, commit)} from the drift matrix's baseline."""
    try:
        with open(path, encoding="utf-8") as fh:
            baseline = json.load(fh)["baseline"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise UsageError("cannot read the baseline in %s: %s" % (DRIFT_MATRIX, exc))
    if not isinstance(baseline, dict):
        raise UsageError("the baseline in %s is not an object" % DRIFT_MATRIX)
    result = {}
    for name, version_field, commit_field, _ in UPSTREAMS:
        version, commit = baseline.get(version_field), baseline.get(commit_field)
        match = VERSION_RE.fullmatch(version) if isinstance(version, str) else None
        if not match:
            raise UsageError("baseline.%s in %s is %r, not a version X.Y.Z" % (version_field, DRIFT_MATRIX, version))
        if not isinstance(commit, str) or not COMMIT_RE.fullmatch(commit):
            raise UsageError("baseline.%s in %s is %r, not a full commit ID" % (commit_field, DRIFT_MATRIX, commit))
        result[name] = (order(match.groups()[:3], bool(match.group(4))), version, commit)
    return result


def latest_release(repository):
    """The highest vX.Y.Z tag of a public GitHub repository, as (order key, "X.Y.Z")."""
    out = run(["git", "-c", "credential.helper=", "ls-remote", "--tags", "--refs",
               "https://github.com/%s.git" % repository], "reading the tags of %s" % repository)
    versions = []
    for line in out.splitlines():
        match = TAG_RE.fullmatch(line.partition("\t")[2])
        if match:
            versions.append((order(match.groups()[1:], False), match.group(1)[1:]))
    if not versions:
        raise UpstreamError("%s has no tag of the form vX.Y.Z" % repository)
    return max(versions)


def workflow_issues(repo):
    """The open issues of repo that the workflow opened with TITLE_PREFIX, oldest first, as (number, title, body)."""
    out = run(["gh", "issue", "list", "--repo", repo, "--state", "open", "--limit", str(ISSUE_LIMIT),
               "--json", "number,title,author,body"], "listing the open issues of %s" % repo)
    try:
        issues = [(i["number"], i["title"], i.get("author"), i.get("body")) for i in json.loads(out)]
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise UpstreamError("gh issue list printed something other than a list of issues: %s" % exc)
    if len(issues) >= ISSUE_LIMIT:
        raise UpstreamError("%s has %d or more open issues, more than this check reads" % (repo, ISSUE_LIMIT))
    ours = []
    for number, title, author, body in issues:
        if not isinstance(number, int) or isinstance(number, bool) or not isinstance(title, str):
            raise UpstreamError("gh issue list printed an issue without a number and a title: %r" % [number, title])
        if isinstance(author, dict) and author.get("login") == WORKFLOW_AUTHOR and title.startswith(TITLE_PREFIX):
            ours.append((number, title, body if isinstance(body, str) else ""))
    return sorted(ours)


def issue_text(repo, baseline, releases, due):
    """The title and description that name the releases newer than the reviewed versions."""
    title = TITLE_PREFIX + ", ".join(
        "%s %s" % (name, releases[name][1] if name in due else baseline[name][1]) for name, _, _, _ in UPSTREAMS)
    lines = ["The skill was reviewed against %s. Newer releases:" % " and ".join(
        "%s %s" % (name, baseline[name][1]) for name, _, _, _ in UPSTREAMS), ""]
    for name, _, _, repository in UPSTREAMS:
        if name in due:
            lines.append("- %s %s: https://github.com/%s/compare/%s...v%s" % (
                name, releases[name][1], repository, baseline[name][2], releases[name][1]))
    lines += ["", "Bring the skill up to date as [%s](https://github.com/%s/blob/main/%s) describes, and close "
              "this issue from the pull request that does it." % (RUNBOOK, repo, RUNBOOK), "",
              "The `upstream` workflow opened this issue. It keeps the title and this description up to date, so add "
              "notes as comments, and closes the issue once no release is newer than the reviewed versions."]
    return title, "\n".join(lines) + "\n"


def same_text(a, b):
    return a.replace("\r\n", "\n").strip() == b.replace("\r\n", "\n").strip()


def close(repo, number, title, comment, dry_run):
    if dry_run:
        print("Would close issue #%d: %s" % (number, title))
    else:
        run(["gh", "issue", "close", str(number), "--repo", repo, "--reason", "completed", "--comment", comment],
            "closing issue #%d" % number)
        print("Closed issue #%d: %s" % (number, title))


def check_author(repo, url):
    """Fail when gh does not show the issue just opened as the workflow's, so the next run would not find it.

    The issue is closed again first, so that each failed run leaves one closed issue, not one more open one.
    """
    match = re.fullmatch(r"https://github\.com/%s/issues/([0-9]+)" % re.escape(repo), url)
    if not match:
        raise UpstreamError("gh issue create printed %r, not the URL of an issue in %s" % (url, repo))
    number = match.group(1)
    out = run(["gh", "issue", "view", number, "--repo", repo, "--json", "author"],
              "reading the author of issue #%s" % number)
    try:
        login = json.loads(out)["author"]["login"]
        problem = None if login == WORKFLOW_AUTHOR else "gh shows the author of issue #%s as %r, not %r" % (
            number, login, WORKFLOW_AUTHOR)
    except (ValueError, KeyError, TypeError) as exc:
        problem = "gh issue view printed something other than the author of issue #%s: %s" % (number, exc)
    if problem:
        try:
            run(["gh", "issue", "close", number, "--repo", repo, "--reason", "not planned", "--comment",
                 "The `upstream` workflow could not confirm that it opened this issue, so it closed it again; "
                 "its failed run says why."], "closing issue #%s" % number)
        except UpstreamError as exc:
            problem += "; %s" % exc
        raise UpstreamError("%s, so the next run would not find it; update WORKFLOW_AUTHOR" % problem)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Keep one issue open while the gateway or fabric has a release newer than the baseline.")
    parser.add_argument("--repo", help="OWNER/REPO that gets the issue (default: $GITHUB_REPOSITORY)")
    parser.add_argument("--dry-run", action="store_true", help="print what would change, and change nothing")
    args = parser.parse_args(argv)
    try:
        repo = args.repo or os.environ.get("GITHUB_REPOSITORY", "")
        if not REPOSITORY_RE.fullmatch(repo):
            raise UsageError("name the repository that gets the issue with --repo OWNER/REPO or GITHUB_REPOSITORY")
        dry_run = args.dry_run or not (os.environ.get("GITHUB_ACTIONS") == "true"
                                       and os.environ.get("GITHUB_REF") == "refs/heads/main")
        baseline = read_baseline(os.path.join(REPO_ROOT, DRIFT_MATRIX))
        releases = {name: latest_release(repository) for name, _, _, repository in UPSTREAMS}
        due = []
        for name, _, _, repository in UPSTREAMS:
            print("%s: reviewed %s, latest release %s (%s)" % (name, baseline[name][1], releases[name][1], repository))
            if releases[name][0] > baseline[name][0]:
                due.append(name)
        issues = workflow_issues(repo)
        if not due:
            print("No release is newer than the reviewed versions.")
            comment = "No release is newer than the reviewed versions (%s) any more, so the `upstream` workflow " \
                      "closed this issue." % " and ".join("%s %s" % (n, baseline[n][1]) for n, _, _, _ in UPSTREAMS)
            for number, title, _ in issues:
                close(repo, number, title, comment, dry_run)
            return 0
        title, body = issue_text(repo, baseline, releases, due)
        target = next((i for i in issues if i[1] == title), issues[0] if issues else None)
        if target and target[1] == title and same_text(target[2], body):
            print("Issue #%d already says so: %s" % (target[0], title))
        elif dry_run:
            print("Would %s: %s\n\n%s" % ("update issue #%d" % target[0] if target else "open an issue", title, body),
                  end="")
        elif target:
            run(["gh", "issue", "edit", str(target[0]), "--repo", repo, "--title", title, "--body-file", "-"],
                "updating issue #%d" % target[0], stdin=body)
            print("Updated issue #%d: %s" % (target[0], title))
        else:
            url = run(["gh", "issue", "create", "--repo", repo, "--title", title, "--body-file", "-"],
                      "opening an issue in %s" % repo, stdin=body).strip()
            print("Opened %s: %s" % (url, title))
            check_author(repo, url)
        for number, old_title, _ in issues:
            if target and number != target[0]:
                close(repo, number, old_title, "Superseded by #%d, which the `upstream` workflow keeps up to date."
                      % target[0], dry_run)
        return 0
    except UsageError as exc:
        print("upstream-check: %s" % exc, file=sys.stderr)
        return 2
    except UpstreamError as exc:
        print("upstream-check: %s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
