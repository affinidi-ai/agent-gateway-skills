"""Unit tests for scripts/gen-cli-reference.py.

The parser runs on help pages copied from the real binary (tests/unit/fixtures/help/). The crawl and
--check run against a fake `fabric`, a shell script in a temp directory that prints those pages and
logs how it was called, so the tests can also prove the binary only ever sees --help and --version
with an isolated environment.
"""

import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

import fixture_repo

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
SCRIPT = os.path.join(REPO, "scripts", "gen-cli-reference.py")
HELP = os.path.join(HERE, "fixtures", "help")

spec = importlib.util.spec_from_file_location("gen_cli_reference", SCRIPT)
gen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gen)

FAKE_FABRIC = """#!/bin/sh
HELP='{help}'
LOG='{log}'
{{
  printf 'ARGV'
  for a in "$@"; do printf ' [%s]' "$a"; done
  printf '\\n'
  env | sed 's/^/ENV /'
  printf 'CWD %s\\n' "$(pwd)"
}} >> "$LOG"
if [ "$#" -eq 1 ] && [ "$1" = --version ]; then
  cat "$HELP/version.txt"
  exit 0
fi
last=
for a in "$@"; do last=$a; done
if [ "$last" != --help ]; then
  echo "fake fabric: only --help and --version" >&2
  exit 2
fi
name=fabric
i=1
for a in "$@"; do
  if [ "$i" -lt "$#" ]; then name="$name-$a"; fi
  i=$((i + 1))
done
if [ ! -f "$HELP/$name.txt" ]; then
  echo "error: unrecognized subcommand" >&2
  exit 2
fi
cat "$HELP/$name.txt"
"""


def page(name):
    with open(os.path.join(HELP, name), encoding="utf-8") as fh:
        return fh.read()


def option(node, long_name):
    for opt in node["options"]:
        if opt.get("long") == long_name:
            return opt
    raise AssertionError("no option --%s in %r" % (long_name, [o.get("long") for o in node["options"]]))


class Parser(unittest.TestCase):
    def test_compact_layout_with_annotations(self):
        """gen-cli-reference: one-line options carry value, env, default and possible values"""
        node = gen.parse_help(page("fabric-agent-gateway.txt"))
        self.assertEqual(node["about"], "Manage Affinidi Agent Gateway")
        self.assertEqual(node["usage"], "fabric agent-gateway [OPTIONS] <COMMAND>")
        conn = option(node, "connection")
        self.assertEqual((conn["short"], conn["value"], conn["env"]), ("c", "<CONNECTION>", "FABRIC_CONNECTION"))
        self.assertEqual(conn["help"], "Named gateway connection.")
        self.assertEqual(option(node, "token")["env"], "FABRIC_TOKEN")
        self.assertNotIn("value", option(node, "allow-http"))
        out = option(node, "output")
        self.assertEqual((out["default"], out["possible_values"]), ("table", ["json", "table"]))
        self.assertNotIn("value", option(node, "help"))

    def test_root_holds_only_the_appliance_groups(self):
        """gen-cli-reference: the root page has the appliance groups, --help and --version, and no globals"""
        node = gen.parse_help(page("fabric.txt"))
        self.assertEqual(node["about"], "Manage Affinidi appliances")
        self.assertEqual(node["usage"], "fabric <COMMAND>")
        self.assertEqual([c["name"] for c in node["commands"]], ["agent-gateway", "help"])
        self.assertEqual([o.get("long") for o in node["options"]], ["help", "version"])
        self.assertEqual(option(node, "version")["short"], "V")

    def test_subcommand_list(self):
        """gen-cli-reference: the Commands section lists names and abouts, help included"""
        node = gen.parse_help(page("fabric-agent-gateway.txt"))
        names = [c["name"] for c in node["commands"]]
        self.assertEqual(names, ["login", "runtime", "whoami", "surfaces", "secrets", "api", "help"])
        self.assertEqual(node["commands"][3]["about"], "Manage Agent Surfaces")

    def test_next_line_layout(self):
        """gen-cli-reference: help on the next line, empty help, quoted and address defaults"""
        node = gen.parse_help(page("fabric-agent-gateway-surfaces-create.txt"))
        self.assertNotIn("help", option(node, "name"))
        self.assertEqual(option(node, "description")["default"], '""')
        self.assertEqual(option(node, "listen-address")["default"], "0.0.0.0:8080")
        protocol = option(node, "protocol")
        self.assertEqual((protocol["default"], protocol["possible_values"]), ("a2a", ["a2a", "ap2", "mcp", "didcomm"]))
        self.assertEqual(option(node, "file")["help"], "Complete AgentSurface JSON.")

    def test_long_layout_and_positional_possible_values(self):
        """gen-cli-reference: long help puts annotations on their own lines and lists possible values"""
        node = gen.parse_help(page("fabric-agent-gateway-runtime-show.txt"))
        self.assertEqual(node["usage"], "fabric agent-gateway runtime show [OPTIONS] <VIEW>")
        view = node["arguments"][0]
        self.assertEqual((view["name"], view["required"]), ("VIEW", True))
        self.assertEqual(view["possible_values"], ["surface-routing", "x402", "networking"])
        self.assertEqual(option(node, "host")["env"], "FABRIC_HOST")
        out = option(node, "output")
        self.assertEqual((out["default"], out["possible_values"]), ("table", ["json", "table"]))

    def test_multi_paragraph_about_and_optional_value(self):
        """gen-cli-reference: multi-paragraph about, flags without values, an optional [<PAT>] value"""
        node = gen.parse_help(page("fabric-agent-gateway-login.txt"))
        self.assertTrue(node["about"].startswith("Authenticate and save a named gateway connection.\n\nOpens a browser"))
        self.assertNotIn("value", option(node, "token-stdin"))
        pat = option(node, "pat")
        self.assertEqual(pat["value"], "[<PAT>]")
        self.assertEqual(pat["help"], "Authenticate with a personal access token (agpat_...) instead of the browser login.")

    def test_positional_arguments(self):
        """gen-cli-reference: several positionals, inline possible values and help"""
        node = gen.parse_help(page("fabric-agent-gateway-api.txt"))
        method, path = node["arguments"]
        self.assertEqual(method["name"], "METHOD")
        self.assertEqual(method["possible_values"], ["get", "post", "put", "patch", "delete"])
        self.assertEqual((path["name"], path["help"]), ("PATH", "API path such as /v1/limits"))

    def test_value_name_differs_from_long(self):
        """gen-cli-reference: value names are kept as clap prints them"""
        node = gen.parse_help(page("fabric-agent-gateway-secrets-create.txt"))
        self.assertEqual(option(node, "type")["value"], "<SECRET_TYPE>")
        self.assertEqual(option(node, "tag")["value"], "<TAGS>")

    def test_free_text_headings_after_the_options(self):
        """gen-cli-reference: an after-help heading such as Examples: is free text, not an options section"""
        node = gen.parse_help("Usage: fabric x [OPTIONS]\n\nOptions:\n  -h, --help  Print help\n\n"
                              "Examples:\n  Check one tool:\n    fabric x --tool a\n\n"
                              "Reading the result:\n  RESULT is ALLOW or DENY.\n")
        self.assertEqual([o["long"] for o in node["options"]], ["help"])
        self.assertEqual(node["after_help"], "Examples: Check one tool: fabric x --tool a\n\n"
                                             "Reading the result: RESULT is ALLOW or DENY.")

    def test_layout_errors_fail_loudly(self):
        """gen-cli-reference: a page it cannot place raises HelpParseError instead of dropping lines"""
        bad = {
            "no usage": "Just text\n",
            "odd option": "Usage: fabric x\n\nOptions:\n  +x  weird\n",
            "continuation without entry": "Usage: fabric x\n\nOptions:\n          stray help\n",
            "indented text outside a section": "Usage: fabric x\n  stray\n",
            "odd command": "Usage: fabric x\n\nCommands:\n  !bang  no\n",
        }
        for label, text in bad.items():
            with self.subTest(label):
                with self.assertRaises(gen.HelpParseError):
                    gen.parse_help(text)

    def test_first_sentence(self):
        """gen-cli-reference: first_sentence stops at a sentence end, not inside names or paths"""
        self.assertEqual(gen.first_sentence("Read it. Then more."), "Read it.")
        self.assertEqual(gen.first_sentence("Use '-' for standard input"), "Use '-' for standard input")
        self.assertEqual(gen.first_sentence("Path such as /v1/x.y here. Next"), "Path such as /v1/x.y here.")


class FakeFabricCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="gen-cli-test-")
        self.help = os.path.join(self.tmp, "help")
        shutil.copytree(HELP, self.help)
        self.log = os.path.join(self.tmp, "calls.log")
        self.fabric = os.path.join(self.tmp, "bin", "fabric")
        os.makedirs(os.path.dirname(self.fabric))
        with open(self.fabric, "w") as fh:
            fh.write(FAKE_FABRIC.format(help=self.help, log=self.log))
        os.chmod(self.fabric, os.stat(self.fabric).st_mode | stat.S_IXUSR)
        self.root = os.path.join(self.tmp, "repo")
        fixture_repo.build(self.root)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_gen(self, *args, env=None):
        full = dict(os.environ)
        full.update(env or {})
        return subprocess.run([sys.executable, SCRIPT, "--fabric", self.fabric, "--root", self.root] + list(args),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, env=full)

    def edit_page(self, name, old, new):
        path = os.path.join(self.help, name)
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn(old, text)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text.replace(old, new, 1))

    def calls(self):
        out = []
        with open(self.log, encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("ARGV"):
                    out.append({"argv": line[len("ARGV"):].strip(), "env": {}, "cwd": None})
                elif line.startswith("ENV ") and "=" in line:
                    key, value = line[4:].rstrip("\n").split("=", 1)
                    out[-1]["env"][key] = value
                elif line.startswith("CWD "):
                    out[-1]["cwd"] = line[4:].rstrip("\n")
        return out


class Crawl(FakeFabricCase):
    def test_crawl_builds_the_tree(self):
        """gen-cli-reference: crawl recurses into every subcommand, skips help and finds the globals below the root"""
        fabric = gen.Fabric(self.fabric)
        try:
            doc = gen.crawl(fabric)
        finally:
            fabric.close()
        self.assertEqual(doc["fabric_version"], "9.8.7")
        self.assertEqual(doc["global_options"], ["allow-http", "connection", "help", "host", "output", "token"])
        root = doc["root"]
        self.assertEqual([c["name"] for c in root["commands"]], ["agent-gateway"])
        group = root["commands"][0]
        self.assertEqual([c["name"] for c in group["commands"]], ["login", "runtime", "whoami", "surfaces", "secrets", "api"])
        runtime = group["commands"][1]
        self.assertEqual([c["name"] for c in runtime["commands"]], ["show"])
        self.assertEqual(runtime["commands"][0]["arguments"][0]["name"], "VIEW")

    def test_fixture_is_fresh(self):
        """gen-cli-reference: --check through the binary agrees with the fixture built from these pages"""
        proc = self.run_gen("--check")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("gen-cli-reference: OK", proc.stdout)

    def test_write_then_check(self):
        """gen-cli-reference: after writing, --check passes, and output is byte-for-byte deterministic"""
        os.remove(os.path.join(self.root, gen.TREE_PATH))
        os.remove(os.path.join(self.root, gen.COMMANDS_PATH))
        proc = self.run_gen()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        with open(os.path.join(self.root, gen.TREE_PATH), "rb") as fh:
            first_tree = fh.read()
        with open(os.path.join(self.root, gen.COMMANDS_PATH), "rb") as fh:
            first_md = fh.read()
        self.assertEqual(self.run_gen().returncode, 0)
        with open(os.path.join(self.root, gen.TREE_PATH), "rb") as fh:
            self.assertEqual(fh.read(), first_tree)
        with open(os.path.join(self.root, gen.COMMANDS_PATH), "rb") as fh:
            self.assertEqual(fh.read(), first_md)
        self.assertEqual(json.loads(first_tree.decode("utf-8"))["format"], gen.TREE_FORMAT)
        self.assertEqual(self.run_gen("--check").returncode, 0)

    def test_drift_is_detected(self):
        """gen-cli-reference: --check exits 1 with a diff when a help page gains an option"""
        self.edit_page("fabric-agent-gateway-surfaces-create.txt", "      --tags <TAGS>\n",
                       "      --tags <TAGS>\n          \n      --owner <OWNER>\n          Who owns it\n")
        before = os.listdir(os.path.join(self.root, ".github"))
        proc = self.run_gen("--check")
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertIn(gen.TREE_PATH + ":1: out of date with the fabric binary", proc.stdout)
        self.assertIn(gen.COMMANDS_PATH + ":1: out of date", proc.stdout)
        self.assertIn("`--owner`", proc.stdout)
        self.assertIn("gen-cli-reference: FAILED, 2 file(s) out of date with fabric 9.8.7", proc.stdout)
        self.assertEqual(os.listdir(os.path.join(self.root, ".github")), before)
        self.assertEqual(self.run_gen("--check").returncode, 1, "--check must not have written the files")

    def test_version_drift_is_detected(self):
        """gen-cli-reference: --check exits 1 when the binary reports a different fabric version"""
        with open(os.path.join(self.help, "version.txt"), "w") as fh:
            fh.write("fabric 9.8.8\n")
        proc = self.run_gen("--check")
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertIn("records fabric 9.8.7 but the binary is fabric 9.8.8", proc.stdout)

    def test_missing_file(self):
        """gen-cli-reference: --check reports a missing generated file"""
        os.remove(os.path.join(self.root, gen.TREE_PATH))
        proc = self.run_gen("--check")
        self.assertEqual(proc.returncode, 1)
        self.assertIn(gen.TREE_PATH + ":1: missing; run make cli-reference", proc.stdout)

    def test_unparseable_page_fails(self):
        """gen-cli-reference: a help page it cannot parse fails the run and names the command"""
        self.edit_page("fabric-agent-gateway-whoami.txt", "Options:\n", "Options:\n  ++weird\n")
        proc = self.run_gen("--check")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("fabric agent-gateway whoami --help: line", proc.stdout)
        self.assertIn("gen-cli-reference: FAILED, could not read the command tree", proc.stdout)

    def test_missing_binary(self):
        """gen-cli-reference: a fabric binary that does not exist is a usage error"""
        proc = subprocess.run([sys.executable, SCRIPT, "--fabric", os.path.join(self.tmp, "nope"), "--check"],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("fabric binary not found", proc.stderr)

    def test_only_help_and_version_with_isolated_env(self):
        """gen-cli-reference: the binary sees only --help/--version, a temp HOME and no FABRIC_* variables"""
        proc = self.run_gen("--check", env={
            "FABRIC_HOST": "http://gateway.example.com", "FABRIC_TOKEN": "leaked-token-value",
            "FABRIC_CONNECTION": "prod", "FABRIC_PAT": "leaked-pat", "COLUMNS": "40", "TERM": "xterm-256color",
        })
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        calls = self.calls()
        self.assertGreater(len(calls), 10)
        real_home = os.path.realpath(os.path.expanduser("~"))
        for call in calls:
            self.assertTrue(call["argv"].endswith("[--help]") or call["argv"] == "[--version]", call["argv"])
            env = call["env"]
            self.assertEqual([k for k in env if k.startswith("FABRIC")], [])
            self.assertNotIn("COLUMNS", env)
            self.assertEqual((env.get("NO_COLOR"), env.get("TERM")), ("1", "dumb"))
            self.assertNotEqual(os.path.realpath(env["HOME"]), real_home)
            self.assertTrue(env["XDG_CONFIG_HOME"].startswith(env["HOME"] + os.sep), env)
            self.assertNotEqual(os.path.realpath(call["cwd"]), os.path.realpath(self.root))
        self.assertNotIn("leaked", proc.stdout + proc.stderr)
        self.assertFalse(os.path.exists(calls[0]["env"]["HOME"]), "the temp HOME must be removed afterwards")

    def test_refuses_other_arguments(self):
        """gen-cli-reference: Fabric.run refuses anything but --help and --version"""
        fabric = gen.Fabric(self.fabric)
        try:
            with self.assertRaises(gen.FabricError):
                fabric.run(["whoami"])
            with self.assertRaises(gen.FabricError):
                fabric.run(["login", "--host", "x"])
        finally:
            fabric.close()
        self.assertFalse(os.path.exists(self.log), "the binary must not have been started")


class Render(FakeFabricCase):
    def setUp(self):
        FakeFabricCase.setUp(self)
        fabric = gen.Fabric(self.fabric)
        try:
            self.doc = gen.crawl(fabric)
        finally:
            fabric.close()
        self.md = gen.render_markdown(self.doc)

    def test_banner_title_and_note(self):
        """gen-cli-reference: commands.md starts with the banner, then the title and the --help note"""
        lines = self.md.splitlines()
        self.assertEqual(lines[0], gen.BANNER.format(version="9.8.7"))
        self.assertTrue(gen.BANNER_RE.match(lines[0]))
        self.assertEqual(lines[2], "# fabric command reference")
        self.assertIn("`fabric agent-gateway <command> --help` is the authoritative detail", self.md)
        self.assertIn("Every command is under an appliance group: `fabric agent-gateway`. Before the group, "
                      "`fabric` takes only `-h, --help` and `-V, --version`.", self.md)

    def test_global_options_come_from_the_appliance_group(self):
        """gen-cli-reference: the global options table lists the group's options, not the root's --version"""
        table = self.md.split("## Global options", 1)[1].split("\n## ", 1)[0]
        self.assertIn("after its appliance group, `fabric agent-gateway`", table)
        self.assertIn("| `--allow-http` |", table)
        self.assertIn("| `-c, --connection <CONNECTION>` | Named gateway connection. |", table)
        self.assertNotIn("--version", table)

    def test_tables_leave_out_globals_and_show_positionals(self):
        """gen-cli-reference: a section per command group, rows with own options by long name and positionals as <NAME>"""
        self.assertIn("\n## surfaces\n", self.md)
        self.assertNotIn("\n## agent-gateway\n", self.md)
        self.assertIn("| Command | What it does | Options |", self.md)
        row = [l for l in self.md.splitlines() if l.startswith("| `fabric agent-gateway runtime show`")][0]
        self.assertIn("`<VIEW>`", row)
        self.assertNotIn("--output", row)
        self.assertNotIn("--allow-http", row)
        row = [l for l in self.md.splitlines() if l.startswith("| `fabric agent-gateway surfaces create`")][0]
        self.assertIn("`--name`, `--description`, `--file`", row)
        self.assertNotIn("--host", row)
        self.assertFalse([l for l in self.md.splitlines() if l.startswith("| `fabric agent-gateway runtime` |")],
                         "a group with only global options gets no row")

    def test_render_is_pure(self):
        """gen-cli-reference: rendering twice gives the same text and leaves the tree unchanged"""
        tree = gen.render_json(self.doc)
        self.assertEqual(gen.render_markdown(self.doc), self.md)
        self.assertEqual(gen.render_json(self.doc), tree)
        self.assertNotIn("_own_options", tree)


if __name__ == "__main__":
    unittest.main()
