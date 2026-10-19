#!/usr/bin/env python3
"""Replace credentials with <redacted>.

  redact.py              copy standard input to standard output, line by line, redacted
  redact.py --tree DIR   redact every text file under DIR in place (symbolic links are skipped)

run.sh passes everything a case prints (its own lines, `fail` output with the last lines of a
block's output, guard findings and refusals) through the filter, and redacts a kept work directory
(E2E_KEEP=1) in place before it leaves it behind. Saved block output is not rewritten while the
case runs, because the case's checks read it. Replaced:

  - the exact value of FABRIC_TOKEN (the administrator token the run uses);
  - personal access tokens (agpat_...) and JWTs (eyJ....eyJ....);
  - the value after "Bearer" or "Basic" (the scheme is kept), and UUID-shaped values after a
    session key (session, session_id, session_token, ...);
  - the value of an HTTP header (`Name: value`) whose name is Authorization, Proxy-Authorization,
    or ends in -token, -key or -secret (X-API-Key, X-Transit-Token, ...), scheme included;
  - the value of any JSON member or key=value pair named token, secret, api_key, key, password,
    or ending in _token, _secret, _key, -token, -secret or -key (access_token, client_secret,
    x-api-key, ...).

Bare UUIDs elsewhere are resource IDs, which cases need to read, so they are kept.
"""

import os
import re
import sys

R = "<redacted>"
UUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
KEY_NAMES = r"(?:[A-Za-z0-9]+[_-])*(?:token|secret|api[_-]key|apikey|key|password)"
HEADER_NAMES = r"(?:proxy-)?authorization|(?:[A-Za-z0-9]+-)+(?:token|key|secret)"
PATTERNS = [
    (re.compile(r"agpat_[A-Za-z0-9_-]+"), R),
    (re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]*)?"), R),
    (re.compile(r"(?i)(?<![A-Za-z0-9-])((?:" + HEADER_NAMES + r")\s*:\s*)(?!<redacted>)(?:(?:bearer|basic)\s+)?"
                r"[^\s\"',;]+"), r"\1" + R),
    (re.compile(r"(?i)(\b(?:bearer|basic)\s+)(?!<redacted>)[A-Za-z0-9._~+/=-]{6,}"), r"\1" + R),
    (re.compile(r"(?i)(\bsession[A-Za-z0-9_-]*[\"']?\s*[:=]\s*[\"']?)" + UUID), r"\1" + R),
    (re.compile(r"(?i)(\"" + KEY_NAMES + r"\"\s*:\s*\")(?:[^\"\\]|\\.)*(\")"), r"\1" + R + r"\2"),
    (re.compile(r"(?i)(\b" + KEY_NAMES + r"\s*=\s*)(?!<redacted>)(?:\"[^\"]*\"|'[^']*'|[^\s\"',;&`]+)"), r"\1" + R),
]


def redact(line, token):
    if token:
        line = line.replace(token, R)
    for pattern, replacement in PATTERNS:
        line = pattern.sub(replacement, line)
    return line


def redact_tree(root, token):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not os.path.islink(os.path.join(dirpath, d))]
        for name in filenames:
            path = os.path.join(dirpath, name)
            if os.path.islink(path) or not os.path.isfile(path):
                continue
            with open(path, "rb") as fh:
                data = fh.read()
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                continue
            clean = "".join(redact(line, token) for line in text.splitlines(True))
            if clean != text:
                with open(path, "w", encoding="utf-8", newline="") as fh:
                    fh.write(clean)


def main():
    if len(sys.argv) > 1 and sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        return 0
    token = os.environ.get("FABRIC_TOKEN", "")
    if len(sys.argv) == 3 and sys.argv[1] == "--tree":
        redact_tree(sys.argv[2], token)
        return 0
    if len(sys.argv) > 1:
        print("usage: redact.py [--tree DIR]", file=sys.stderr)
        return 2
    stdin = open(sys.stdin.fileno(), "r", encoding="utf-8", errors="replace", newline="", closefd=False)
    stdout = open(sys.stdout.fileno(), "w", encoding="utf-8", errors="replace", newline="", closefd=False)
    for line in iter(stdin.readline, ""):
        stdout.write(redact(line, token))
        stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
