"""Unit tests for tests/e2e/redact.py, the filter run.sh passes every line it prints through.

Credential-shaped samples are assembled at run time, so this file holds none of the literals
scripts/validate.py bans.
"""

import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
REDACT = os.path.join(REPO, "tests", "e2e", "redact.py")

_spec = importlib.util.spec_from_file_location("e2e_redact", REDACT)
redact = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(redact)

R = "<redacted>"
PAT = "ag" + "pat_" + "Q" * 24
JWT = "ey" + "JhbGciOiJFUzI1NiJ9." + "ey" + "JzdWIiOiJ4In0.c2lnbmF0dXJl"
ZERO_UUID = "00000000-0000-0000-0000-000000000000"


class Patterns(unittest.TestCase):
    def check(self, line, expected, token=""):
        self.assertEqual(redact.redact(line, token), expected)

    def test_exact_token(self):
        """redact: the exact FABRIC_TOKEN value is replaced wherever it appears"""
        self.check("token is opaque-admin-value, again opaque-admin-value\n",
                   "token is %s, again %s\n" % (R, R), token="opaque-admin-value")

    def test_pat_and_jwt(self):
        """redact: personal access tokens and JWTs are replaced anywhere in a line"""
        self.check("created %s for ci\n" % PAT, "created %s for ci\n" % R)
        self.check("x-transit %s end" % JWT, "x-transit %s end" % R)

    def test_bearer_and_basic_values(self):
        """redact: the value after Bearer or Basic is replaced and the scheme kept"""
        self.check('{"authorization": "Bearer e2e-access-17"}', '{"authorization": "Bearer %s"}' % R)
        self.check("sent basic dXNlcjpwYXNz", "sent basic %s" % R)
        self.check('"header_format": "Bearer {value}"', '"header_format": "Bearer {value}"')

    def test_header_lines(self):
        """redact: Authorization and *-token, *-key, *-secret header values are replaced"""
        self.check("Authorization: Bearer opaque123\n", "Authorization: %s\n" % R)
        self.check('curl -H "X-API-Key: caller-value-1" -d x', 'curl -H "X-API-Key: %s" -d x' % R)
        self.check("x-transit-token: abc.def", "x-transit-token: %s" % R)
        self.check("x-upstream-secret:v1", "x-upstream-secret:%s" % R)
        self.check("not allowed by policy: Missing credential: API key not found in request",
                   "not allowed by policy: Missing credential: API key not found in request")

    def test_named_json_members_and_assignments(self):
        """redact: JSON members and key=value pairs named like credentials lose their values"""
        self.check('{"access_token": "a1", "client_secret": "s", "x-api-key": "k", "token": "t"}',
                   '{"access_token": "%s", "client_secret": "%s", "x-api-key": "%s", "token": "%s"}' % (R, R, R, R))
        self.check("password=hunter2 api_key='k' secret_id=kept-id", "password=%s api_key=%s secret_id=kept-id" % (R, R))
        self.check('{"token_stored": true, "secret_id": "rotate-key", "key_pair": {}}',
                   '{"token_stored": true, "secret_id": "rotate-key", "key_pair": {}}')
        self.check("holds a `token =` line", "holds a `token =` line")

    def test_session_uuid_but_not_resource_ids(self):
        """redact: a UUID after a session key is replaced; a bare UUID is a resource id and kept"""
        self.check('{"session_id": "%s"}' % ZERO_UUID, '{"session_id": "%s"}' % R)
        self.check("session=%s" % ZERO_UUID, "session=%s" % R)
        self.check("surface_id %s created" % ZERO_UUID, "surface_id %s created" % ZERO_UUID)


class CommandLine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="redact-test-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_filter_reads_the_token_from_the_environment(self):
        """redact: as a filter it redacts line by line with FABRIC_TOKEN from the environment"""
        env = dict(os.environ, FABRIC_TOKEN="opaque-admin-value")
        proc = subprocess.run([sys.executable, REDACT], input="a opaque-admin-value\nb %s\nno newline" % PAT,
                              env=env, stdout=subprocess.PIPE, universal_newlines=True)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, "a %s\nb %s\nno newline" % (R, R))

    def test_tree_redacts_text_files_in_place_and_skips_links_and_binaries(self):
        """redact: --tree rewrites text files that hold a credential, never follows links"""
        outside = os.path.join(self.tmp, "outside.txt")
        with open(outside, "w") as fh:
            fh.write(PAT + "\n")
        tree = os.path.join(self.tmp, "tree")
        os.makedirs(os.path.join(tree, "case"))
        with open(os.path.join(tree, "case", "block-1.out"), "w") as fh:
            fh.write("Bearer opaque-value\nplain\n")
        with open(os.path.join(tree, "blob.bin"), "wb") as fh:
            fh.write(b"\xff\xfe" + PAT.encode())
        os.symlink(outside, os.path.join(tree, "link.txt"))
        proc = subprocess.run([sys.executable, REDACT, "--tree", tree], stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, universal_newlines=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        with open(os.path.join(tree, "case", "block-1.out")) as fh:
            self.assertEqual(fh.read(), "Bearer %s\nplain\n" % R)
        with open(outside) as fh:
            self.assertEqual(fh.read(), PAT + "\n")
        with open(os.path.join(tree, "blob.bin"), "rb") as fh:
            self.assertIn(PAT.encode(), fh.read())

    def test_usage(self):
        """redact: unknown arguments are a usage error"""
        proc = subprocess.run([sys.executable, REDACT, "--nope"], stderr=subprocess.PIPE, universal_newlines=True)
        self.assertEqual(proc.returncode, 2)


if __name__ == "__main__":
    unittest.main()
