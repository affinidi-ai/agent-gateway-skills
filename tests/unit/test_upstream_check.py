"""Unit tests for scripts/upstream-check.py, against upstream repositories built at test time and a fake `gh`.

The script reads the tags of https://github.com/affinidi-ai/agent-gateway.git and
https://github.com/affinidi-ai/affinidi-trust-fabric-cli.git with the real git. Each test points those URLs at
two local repositories through `url.<base>.insteadOf` in its own git config, as CONTRIBUTING's install check
does for this repository. The fake `gh` keeps the issues in a JSON file, logs every call and fails on any call
it does not know, so a changed command line fails the tests.

Every run gets the environment of the workflow on main (GITHUB_ACTIONS=true, GITHUB_REF=refs/heads/main), the
only one in which the script changes issues, unless a test says otherwise. So nothing can reach GitHub: PATH holds
only the fake `gh` and `git`, gh gets an empty config directory and no token, the caller's GIT_* variables are
dropped, and the issue repository is one whose owner, with an underscore, no GitHub account can have.
"""

import importlib.util
import json
import os
import random
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
SCRIPT = os.path.join(REPO, "scripts", "upstream-check.py")
SELF = "upstream_check_test/agent-gateway-skills"
BOT = "app/github-actions"
GATEWAY = "agent-gateway"
CLI = "affinidi-trust-fabric-cli"
TOKENS = ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN", "GH_HOST")

GIT_ENV = {
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
}

# Stands in for gh: `issue list`, `issue view`, `issue create`, `issue edit` and `issue close` exactly as the
# script calls them, with the issues in FAKE_GH_STATE. Issues it creates have the author gh shows for the
# workflow's token. A "fail" entry there makes that call print its message and exit 1; "list_output" and
# "create_output" replace what those calls print, and "view_author" the author that `issue view` shows.
FAKE_GH = r'''
import json
import os
import sys

STATE = os.environ["FAKE_GH_STATE"]
BOT = "app/github-actions"
args = sys.argv[1:]
with open(os.environ["FAKE_GH_LOG"], "a", encoding="utf-8") as fh:
    fh.write(json.dumps(args) + "\n")
with open(STATE, encoding="utf-8") as fh:
    state = json.load(fh)
repo = state["repo"]


def like(pattern):
    return len(args) == len(pattern) and all(p is None or p == a for p, a in zip(pattern, args))


def fail(kind):
    if kind in state.get("fail", {}):
        sys.stderr.write(state["fail"][kind] + "\n")
        sys.exit(1)


def save():
    with open(STATE, "w", encoding="utf-8") as fh:
        json.dump(state, fh)


def find(number, open_only=True):
    for issue in state["issues"]:
        if str(issue["number"]) == number and (issue["state"] == "open" or not open_only):
            return issue
    sys.stderr.write("no open issue #%s\n" % number)
    sys.exit(1)


def author(login):
    return {"is_bot": login == BOT, "login": login}


if like(["issue", "list", "--repo", repo, "--state", "open", "--limit", "1000",
         "--json", "number,title,author,body"]):
    fail("list")
    if "list_output" in state:
        sys.stdout.write(state["list_output"])
    else:
        issues = sorted((i for i in state["issues"] if i["state"] == "open"), key=lambda i: -i["number"])
        print(json.dumps([{"number": i["number"], "title": i["title"], "body": i["body"],
                           "author": author(i["author"])} for i in issues]))
elif like(["issue", "view", None, "--repo", repo, "--json", "author"]):
    fail("view")
    print(json.dumps({"author": author(state.get("view_author", find(args[2], False)["author"]))}))
elif like(["issue", "create", "--repo", repo, "--title", None, "--body-file", "-"]):
    fail("create")
    number = max([i["number"] for i in state["issues"]] + [0]) + 1
    state["issues"].append({"number": number, "title": args[5], "body": sys.stdin.read(), "state": "open",
                            "author": BOT})
    save()
    print(state.get("create_output", "https://github.com/%s/issues/%d" % (repo, number)))
elif like(["issue", "edit", None, "--repo", repo, "--title", None, "--body-file", "-"]):
    fail("edit")
    find(args[2]).update(title=args[6], body=sys.stdin.read())
    save()
    print("https://github.com/%s/issues/%s" % (repo, args[2]))
elif like(["issue", "close", None, "--repo", repo, "--reason", None, "--comment", None]) \
        and args[6] in ("completed", "not planned"):
    fail("close")
    find(args[2]).update(state="closed", reason=args[6], comment=args[8])
    save()
else:
    sys.stderr.write("fake gh: unexpected call %r\n" % (args,))
    sys.exit(64)
'''

# Stands in for git in the credential test: logs the arguments and the credential settings, then runs git.
FAKE_GIT = r"""#!/bin/sh
printf '%%s|%%s|%%s\n' "$*" "${GIT_TERMINAL_PROMPT-unset}" "${GIT_ASKPASS-unset}" >> %(log)s
exec %(git)s "$@"
"""


def write_exe(path, text):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)


class UpstreamCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="upstream-check-test-")
        self.repos = os.path.join(self.tmp, "repos")
        self.skill = os.path.join(self.tmp, "skill")
        self.bin = os.path.join(self.tmp, "bin")
        self.tools = os.path.join(self.tmp, "tools")
        self.state_file = os.path.join(self.tmp, "gh-state.json")
        self.log = os.path.join(self.tmp, "gh-log.jsonl")
        gitconfig = os.path.join(self.tmp, "gitconfig")
        with open(gitconfig, "w", encoding="utf-8") as fh:
            fh.write('[url "%s/"]\n\tinsteadOf = https://github.com/affinidi-ai/\n' % self.repos)
        for path in (self.bin, self.tools, os.path.join(self.tmp, "gh-config")):
            os.makedirs(path)
        git = shutil.which("git")
        self.assertIsNotNone(git, "git is needed on PATH")
        os.symlink(git, os.path.join(self.tools, "git"))
        fake = os.path.join(self.tmp, "fake_gh.py")
        with open(fake, "w", encoding="utf-8") as fh:
            fh.write(FAKE_GH)
        write_exe(os.path.join(self.bin, "gh"),
                  "#!/bin/sh\nexec %s %s \"$@\"\n" % (shlex.quote(sys.executable), shlex.quote(fake)))
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_") and k not in TOKENS}
        self.env.update(GIT_ENV, GIT_CONFIG_GLOBAL=gitconfig, PATH=self.bin + os.pathsep + self.tools,
                        GH_CONFIG_DIR=os.path.join(self.tmp, "gh-config"), GITHUB_REPOSITORY=SELF,
                        GITHUB_ACTIONS="true", GITHUB_REF="refs/heads/main", FAKE_GH_STATE=self.state_file,
                        FAKE_GH_LOG=self.log)
        self.commits = {}
        for name in (GATEWAY, CLI):
            path = os.path.join(self.repos, name + ".git")
            self.git("init", "-q", path)
            self.git("-C", path, "commit", "-q", "--allow-empty", "-m", "chore: start")
            self.commits[name] = self.git("-C", path, "rev-parse", "HEAD")
        os.makedirs(os.path.join(self.skill, "scripts"))
        shutil.copy(SCRIPT, os.path.join(self.skill, "scripts"))
        self.tag(GATEWAY, "v1.0.0", "v0.0.1-rc8")
        self.tag(CLI, "v0.1.0", "v0.1.2")
        self.baseline("1.0.0", "0.1.2")
        self.issues()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def git(self, *args):
        return subprocess.run(["git"] + list(args), env=self.env, cwd=self.tmp, check=True, stdout=subprocess.PIPE,
                              universal_newlines=True).stdout.strip()

    def tag(self, name, *tags, annotated=False):
        for tag in tags:
            extra = ["-a", "-m", tag] if annotated else []
            self.git("-C", os.path.join(self.repos, name + ".git"), "tag", *(extra + [tag]))

    def baseline(self, gateway, fabric, override=None):
        baseline = {"agent_gateway": self.commits[GATEWAY], "fabric_cli": self.commits[CLI],
                    "gateway": gateway, "fabric": fabric, "docs_read": "2026-01-01"}
        baseline.update(override or {})
        os.makedirs(os.path.join(self.skill, ".github"), exist_ok=True)
        with open(os.path.join(self.skill, ".github", "skill-drift-matrix.json"), "w", encoding="utf-8") as fh:
            json.dump({"baseline": baseline, "pages": {}}, fh, indent=2)

    def issues(self, *issues, **extra):
        """Issues as (number, title, state[, author[, body]]); the author defaults to the workflow."""
        state = {"repo": SELF, "issues": [dict(number=i[0], title=i[1], state=i[2],
                                               author=i[3] if len(i) > 3 else BOT, body=i[4] if len(i) > 4 else "")
                                          for i in issues]}
        state.update(extra)
        with open(self.state_file, "w", encoding="utf-8") as fh:
            json.dump(state, fh)

    def state(self):
        with open(self.state_file, encoding="utf-8") as fh:
            return json.load(fh)

    def by_number(self):
        return {i["number"]: i for i in self.state()["issues"]}

    def calls(self):
        if not os.path.exists(self.log):
            return []
        with open(self.log, encoding="utf-8") as fh:
            return [json.loads(line) for line in fh]

    def writes(self):
        """The gh calls that change an issue, as their first three arguments."""
        return [c[:3] for c in self.calls() if c[1] in ("create", "edit", "close")]

    def check(self, *args, **env):
        if os.path.exists(self.log):
            os.remove(self.log)
        script = os.path.join(self.skill, "scripts", "upstream-check.py")
        return subprocess.run([sys.executable, script] + list(args), env=dict(self.env, **env), cwd=self.tmp,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)

    def assertOk(self, proc):
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def assertFails(self, proc, code, message):
        self.assertEqual(proc.returncode, code, proc.stdout + proc.stderr)
        self.assertIn(message, proc.stderr)

    def test_nothing_newer(self):
        """upstream-check: with no release newer than the baseline it says so, reads the issues and writes nothing"""
        self.git("-C", os.path.join(self.repos, GATEWAY + ".git"), "tag", "nightly")
        self.tag(GATEWAY, "v2.0", "release-3.0.0", "v3.0.0-beta.1", "v4.0.0x", "v1.0.01", "v01.2.3", "v١.0.0")
        proc = self.check()
        self.assertOk(proc)
        self.assertEqual(proc.stdout,
                         "gateway: reviewed 1.0.0, latest release 1.0.0 (affinidi-ai/agent-gateway)\n"
                         "fabric: reviewed 0.1.2, latest release 0.1.2 (affinidi-ai/affinidi-trust-fabric-cli)\n"
                         "No release is newer than the reviewed versions.\n")
        self.assertEqual([c[:2] for c in self.calls()], [["issue", "list"]])

    def test_newer_gateway_opens_an_issue(self):
        """upstream-check: a newer gateway tag opens one issue that names it, compared numerically"""
        self.tag(GATEWAY, "v1.0.9", "v1.0.10")
        proc = self.check()
        self.assertOk(proc)
        title = "Upstream sync: gateway 1.0.10, fabric 0.1.2"
        self.assertIn("Opened https://github.com/%s/issues/1: %s\n" % (SELF, title), proc.stdout)
        (issue,) = self.state()["issues"]
        self.assertEqual((issue["title"], issue["author"]), (title, BOT))
        self.assertIn("The skill was reviewed against gateway 1.0.0 and fabric 0.1.2. Newer releases:\n\n"
                      "- gateway 1.0.10: https://github.com/affinidi-ai/agent-gateway/compare/%s...v1.0.10\n\n"
                      % self.commits[GATEWAY], issue["body"])
        self.assertNotIn("- fabric", issue["body"])
        self.assertIn("[docs/upstream-sync.md](https://github.com/%s/blob/main/docs/upstream-sync.md)" % SELF,
                      issue["body"])
        self.assertIn("so add notes as comments", issue["body"])
        self.assertEqual([c[:3] for c in self.calls()],
                         [["issue", "list", "--repo"], ["issue", "create", "--repo"], ["issue", "view", "1"]])

    def test_both_newer_and_annotated_tags(self):
        """upstream-check: annotated and lightweight tags both count, and both newer releases are listed"""
        self.tag(GATEWAY, "v1.1.0", annotated=True)
        self.tag(CLI, "v0.2.0")
        self.assertOk(self.check())
        (issue,) = self.state()["issues"]
        self.assertEqual(issue["title"], "Upstream sync: gateway 1.1.0, fabric 0.2.0")
        self.assertIn("- gateway 1.1.0: https://github.com/affinidi-ai/agent-gateway/compare/", issue["body"])
        self.assertIn("- fabric 0.2.0: https://github.com/affinidi-ai/affinidi-trust-fabric-cli/compare/%s...v0.2.0"
                      % self.commits[CLI], issue["body"])

    def test_baseline_ahead_and_pre_releases(self):
        """upstream-check: a baseline ahead of the tags is not due, and a pre-release baseline is before its release"""
        self.baseline("1.1.0-rc.1", "0.1.2+build.7")
        proc = self.check()
        self.assertOk(proc)
        self.assertIn("gateway: reviewed 1.1.0-rc.1, latest release 1.0.0", proc.stdout)
        self.assertIn("No release is newer", proc.stdout)
        self.assertEqual(self.writes(), [])
        self.tag(GATEWAY, "v1.1.0")
        self.assertOk(self.check())
        (issue,) = self.state()["issues"]
        self.assertEqual(issue["title"], "Upstream sync: gateway 1.1.0, fabric 0.1.2+build.7")
        self.assertIn("reviewed against gateway 1.1.0-rc.1 and fabric 0.1.2+build.7", issue["body"])

    def test_the_right_issue_is_left_alone(self):
        """upstream-check: an issue with the right title and description gets no write, however often it runs"""
        self.tag(CLI, "v0.1.3")
        self.assertOk(self.check())
        issue = self.state()["issues"][0]
        self.issues((issue["number"], issue["title"], "open", BOT, issue["body"].replace("\n", "\r\n") + "  \n"))
        for _ in range(2):
            proc = self.check()
            self.assertOk(proc)
            self.assertIn("Issue #1 already says so: Upstream sync: gateway 1.0.0, fabric 0.1.3\n", proc.stdout)
            self.assertEqual(self.writes(), [])

    def test_a_changed_description_is_put_back(self):
        """upstream-check: a right title over an edited or stale description gets the description back"""
        self.tag(CLI, "v0.1.3")
        title = "Upstream sync: gateway 1.0.0, fabric 0.1.3"
        self.issues((4, title, "open", BOT, "notes someone typed here"))
        proc = self.check()
        self.assertOk(proc)
        self.assertIn("Updated issue #4: %s" % title, proc.stdout)
        self.assertIn("- fabric 0.1.3:", self.by_number()[4]["body"])

    def test_one_issue_stays_open_while_a_release_is_newer(self):
        """upstream-check: the oldest sync issue is retitled, or the one already right is kept, and others close"""
        self.tag(GATEWAY, "v1.0.2")
        self.issues((9, "Upstream sync: something else", "open"),
                    (3, "Upstream sync: gateway 1.0.1, fabric 0.1.2", "open"),
                    (2, "Upstream sync: gateway 0.9.0, fabric 0.1.0", "closed"), (5, "Unrelated", "open"),
                    (1, "Upstream sync: gateway 0.1.0, fabric 0.0.1", "open", "someone"))
        proc = self.check()
        self.assertOk(proc)
        self.assertIn("Updated issue #3: Upstream sync: gateway 1.0.2, fabric 0.1.2\n"
                      "Closed issue #9: Upstream sync: something else\n", proc.stdout)
        issues = self.by_number()
        self.assertIn("- gateway 1.0.2:", issues[3]["body"])
        self.assertEqual(issues[9]["comment"], "Superseded by #3, which the `upstream` workflow keeps up to date.")
        self.assertEqual([(issues[n]["title"], issues[n]["state"]) for n in (2, 5, 1)],
                         [("Upstream sync: gateway 0.9.0, fabric 0.1.0", "closed"), ("Unrelated", "open"),
                          ("Upstream sync: gateway 0.1.0, fabric 0.0.1", "open")])
        self.assertEqual(self.writes(), [["issue", "edit", "3"], ["issue", "close", "9"]])
        right = issues[3]
        self.issues((2, "Upstream sync: reopened by hand", "open"), (3, right["title"], "open", BOT, right["body"]))
        proc = self.check("--dry-run")
        self.assertOk(proc)
        self.assertIn("Issue #3 already says so: %s\nWould close issue #2:" % right["title"], proc.stdout)
        self.assertEqual(self.writes(), [])
        proc = self.check()
        self.assertOk(proc)
        self.assertEqual(self.writes(), [["issue", "close", "2"]])
        self.assertEqual(self.by_number()[2]["comment"],
                         "Superseded by #3, which the `upstream` workflow keeps up to date.")

    def test_issues_opened_by_anyone_else_are_ignored(self):
        """upstream-check: a sync title on an issue the workflow did not open is never adopted, edited or closed"""
        self.tag(GATEWAY, "v1.0.1")
        title = "Upstream sync: gateway 1.0.1, fabric 0.1.2"
        self.issues((1, title, "open", "someone"), (2, "Upstream sync: run this script", "open", "app/other"),
                    (3, "Upstream sync: elsewhere", "open", None))
        proc = self.check()
        self.assertOk(proc)
        self.assertIn("Opened https://github.com/%s/issues/4: %s\n" % (SELF, title), proc.stdout)
        self.assertEqual(self.writes(), [["issue", "create", "--repo"]])
        self.assertOk(self.check())
        self.assertEqual(self.writes(), [])
        self.baseline("1.0.1", "0.1.2")
        self.assertOk(self.check())
        self.assertEqual(self.writes(), [["issue", "close", "4"]])
        issues = self.by_number()
        self.assertEqual([issues[n]["state"] for n in (1, 2, 3, 4)], ["open", "open", "open", "closed"])
        self.assertEqual([issues[n]["title"] for n in (1, 2, 3)],
                         [title, "Upstream sync: run this script", "Upstream sync: elsewhere"])

    def test_closes_its_issue_once_nothing_is_newer(self):
        """upstream-check: once no release is newer, each open sync issue of the workflow is closed with a comment"""
        self.issues((7, "Upstream sync: gateway 1.0.0, fabric 0.1.2", "open"), (8, "Upstream sync: older", "open"),
                    (9, "Upstream sync: closed", "closed"))
        proc = self.check()
        self.assertOk(proc)
        self.assertIn("Closed issue #7: Upstream sync: gateway 1.0.0, fabric 0.1.2\nClosed issue #8:", proc.stdout)
        issues = self.by_number()
        self.assertEqual([issues[n]["state"] for n in (7, 8, 9)], ["closed", "closed", "closed"])
        self.assertEqual(issues[7]["comment"], "No release is newer than the reviewed versions (gateway 1.0.0 and "
                                               "fabric 0.1.2) any more, so the `upstream` workflow closed this issue.")
        self.assertNotIn("comment", issues[9])

    def test_new_issue_author_is_checked(self):
        """upstream-check: a new issue that gh does not show as the workflow's is closed again and fails the run"""
        self.tag(GATEWAY, "v1.0.1")
        for extra, message, closed in (
                ({"view_author": "github-actions[bot]"},
                 "gh shows the author of issue #1 as 'github-actions[bot]', not 'app/github-actions', so the next run "
                 "would not find it; update WORKFLOW_AUTHOR", True),
                ({"view_author": None}, "gh shows the author of issue #1 as None", True),
                ({"view_author": "github-actions[bot]", "fail": {"close": "HTTP 500"}},
                 "not 'app/github-actions'; closing issue #1: gh exited 1: HTTP 500, so the next run", False),
                ({"create_output": "Created issue"},
                 "gh issue create printed 'Created issue', not the URL of an issue in %s" % SELF, False),
                ({"fail": {"view": "HTTP 404"}}, "reading the author of issue #1: gh exited 1", False)):
            with self.subTest(extra=extra):
                self.issues(**extra)
                self.assertFails(self.check(), 1, message)
                (issue,) = self.state()["issues"]
                self.assertEqual(issue["state"], "closed" if closed else "open")
                if closed:
                    self.assertEqual(issue["reason"], "not planned")
                    self.assertIn("could not confirm that it opened this issue", issue["comment"])

    def test_writes_only_from_the_workflow_on_main(self):
        """upstream-check: --dry-run, a branch other than main or a run outside Actions prints and writes nothing"""
        self.tag(GATEWAY, "v1.0.1")
        for args, env in ((("--dry-run",), {}), ((), {"GITHUB_REF": "refs/heads/old-branch"}),
                          ((), {"GITHUB_ACTIONS": ""}), ((), {"GITHUB_REF": "refs/tags/v1.0.0"})):
            with self.subTest(args=args, env=env):
                proc = self.check(*args, **env)
                self.assertOk(proc)
                self.assertIn("Would open an issue: Upstream sync: gateway 1.0.1, fabric 0.1.2\n\nThe skill was",
                              proc.stdout)
                self.assertEqual(self.writes(), [])
        self.issues((6, "Upstream sync: gateway 1.0.0, fabric 0.1.3", "open"), (5, "Upstream sync: old", "closed"))
        proc = self.check("--dry-run", "--repo", SELF, GITHUB_REPOSITORY="")
        self.assertOk(proc)
        self.assertIn("Would update issue #6: Upstream sync: gateway 1.0.1, fabric 0.1.2\n", proc.stdout)
        self.baseline("1.0.1", "0.1.2")
        proc = self.check("--dry-run")
        self.assertOk(proc)
        self.assertIn("Would close issue #6: Upstream sync: gateway 1.0.0, fabric 0.1.3\n", proc.stdout)
        self.assertEqual(self.writes(), [])
        self.assertEqual(self.by_number()[6]["state"], "open")

    def test_git_never_asks_for_credentials(self):
        """upstream-check: git runs with no credential helper, no terminal prompt and no askpass program"""
        log = os.path.join(self.tmp, "git-log")
        shim = os.path.join(self.tmp, "shim")
        os.makedirs(shim)
        git = os.path.join(self.tools, "git")
        write_exe(os.path.join(shim, "git"), FAKE_GIT % {"log": shlex.quote(log), "git": shlex.quote(git)})
        self.assertOk(self.check(PATH=shim + os.pathsep + self.env["PATH"], GIT_ASKPASS="/bin/echo",
                                 GIT_TERMINAL_PROMPT="1"))
        with open(log, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
        self.assertEqual(lines, ["-c credential.helper= ls-remote --tags --refs https://github.com/affinidi-ai/%s.git"
                                 "|0|" % name for name in (GATEWAY, CLI)])

    def test_git_failures(self):
        """upstream-check: an unreadable upstream or one without a vX.Y.Z tag exits 1 before any issue is read"""
        shutil.rmtree(os.path.join(self.repos, CLI + ".git"))
        self.assertFails(self.check(), 1,
                         "upstream-check: reading the tags of affinidi-ai/affinidi-trust-fabric-cli: git exited")
        self.assertEqual(self.calls(), [])
        path = os.path.join(self.repos, CLI + ".git")
        self.git("init", "-q", path)
        self.git("-C", path, "commit", "-q", "--allow-empty", "-m", "chore: start")
        self.git("-C", path, "tag", "nightly")
        self.assertFails(self.check(), 1, "affinidi-ai/affinidi-trust-fabric-cli has no tag of the form vX.Y.Z")

    def test_gh_failures(self):
        """upstream-check: a failed or unreadable gh answer exits 1, and a failed list never leads to a write"""
        self.tag(GATEWAY, "v1.0.1")
        many = json.dumps([{"number": n, "title": "x", "author": None, "body": ""} for n in range(1, 1001)])
        cases = (
            ({"fail": {"list": "HTTP 502: Bad Gateway"}},
             "listing the open issues of %s: gh exited 1: HTTP 502" % SELF),
            ({"list_output": "<html>"}, "gh issue list printed something other than a list of issues"),
            ({"list_output": '{"number": 1}'}, "gh issue list printed something other than a list of issues"),
            ({"list_output": '[{"number": "1", "title": "x"}]'}, "an issue without a number and a title"),
            ({"list_output": '[{"number": 1, "title": null, "author": null}]'},
             "an issue without a number and a title"),
            ({"list_output": many}, "has 1000 or more open issues, more than this check reads"),
            ({"fail": {"create": "HTTP 403: Resource not accessible by integration"}},
             "opening an issue in %s: gh exited 1: HTTP 403" % SELF),
        )
        for extra, message in cases:
            with self.subTest(message=message):
                self.issues(**extra)
                self.assertFails(self.check(), 1, message)
                self.assertEqual(self.state()["issues"], [])
        self.issues((1, "Upstream sync: old", "open"), fail={"edit": "HTTP 500"})
        self.assertFails(self.check(), 1, "updating issue #1: gh exited 1: HTTP 500")
        self.baseline("1.0.1", "0.1.2")
        self.issues((1, "Upstream sync: old", "open"), fail={"close": "HTTP 500"})
        self.assertFails(self.check(), 1, "closing issue #1: gh exited 1: HTTP 500")

    def test_gh_missing_or_not_runnable(self):
        """upstream-check: a gh that is not on PATH, or cannot be run, exits 1 and names gh"""
        self.assertFails(self.check(PATH=self.tools), 1, "listing the open issues of %s: gh is not installed" % SELF)
        os.chmod(os.path.join(self.bin, "gh"), 0o644)
        self.assertFails(self.check(), 1, "listing the open issues of %s: gh cannot be run" % SELF)

    def test_usage_errors(self):
        """upstream-check: no repository for the issue, or a baseline without versions or commits, exits 2"""
        for args, env in (((), {"GITHUB_REPOSITORY": ""}), (("--repo", "no-slash"), {})):
            with self.subTest(args=args):
                self.assertFails(self.check(*args, **env), 2, "name the repository that gets the issue")
        matrix = ".github/skill-drift-matrix.json"
        for override, message in (({"gateway": "1.0"}, "baseline.gateway in %s is '1.0'" % matrix),
                                  ({"gateway": "01.0.0"}, "baseline.gateway in %s is '01.0.0'" % matrix),
                                  ({"fabric": None}, "baseline.fabric in %s is None" % matrix),
                                  ({"fabric_cli": "abc1234"}, "baseline.fabric_cli in %s is 'abc1234'" % matrix)):
            with self.subTest(override=override):
                self.baseline("1.0.0", "0.1.2", override)
                self.assertFails(self.check(), 2, message)
                self.assertEqual(self.calls(), [])
        os.remove(os.path.join(self.skill, ".github", "skill-drift-matrix.json"))
        self.assertFails(self.check(), 2, "cannot read the baseline in .github/skill-drift-matrix.json")

    def test_repository_baseline_is_readable(self):
        """upstream-check: this repository's own drift matrix has a baseline the weekly check can read"""
        spec = importlib.util.spec_from_file_location("upstream_check", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        baseline = module.read_baseline(os.path.join(REPO, ".github", "skill-drift-matrix.json"))
        self.assertEqual(sorted(baseline), ["fabric", "gateway"])

    def test_repeated_runs_converge(self):
        """upstream-check: over random releases, syncs and issues, each run leaves one right issue or none"""
        rng = random.Random(20261021)
        releases = {GATEWAY: [1, 0, 0], CLI: [0, 1, 2]}
        reviewed = {GATEWAY: [1, 0, 0], CLI: [0, 1, 2]}
        actions = ("gateway", "fabric", "sync", "partial", "close", "reopen", "edit", "unrelated", "lookalike")
        for step in range(24):
            action = rng.choice(actions)
            if action in ("gateway", "fabric"):
                name = GATEWAY if action == "gateway" else CLI
                part = rng.choice((0, 1, 2, 2, 2))
                releases[name] = [n + 1 if i == part else (0 if i > part else n)
                                  for i, n in enumerate(releases[name])]
                self.tag(name, "v%d.%d.%d" % tuple(releases[name]))
            state = self.state()
            if action == "sync":
                reviewed = {k: list(v) for k, v in releases.items()}
            elif action == "partial":
                name = rng.choice((GATEWAY, CLI))
                reviewed[name] = list(releases[name])
            elif action in ("close", "reopen", "edit") and state["issues"]:
                issue = rng.choice(state["issues"])
                if action == "edit":
                    issue["body"] = "edited at step %d" % step
                else:
                    issue["state"] = "closed" if action == "close" else "open"
            elif action in ("unrelated", "lookalike"):
                title = ("Unrelated %d" if action == "unrelated" else "Upstream sync: lookalike %d") % step
                state["issues"].append({"number": max([i["number"] for i in state["issues"]] + [0]) + 1,
                                        "title": title, "body": "", "state": "open", "author": "someone"})
            with open(self.state_file, "w", encoding="utf-8") as fh:
                json.dump(state, fh)
            self.baseline("%d.%d.%d" % tuple(reviewed[GATEWAY]), "%d.%d.%d" % tuple(reviewed[CLI]))
            theirs = [(i["number"], i["title"], i["body"], i["state"]) for i in state["issues"] if i["author"] != BOT]
            due = [n for n in (GATEWAY, CLI) if releases[n] > reviewed[n]]
            for attempt in range(2):
                with self.subTest(step=step, action=action, attempt=attempt):
                    self.assertOk(self.check())
                    after = self.state()["issues"]
                    self.assertEqual([(i["number"], i["title"], i["body"], i["state"])
                                      for i in after if i["author"] != BOT], theirs)
                    ours = [i for i in after if i["state"] == "open" and i["author"] == BOT]
                    if attempt:
                        self.assertEqual(self.writes(), [])
                    if not due:
                        self.assertEqual(ours, [])
                        continue
                    want = "Upstream sync: gateway %d.%d.%d, fabric %d.%d.%d" % tuple(
                        (releases[n] if n in due else reviewed[n])[i] for n in (GATEWAY, CLI) for i in range(3))
                    self.assertEqual([i["title"] for i in ours], [want])
                    for name, label in ((GATEWAY, "- gateway "), (CLI, "- fabric ")):
                        self.assertEqual(label in ours[0]["body"], name in due)


if __name__ == "__main__":
    unittest.main()
