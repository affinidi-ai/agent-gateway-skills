"""Unit tests for scripts/validate.py.

Each negative test builds the clean fixture repository (fixture_repo.py) in a temp directory, makes
one change, runs validate.py on it and asserts two things: it exits 1, and every problem it prints
carries the tag of the check the change targets (so the change trips that check and nothing else).
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

import fixture_repo

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
VALIDATE = os.path.join(REPO, "scripts", "validate.py")
FIXTURES = os.path.join(HERE, "fixtures")
SKILL = fixture_repo.SKILL
PROBLEM_RE = re.compile(r"^(?P<path>[^:\n]+):(?P<line>\d+): \[(?P<check>[a-z]+)\] (?P<message>.*)$")


class ValidateCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="validate-test-")
        self.root = os.path.join(self.tmp, "repo")
        fixture_repo.build(self.root)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def path(self, rel):
        return os.path.join(self.root, rel)

    def read(self, rel):
        with open(self.path(rel), encoding="utf-8") as fh:
            return fh.read()

    def write(self, rel, text):
        os.makedirs(os.path.dirname(self.path(rel)), exist_ok=True)
        with open(self.path(rel), "w", encoding="utf-8") as fh:
            fh.write(text)

    def replace(self, rel, old, new):
        text = self.read(rel)
        self.assertIn(old, text, "fixture %s no longer contains %r" % (rel, old))
        self.write(rel, text.replace(old, new, 1))

    def append(self, rel, text):
        self.write(rel, self.read(rel) + text)

    def run_validate(self):
        proc = subprocess.run([sys.executable, VALIDATE, "--root", self.root],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        problems = [PROBLEM_RE.match(line).groupdict() for line in proc.stdout.splitlines() if PROBLEM_RE.match(line)]
        return proc, problems

    def assertFailsOnly(self, checks, fragment):
        proc, problems = self.run_validate()
        self.assertEqual(proc.returncode, 1, "expected exit 1:\n%s%s" % (proc.stdout, proc.stderr))
        self.assertTrue(problems, "no problems printed:\n" + proc.stdout)
        self.assertEqual(set(p["check"] for p in problems), set(checks), proc.stdout)
        self.assertTrue(any(fragment in p["message"] for p in problems),
                        "no problem mentions %r:\n%s" % (fragment, proc.stdout))
        self.assertRegex(proc.stdout.splitlines()[-1], r"^validate: FAILED, \d+ problems?")
        return problems


class CleanFixture(ValidateCase):
    def test_clean_fixture_passes(self):
        """validate: the clean fixture passes every check"""
        proc, problems = self.run_validate()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(problems, [])
        self.assertTrue(proc.stdout.startswith("validate: OK"), proc.stdout)

    def test_help(self):
        """validate: --help exits 0"""
        proc = subprocess.run([sys.executable, VALIDATE, "--help"], stdout=subprocess.PIPE, universal_newlines=True)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("--root", proc.stdout)

    def test_reports_every_problem_not_just_the_first(self):
        """validate: several independent problems are all reported"""
        self.append(SKILL + "/references/guide.md", "\n[a](missing-one.md) and [b](missing-two.md)\n")
        self.replace(SKILL + "/SKILL.md", "description: Fixture skill for the validate.py unit tests. Use only in tests.\n", "")
        proc, problems = self.run_validate()
        self.assertEqual(proc.returncode, 1)
        messages = " ".join(p["message"] for p in problems)
        self.assertIn("missing-one.md", messages)
        self.assertIn("missing-two.md", messages)
        self.assertIn("needs a non-empty 'description'", messages)

    def test_git_ignored_files_are_not_scanned(self):
        """validate: inside a git work tree only tracked and unignored files are checked"""
        self.write(".gitignore", "ignored.txt\n")
        self.write("ignored.txt", "token agpat_abcdefghijklmnop1234\n")
        subprocess.run(["git", "init", "-q", self.root], check=True)
        proc, problems = self.run_validate()
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.write("visible.txt", "token agpat_abcdefghijklmnop1234\n")
        self.assertFailsOnly({"banned"}, "secret")


class Frontmatter(ValidateCase):
    def test_missing_name(self):
        """validate: SKILL.md without a name fails the frontmatter rule"""
        self.replace(SKILL + "/SKILL.md", "name: affinidi-agent-gateway\n", "")
        self.assertFailsOnly({"frontmatter"}, "needs a non-empty 'name'")

    def test_missing_description(self):
        """validate: a missing description fails the frontmatter rule"""
        self.replace(SKILL + "/SKILL.md", "description: Fixture skill for the validate.py unit tests. Use only in tests.\n", "")
        self.assertFailsOnly({"frontmatter"}, "needs a non-empty 'description'")

    def test_empty_quoted_description(self):
        """validate: a description that is an empty quoted string fails the frontmatter rule"""
        self.replace(SKILL + "/SKILL.md", "description: Fixture skill for the validate.py unit tests. Use only in tests.",
                     'description: ""')
        self.assertFailsOnly({"frontmatter"}, "needs a non-empty 'description'")

    def test_block_scalar_description_is_accepted(self):
        """validate: a folded block scalar description counts as present"""
        self.replace(SKILL + "/SKILL.md", "description: Fixture skill for the validate.py unit tests. Use only in tests.",
                     "description: >-\n  Fixture skill for the validate.py\n  unit tests.")
        proc, problems = self.run_validate()
        self.assertEqual(proc.returncode, 0, proc.stdout)

    def test_missing_frontmatter(self):
        """validate: SKILL.md without frontmatter fails the frontmatter rule"""
        text = self.read(SKILL + "/SKILL.md")
        self.write(SKILL + "/SKILL.md", text.split("---\n", 2)[2])
        self.assertFailsOnly({"frontmatter"}, "must start with '---' frontmatter")


class Size(ValidateCase):
    def test_skill_md_too_long(self):
        """validate: a 500-line SKILL.md fails the size rule"""
        self.append(SKILL + "/SKILL.md", "\n" + "filler line\n" * 490)
        self.assertFailsOnly({"size"}, "keep it under 500")

    def test_skill_body_too_many_tokens(self):
        """validate: a SKILL.md body over 5000 estimated tokens fails the size rule"""
        self.append(SKILL + "/SKILL.md", "\n" + ("word " * 4001) + "\n")
        self.assertFailsOnly({"size"}, "keep it under 5000")


class References(ValidateCase):
    def test_skill_link_leaves_skill(self):
        """validate: a SKILL.md link outside the skill directory fails the references rule"""
        self.append(SKILL + "/SKILL.md", "\nSee [the manifest](../../.claude-plugin/plugin.json).\n")
        self.assertFailsOnly({"references"}, "leaves the skill directory")

    def test_reference_link_leaves_skill(self):
        """validate: a reference page link outside the skill directory fails the references rule"""
        self.append(SKILL + "/references/guide.md", "\nSee [the readme](../../../README.md#installation).\n")
        self.assertFailsOnly({"references"}, "leaves the skill directory")


class Links(ValidateCase):
    def test_broken_relative_link(self):
        """validate: a relative link to a missing file fails the links rule"""
        self.append(SKILL + "/references/guide.md", "\nSee [nothing](nothing-here.md).\n")
        self.assertFailsOnly({"links"}, "broken link 'nothing-here.md'")

    def test_broken_anchor(self):
        """validate: a link to a heading that does not exist fails the anchor rule"""
        self.append(SKILL + "/SKILL.md", "\nSee [start](references/guide.md#getting-startd).\n")
        problems = self.assertFailsOnly({"links"}, "no heading with anchor #getting-startd")
        self.assertIn("did you mean: #getting-started", problems[0]["message"])

    def test_broken_same_file_anchor(self):
        """validate: a same-file #anchor that does not exist fails the anchor rule"""
        self.append(SKILL + "/references/guide.md", "\nBack to [top](#no-such-heading).\n")
        self.assertFailsOnly({"links"}, "#no-such-heading")

    def test_duplicate_heading_slugs(self):
        """validate: repeated headings get -1, -2 anchors like GitHub"""
        self.append(SKILL + "/references/guide.md", "\n## Getting started\n\n[second](#getting-started-1)\n")
        proc, problems = self.run_validate()
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.append(SKILL + "/references/guide.md", "\n[third](#getting-started-2)\n")
        self.assertFailsOnly({"links"}, "#getting-started-2")

    def test_heading_slug_strips_code_and_punctuation(self):
        """validate: slugs drop backticks and punctuation, keep hyphens"""
        self.append(SKILL + "/references/guide.md", "\n## The `fabric` CLI: 1.0 (beta)\n\n[x](#the-fabric-cli-10-beta)\n")
        proc, problems = self.run_validate()
        self.assertEqual(proc.returncode, 0, proc.stdout)

    def test_absolute_link(self):
        """validate: a link to an absolute path fails the links rule"""
        self.append(SKILL + "/references/guide.md", "\nSee [root](/etc/hosts).\n")
        self.assertFailsOnly({"links"}, "is absolute")

    def test_links_inside_code_are_ignored(self):
        """validate: link syntax inside code spans and fences is not checked"""
        self.append(SKILL + "/references/guide.md", "\n`[x](missing.md)`\n\n```text\n[y](missing.md)\n```\n")
        proc, problems = self.run_validate()
        self.assertEqual(proc.returncode, 0, proc.stdout)

    def test_links_inside_html_comments_are_ignored(self):
        """validate: link syntax inside an HTML comment, closed with --> or --!>, is not checked"""
        self.append(SKILL + "/references/guide.md", "\n<!-- [x](missing.md) -->\n\n<!-- [y](missing.md) --!>\n")
        proc, problems = self.run_validate()
        self.assertEqual(proc.returncode, 0, proc.stdout)

    def test_fence_shown_inside_a_readable_fence_is_fine(self):
        """validate: an indented fence shown as text inside a readable fence is not an error"""
        self.append(SKILL + "/references/guide.md", "\n````markdown\n    ```bash\n    echo hi\n    ```\n````\n")
        proc, problems = self.run_validate()
        self.assertEqual(proc.returncode, 0, proc.stdout)

    def test_unclosed_fence(self):
        """validate: an unclosed code fence is reported"""
        self.append(SKILL + "/references/guide.md", "\n```bash\necho open\n")
        self.assertFailsOnly({"markdown"}, "never closed")


class DriftMatrix(ValidateCase):
    MATRIX = ".github/skill-drift-matrix.json"

    def test_shipped_page_without_entry(self):
        """validate: a reference page with no matrix entry fails the matrix rule"""
        self.write(SKILL + "/references/other.md", "# Other\n")
        self.assertFailsOnly({"matrix"}, "no entry for %s/references/other.md, a page the skill ships" % SKILL)

    def test_entry_without_page(self):
        """validate: a matrix entry for a page the skill does not ship fails the matrix rule"""
        os.remove(self.path(SKILL + "/references/guide.md"))
        self.replace(SKILL + "/SKILL.md", "Read the [guide](references/guide.md), the", "Read the")
        self.assertFailsOnly({"matrix"}, "entry for %s/references/guide.md, which is not a page the skill ships" % SKILL)

    def test_missing_or_unreadable_matrix(self):
        """validate: without a readable drift matrix the matrix rule fails"""
        for text in (None, "{ not json\n", '{"pages": {}}\n'):
            with self.subTest(text=text):
                if text is None:
                    os.remove(self.path(self.MATRIX))
                else:
                    self.write(self.MATRIX, text)
                self.assertFailsOnly({"matrix"}, "missing or unreadable")


class Banned(ValidateCase):
    @staticmethod
    def samples(name):
        with open(os.path.join(FIXTURES, name), encoding="utf-8") as fh:
            return [line.rstrip("\n") for line in fh if line.strip()]

    def test_each_banned_family_is_caught(self):
        """validate: every banned-content sample fails the banned rule with its family named"""
        for line in self.samples("banned-samples.txt"):
            family, sample = line.split("\t", 1)
            with self.subTest(family=family, sample=sample):
                self.write("notes.txt", "intro\n" + sample + "\n")
                problems = self.assertFailsOnly({"banned"}, family + ":")
                self.assertTrue(all(p["path"] == "notes.txt" and p["line"] == "2" for p in problems), problems)

    def test_allowed_look_alikes_pass(self):
        """validate: loopback, documentation IPs, versions, technical names, known-issue IDs and example.com pass"""
        self.write("notes.txt", "\n".join(self.samples("allowed-samples.txt")) + "\n")
        proc, problems = self.run_validate()
        self.assertEqual(proc.returncode, 0, proc.stdout)

    def test_secret_is_redacted_in_output(self):
        """validate: a detected secret is not echoed in full"""
        self.write("notes.txt", "agpat_abcdefghijklmnop1234\n")
        proc, _ = self.run_validate()
        self.assertNotIn("abcdefghijklmnop1234", proc.stdout)
        self.assertIn("redacted", proc.stdout)

    def test_banned_file_name(self):
        """validate: a tracked file named like a test-only token fails the banned rule"""
        self.write(".repro-token", "nothing\n")
        self.assertFailsOnly({"banned"}, "file name contains a test-only gateway hook")


class FabricCommands(ValidateCase):
    def add_block(self, *lines):
        self.append(SKILL + "/references/guide.md", "\n```bash\n" + "\n".join(lines) + "\n```\n")

    def test_unknown_subcommand(self):
        """validate: a fabric subcommand that does not exist fails the fabric rule"""
        self.add_block("fabric agent-gateway surfacs create --name x")
        problems = self.assertFailsOnly({"fabric"}, "`fabric agent-gateway` has no subcommand 'surfacs'")
        self.assertIn("did you mean: surfaces", problems[0]["message"])

    def test_unknown_nested_subcommand(self):
        """validate: an unknown second-level subcommand fails the fabric rule"""
        self.add_block("fabric agent-gateway runtime shw surface-routing")
        self.assertFailsOnly({"fabric"}, "`fabric agent-gateway runtime` has no subcommand 'shw'")

    def test_command_outside_the_appliance_group(self):
        """validate: a command written without agent-gateway fails the fabric rule and names the group"""
        self.add_block("fabric surfaces create --name x")
        self.assertFailsOnly({"fabric"}, "`fabric` has no subcommand 'surfaces'; it is under the appliance group: "
                                         "`fabric agent-gateway surfaces`")

    def test_global_option_before_the_appliance_group(self):
        """validate: a global option before agent-gateway fails the fabric rule and says where it goes"""
        self.add_block("fabric -o json agent-gateway whoami", "fabric --allow-http agent-gateway whoami")
        problems = self.assertFailsOnly({"fabric"}, "`fabric` has no option -o; it goes after the appliance group: "
                                                    "`fabric agent-gateway -o`")
        self.assertTrue(any("`fabric` has no option --allow-http" in p["message"] for p in problems), problems)

    def test_unknown_flag(self):
        """validate: a flag the command does not have fails the fabric rule"""
        self.add_block("fabric agent-gateway surfaces create --nam demo")
        problems = self.assertFailsOnly({"fabric"}, "`fabric agent-gateway surfaces create` has no option --nam")
        self.assertIn("did you mean: --name", problems[0]["message"])

    def test_flag_of_another_command(self):
        """validate: a flag that belongs to a different command fails the fabric rule"""
        self.add_block("fabric agent-gateway runtime show surface-routing --protocol mcp")
        self.assertFailsOnly({"fabric"}, "has no option --protocol")

    def test_version_flag_only_at_root(self):
        """validate: -V is a root option, not a global one"""
        self.add_block("fabric -V", "fabric agent-gateway whoami -V")
        self.assertFailsOnly({"fabric"}, "`fabric agent-gateway whoami` has no option -V")

    def test_inline_code_command(self):
        """validate: inline `fabric ...` spans are checked too"""
        self.append(SKILL + "/references/guide.md", "\nRun `fabric agent-gateway surfaces create --protcol mcp`.\n")
        self.assertFailsOnly({"fabric"}, "has no option --protcol")

    def test_command_substitution_and_pipes(self):
        """validate: fabric inside $(...) and after pipes and && is checked"""
        self.add_block('ID=$(fabric agent-gateway surfaces create --fil x.json | jq -r .id) && echo "$ID"',
                       "cat x.json | fabric agent-gateway api post /v1/x --dat @-")
        proc, problems = self.run_validate()
        self.assertEqual(proc.returncode, 1)
        messages = " ".join(p["message"] for p in problems)
        self.assertIn("has no option --fil", messages)
        self.assertIn("has no option --dat", messages)

    def test_flag_on_continued_line(self):
        """validate: a bad flag on a backslash-continued line fails the fabric rule"""
        self.add_block("fabric agent-gateway surfaces create --name demo \\", "    --protocl mcp")
        self.assertFailsOnly({"fabric"}, "`fabric agent-gateway surfaces create` has no option --protocl")

    def test_subcommand_on_continued_line(self):
        """validate: a bad subcommand on a backslash-continued line fails the fabric rule"""
        self.add_block("fabric agent-gateway runtime \\", "  shw surface-routing")
        self.assertFailsOnly({"fabric"}, "`fabric agent-gateway runtime` has no subcommand 'shw'")

    def test_incomplete_command_in_block(self):
        """validate: a group command with no subcommand in a code block fails the fabric rule"""
        self.add_block("fabric agent-gateway surfaces")
        self.assertFailsOnly({"fabric"}, "`fabric agent-gateway surfaces` needs a subcommand")

    def test_bare_appliance_group_in_block(self):
        """validate: fabric or fabric agent-gateway with no subcommand in a code block fails the fabric rule"""
        self.add_block("fabric agent-gateway -o json", "fabric")
        problems = self.assertFailsOnly({"fabric"}, "`fabric agent-gateway` needs a subcommand")
        self.assertTrue(any(p["message"].startswith("`fabric` needs a subcommand (agent-gateway)") for p in problems),
                        problems)

    def test_valid_forms_pass(self):
        """validate: globals after the group, --opt=value, -ovalue, placeholders, help and continuations pass"""
        self.add_block(
            "$ fabric agent-gateway --host http://localhost:8080 -c prod surfaces create \\",
            "    --name demo --protocol mcp -ojson --allow-http",
            "fabric agent-gateway surfaces -o json create --file=surface.json",
            "fabric agent-gateway <command> --help",
            "fabric help agent-gateway runtime show",
            "fabric agent-gateway help runtime show",
            "fabric agent-gateway surfaces help",
            'fabric agent-gateway api post /v1/limits --data \'{"a": "b | c; d"}\'',
            "fabric agent-gateway secrets create --value-stdin --name x <<'EOF'",
            "fabric not-a-command inside a heredoc",
            "EOF",
            "fabric agent-gateway login --pat --token-stdin",
            'FABRIC_HOST=x fabric agent-gateway whoami  # trailing comment',
            "fabric --version",
            "fabric --help",
        )
        proc, problems = self.run_validate()
        self.assertEqual(proc.returncode, 0, proc.stdout)

    def test_escaped_pipe_in_a_table_cell(self):
        """validate: in a table row, \\| inside a code span is a pipe, so what follows is not fabric's"""
        self.append(SKILL + "/references/guide.md",
                    "\n| Check | Command |\n| --- | --- |\n"
                    "| routing | `fabric agent-gateway runtime show surface-routing -o json \\| jq --arg k v '.[$k]'` |\n"
                    "| typo | `fabric agent-gateway runtime shw surface-routing \\| jq .` |\n")
        problems = self.assertFailsOnly({"fabric"}, "`fabric agent-gateway runtime` has no subcommand 'shw'")
        self.assertEqual(len(problems), 1, problems)

    def test_escaped_pipe_outside_a_table_is_literal(self):
        """validate: outside a table, \\| in a code span is a backslash and a pipe, one shell word"""
        self.append(SKILL + "/references/guide.md",
                    "\nRun `fabric agent-gateway runtime show surface-routing \\| --arg`.\n")
        self.assertFailsOnly({"fabric"}, "has no option --arg")

    def test_parameter_expansion_is_one_word(self):
        """validate: ${...} is one shell word, so a pipe or brace inside it does not cut the command"""
        self.add_block("fabric agent-gateway surfaces create --name ${NAME//|/-} --route ${PREFIX%/}/x --protcol mcp",
                       'ID=${ID:-$(fabric agent-gateway surfacs list)}')
        proc, problems = self.run_validate()
        self.assertEqual(proc.returncode, 1, proc.stdout)
        messages = [p["message"] for p in problems]
        self.assertTrue(any("`fabric agent-gateway surfaces create` has no option --protcol" in m for m in messages),
                        messages)
        self.assertTrue(any("has no subcommand 'surfacs'" in m for m in messages), messages)
        self.assertEqual(len(messages), 2, messages)

    def test_substitution_inside_double_quotes(self):
        """validate: a fabric command in "$(...)" is checked, and the quoted word around it is a placeholder"""
        self.add_block('URL="$(fabric agent-gateway surfacs get x -o json | jq -r .url)"',
                       'fabric agent-gateway surfaces create --name "$(cat name.txt)" --protcol mcp')
        proc, problems = self.run_validate()
        messages = [p["message"] for p in problems]
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertTrue(any("has no subcommand 'surfacs'" in m for m in messages), messages)
        self.assertTrue(any("has no option --protcol" in m for m in messages), messages)
        self.assertEqual(len(messages), 2, messages)

    def test_redirections_and_other_commands_pass(self):
        """validate: redirections end the command; fabric as an argument of another command is not read"""
        self.add_block("fabric agent-gateway whoami -o json > out.json 2>&1",
                       "fabric agent-gateway runtime show surface-routing -o json 2>/dev/null | jq .",
                       "command -v fabric || echo 'install fabric first'",
                       "echo fabric surfacs is not a command here")
        proc, problems = self.run_validate()
        self.assertEqual(proc.returncode, 0, proc.stdout)

    def test_indented_fence_is_read(self):
        """validate: a fence nested in a list item, indented four spaces, is checked too"""
        self.append(SKILL + "/references/guide.md",
                    "\n1. Create it:\n\n    ```bash\n    fabric agent-gateway surfacs create --name x\n    ```\n")
        self.assertFailsOnly({"fabric"}, "has no subcommand 'surfacs'")

    def test_missing_snapshot(self):
        """validate: without the CLI snapshot the fabric check reports how to generate it"""
        os.remove(self.path(".github/fabric-cli-snapshot.json"))
        self.assertFailsOnly({"fabric"}, "run make cli-reference")


class Generated(ValidateCase):
    COMMANDS = SKILL + "/references/commands.md"

    def test_hand_edited_commands_md(self):
        """validate: a hand edit to references/commands.md fails the generated rule"""
        self.replace(self.COMMANDS, "Manage Agent Surfaces", "Manage Agent Surfaces by hand")
        self.assertFailsOnly({"generated"}, "does not match what gen-cli-reference.py renders")

    def test_missing_banner(self):
        """validate: commands.md without the generator banner fails the generated rule"""
        text = self.read(self.COMMANDS)
        self.write(self.COMMANDS, text.split("\n", 1)[1])
        self.assertFailsOnly({"generated"}, "must start with the banner")

    def test_banner_version_differs_from_tree(self):
        """validate: a banner fabric version unlike the CLI snapshot fails the generated rule"""
        self.replace(self.COMMANDS, "help of fabric 9.8.7 by", "help of fabric 9.8.6 by")
        self.assertFailsOnly({"generated"}, "banner says fabric 9.8.6 but .github/fabric-cli-snapshot.json records fabric 9.8.7")


class MaintainerMaterial(ValidateCase):
    GUIDE = SKILL + "/references/guide.md"

    def test_tests_path(self):
        """validate: a skill page naming tests/ fails the maintainer rule"""
        self.append(self.GUIDE, "\nThe case in tests/e2e/cases/demo.sh exercises it.\n")
        self.assertFailsOnly({"maintainer"}, "names 'tests/'")

    def test_scripts_path(self):
        """validate: SKILL.md naming scripts/ fails the maintainer rule"""
        self.append(SKILL + "/SKILL.md", "\nRun scripts/validate.py first.\n")
        self.assertFailsOnly({"maintainer"}, "names 'scripts/'")

    def test_commit_id(self):
        """validate: a nine-character hex commit id in a skill page fails the maintainer rule"""
        self.append(self.GUIDE, "\nRead from the gateway source at commit 02f472e42.\n")
        self.assertFailsOnly({"maintainer"}, "'02f472e42' looks like a commit id")

    def test_gateway_commit_key_passes(self):
        """validate: the reviewed public gateway commit in metadata.gateway_commit passes the maintainer rule"""
        proc, problems = self.run_validate()
        self.assertEqual(proc.returncode, 0, proc.stdout)

    def test_commit_id_in_other_metadata_key(self):
        """validate: a commit id in any other SKILL.md metadata key fails the maintainer rule"""
        self.replace(SKILL + "/SKILL.md", '  checked: "2026-03-04"', '  checked: "2026-03-04"\n  fabric_commit: "02f472e42abc"')
        self.assertFailsOnly({"maintainer"}, "'02f472e42abc' looks like a commit id")

    def test_frontmatter_is_scanned(self):
        """validate: a SKILL.md frontmatter value naming scripts/ fails the maintainer rule"""
        self.replace(SKILL + "/SKILL.md", "license: Apache-2.0", "license: Apache-2.0\ncompatibility: Built with scripts/build.sh")
        self.assertFailsOnly({"maintainer"}, "names 'scripts/'")

    def test_fenced_code_and_plain_words_pass(self):
        """validate: fenced code, words ending in 'tests' and short or all-digit hex runs pass"""
        self.append(self.GUIDE, "\n```text\ntests/e2e/run.sh at 02f472e42\n```\n\n"
                                "The gateway tests requests; ids like 1234567890 and abc123 are fine.\n")
        proc, problems = self.run_validate()
        self.assertEqual(proc.returncode, 0, proc.stdout)

    def test_files_outside_skills_pass(self):
        """validate: a file outside skills/ may name tests/ and commit ids"""
        self.write("README.md", "# Readme\n\nRun tests/unit at commit 02f472e42.\n")
        proc, problems = self.run_validate()
        self.assertEqual(proc.returncode, 0, proc.stdout)


class ReviewedLiterals(ValidateCase):
    GUIDE = SKILL + "/references/guide.md"
    LINE = "Reviewed against gateway 1.2.3 and fabric 9.8.7 (March 2026)."

    def test_gateway_version_in_page(self):
        """validate: the reviewed gateway version in a reference page fails the reviewed rule"""
        self.append(self.GUIDE, "\nThe caller-context mode has no effect in 1.2.3.\n")
        self.assertFailsOnly({"reviewed"}, "version literal '1.2.3'")

    def test_named_version_other_than_reviewed(self):
        """validate: 'fabric X.Y.Z' for any version outside the allowed places fails the reviewed rule"""
        self.append(self.GUIDE, "\nNeeds fabric 4.5.6 or later.\n")
        self.assertFailsOnly({"reviewed"}, "version literal 'fabric 4.5.6'")

    def test_one_problem_per_literal(self):
        """validate: 'gateway 1.2.3' is reported once, not once per matching pattern"""
        self.append(self.GUIDE, "\nChecked against gateway 1.2.3.\n")
        problems = self.assertFailsOnly({"reviewed"}, "version literal 'gateway 1.2.3'")
        self.assertEqual(len(problems), 1, problems)

    def test_version_in_fenced_code(self):
        """validate: a reviewed version inside fenced code fails the reviewed rule too"""
        self.append(self.GUIDE, '\n```json\n{"version": "1.2.3"}\n```\n')
        self.assertFailsOnly({"reviewed"}, "version literal '1.2.3'")

    def test_review_month_date(self):
        """validate: a date in the metadata.checked month fails the reviewed rule"""
        self.append(self.GUIDE, "\nObserved on 2026-03-15.\n")
        self.assertFailsOnly({"reviewed"}, "date '2026-03-15' is in the review month")

    def test_other_dates_and_versions_pass(self):
        """validate: protocol dates, other months and unrelated versions pass"""
        self.append(self.GUIDE, "\nMCP `2024-11-05` clients, a token that expires 2027-01-01, OpenAPI 3.0.0 and "
                                "the regorus crate 0.5.0 are fine, and so is 11.2.3.\n")
        proc, problems = self.run_validate()
        self.assertEqual(proc.returncode, 0, proc.stdout)

    def test_version_in_compatibility(self):
        """validate: a reviewed version in frontmatter outside metadata fails the reviewed rule"""
        self.replace(SKILL + "/SKILL.md", "license: Apache-2.0", "license: Apache-2.0\ncompatibility: Needs fabric 9.8.7.")
        self.assertFailsOnly({"reviewed"}, "version literal 'fabric 9.8.7'")

    def test_plugin_description(self):
        """validate: a version in a plugin description fails the reviewed rule"""
        self.replace(".claude-plugin/plugin.json", "Fixture plugin for the validate.py unit tests.",
                     "Fixture plugin. Checked against gateway 1.2.3.")
        self.assertFailsOnly({"reviewed"}, "description names 'gateway 1.2.3'")

    def test_reviewed_line_disagrees_with_metadata(self):
        """validate: a 'Reviewed against' line naming another version fails the reviewed rule"""
        self.replace(SKILL + "/SKILL.md", self.LINE, self.LINE.replace("gateway 1.2.3", "gateway 1.2.4"))
        self.assertFailsOnly({"reviewed"}, "says gateway 1.2.4 but metadata.gateway is 1.2.3")

    def test_gateway_commit_disagrees_with_baseline(self):
        """validate: a metadata.gateway_commit other than the matrix baseline's start fails the reviewed rule"""
        self.replace(SKILL + "/SKILL.md", 'gateway_commit: "0123456789ab"', 'gateway_commit: "0123456789ac"')
        self.assertFailsOnly({"reviewed"}, "metadata.gateway_commit 0123456789ac is not the start of baseline.agent_gateway")

    def test_baseline_versions_disagree_with_metadata(self):
        """validate: a matrix baseline version other than the one in SKILL.md's metadata fails the reviewed rule"""
        for old, new, fragment in (
                ('"gateway": "1.2.3"', '"gateway": "1.2.4"', "metadata.gateway 1.2.3 is not baseline.gateway 1.2.4"),
                ('"fabric": "9.8.7"', '"fabric": "9.8.8"', "metadata.fabric 9.8.7 is not baseline.fabric 9.8.8")):
            with self.subTest(key=old):
                self.replace(".github/skill-drift-matrix.json", old, new)
                self.assertFailsOnly({"reviewed"}, fragment)
                self.replace(".github/skill-drift-matrix.json", new, old)

    def test_gateway_commit_shape(self):
        """validate: a metadata.gateway_commit that is not 12 lowercase hex characters fails the reviewed rule"""
        self.replace(SKILL + "/SKILL.md", 'gateway_commit: "0123456789ab"', 'gateway_commit: "0123456789"')
        self.assertFailsOnly({"reviewed"}, "is not 12 lowercase hex characters")

    def test_gateway_commit_missing(self):
        """validate: SKILL.md with metadata.gateway but no metadata.gateway_commit fails the reviewed rule"""
        self.replace(SKILL + "/SKILL.md", '  gateway_commit: "0123456789ab"\n', '')
        self.assertFailsOnly({"reviewed"}, "no metadata.gateway_commit")

    def test_reviewed_month_disagrees_with_checked(self):
        """validate: a 'Reviewed against' month other than metadata.checked's fails the reviewed rule"""
        self.replace(SKILL + "/SKILL.md", self.LINE, self.LINE.replace("March", "February"))
        self.assertFailsOnly({"reviewed"}, "says (February 2026) but metadata.checked is 2026-03-04 (March 2026)")

    def test_missing_reviewed_line(self):
        """validate: SKILL.md with review metadata but no 'Reviewed against' line fails the reviewed rule"""
        self.replace(SKILL + "/SKILL.md", self.LINE + "\n", "")
        self.assertFailsOnly({"reviewed"}, "no 'Reviewed against gateway")

    def test_malformed_reviewed_line(self):
        """validate: a 'Reviewed against' line in another shape fails the reviewed rule"""
        self.replace(SKILL + "/SKILL.md", self.LINE, "Reviewed against gateway 1.2.3 in March 2026.")
        self.assertFailsOnly({"reviewed"}, "must read exactly")

    def test_second_reviewed_line(self):
        """validate: two 'Reviewed against' lines fail the reviewed rule"""
        self.append(SKILL + "/SKILL.md", "\n" + self.LINE + "\n")
        self.assertFailsOnly({"reviewed"}, "a second 'Reviewed against' line")


if __name__ == "__main__":
    unittest.main()
