"""Unit tests for tests/e2e/expr.py and the recorder secret in tests/e2e/targets.py."""

import json
import os
import subprocess
import sys
import unittest
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "tests", "e2e"))

import expr  # noqa: E402


class ExprTest(unittest.TestCase):
    def test_the_checks_the_cases_use_evaluate(self):
        doc = [{"path": "/mcp", "body": {"method": "tools/call"}, "headers": {"x": "abc"}}]
        for check in (
            'doc[0]["body"]["method"] == "tools/call"',
            'all(r["path"] == "/mcp" for r in doc)',
            'any(k.startswith("x") for k in doc[0]["headers"].keys())',
            'len(doc) == 1 and isinstance(doc, list) and doc[0].get("missing") is None',
            '{r["path"] for r in doc} == {"/mcp"}',
            'next((r for r in doc if r["path"].endswith("mcp")), None) is not None',
        ):
            with self.subTest(check=check):
                self.assertTrue(expr.evaluate(check, doc))

    def test_env_is_readable(self):
        os.environ["E2E_EXPR_TEST"] = "yes"
        self.assertTrue(expr.evaluate('env["E2E_EXPR_TEST"] == "yes"', {}))

    def test_anything_outside_the_grammar_is_refused(self):
        for bad in (
            '__import__("os").system("true")',
            "doc.__class__",
            "().__class__.__bases__[0].__subclasses__()",
            "open('/etc/passwd')",
            "(lambda: 1)()",
            "exec('1')",
            "getattr(doc, 'get')",
            "doc.get.__self__",
            "[x := 1]",
            "doc.format()",
        ):
            with self.subTest(bad=bad):
                with self.assertRaises((expr.Refused, SyntaxError)):
                    expr.evaluate(bad, {"a": 1})

    def test_the_command_line_checks_and_gets(self):
        path = os.path.join(os.environ.get("TMPDIR", "/tmp"), "e2e-expr-%d.json" % os.getpid())
        with open(path, "w", encoding="utf-8") as fh:
            fh.write('note: before\n{"total": 2, "events": [1, 2]}\n')
        try:
            run = [sys.executable, os.path.join(ROOT, "tests", "e2e", "expr.py")]
            self.assertEqual(subprocess.run(run + ["check", path, 'doc["total"] == 2']).returncode, 0)
            self.assertEqual(subprocess.run(run + ["check", path, 'doc["total"] == 3']).returncode, 1)
            refused = subprocess.run(run + ["check", path, "doc.__class__"], capture_output=True, text=True)
            self.assertNotEqual(refused.returncode, 0)
            self.assertIn("not allowed", refused.stderr)
        finally:
            os.remove(path)


class RecorderSecretTest(unittest.TestCase):
    def start(self, secret):
        env = dict(os.environ)
        env.pop("E2E_RECORDER_SECRET", None)
        if secret is not None:
            env["E2E_RECORDER_SECRET"] = secret
        proc = subprocess.Popen([sys.executable, os.path.join(ROOT, "tests", "e2e", "targets.py"), "mcp"],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        self.addCleanup(proc.stderr.close)
        self.addCleanup(proc.stdout.close)
        self.addCleanup(proc.wait)
        self.addCleanup(proc.kill)
        return proc

    def test_targets_refuse_to_start_without_a_secret(self):
        proc = self.start(None)
        self.assertNotEqual(proc.wait(timeout=10), 0)
        self.assertIn("E2E_RECORDER_SECRET", proc.stderr.read())

    def test_the_recorder_answers_only_with_the_secret(self):
        secret = "0123456789abcdef0123"
        proc = self.start(secret)
        line = proc.stdout.readline().strip()
        self.assertTrue(line.startswith("listening http://"), line)
        url = line.split(" ", 1)[1] + "/_e2e/requests"
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(url, timeout=5)
        caught.exception.close()
        self.assertEqual(caught.exception.code, 403)
        wrong = urllib.request.Request(url, headers={"X-E2E-Recorder": "wrong"})
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(wrong, timeout=5)
        caught.exception.close()
        self.assertEqual(caught.exception.code, 403)
        right = urllib.request.Request(url, headers={"X-E2E-Recorder": secret})
        with urllib.request.urlopen(right, timeout=5) as response:
            self.assertEqual(json.loads(response.read()), [])


if __name__ == "__main__":
    unittest.main()
