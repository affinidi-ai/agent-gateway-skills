#!/usr/bin/env python3
"""List and extract the literate end-to-end cases embedded in Markdown.

A marker on the line directly before a fenced code block puts that block into a case:

  <!-- e2e: CASE -->               append the block to CASE's script
  <!-- e2e: CASE expect-fail -->   the same, but the block must exit non-zero
  <!-- e2e-file: CASE NAME -->     write the block's content to NAME in CASE's work directory

Script blocks are bash, sh, shell or untagged, without '$ ' prompts. A case's blocks must all be in
one Markdown file, and they run in document order.

Commands:
  list                 print CASE<TAB>FILE for every case
  script CASE          print the case's script (all its blocks, in order)
  emit CASE OUTDIR     write OUTDIR/.e2e/block-N.sh, OUTDIR/.e2e/blocks (N, ok|fail, FILE:LINE),
                       OUTDIR/.e2e/files (NAME, FILE:LINE), OUTDIR/.e2e/script.sh and every
                       e2e-file into OUTDIR

--root is a Markdown file or a directory searched recursively (default: $E2E_DOCS_ROOT, else
skills/ in this repository). Problems are printed as FILE:LINE: message and exit 1.
"""

import argparse
import os
import re
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MARKER_RE = re.compile(r"^\s*<!--\s*(e2e|e2e-file):\s*(.*?)\s*-->\s*$")
LOOSE_MARKER_RE = re.compile(r"<!--\s*e2e")
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
FENCE_RE = re.compile(r"^( {0,3})(`{3,}|~{3,})(.*)$")
SCRIPT_LANGS = ("", "bash", "sh", "shell")


class Case:
    def __init__(self, name, path):
        self.name = name
        self.path = path
        self.blocks = []   # (lineno, expect, text)
        self.files = []    # (lineno, name, text)


def markdown_files(root):
    if os.path.isfile(root):
        return [root]
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        out.extend(os.path.join(dirpath, f) for f in sorted(filenames) if f.endswith(".md"))
    return out


def fences(lines):
    """{opening line index: (lang, body_lines, closed)} for every fenced block."""
    out = {}
    i = 0
    while i < len(lines):
        m = FENCE_RE.match(lines[i])
        if not m:
            i += 1
            continue
        char, width = m.group(2)[0], len(m.group(2))
        close = re.compile(r"^ {0,3}" + re.escape(char) + "{" + str(width) + r",}\s*$")
        j = i + 1
        while j < len(lines) and not close.match(lines[j]):
            j += 1
        info = m.group(3).strip()
        out[i] = (info.split()[0].lower() if info else "", lines[i + 1:j], j < len(lines))
        i = j + 1
    return out


def collect(root, display_root):
    cases = {}
    problems = []
    for path in markdown_files(root):
        shown = os.path.relpath(path, display_root)
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().split("\n")
        blocks = fences(lines)
        inside = set()
        for start, (_, body, _) in blocks.items():
            inside.update(range(start, start + len(body) + 2))
        for idx, line in enumerate(lines):
            if idx in inside or not LOOSE_MARKER_RE.search(line):
                continue
            lineno = idx + 1
            m = MARKER_RE.match(line)
            if not m:
                problems.append("%s:%d: malformed e2e marker %r" % (shown, lineno, line.strip()))
                continue
            kind, args = m.group(1), m.group(2).split()
            if idx + 1 not in blocks:
                problems.append("%s:%d: e2e marker must be on the line directly before a fenced code block" % (shown, lineno))
                continue
            lang, body, closed = blocks[idx + 1]
            if not closed:
                problems.append("%s:%d: the code block after this marker is never closed" % (shown, lineno))
                continue
            text = "\n".join(body)
            if kind == "e2e":
                if not (1 <= len(args) <= 2) or (len(args) == 2 and args[1] != "expect-fail") or not NAME_RE.match(args[0]):
                    problems.append("%s:%d: expected <!-- e2e: CASE --> or <!-- e2e: CASE expect-fail -->" % (shown, lineno))
                    continue
                if lang not in SCRIPT_LANGS:
                    problems.append("%s:%d: e2e script blocks must be bash, sh, shell or untagged, not %r" % (shown, lineno, lang))
                    continue
                if any(b.lstrip().startswith("$ ") for b in body):
                    problems.append("%s:%d: e2e script blocks must not contain '$ ' prompts" % (shown, lineno))
                    continue
            else:
                if len(args) != 2 or not NAME_RE.match(args[0]) or not NAME_RE.match(args[1]):
                    problems.append("%s:%d: expected <!-- e2e-file: CASE NAME --> with NAME a plain file name" % (shown, lineno))
                    continue
            name = args[0]
            case = cases.get(name)
            if case is None:
                case = cases[name] = Case(name, shown)
            elif case.path != shown:
                problems.append("%s:%d: case %s already has blocks in %s; a case's blocks must be in one file"
                                % (shown, lineno, name, case.path))
                continue
            if kind == "e2e":
                case.blocks.append((lineno, "fail" if len(args) == 2 else "ok", text))
            else:
                if any(f[1] == args[1] for f in case.files):
                    problems.append("%s:%d: case %s writes %s twice" % (shown, lineno, name, args[1]))
                    continue
                case.files.append((lineno, args[1], text))
    for case in cases.values():
        if not case.blocks:
            problems.append("%s:1: case %s has files but no e2e blocks" % (case.path, case.name))
    return cases, problems


def script_of(case):
    parts = []
    for n, (lineno, expect, text) in enumerate(case.blocks, start=1):
        parts.append("# --- block %d (%s:%d)%s ---\n%s\n" % (n, case.path, lineno, ", expect-fail" if expect == "fail" else "", text))
    return "".join(parts)


def emit(case, outdir):
    meta = os.path.join(outdir, ".e2e")
    os.makedirs(meta, exist_ok=True)
    rows = []
    for n, (lineno, expect, text) in enumerate(case.blocks, start=1):
        with open(os.path.join(meta, "block-%d.sh" % n), "w", encoding="utf-8") as fh:
            fh.write("# %s:%d\n%s\n" % (case.path, lineno, text))
        rows.append("%d\t%s\t%s:%d\n" % (n, expect, case.path, lineno))
    with open(os.path.join(meta, "blocks"), "w", encoding="utf-8") as fh:
        fh.write("".join(rows))
    with open(os.path.join(meta, "script.sh"), "w", encoding="utf-8") as fh:
        fh.write(script_of(case))
    with open(os.path.join(meta, "files"), "w", encoding="utf-8") as fh:
        fh.write("".join("%s\t%s:%d\n" % (name, case.path, lineno) for lineno, name, _ in case.files))
    for _, name, text in case.files:
        with open(os.path.join(outdir, name), "w", encoding="utf-8") as fh:
            fh.write(text + "\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description="List and extract literate e2e cases from Markdown.")
    parser.add_argument("--root", default=os.environ.get("E2E_DOCS_ROOT") or "skills/",
                        help="Markdown file or directory (default: $E2E_DOCS_ROOT, else skills/)")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("list", help="print CASE<TAB>FILE for every case")
    p_script = sub.add_parser("script", help="print a case's script")
    p_script.add_argument("case")
    p_emit = sub.add_parser("emit", help="write a case's blocks and files into OUTDIR")
    p_emit.add_argument("case")
    p_emit.add_argument("outdir")
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 2
    root = args.root if os.path.isabs(args.root) else os.path.join(REPO_ROOT, args.root)
    if not os.path.exists(root):
        print("extract.py: %s does not exist" % args.root, file=sys.stderr)
        return 2
    cases, problems = collect(root, REPO_ROOT)
    if problems:
        for p in problems:
            print(p)
        print("extract.py: FAILED, %d problem%s in e2e markers" % (len(problems), "" if len(problems) == 1 else "s"))
        return 1
    if args.command == "list":
        for name in sorted(cases):
            print("%s\t%s" % (name, cases[name].path))
        return 0
    case = cases.get(args.case)
    if case is None:
        print("extract.py: no case %r under %s" % (args.case, args.root), file=sys.stderr)
        return 1
    if args.command == "script":
        sys.stdout.write(script_of(case))
    else:
        emit(case, args.outdir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
