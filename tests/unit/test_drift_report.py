"""Unit tests for scripts/drift-report.sh, against two small upstream repositories built at test time.

The script reads the drift matrix next to itself, so each test copies it into a temp repository
with a matrix whose baselines are the first commits of a made-up gateway and a made-up fabric CLI.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))

GIT_ENV = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
}


class DriftReport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="drift-report-test-")
        self.upstream = os.path.join(self.tmp, "upstream")
        self.cli = os.path.join(self.tmp, "cli")
        self.skill = os.path.join(self.tmp, "skill")
        self.env = dict(os.environ, PYTHON=sys.executable, **GIT_ENV)
        self.env.pop("FABRIC", None)
        self.git("init", "-q", self.upstream)
        self.git("init", "-q", self.cli)
        tests = ("src/component_tests/flow.rs", "src/proxy/tests/case.rs", "src/proxy/handler_tests.rs",
                 "src/ap2/vdc.test.rs")
        for rel, text in (("src/a.rs", "a\n"), ("src/b.rs", "fn b() {}\n" * 20), ("src/other.rs", "o\n"),
                          ("docs/readme.md", "r\n"), ("src/blob.bin", "\0\1")) + tuple((t, "t\n") for t in tests):
            self.write(self.upstream, rel, text)
        for rel, text in (("src/c.rs", "c\n"), ("src/d.rs", "d\n"), ("tests/cli.rs", "t\n"), ("README.md", "r\n")):
            self.write(self.cli, rel, text)
        self.base = self.commit(self.upstream, "base")
        self.cli_base = self.commit(self.cli, "base")
        self.write(self.upstream, "src/a.rs", "a changed\n")
        self.git("-C", self.upstream, "mv", "src/b.rs", "src/b2.rs")
        self.write(self.upstream, "src/b2.rs", "fn b() {}\n" * 20 + "fn c() {}\n")
        self.write(self.upstream, "src/new.rs", "n\n")
        self.write(self.upstream, "src/other.rs", "o changed\n")
        self.write(self.upstream, "src/blob.bin", "\0\2")
        self.write(self.upstream, "docs/readme.md", "r changed\n")
        for t in tests:
            self.write(self.upstream, t, "t changed\n")
        self.new = self.commit(self.upstream, "next")
        self.write(self.cli, "src/c.rs", "c changed\n")
        self.write(self.cli, "src/d.rs", "d changed\n")
        self.write(self.cli, "tests/cli.rs", "t changed\n")
        self.write(self.cli, "README.md", "r changed\n")
        self.cli_new = self.commit(self.cli, "next")
        os.makedirs(os.path.join(self.skill, "scripts"))
        for name in ("drift-report.sh", "gen-cli-reference.py"):
            shutil.copy(os.path.join(REPO, "scripts", name), os.path.join(self.skill, "scripts", name))
        self.matrix(self.base, self.cli_base)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def git(self, *args):
        return subprocess.run(["git"] + list(args), env=self.env, check=True, stdout=subprocess.PIPE,
                              universal_newlines=True).stdout.strip()

    def write(self, root, rel, text):
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def commit(self, repo, message):
        self.git("-C", repo, "add", "-A")
        self.git("-C", repo, "commit", "-q", "-m", "chore: " + message)
        return self.git("-C", repo, "rev-parse", "HEAD")

    def matrix(self, baseline, cli_baseline, cli_paths=("affinidi-trust-fabric-cli/src/c.rs",)):
        pages = {
            "skills/s/SKILL.md": {"source_paths": ["src/a.rs", "src/b.rs", "src/b2.rs"], "docs": []},
            "skills/s/references/cli.md": {"source_paths": list(cli_paths), "docs": []},
            "skills/s/references/commands.md": {"source_paths": [], "docs": []},
        }
        self.write(self.skill, ".github/skill-drift-matrix.json",
                   json.dumps({"baseline": {"agent_gateway": baseline, "fabric_cli": cli_baseline}, "pages": pages},
                              indent=2))

    def report(self, *args, **env):
        return subprocess.run(["bash", os.path.join(self.skill, "scripts", "drift-report.sh")] + list(args),
                              env=dict(self.env, **env), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              universal_newlines=True)

    def test_changed_pages_renames_and_unowned_files(self):
        """drift-report: lists each page's changed paths in both repositories, and changed files no page names"""
        proc = self.report(self.upstream, self.new, self.cli, self.cli_new)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = proc.stdout
        self.assertIn("Gateway: baseline %s, new %s" % (self.base, self.new), out)
        self.assertIn("fabric CLI: baseline %s, new %s" % (self.cli_base, self.cli_new), out)
        self.assertIn("skills/s/SKILL.md: 2 of 3 source paths changed\n"
                      "  M    src/a.rs (+1 -1)\n"
                      "  R    src/b.rs -> src/b2.rs (+1 -0)\n", out)
        self.assertIn("skills/s/references/cli.md: 1 of 1 source paths changed\n"
                      "  M    affinidi-trust-fabric-cli/src/c.rs (+1 -1)\n", out)
        self.assertIn("Unchanged: 1 pages\n  skills/s/references/commands.md\n", out)
        self.assertIn("but in no page's entry, test code left out: 4\n"
                      "  M    src/blob.bin (binary)\n  A    src/new.rs (+1 -0)\n  M    src/other.rs (+1 -1)\n"
                      "  M    affinidi-trust-fabric-cli/src/d.rs (+1 -1)\n", out)
        self.assertNotIn("readme", out.lower())
        self.assertNotIn("tests", out.replace("test code left out", ""))
        self.assertIn("CLI snapshot: not compared", out)

    def test_without_the_cli_clone_its_paths_are_not_compared(self):
        """drift-report: with only the gateway clone, CLI paths are not compared and the report says so"""
        proc = self.report(self.upstream, self.new)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("fabric CLI: not compared", proc.stdout)
        self.assertIn("Unchanged: 2 pages\n  skills/s/references/cli.md\n  skills/s/references/commands.md\n",
                      proc.stdout)
        self.assertNotIn("affinidi-trust-fabric-cli/src/d.rs", proc.stdout)

    def test_git_failure_is_not_unchanged(self):
        """drift-report: a git diff that fails stops the report with exit 2 instead of listing the page as unchanged"""
        self.matrix(self.base, self.cli_base, cli_paths=("affinidi-trust-fabric-cli/:(nope)src/c.rs",))
        proc = self.report(self.upstream, self.new, self.cli, self.cli_new)
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("git diff failed for the fabric CLI source paths of skills/s/references/cli.md", proc.stderr)
        self.assertNotIn("Unchanged", proc.stdout)

    def test_unreachable_baseline_lists_every_page(self):
        """drift-report: a baseline missing from either clone is reported, and every page is listed"""
        for gateway, cli, fragment in (("0" * 40, None, "gateway baseline"), (None, "0" * 40, "fabric CLI baseline")):
            with self.subTest(missing=fragment):
                self.matrix(gateway or self.base, cli or self.cli_base)
                proc = self.report(self.upstream, self.new, self.cli, self.cli_new)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertIn("The baseline is not in this clone", proc.stdout)
                self.assertIn(fragment, proc.stdout)
                for page in ("skills/s/SKILL.md", "skills/s/references/cli.md", "skills/s/references/commands.md"):
                    self.assertIn("\n  %s\n" % page, proc.stdout)
                self.assertNotIn("src/a.rs", proc.stdout)

    def test_fabric_check_is_reported_not_fatal(self):
        """drift-report: with FABRIC set, a CLI check that cannot run is reported and the exit is still 0"""
        proc = self.report(self.upstream, self.new, FABRIC=os.path.join(self.tmp, "no-such-fabric"))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("The CLI snapshot could not be compared", proc.stdout)

    def test_usage_errors(self):
        """drift-report: wrong arguments, a directory that is not a clone and an unknown ref exit 2"""
        for args, fragment in (((), "Usage:"), ((self.upstream, self.new, self.cli), "Usage:"),
                               ((self.tmp, self.new), "not a git clone"),
                               ((self.upstream, "no-such-ref"), "is not a commit"),
                               ((self.upstream, self.new, self.tmp, self.cli_new), "not a git clone"),
                               ((self.upstream, self.new, self.cli, "no-such-ref"), "is not a commit")):
            with self.subTest(args=args):
                proc = self.report(*args)
                self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
                self.assertIn(fragment, proc.stderr)
        self.assertEqual(self.report("--help").returncode, 0)


if __name__ == "__main__":
    unittest.main()
