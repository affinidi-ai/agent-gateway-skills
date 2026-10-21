"""Unit tests for the literate e2e machinery: tests/e2e/extract.py, run.sh and lib.sh.

The runner tests use no gateway and no keychain. Every run gets a temp HOME (standing in for the
real one), a temp TMPDIR, and fakes first on PATH: `fabric` (a shell script that logs its calls and
answers a few made-up commands), `security` and `dbus-send` in every test, and `uname` where a test
needs macOS or Linux. The fake `security` keeps its state in files, so the tests can prove what the
runner would have done to a keychain search list without ever calling the real tool.
"""

import os
import platform
import re
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
E2E = os.path.join(REPO, "tests", "e2e")
EXTRACT = os.path.join(E2E, "extract.py")
RUN = os.path.join(E2E, "run.sh")

FAKE_FABRIC = r"""#!/bin/sh
LOG='{log}'
{{
  printf 'ARGV'
  for a in "$@"; do printf ' [%s]' "$a"; done
  printf ' HOME=%s TOKEN=%s\n' "$HOME" "${{FABRIC_TOKEN:+set}}"
}} >> "$LOG"
# Every command is under agent-gateway, and the global options follow it, as in fabric, so a call
# such as `fabric agent-gateway -o json whoami` works and `fabric whoami` does not.
case "$1" in
  -V|--version) echo "fabric 0.0.0-fake"; exit 0 ;;
  agent-gateway) shift ;;
  *) echo "fake fabric: unrecognized subcommand $1" >&2; exit 2 ;;
esac
while [ "$#" -gt 0 ]; do
  case "$1" in
    -c|--connection|--host|--token|-o|--output) shift 2 ;;
    --connection=*|--host=*|--token=*|--output=*|-c?*|-o?*|--allow-http) shift ;;
    *) break ;;
  esac
done
case "$1" in
  whoami)
    for c in "$HOME/Library/Application Support/fabric/config.toml" "$XDG_CONFIG_HOME/fabric/config.toml"; do
      if [ -f "$c" ]; then printf 'CONFIG %s\n' "$c" >> "$LOG"; sed 's/^/CONFIG| /' "$c" >> "$LOG"; fi
    done
    printf '{{"authenticated": true, "connection": "e2e", "host": "%s"}}\n' "$GATEWAY"
    ;;
  show-file) cat "$2" ;;
  boom) echo "error: boom" >&2; exit 1 ;;
  leak) echo "the token is $FABRIC_TOKEN"; exit 1 ;;
  login|logout) cat > /dev/null; echo "$1 done" ;;
  mkkeychains) mkdir -p "$HOME/Library/Keychains" ;;
  settings)
    case "$2" in
      show) if [ -f '{settings}' ]; then cat '{settings}'; else echo '{{"audit_enabled": false}}'; fi ;;
      set) shift 2; while [ "$#" -gt 0 ]; do [ "$1" = --file ] && cp "$2" '{settings}'; shift; done; cat '{settings}' ;;
    esac ;;
  *) echo "fake fabric: unknown command $1" >&2; exit 2 ;;
esac
"""

# FAKE_SECURITY_MODE: isolating (state follows HOME, like a well-behaved tool), shared (ignores
# HOME, so the sandbox would see the real search list) or leaky (reads follow HOME, writes go to
# the real state).
FAKE_SECURITY = r"""#!/bin/sh
LOG='{log}'
REAL_HOME='{real_home}'
printf 'HOME=%s security %s\n' "$HOME" "$*" >> "$LOG"
mode=${{FAKE_SECURITY_MODE:-isolating}}
read_home=$HOME
write_home=$HOME
case "$mode" in
  shared) read_home=$REAL_HOME; write_home=$REAL_HOME ;;
  leaky) write_home=$REAL_HOME ;;
esac
show() {{
  if [ -f "$1/.fake-security/$2" ]; then cat "$1/.fake-security/$2"
  else printf '    "%s/Library/Keychains/login.keychain-db"\n' "$1"; fi
}}
save() {{
  mkdir -p "$write_home/.fake-security"
  shift_to=$1; shift
  : > "$write_home/.fake-security/$shift_to"
  for p in "$@"; do printf '    "%s"\n' "$p" >> "$write_home/.fake-security/$shift_to"; done
}}
listed() {{
  show "$write_home" list-keychains | sed -n 's/^[[:space:]]*"\(.*\)"[[:space:]]*$/\1/p' | grep -vxF "${{1:-}}"
}}
cmd=$1; shift
case "$cmd" in
  list-keychains|default-keychain)
    [ "$1" = -d ] && shift 2
    if [ "${{1:-}}" = -s ]; then shift; save "$cmd" "$@"; else show "$read_home" "$cmd"; fi ;;
  create-keychain)
    [ "$1" = -p ] && shift 2; mkdir -p "$(dirname "$1")"; : > "$1"
    save list-keychains $(listed) "$1" ;;
  unlock-keychain) [ "$1" = -p ] && shift 2; [ -f "$1" ] ;;
  delete-keychain) rm -f "$1"; save list-keychains $(listed "$1") ;;
  *) echo "fake security: unsupported $cmd" >&2; exit 2 ;;
esac
"""

# Stands in for dbus-send: no session bus answers unless FAKE_DBUS=up, or FAKE_DBUS=fallback and
# DBUS_SESSION_BUS_ADDRESS is unset (a bus libdbus would find without an address).
FAKE_DBUS_SEND = r"""#!/bin/sh
printf 'dbus-send %s ADDRESS=%s\n' "$*" "${{DBUS_SESSION_BUS_ADDRESS-}}" >> '{log}'
case "${{FAKE_DBUS:-down}}" in
  up) exit 0 ;;
  fallback) [ -z "${{DBUS_SESSION_BUS_ADDRESS+x}}" ] ;;
  *) exit 1 ;;
esac
"""


def lan_self_connect():
    """(address, answers): this machine's non-loopback IPv4 address, and whether it accepts a
    connection from this machine. Both are what start_target --lan depends on."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.0.2.1", 9))
        ip = s.getsockname()[0]
    except OSError:
        return "", False
    finally:
        s.close()
    if ip.startswith("127."):
        return "", False
    socks = [socket.socket()]
    try:
        srv = socks[0]
        srv.bind((ip, 0))
        srv.listen(1)
        srv.settimeout(3)
        socks.append(socket.create_connection(srv.getsockname(), timeout=3))
        socks.append(srv.accept()[0])
        socks[1].sendall(b"x")
        socks[2].settimeout(3)
        return ip, socks[2].recv(1) == b"x"
    except OSError:
        return ip, False
    finally:
        for sock in socks:
            sock.close()


def write_exe(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)


class Extract(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="e2e-extract-test-")
        self.docs = os.path.join(self.tmp, "docs")
        os.makedirs(self.docs)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def md(self, name, text):
        with open(os.path.join(self.docs, name), "w") as fh:
            fh.write(text)

    def extract(self, *args):
        return subprocess.run([sys.executable, EXTRACT, "--root", self.docs] + list(args),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)

    def assertProblem(self, fragment):
        proc = self.extract("list")
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn(fragment, proc.stdout)
        self.assertRegex(proc.stdout, r"\.md:\d+: ")
        self.assertIn("extract.py: FAILED", proc.stdout)

    def test_list_script_and_emit(self):
        """extract: blocks join in document order; e2e-file content lands in the work directory"""
        self.md("a.md", "# A\n\n<!-- e2e: alpha -->\n```bash\necho one\n```\n\ntext\n\n"
                        "<!-- e2e-file: alpha payload.json -->\n```json\n{\"k\": 1}\n```\n\n"
                        "<!-- e2e: alpha expect-fail -->\n```\nfalse\n```\n")
        self.md("b.md", "<!-- e2e: beta -->\n```sh\necho beta\n```\n")
        proc = self.extract("list")
        self.assertEqual(proc.returncode, 0, proc.stdout)
        names = [line.split("\t")[0] for line in proc.stdout.splitlines()]
        self.assertEqual(names, ["alpha", "beta"])
        script = self.extract("script", "alpha").stdout
        self.assertLess(script.index("echo one"), script.index("false"))
        self.assertIn("expect-fail", script)
        out = os.path.join(self.tmp, "out")
        self.assertEqual(self.extract("emit", "alpha", out).returncode, 0)
        with open(os.path.join(out, ".e2e", "blocks")) as fh:
            rows = [line.rstrip("\n").split("\t") for line in fh]
        self.assertEqual([(r[0], r[1]) for r in rows], [("1", "ok"), ("2", "fail")])
        self.assertTrue(rows[0][2].endswith("a.md:3"), rows)
        with open(os.path.join(out, ".e2e", "block-1.sh")) as fh:
            self.assertEqual(fh.read().splitlines()[1], "echo one")
        with open(os.path.join(out, "payload.json")) as fh:
            self.assertEqual(fh.read(), '{"k": 1}\n')

    def test_markers_inside_fences_are_ignored(self):
        """extract: a marker shown inside a code block is documentation, not a marker"""
        self.md("a.md", "````markdown\n<!-- e2e: shown -->\n```bash\necho no\n```\n````\n")
        proc = self.extract("list")
        self.assertEqual((proc.returncode, proc.stdout), (0, ""))

    def test_unknown_case(self):
        """extract: asking for a case that does not exist fails"""
        self.md("a.md", "<!-- e2e: alpha -->\n```bash\ntrue\n```\n")
        proc = self.extract("script", "gamma")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("no case 'gamma'", proc.stderr)

    def test_marker_problems(self):
        """extract: every malformed or misplaced marker is an error with FILE:LINE"""
        cases = [
            ("<!-- e2e alpha -->\n```bash\ntrue\n```\n", "malformed e2e marker"),
            ("<!-- e2e: alpha -->\n\n```bash\ntrue\n```\n", "must be on the line directly before a fenced code block"),
            ("<!-- e2e: alpha -->\n```bash\ntrue\n", "is never closed"),
            ("<!-- e2e: alpha -->\n```json\n{}\n```\n", "must be bash, sh, shell or untagged, not 'json'"),
            ("<!-- e2e: alpha -->\n```bash\n$ fabric agent-gateway whoami\n```\n", "must not contain '$ ' prompts"),
            ("<!-- e2e: alpha later -->\n```bash\ntrue\n```\n", "expected <!-- e2e: CASE -->"),
            ("<!-- e2e: al/pha -->\n```bash\ntrue\n```\n", "expected <!-- e2e: CASE -->"),
            ("<!-- e2e: alpha -->\n```bash\ntrue\n```\n<!-- e2e-file: alpha ../x.json -->\n```json\n{}\n```\n",
             "NAME a plain file name"),
            ("<!-- e2e: alpha -->\n```bash\ntrue\n```\n<!-- e2e-file: alpha x.json -->\n```json\n{}\n```\n"
             "<!-- e2e-file: alpha x.json -->\n```json\n{}\n```\n", "writes x.json twice"),
            ("<!-- e2e-file: alpha x.json -->\n```json\n{}\n```\n", "has files but no e2e blocks"),
        ]
        for text, fragment in cases:
            with self.subTest(fragment):
                self.md("a.md", text)
                self.assertProblem(fragment)

    def test_case_split_across_files(self):
        """extract: a case's blocks must all be in one Markdown file"""
        self.md("a.md", "<!-- e2e: alpha -->\n```bash\ntrue\n```\n")
        self.md("b.md", "<!-- e2e: alpha -->\n```bash\ntrue\n```\n")
        self.assertProblem("a case's blocks must be in one file")


class Runner(unittest.TestCase):
    TOKEN = "e2e-unit-token-5f3a9c1d"
    HOST = "http://gateway.example.test:8080"

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="e2e-runner-test-")
        self.home = os.path.join(self.tmp, "real-home")
        self.tmpdir = os.path.join(self.tmp, "tmpdir")
        self.docs = os.path.join(self.tmp, "docs")
        self.cases = os.path.join(self.tmp, "cases")
        self.bin = os.path.join(self.tmp, "bin")
        self.marks = os.path.join(self.tmp, "marks")
        for d in (self.home, self.tmpdir, self.docs, self.cases, self.bin, self.marks):
            os.makedirs(d)
        self.fabric_log = os.path.join(self.tmp, "fabric.log")
        self.security_log = os.path.join(self.tmp, "security.log")
        self.dbus_log = os.path.join(self.tmp, "dbus.log")
        self.settings_state = os.path.join(self.tmp, "settings.json")
        write_exe(os.path.join(self.bin, "fabric"), FAKE_FABRIC.format(log=self.fabric_log, settings=self.settings_state))
        # Every runner test gets the fake security and dbus-send, so no test can reach the real ones.
        write_exe(os.path.join(self.bin, "security"),
                  FAKE_SECURITY.format(log=self.security_log, real_home=self.home))
        write_exe(os.path.join(self.bin, "dbus-send"), FAKE_DBUS_SEND.format(log=self.dbus_log))
        for tool in ("security", "dbus-send"):
            found = shutil.which(tool, path=self.env()["PATH"])
            self.assertEqual(found, os.path.join(self.bin, tool), "the fake %s must shadow the real one" % tool)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def fake_uname(self, system):
        write_exe(os.path.join(self.bin, "uname"), "#!/bin/sh\necho %s\n" % system)

    def env(self, **extra):
        env = {
            "PATH": self.bin + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": self.home,
            "TMPDIR": self.tmpdir,
            "PYTHON": sys.executable,
            "FABRIC": "fabric",
            "FABRIC_E2E_HOST": self.HOST,
            "FABRIC_E2E_TOKEN": self.TOKEN,
            "E2E_DOCS_ROOT": self.docs,
            "E2E_CASES_DIR": self.cases,
            "MARKS": self.marks,
            "LANG": "C",
        }
        env.update(extra)
        return {k: v for k, v in env.items() if v is not None}

    def recipe(self, case, *blocks, expect_fail=(), files=None, doc="recipes.md"):
        parts = ["# Recipes\n"]
        for name, content in (files or {}).items():
            parts.append("<!-- e2e-file: %s %s -->\n```json\n%s\n```\n" % (case, name, content))
        for n, block in enumerate(blocks, start=1):
            marker = "%s expect-fail" % case if n in expect_fail else case
            parts.append("<!-- e2e: %s -->\n```bash\n%s\n```\n" % (marker, block))
        path = os.path.join(self.docs, doc)
        with open(path, "a") as fh:
            fh.write("\n".join(parts))

    def case(self, name, text):
        with open(os.path.join(self.cases, name + ".sh"), "w") as fh:
            fh.write(text)

    def run_e2e(self, *cases, **env):
        proc = subprocess.run([RUN] + list(cases), env=self.env(**env), cwd=self.tmp,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=120)
        self.assertNotIn(self.TOKEN, proc.stdout + proc.stderr, "the token was printed")
        return proc

    def fabric_calls(self):
        if not os.path.exists(self.fabric_log):
            return []
        with open(self.fabric_log) as fh:
            return [line for line in fh.read().splitlines() if line.startswith("ARGV")]

    def security_calls(self):
        if not os.path.exists(self.security_log):
            return []
        with open(self.security_log) as fh:
            return fh.read().splitlines()

    def real_home_security_calls(self):
        prefix = "HOME=%s security " % self.home
        return [c[len(prefix):] for c in self.security_calls() if c.startswith(prefix)]

    def mark(self, name):
        return os.path.exists(os.path.join(self.marks, name))

    def assertWorkRemoved(self):
        self.assertEqual(os.listdir(self.tmpdir), [], "run.sh left its work directory behind")

    # ---- usage -------------------------------------------------------------------------------

    def test_help(self):
        """e2e runner: --help prints the usage and exits 0"""
        proc = subprocess.run([RUN, "--help"], stdout=subprocess.PIPE, universal_newlines=True, env=self.env())
        self.assertEqual(proc.returncode, 0)
        self.assertIn("FABRIC_E2E_HOST", proc.stdout)
        self.assertNotIn("set -euo pipefail", proc.stdout)

    def test_refuses_without_host_or_token(self):
        """e2e runner: refuses to run when the host or token is unset or the host is not a URL"""
        for extra, fragment in (({"FABRIC_E2E_HOST": None}, "FABRIC_E2E_HOST is not set"),
                                ({"FABRIC_E2E_TOKEN": None}, "FABRIC_E2E_TOKEN is not set"),
                                ({"FABRIC_E2E_HOST": "gateway:8080"}, "must start with http:// or https://"),
                                ({"FABRIC": "no-such-fabric"}, "fabric binary not found")):
            with self.subTest(fragment):
                proc = self.run_e2e(**extra)
                self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
                self.assertIn(fragment, proc.stderr)
        self.assertEqual(self.fabric_calls(), [])

    def test_no_cases(self):
        """e2e runner: finding no case to run is a failure, not a pass"""
        with open(os.path.join(self.docs, "empty.md"), "w") as fh:
            fh.write("# Nothing here\n")
        proc = self.run_e2e()
        self.assertEqual(proc.returncode, 1)
        self.assertIn("e2e: FAILED, no cases ran", proc.stdout)

    def test_recipes_without_case_file_are_noted(self):
        """e2e runner: recipe blocks with no case file are reported and not run"""
        self.recipe("orphan", "fabric agent-gateway whoami -o json")
        proc = self.run_e2e()
        self.assertEqual(proc.returncode, 1)
        self.assertIn("orphan", proc.stderr)
        self.assertIn("no case file; not run", proc.stderr)
        self.assertEqual(self.fabric_calls(), [])

    def test_named_case_without_case_file_is_refused(self):
        """e2e runner: naming a case that has no case file refuses it"""
        self.recipe("orphan", "fabric agent-gateway whoami -o json")
        proc = self.run_e2e("orphan")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("REFUSED orphan", proc.stdout)
        self.assertIn("no case file", proc.stderr)

    def test_marker_problems_stop_the_run(self):
        """e2e runner: malformed markers fail the run before any case starts"""
        with open(os.path.join(self.docs, "bad.md"), "w") as fh:
            fh.write("<!-- e2e: bad -->\n\n```bash\nfabric agent-gateway whoami\n```\n")
        self.case("bad", "")
        proc = self.run_e2e()
        self.assertEqual(proc.returncode, 1)
        self.assertIn("must be on the line directly before a fenced code block", proc.stdout)
        self.assertEqual(self.fabric_calls(), [])

    # ---- a passing case ------------------------------------------------------------------------

    def test_sample_case_passes_in_a_sandbox(self):
        """e2e runner: blocks run in order in a sandbox with the saved connection and the token"""
        self.recipe("sample", "fabric agent-gateway whoami -o json", "fabric agent-gateway show-file payload.json",
                    "if env | grep -F '%s'; then exit 1; fi" % self.home,
                    files={"payload.json": '{"name": "demo"}'})
        self.case("sample", "\n".join([
            "setup() { : > \"$MARKS/setup\"; }",
            "cleanup() { : > \"$MARKS/cleanup\"; }",
            "verify() {",
            "    expect_json 1 'doc[\"authenticated\"] is True and doc[\"host\"] == env[\"GATEWAY\"]' 'whoami'",
            "    expect_block 2 '\"name\": \"demo\"'",
            "    [ -z \"${E2E_REAL_HOME+x}${real_home+x}\" ] || fail 'the real HOME is visible to the case'",
            "    pass 'no real HOME in the case'",
            "    for f in real_keychains keychain_restore_hint keychain_start keychain_stop finish_run remove_work refuse_run; do",
            "        ! declare -F \"$f\" >/dev/null || fail \"the runner's $f is visible to the case\"",
            "    done",
            "    pass 'no keychain function of the runner in the case'",
            "}", ""]))
        proc = self.run_e2e(E2E_REAL_HOME=self.home)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("PASS    sample", proc.stdout)
        self.assertIn("ok: block 1: whoami", proc.stdout + proc.stderr)
        self.assertEqual(proc.stdout.splitlines()[-1], "e2e: OK, 1 passed (1 cases)")
        self.assertIn("ok: no keychain function of the runner in the case", proc.stdout)
        self.assertTrue(self.mark("setup") and self.mark("cleanup"))
        calls = self.fabric_calls()
        self.assertEqual([c.split(" HOME=")[0] for c in calls],
                         ["ARGV [agent-gateway] [whoami] [-o] [json]", "ARGV [agent-gateway] [show-file] [payload.json]"])
        for call in calls:
            self.assertIn("TOKEN=set", call)
            self.assertNotIn("HOME=" + self.home + " ", call)
        with open(self.fabric_log) as fh:
            log = fh.read()
        expected_dir = ("Library/Application Support/fabric/config.toml" if platform.system() == "Darwin"
                        else ".config/fabric/config.toml")
        self.assertRegex(log, r"CONFIG .*/home/" + re.escape(expected_dir))
        self.assertIn('CONFIG| current = "e2e"', log)
        self.assertIn("CONFIG| [connections.e2e]", log)
        self.assertIn('CONFIG| host = "%s"' % self.HOST, log)
        self.assertNotIn("token", log.lower().replace("token=set", ""))
        self.assertWorkRemoved()
        self.assertEqual(os.listdir(self.home), [], "the real HOME must not be touched")

    def test_expect_fail_block(self):
        """e2e runner: a block marked expect-fail must fail, and expect_fail_block checks its output"""
        self.recipe("errors", "fabric agent-gateway whoami -o json", "fabric agent-gateway boom", expect_fail=(2,))
        self.case("errors", "verify() { expect_fail_block 2 'error: boom'; }\n")
        proc = self.run_e2e()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("PASS    errors", proc.stdout)

    def test_expect_fail_block_that_succeeds(self):
        """e2e runner: a block marked expect-fail that exits 0 fails the case"""
        self.recipe("errors", "fabric agent-gateway whoami -o json", expect_fail=(1,))
        self.case("errors", "")
        proc = self.run_e2e()
        self.assertEqual(proc.returncode, 1)
        self.assertIn("was marked expect-fail but exited 0", proc.stderr)

    # ---- failures ------------------------------------------------------------------------------

    def test_failing_block_fails_and_cleanup_still_runs(self):
        """e2e runner: a failing block fails the case, later blocks do not run, cleanup runs"""
        self.recipe("broken", "fabric agent-gateway boom", "fabric agent-gateway whoami -o json")
        self.case("broken", "cleanup() { : > \"$MARKS/cleanup\"; }\nverify() { : > \"$MARKS/verify\"; }\n")
        proc = self.run_e2e()
        self.assertEqual(proc.returncode, 1)
        self.assertIn("FAIL    broken", proc.stdout)
        self.assertRegex(proc.stderr, r"fail: block 1 \(.*recipes\.md:\d+\) exited 1")
        self.assertIn("| error: boom", proc.stderr)
        self.assertEqual(proc.stdout.splitlines()[-1], "e2e: FAILED, 0 passed, 1 failed, 0 refused (1 cases)")
        self.assertTrue(self.mark("cleanup"))
        self.assertFalse(self.mark("verify"))
        self.assertEqual(len(self.fabric_calls()), 1)
        self.assertWorkRemoved()

    def test_failing_verify(self):
        """e2e runner: an expectation that does not hold fails the case"""
        self.recipe("wrong", "fabric agent-gateway whoami -o json")
        self.case("wrong", "verify() { expect_json 1 'doc[\"connection\"] == \"prod\"' 'connection is prod'; }\n")
        proc = self.run_e2e()
        self.assertEqual(proc.returncode, 1)
        self.assertIn("fail: block 1: connection is prod", proc.stderr)

    def test_failing_cleanup(self):
        """e2e runner: a cleanup that fails turns the case into a failure"""
        self.recipe("messy", "fabric agent-gateway whoami -o json")
        self.case("messy", "cleanup() { false; }\n")
        proc = self.run_e2e()
        self.assertEqual(proc.returncode, 1)
        self.assertIn("cleanup exited 1; the case may have left resources behind", proc.stderr)

    def test_token_is_redacted_from_failure_output(self):
        """e2e runner: output shown for a failure has the token replaced"""
        self.recipe("leaky", "fabric agent-gateway leak")
        self.case("leaky", "")
        proc = self.run_e2e()
        self.assertEqual(proc.returncode, 1)
        self.assertIn("the token is <redacted>", proc.stderr)

    # ---- the keychain guard: the scan before a case runs ---------------------------------------

    def assertScanRefusal(self, proc, name):
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("REFUSED " + name, proc.stdout)
        self.assertIn("names login, logout, config remove or agent-gateway shell", proc.stderr)

    def test_login_recipe_is_refused(self):
        """e2e runner: a recipe that signs in, signs out, removes a connection or opens the shell is refused before setup"""
        variants = [
            'fabric agent-gateway login --host "$GATEWAY" --token-stdin <<<"$FABRIC_TOKEN"',
            "fabric agent-gateway -c e2e logout",
            '"$FABRIC" agent-gateway login --paste',
            "${FABRIC} agent-gateway logout",
            "fab agent-gateway login",
            "echo x | fabric agent-gateway --host \"$GATEWAY\" login --token-stdin",
            'f=fabric; "$f" agent-gateway logout',
            "fabric agent-gateway config  remove e2e",
            "fabric agent-gateway shell < /dev/null",
        ]
        for n, block in enumerate(variants):
            with self.subTest(block):
                name = "signin%d" % n
                self.recipe(name, block, doc=name + ".md")
                self.case(name, "setup() { : > \"$MARKS/setup-%s\"; }\n" % name)
                proc = self.run_e2e(name)
                self.assertScanRefusal(proc, name)
                self.assertFalse(self.mark("setup-" + name))
        self.assertEqual(self.fabric_calls(), [])

    def test_case_file_and_written_files_are_scanned(self):
        """e2e runner: the case file and the files a recipe writes are scanned too, before setup"""
        self.recipe("casefile", "fabric agent-gateway whoami -o json", doc="casefile.md")
        self.case("casefile", 'setup() { : > "$MARKS/setup"; fab agent-gateway logout; }\n')
        self.recipe("written", "bash script.sh", files={"script.sh": "fabric agent-gateway config remove e2e"}, doc="written.md")
        self.case("written", 'setup() { : > "$MARKS/setup"; }\n')
        for name in ("casefile", "written"):
            with self.subTest(name):
                self.assertScanRefusal(self.run_e2e(name), name)
        self.assertFalse(self.mark("setup"))
        self.assertEqual(self.fabric_calls(), [])

    def test_unreadable_case_file_is_refused(self):
        """e2e runner: a case file the scan cannot read is refused, not passed"""
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            self.skipTest("root reads any file")
        self.recipe("locked", "fabric agent-gateway whoami -o json")
        self.case("locked", "")
        os.chmod(os.path.join(self.cases, "locked.sh"), 0)
        proc = self.run_e2e("locked")
        self.assertScanRefusal(proc, "locked")
        self.assertIn("locked.sh: cannot be read", proc.stderr)
        self.assertEqual(self.fabric_calls(), [])

    def test_a_doc_path_is_not_a_finding(self):
        """e2e runner: a recipe in a file whose name holds login is not refused for its path"""
        self.recipe("notes", "fabric agent-gateway whoami -o json", doc="login-notes.md")
        self.case("notes", "")
        proc = self.run_e2e()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("PASS    notes", proc.stdout)

    def test_keychains_dir_fails_the_block_and_refuses_later_cases(self):
        """e2e runner: a block that creates Library/Keychains fails; the next case is refused"""
        self.recipe("a-first", "fabric agent-gateway mkkeychains", doc="a.md")
        self.recipe("b-second", "fabric agent-gateway whoami -o json", doc="b.md")
        self.case("a-first", "")
        self.case("b-second", "")
        proc = self.run_e2e()
        self.assertEqual(proc.returncode, 1)
        self.assertIn("FAIL    a-first", proc.stdout)
        self.assertIn("created Library/Keychains in the sandbox HOME", proc.stderr)
        self.assertIn("REFUSED b-second", proc.stdout)
        self.assertEqual(proc.stdout.splitlines()[-1], "e2e: FAILED, 0 passed, 1 failed, 1 refused (2 cases)")
        self.assertEqual(len(self.fabric_calls()), 1)

    # ---- the keychain guard: one throwaway keychain per run on macOS ---------------------------

    def two_cases(self):
        self.recipe("first", "fabric agent-gateway whoami -o json", doc="a.md")
        self.recipe("second", "fabric agent-gateway whoami -o json", doc="b.md")
        self.case("first", "")
        self.case("second", "")

    def test_run_keychain_is_created_once_and_removed(self):
        """e2e runner: on macOS one keychain inside the sandbox serves the whole run and is deleted"""
        self.fake_uname("Darwin")
        self.two_cases()
        proc = self.run_e2e(FAKE_SECURITY_MODE="isolating")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(proc.stdout.splitlines()[-1], "e2e: OK, 2 passed (2 cases)")
        calls = self.security_calls()
        creates = [c for c in calls if " create-keychain " in c]
        self.assertEqual(len(creates), 1, calls)
        keychain = creates[0].rsplit(" ", 1)[1]
        self.assertTrue(keychain.startswith(os.path.realpath(self.tmpdir)), keychain)
        self.assertFalse(os.path.exists(keychain))
        self.assertEqual(sum(" delete-keychain " in c for c in calls), 1, calls)
        # The probe: the real state is read right after create-keychain, before the search list is set.
        i = calls.index(creates[0])
        self.assertEqual(calls[i + 1], "HOME=%s security list-keychains -d user" % self.home)
        self.assertTrue(calls[i + 3].endswith(" security list-keychains -d user -s " + keychain), calls[i + 3])
        self.assertEqual(set(self.real_home_security_calls()), {"list-keychains -d user", "default-keychain -d user"})
        self.assertFalse(os.path.exists(os.path.join(self.home, ".fake-security")))
        self.assertWorkRemoved()

    def test_run_refused_when_security_ignores_home(self):
        """e2e runner: if security shows the real search list inside the sandbox, nothing is created"""
        self.fake_uname("Darwin")
        self.two_cases()
        proc = self.run_e2e(FAKE_SECURITY_MODE="shared")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("does not isolate keychain preferences", proc.stderr)
        self.assertEqual(proc.stdout.splitlines()[-1], "e2e: FAILED, refused before any case ran")
        self.assertFalse(any(" create-keychain " in c for c in self.security_calls()))
        self.assertEqual(set(self.real_home_security_calls()), {"list-keychains -d user", "default-keychain -d user"})
        self.assertEqual(self.fabric_calls(), [])
        self.assertWorkRemoved()

    def test_run_refused_when_the_probe_write_leaks(self):
        """e2e runner: a probe write that reaches the real search list stops the run before any case"""
        self.fake_uname("Darwin")
        self.two_cases()
        proc = self.run_e2e(FAKE_SECURITY_MODE="leaky")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("changed the real keychain search list", proc.stderr)
        self.assertEqual(proc.stdout.splitlines()[-1], "e2e: FAILED, refused before any case ran")
        calls = self.security_calls()
        self.assertEqual(sum(" create-keychain " in c for c in calls), 1, calls)
        self.assertFalse(any(" -s " in c for c in calls), "the search list was replaced after a leak")
        self.assertTrue(any(" delete-keychain " in c for c in calls), calls)
        self.assertEqual(self.fabric_calls(), [])
        self.assertRestoreHint(proc)
        self.assertIn("after the throwaway keychain was deleted, the real keychain state matches the saved state again",
                      proc.stderr)

    def assertRestoreHint(self, proc):
        """The saved real state and the restore commands are printed once, and never run."""
        login = os.path.join(self.home, "Library/Keychains/login.keychain-db")
        self.assertEqual(proc.stderr.count("the real keychain state before the run was:"), 1, proc.stderr)
        self.assertIn('    search list:\n        "%s"\n    default keychain:\n        "%s"\n' % (login, login), proc.stderr)
        self.assertIn("run these yourself; run.sh does not run them:\n"
                      "    security list-keychains -d user -s %s\n"
                      "    security default-keychain -d user -s %s\n" % (login, login), proc.stderr)
        self.assertEqual(set(self.real_home_security_calls()), {"list-keychains -d user", "default-keychain -d user"},
                         "the runner ran a restore command")

    def test_run_fails_when_the_real_state_changes_during_the_run(self):
        """e2e runner: a change to the real default keychain during the run fails it at the end"""
        self.fake_uname("Darwin")
        state = os.path.join(self.home, ".fake-security")
        self.recipe("meddle", "mkdir -p '%s'\nprintf '    \"/elsewhere.keychain-db\"\\n' > '%s/default-keychain'\n"
                              "fabric agent-gateway whoami -o json" % (state, state))
        self.case("meddle", "")
        proc = self.run_e2e(FAKE_SECURITY_MODE="isolating")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("PASS    meddle", proc.stdout)
        self.assertIn("default keychain changed during the run", proc.stderr)
        self.assertEqual(proc.stdout.splitlines()[-1],
                         "e2e: FAILED, the keychain check at the end of the run failed (1 cases)")
        self.assertRestoreHint(proc)

    # ---- the keychain guard: no session bus -----------------------------------------------------

    def test_session_bus_is_out_of_reach(self):
        """e2e runner: blocks get a D-Bus address with no bus, a private XDG_RUNTIME_DIR and no display"""
        self.fake_uname("Linux")
        self.recipe("bus", "\n".join([
            'printf "%s;%s;%s;%s\\n" "$DBUS_SESSION_BUS_ADDRESS" "$XDG_RUNTIME_DIR" "${DISPLAY-unset}" "${WAYLAND_DISPLAY-unset}"',
            'ls -ld "$XDG_RUNTIME_DIR"',
            "fabric agent-gateway whoami -o json"]))
        self.case("bus", 'verify() {\n    expect_block 1 "^unix:path=$E2E_WORK/no-bus;$E2E_WORK/run;unset;unset$"\n'
                         '    expect_block 1 "^drwx------"\n}\n')
        proc = self.run_e2e(DISPLAY=":0", WAYLAND_DISPLAY="wayland-0", XDG_RUNTIME_DIR="/run/user/1000",
                            DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/1000/bus")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        with open(self.dbus_log) as fh:
            probe = fh.read()
        self.assertIn("--session", probe)
        # Probed twice: with the address fabric sees, and with none, as a block that unsets it would.
        self.assertRegex(probe, r"(?m)^dbus-send --session .* ADDRESS=unix:path=\S+/no-bus$")
        self.assertRegex(probe, r"(?m)^dbus-send --session .* ADDRESS=$")
        self.assertEqual(self.security_calls(), [])

    def test_run_refused_when_a_session_bus_answers(self):
        """e2e runner: the run is refused before any case when a session bus answers, with or without the address"""
        self.fake_uname("Linux")
        self.two_cases()
        for mode in ("up", "fallback"):
            with self.subTest(mode):
                proc = self.run_e2e(FAKE_DBUS=mode)
                self.assertEqual(proc.returncode, 1)
                self.assertIn("a D-Bus session bus answers inside the sandbox", proc.stderr)
                self.assertEqual(proc.stdout.splitlines()[-1], "e2e: FAILED, refused before any case ran")
                self.assertEqual(self.fabric_calls(), [])
                self.assertWorkRemoved()

    def test_run_refused_without_dbus_send_off_macos(self):
        """e2e runner: off macOS, a run with no dbus-send to probe the session bus is refused"""
        self.fake_uname("Linux")
        self.two_cases()
        os.remove(os.path.join(self.bin, "dbus-send"))
        # Hide a real dbus-send too: its directory is replaced by links to everything else in it.
        path = [self.bin]
        for n, d in enumerate(os.environ.get("PATH", "/usr/bin:/bin").split(os.pathsep)):
            if d and os.path.isfile(os.path.join(d, "dbus-send")):
                shadow = os.path.join(self.tmp, "path-%d" % n)
                os.makedirs(shadow)
                for name in os.listdir(d):
                    if name != "dbus-send":
                        os.symlink(os.path.join(d, name), os.path.join(shadow, name))
                d = shadow
            path.append(d)
        env_path = os.pathsep.join(path)
        self.assertIsNone(shutil.which("dbus-send", path=env_path))
        proc = self.run_e2e(PATH=env_path)
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("dbus-send is not available", proc.stderr)
        self.assertEqual(proc.stdout.splitlines()[-1], "e2e: FAILED, refused before any case ran")
        self.assertEqual(self.fabric_calls(), [])
        self.assertWorkRemoved()

    def test_macos_needs_no_dbus_send(self):
        """e2e runner: on macOS the D-Bus probe does not run, so a missing dbus-send is not a refusal"""
        self.fake_uname("Darwin")
        self.two_cases()
        os.remove(os.path.join(self.bin, "dbus-send"))
        proc = self.run_e2e(FAKE_SECURITY_MODE="isolating")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertFalse(os.path.exists(self.dbus_log))

    # ---- the fabric wrapper --------------------------------------------------------------------

    def assertRuntimeRefusal(self, proc, name, fragment):
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("REFUSED " + name, proc.stdout)
        self.assertIn("refused: the e2e guard refused a fabric call: ", proc.stderr)
        self.assertIn(fragment, proc.stderr)

    def test_wrapper_refuses_what_the_scan_cannot_see(self):
        """e2e runner: calls the scan cannot see are refused by the wrapper at run time"""
        variants = [
            ("printf 'fabric agent-gateway log%s\\n' out > hidden.sh\nbash hidden.sh", "runs fabric logout, which writes the OS keychain"),
            ('n=log\nfabric agent-gateway surfaces show "${n}in"', "runs fabric login, which writes the OS keychain"),
            ('c=config\nfabric agent-gateway "$c" remove e2e', "runs fabric config remove"),
            ("FABRIC_TOKEN= fabric agent-gateway whoami -o json", "FABRIC_TOKEN empty"),
            ("XDG_CONFIG_HOME=/tmp fabric agent-gateway whoami -o json", "HOME or XDG_CONFIG_HOME outside the sandbox"),
        ]
        for n, (block, fragment) in enumerate(variants):
            with self.subTest(block):
                name = "hidden%d" % n
                self.recipe(name, block, doc=name + ".md")
                self.case(name, 'verify() { : > "$MARKS/verify-%s"; }\n' % name)
                self.assertRuntimeRefusal(self.run_e2e(name), name, fragment)
                self.assertFalse(self.mark("verify-" + name))
        self.assertEqual(self.fabric_calls(), [])

    def test_wrapper_refusal_in_an_expect_fail_block_is_not_a_pass(self):
        """e2e runner: a refused call makes an expect-fail block refuse the case, not satisfy it"""
        self.recipe("notoken", "fabric agent-gateway whoami -o json", "unset FABRIC_TOKEN\nfabric agent-gateway whoami -o json", expect_fail=(2,))
        self.case("notoken", "verify() { expect_fail_block 2 'refused'; }\n")
        proc = self.run_e2e()
        self.assertRuntimeRefusal(proc, "notoken", "FABRIC_TOKEN empty")
        self.assertEqual(len(self.fabric_calls()), 1)

    def test_fab_and_FABRIC_go_through_the_wrapper(self):
        """e2e runner: fab and $FABRIC in a case file are the wrapper, and its refusals refuse the case"""
        self.recipe("casefab", "fabric agent-gateway whoami -o json")
        self.case("casefab", "\n".join([
            "setup() {",
            '    case "$FABRIC" in "$E2E_WORK"/bin/fabric) ;; *) fail "FABRIC is not the wrapper: $FABRIC" ;; esac',
            '    [ "$(command -v fabric)" = "$FABRIC" ] || fail "fabric on PATH is not the wrapper"',
            "    ( unset FABRIC_TOKEN; fab agent-gateway whoami -o json ) || true",
            '    ( HOME=/ "$FABRIC" agent-gateway whoami -o json ) || true',
            "}", ""]))
        proc = self.run_e2e()
        self.assertRuntimeRefusal(proc, "casefab", "FABRIC_TOKEN empty")
        self.assertIn("HOME or XDG_CONFIG_HOME outside the sandbox", proc.stderr)
        self.assertEqual(len(self.fabric_calls()), 1)

    def test_wrapper_refuses_bare_fabric_and_a_legacy_token_line(self):
        """e2e runner: bare fabric, bare fabric agent-gateway and a config.toml `token =` line are refused at run time"""
        self.recipe("bare", 'f=fabric\n"$f" < /dev/null || true', doc="bare.md")
        self.case("bare", "")
        self.recipe("baregroup", 'fabric agent-gateway < /dev/null || true', doc="baregroup.md")
        self.case("baregroup", "")
        self.recipe("legacy", "\n".join([
            'for c in "$HOME/Library/Application Support/fabric/config.toml" "$XDG_CONFIG_HOME/fabric/config.toml"; do',
            '    if [ -f "$c" ]; then printf \'%s = "legacy"\\n\' token >> "$c"; fi',
            "done",
            "fabric agent-gateway whoami -o json"]), doc="legacy.md")
        self.case("legacy", "")
        proc = self.run_e2e("bare", "baregroup", "legacy")
        self.assertIn("REFUSED bare", proc.stdout)
        self.assertIn("REFUSED baregroup", proc.stdout)
        self.assertIn("REFUSED legacy", proc.stdout)
        self.assertEqual(proc.stderr.count("runs fabric with no subcommand after agent-gateway"), 2, proc.stderr)
        self.assertIn("holds a token line", proc.stderr)
        self.assertEqual(self.fabric_calls(), [])

    def test_wrapper_refuses_global_options_with_no_subcommand(self):
        """e2e runner: global options and their values without a subcommand are refused, as bare fabric is"""
        nosub = "runs fabric with no subcommand after agent-gateway"
        variants = [
            ("printf 'whoami\\n' | fabric agent-gateway -o json", nosub),
            ('fabric agent-gateway -c e2e --host "$GATEWAY" < /dev/null', nosub),
            ("fabric agent-gateway --output=json -cother -ojson --allow-http --", nosub),
            ("fabric agent-gateway --token whoami", nosub),
            ("fabric agent-gateway --frobnicate whoami", "runs fabric with --frobnicate before any subcommand"),
            ("fabric agent-gateway --tokn=hidden-value-789 whoami", "runs fabric with --tokn before any subcommand"),
            ("fabric -o json agent-gateway whoami", "runs fabric with -o before agent-gateway"),
            ("fabric --tokn=hidden-value-789 agent-gateway whoami", "runs fabric with --tokn before agent-gateway"),
        ]
        for n, (block, fragment) in enumerate(variants):
            with self.subTest(block):
                name = "nosub%d" % n
                self.recipe(name, block, doc=name + ".md")
                self.case(name, "")
                proc = self.run_e2e(name)
                self.assertRuntimeRefusal(proc, name, fragment)
                self.assertNotIn("hidden-value-789", proc.stdout + proc.stderr)
        self.assertEqual(self.fabric_calls(), [])

    def test_wrapper_refuses_the_shell(self):
        """e2e runner: fabric agent-gateway shell is refused at run time, whatever global options precede it"""
        variants = [
            "fabric agent-gateway --allow-http shell < /dev/null",
            'fabric agent-gateway -c e2e --host "$GATEWAY" shell < /dev/null',
            's=shell\n"$FABRIC" agent-gateway -o json "$s" < /dev/null',
        ]
        for n, block in enumerate(variants):
            with self.subTest(block):
                name = "shell%d" % n
                self.recipe(name, block, doc=name + ".md")
                self.case(name, "")
                self.assertRuntimeRefusal(self.run_e2e(name), name, "runs fabric agent-gateway shell, the interactive shell")
        self.assertEqual(self.fabric_calls(), [])

    def test_wrapper_passes_global_options_before_a_subcommand(self):
        """e2e runner: global options after agent-gateway and before a subcommand, --version and --help reach fabric"""
        self.recipe("globals", "\n".join([
            "fabric agent-gateway -o json whoami",
            'fabric agent-gateway --connection=e2e --host "$GATEWAY" -ojson --allow-http whoami',
            "fabric -V",
            "fabric --version"]))
        self.case("globals", "verify() { expect_json 1 'doc[\"authenticated\"] is True'; expect_block 1 'fabric 0.0.0-fake'; }\n")
        proc = self.run_e2e()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("PASS    globals", proc.stdout)
        self.assertEqual([c.split(" HOME=")[0] for c in self.fabric_calls()],
                         ["ARGV [agent-gateway] [-o] [json] [whoami]",
                          "ARGV [agent-gateway] [--connection=e2e] [--host] [%s] [-ojson] [--allow-http] [whoami]" % self.HOST,
                          "ARGV [-V]", "ARGV [--version]"])

    # ---- priority and serial cases -------------------------------------------------------------

    def test_p2_cases_are_excluded_by_name_unless_asked_for(self):
        """e2e runner: P2 cases are listed as excluded, and run when named or with E2E_PRIORITY=all"""
        self.recipe("alpha", "fabric agent-gateway whoami -o json", doc="a.md")
        self.recipe("beta", "fabric agent-gateway whoami -o json", doc="b.md")
        self.case("alpha", "")
        self.case("beta", "# priority: P2\n")
        proc = self.run_e2e()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("EXCLUDED beta (priority P2", proc.stdout)
        self.assertNotIn("RUN     beta", proc.stdout)
        self.assertEqual(proc.stdout.splitlines()[-1], "e2e: OK, 1 passed (1 cases); excluded 1 P2: beta")
        named = self.run_e2e("beta")
        self.assertIn("PASS    beta", named.stdout)
        self.assertNotIn("EXCLUDED", named.stdout)
        every = self.run_e2e(E2E_PRIORITY="all")
        self.assertEqual(every.stdout.splitlines()[-1], "e2e: OK, 2 passed (2 cases)")
        bad = self.run_e2e(E2E_PRIORITY="some")
        self.assertEqual(bad.returncode, 2)
        self.assertIn("E2E_PRIORITY must be empty or all", bad.stderr)

    def test_serial_case_must_restore_the_settings(self):
        """e2e runner: an E2E_SERIAL=1 case fails when the settings differ after cleanup"""
        change = "printf '%s\\n' '{\"audit_enabled\": true}' > on.json\nfabric agent-gateway settings set --file on.json -o json"
        self.recipe("tidy", change, doc="tidy.md")
        self.case("tidy", "E2E_SERIAL=1\ncleanup() {\n    printf '%s\\n' '{\"audit_enabled\": false}' > off.json\n"
                          "    fab agent-gateway settings set --file off.json -o json > /dev/null\n}\n")
        self.recipe("messy", change, doc="messy.md")
        self.case("messy", "E2E_SERIAL=1\n")
        proc = self.run_e2e("tidy", "messy")
        self.assertIn("PASS    tidy", proc.stdout)
        self.assertIn("ok: the appliance-wide settings are as they were before the case", proc.stdout)
        self.assertIn("FAIL    messy", proc.stdout)
        self.assertIn("E2E_SERIAL=1: the case did not restore these settings: audit_enabled", proc.stderr)

    # ---- helpers -------------------------------------------------------------------------------

    def test_helpers_start_read_and_clear_targets(self):
        """e2e runner: start_target, target_requests, clear_target, json_get and unique work together"""
        self.recipe("helpers", "\n".join([
            "curl -fsS --noproxy '*' -X POST \"$MCP_URL/mcp\" -H 'Content-Type: application/json' \\",
            "    -d '{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"initialize\"}'"]))
        self.case("helpers", "\n".join([
            "setup() {",
            "    start_target mcp",
            "    start_target a2a BETA_URL",
            "    clear_target MCP_URL",
            "    printf '%s\\n' $E2E_TARGET_PIDS > \"$MARKS/pids\"",
            "}",
            "verify() {",
            "    expect_block 1 '\"protocolVersion\": ?\"2024-11-05\"'",
            "    target_requests MCP_URL > seen.json",
            "    [ \"$(json_get seen.json 'len(doc)')\" = 1 ] || fail 'expected one request' seen.json",
            "    [ \"$(json_get seen.json 'doc[0][\"body\"][\"method\"]')\" = initialize ] || fail 'a string prints as is'",
            "    [ \"$(json_get seen.json 'doc[0][\"method\"] == \"POST\"')\" = true ] || fail 'a bool prints as JSON'",
            "    [ \"$(json_get seen.json 'doc[0].get(\"missing\")')\" = null ] || fail 'None prints as null'",
            "    [ \"$(json_get seen.json 'all(env[\"E2E_CASE\"] and r[\"path\"] == \"/mcp\" for r in doc)')\" = true ] \\",
            "        || fail 'a generator expression sees doc and env'",
            "    expect_json 1 'all(doc[\"result\"][k] for k in (\"protocolVersion\", \"serverInfo\"))' 'genexp in expect_json'",
            "    clear_target MCP_URL",
            "    [ \"$(target_requests MCP_URL)\" = '[]' ] || fail 'clear_target did not clear'",
            "    [ \"$(target_requests BETA_URL)\" = '[]' ] || fail 'the a2a target saw requests'",
            "    [ \"$(unique demo)\" = demo-run42 ] || fail \"unique demo is $(unique demo)\"",
            "    case \"$MCP_URL $BETA_URL\" in 'http://127.0.0.1:'*' http://127.0.0.1:'*) ;; *) fail 'loopback URLs' ;; esac",
            "    pass 'helpers'",
            "}", ""]))
        proc = self.run_e2e(E2E_RUN_ID="run42")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("ok: helpers", proc.stdout)
        with open(os.path.join(self.marks, "pids")) as fh:
            pids = [int(p) for p in fh.read().split()]
        self.assertEqual(len(pids), 2)
        for pid in pids:
            with self.assertRaises(OSError, msg="target %d still runs after the case" % pid):
                os.kill(pid, 0)

    def test_helper_misuse_fails_the_case(self):
        """e2e runner: an unknown target kind, an unset URL variable and a bad run id are errors"""
        for n, (setup, fragment) in enumerate((("start_target nope", "KIND must be mcp, a2a, a2a1, idp or rest"),
                                               ("target_requests NOPE_URL", "NOPE_URL is not set"),
                                               ("clear_target 'not a var'", "expected the name of a variable"),
                                               ("start_target mcp X --wide", "unknown option --wide"))):
            with self.subTest(setup):
                name = "misuse%d" % n
                self.recipe(name, "fabric agent-gateway whoami -o json", doc=name + ".md")
                self.case(name, "setup() { %s; }\n" % setup)
                proc = self.run_e2e(name)
                self.assertIn("FAIL    " + name, proc.stdout)
                self.assertIn(fragment, proc.stderr)
        proc = self.run_e2e(E2E_RUN_ID="Run-1")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("E2E_RUN_ID must be lowercase letters and digits only", proc.stderr)

    def test_lan_target(self):
        """e2e runner: start_target --lan binds a non-loopback IPv4 address, or refuses and says why"""
        self.recipe("lan", "fabric agent-gateway whoami -o json")
        self.case("lan", "\n".join([
            "setup() { start_target rest --lan; }",
            "verify() {",
            '    case "$LAN_HOST" in ""|127.*) fail "LAN_HOST is $LAN_HOST" ;; esac',
            '    case "$REST_URL" in "http://$LAN_HOST:"*) ;; *) fail "REST_URL is $REST_URL" ;; esac',
            "    pass lan",
            "}", ""]))
        proc = self.run_e2e(LAN_HOST="127.0.0.1")
        ip, answers = lan_self_connect()
        if not ip:
            self.assertIn("REFUSED lan", proc.stdout)
            self.assertIn("no non-loopback IPv4 address", proc.stderr)
        elif not answers:
            self.assertIn("REFUSED lan", proc.stdout)
            self.assertIn("does not answer a request from this machine", proc.stderr)
        else:
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertIn("ok: lan", proc.stdout)

    def test_loopback_target(self):
        """e2e runner: E2E_LOOPBACK_TARGETS puts a --lan target of a listed kind on 127.0.0.1 and its port"""
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()
        self.recipe("loop", "fabric agent-gateway whoami -o json", doc="loop.md")
        self.case("loop", "\n".join([
            "setup() { start_target idp IDP_URL --lan; }",
            "verify() {",
            '    [ "$LAN_HOST" = 127.0.0.1 ] || fail "LAN_HOST is $LAN_HOST"',
            '    [ "$IDP_URL" = "http://127.0.0.1:%d" ] || fail "IDP_URL is $IDP_URL"' % port,
            "    target_requests IDP_URL > /dev/null",
            "    pass loop",
            "}", ""]))
        self.recipe("twice", "fabric agent-gateway whoami -o json", doc="twice.md")
        self.case("twice", "setup() { start_target idp A_URL --lan; : > \"$MARKS/twice-first\"; start_target idp B_URL --lan; }\n")
        proc = self.run_e2e("loop", "twice", E2E_LOOPBACK_TARGETS="rest:9,idp:%d" % port)
        self.assertIn("ok: loop", proc.stdout, proc.stdout + proc.stderr)
        self.assertIn("PASS    loop", proc.stdout)
        self.assertIn("REFUSED twice", proc.stdout)
        self.assertTrue(self.mark("twice-first"), "the first loopback port leaked in from the previous case")
        self.assertIn("every E2E_LOOPBACK_TARGETS port for idp is already in use", proc.stderr)
        for bad in ("idp=%d" % port, "idp:%d,web:1" % port, "idp:0", "idp:65536", "idp:%d\nweb" % port):
            with self.subTest(bad):
                proc = self.run_e2e("loop", E2E_LOOPBACK_TARGETS=bad)
                self.assertEqual(proc.returncode, 2)
                self.assertIn("run.sh: E2E_LOOPBACK_TARGETS", proc.stderr)

    # ---- redaction -----------------------------------------------------------------------------

    def test_bearer_and_pat_values_are_redacted(self):
        """e2e runner: fail tails and case messages never show a PAT or a bearer value"""
        pat = "printf 'ag%s_%s' pat ABCDEFGHIJKLMNOPQRSTU"
        self.recipe("tail", "echo \"Authorization: Bearer opaque-value-123\"\necho \"$(%s)\"\nfalse" % pat, doc="tail.md")
        self.case("tail", "")
        self.recipe("says", "fabric agent-gateway whoami -o json", doc="says.md")
        self.case("says", "verify() { pass \"made $(%s)\"; pass \"sent X-API-Key: key-value-456\"; }\n" % pat)
        proc = self.run_e2e("tail", "says")
        out = proc.stdout + proc.stderr
        for secret in ("opaque-value-123", "ABCDEFGHIJKLMNOPQRSTU", "key-value-456"):
            self.assertNotIn(secret, out)
        self.assertIn("| Authorization: <redacted>", proc.stderr)
        self.assertIn("ok: made <redacted>", proc.stdout)
        self.assertIn("ok: sent X-API-Key: <redacted>", proc.stdout)

    def test_kept_work_directory_is_redacted(self):
        """e2e runner: E2E_KEEP=1 keeps the work directory with the token removed from block output"""
        self.recipe("kept", "fabric agent-gateway leak")
        self.case("kept", "")
        proc = self.run_e2e(E2E_KEEP="1")
        m = re.search(r"kept the work directory (\S+)", proc.stderr)
        self.assertIsNotNone(m, proc.stderr)
        kept = m.group(1)
        try:
            with open(os.path.join(kept, "kept", "block-1.out")) as fh:
                text = fh.read()
            self.assertIn("the token is <redacted>", text)
            for dirpath, _, filenames in os.walk(kept):
                for name in filenames:
                    path = os.path.join(dirpath, name)
                    if not os.path.islink(path):
                        with open(path, "rb") as fh:
                            self.assertNotIn(self.TOKEN.encode(), fh.read(), path)
        finally:
            shutil.rmtree(kept, ignore_errors=True)
            parent = os.path.dirname(kept)
            if os.path.basename(parent) == ".e2e-work" and not os.listdir(parent):
                os.rmdir(parent)


if __name__ == "__main__":
    unittest.main()
