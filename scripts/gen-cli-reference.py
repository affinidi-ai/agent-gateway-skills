#!/usr/bin/env python3
"""Generate the fabric command reference from the fabric binary's own help output.

Crawls `fabric --help` and the `--help` of every subcommand, parses clap's help layout and writes:

  .github/fabric-cli-snapshot.json                      the command tree, read by validate.py
  skills/affinidi-agent-gateway/references/commands.md  an index of commands for readers

Only `--help` and `--version` are ever run. The binary gets an isolated environment: a fresh HOME
with XDG_CONFIG_HOME inside it, NO_COLOR=1, TERM=dumb, the caller's PATH, and nothing else, so no
FABRIC_* variable, saved connection or terminal width can leak into the output.

With --check nothing is written: the files are regenerated in memory and compared with the ones on
disk, and any difference (including a different fabric version) exits 1 with a short diff.

Exit status: 0 on success, 1 when --check finds drift, 2 when fabric is missing, its help cannot be read or
parsed, or the arguments are wrong.
"""

import argparse
import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL_NAME = "affinidi-agent-gateway"
TREE_PATH = ".github/fabric-cli-snapshot.json"
COMMANDS_PATH = "skills/" + SKILL_NAME + "/references/commands.md"
BANNER = "<!-- Generated from the help of fabric {version} by make cli-reference. Do not edit by hand. -->"
BANNER_RE = re.compile(
    r"^<!-- Generated from the help of fabric (?P<version>\S+) by make cli-reference\. Do not edit by hand\. -->$"
)
TREE_FORMAT = 1
HELP_TIMEOUT = 30
MAX_DIFF_LINES = 60


class HelpParseError(Exception):
    """A help page did not have the layout this parser understands."""


class FabricError(Exception):
    """Running the fabric binary failed."""


# --------------------------------------------------------------------------------------------
# Parsing one clap help page
# --------------------------------------------------------------------------------------------

SECTION_RE = re.compile(r"^(?P<title>[A-Z][A-Za-z0-9 ()/-]*):$")
# The sections clap prints itself. Any other heading, such as "Examples:" in an after_long_help
# text, starts free text that goes into after_help with the lines under it.
CLAP_SECTIONS = {"Commands": "commands", "Arguments": "arguments", "Options": "options"}
OPTION_RE = re.compile(
    r"^ {2,6}(?:-(?P<short>[A-Za-z0-9?])(?:, --(?P<long1>[A-Za-z0-9][\w-]*))?"
    r"|--(?P<long2>[A-Za-z0-9][\w-]*))(?P<rest>.*)$"
)
OPTION_REST_RE = re.compile(
    r"^(?P<value>(?:[ =](?:<[^>]+>|\[<[^>]+>(?:\.\.\.)?\])(?:\.\.\.)?)*)(?:\s{2,}(?P<help>\S.*))?\s*$"
)
ARGUMENT_RE = re.compile(r"^  (?P<spec>(?:<[^>]+>|\[[^\]]+\])(?:\.\.\.)?)(?:\s{2,}(?P<help>\S.*))?\s*$")
COMMAND_RE = re.compile(r"^  (?P<name>[A-Za-z0-9][\w-]*)(?:\s{2,}(?P<about>\S.*))?\s*$")
ANNOTATION_RE = re.compile(
    r"\s*\[(?P<kind>default|possible values|env|aliases|alias|short aliases|short alias): (?P<value>[^\]]*)\]"
)
CONTINUATION_INDENT = 7


def _paragraphs(lines):
    """Join lines into paragraphs separated by blank lines; whitespace collapsed."""
    out, cur = [], []
    for line in lines:
        if line.strip():
            cur.append(line.strip())
        elif cur:
            out.append(" ".join(cur))
            cur = []
    if cur:
        out.append(" ".join(cur))
    return [" ".join(p.split()) for p in out]


def first_sentence(text):
    """The first sentence of a help text: up to the first '.', '!' or '?' followed by a new sentence."""
    text = " ".join(text.split())
    m = re.match(r"(.+?[.!?])(?=\s+[A-Z(`'\"\[]|$)", text)
    return m.group(1) if m else text


def _finish_entry(entry):
    """Turn an entry's raw help lines into help text and annotations."""
    raw = entry.pop("_lines")
    text_lines = []
    possible = []
    in_possible = False
    for line in raw:
        if not line:
            in_possible = False
            text_lines.append("")
            continue
        if line == "Possible values:":
            in_possible = True
            text_lines.append("")
            continue
        if in_possible and line.startswith("- "):
            possible.append(line[2:].split(":", 1)[0].strip())
            continue
        in_possible = False
        text_lines.append(line)
    annotations = {}
    cleaned = []
    for line in text_lines:
        for m in ANNOTATION_RE.finditer(line):
            annotations.setdefault(m.group("kind"), []).append(m.group("value"))
        cleaned.append(ANNOTATION_RE.sub("", line))
    paragraphs = _paragraphs(cleaned)
    if paragraphs:
        entry["help"] = first_sentence(paragraphs[0])
    if "default" in annotations:
        entry["default"] = annotations["default"][0]
    values = list(possible)
    for group in annotations.get("possible values", []):
        values.extend(v.strip() for v in group.split(",") if v.strip())
    if values:
        entry["possible_values"] = values
    if "env" in annotations:
        entry["env"] = annotations["env"][0].split("=", 1)[0].strip()
    aliases = []
    for kind in ("aliases", "alias", "short aliases", "short alias"):
        for group in annotations.get(kind, []):
            aliases.extend(a.strip() for a in group.split(",") if a.strip())
    if aliases:
        entry["aliases"] = aliases
    return entry


def parse_help(text):
    """Parse one clap help page (short or long layout) into a node dict without subcommand detail.

    Raises HelpParseError on any line it cannot place, so a layout change fails loudly instead of
    silently dropping options.
    """
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").split("\n")]
    i = 0
    about_lines = []
    while i < len(lines) and not lines[i].startswith("Usage:"):
        about_lines.append(lines[i])
        i += 1
    if i == len(lines):
        raise HelpParseError("no 'Usage:' line")
    usage = [lines[i][len("Usage:"):].strip()]
    i += 1
    while i < len(lines) and lines[i].startswith("       ") and lines[i].strip():
        usage.append(lines[i].strip())
        i += 1

    node = {
        "about": "\n\n".join(_paragraphs(about_lines)),
        "usage": "\n".join(usage),
        "arguments": [],
        "options": [],
        "commands": [],
    }
    after = []
    section = None
    current = None

    def close():
        if current is not None:
            _finish_entry(current)

    for lineno, line in enumerate(lines[i:], start=i + 1):
        if not line.strip():
            if current is not None:
                current["_lines"].append("")
            elif section is None and after:
                after.append("")
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent == 0:
            close()
            current = None
            m = SECTION_RE.match(line)
            if m and m.group("title") in CLAP_SECTIONS:
                section = CLAP_SECTIONS[m.group("title")]
            else:
                section = None
                after.append(line)
            continue
        if section is None:
            if not after:
                raise HelpParseError("line %d: indented text outside any section: %r" % (lineno, line))
            after.append(line.strip())
            continue
        if indent >= CONTINUATION_INDENT:
            if current is None:
                raise HelpParseError("line %d: continuation without an entry: %r" % (lineno, line))
            current["_lines"].append(line.strip())
            continue
        close()
        current = None
        if section == "options":
            m = OPTION_RE.match(line)
            rest = OPTION_REST_RE.match(m.group("rest")) if m else None
            if not m or not rest:
                raise HelpParseError("line %d: unrecognised option line: %r" % (lineno, line))
            current = {"_lines": [rest.group("help")] if rest.group("help") else []}
            if m.group("short"):
                current["short"] = m.group("short")
            long_name = m.group("long1") or m.group("long2")
            if long_name:
                current["long"] = long_name
            value = rest.group("value").strip().lstrip("=")
            if value:
                current["value"] = value
            node["options"].append(current)
        elif section == "arguments":
            m = ARGUMENT_RE.match(line)
            if not m:
                raise HelpParseError("line %d: unrecognised argument line: %r" % (lineno, line))
            spec = m.group("spec")
            multiple = spec.endswith("...")
            name = spec[:-3] if multiple else spec
            required = name.startswith("<")
            current = {
                "_lines": [m.group("help")] if m.group("help") else [],
                "name": name.strip("<>[]"),
                "required": required,
            }
            if multiple:
                current["multiple"] = True
            node["arguments"].append(current)
        else:
            m = COMMAND_RE.match(line)
            if not m:
                raise HelpParseError("line %d: unrecognised command line: %r" % (lineno, line))
            current = {"_lines": [m.group("about")] if m.group("about") else [], "name": m.group("name")}
            node["commands"].append(current)
    close()
    for command in node["commands"]:
        command["about"] = command.pop("help", "")
    if after:
        node["after_help"] = "\n\n".join(_paragraphs(after))
    return node


# --------------------------------------------------------------------------------------------
# Crawling the binary
# --------------------------------------------------------------------------------------------


class Fabric:
    """Runs one fabric binary with an isolated environment; only --help and --version."""

    def __init__(self, exe):
        self.exe = exe
        self._tmp = tempfile.mkdtemp(prefix="fabric-help-")
        home = os.path.join(self._tmp, "home")
        config = os.path.join(home, ".config")
        os.makedirs(config)
        self.env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": home,
            "XDG_CONFIG_HOME": config,
            "NO_COLOR": "1",
            "TERM": "dumb",
        }
        if "SYSTEMROOT" in os.environ:
            self.env["SYSTEMROOT"] = os.environ["SYSTEMROOT"]

    def close(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def run(self, args):
        if not args or args[-1] not in ("--help", "--version"):
            raise FabricError("refusing to run fabric with anything but --help or --version")
        shown = " ".join(["fabric"] + args)
        try:
            proc = subprocess.run(
                [self.exe] + args,
                env=self.env,
                cwd=self._tmp,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=HELP_TIMEOUT,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise FabricError("%s: %s" % (shown, exc))
        if proc.returncode != 0:
            detail = proc.stderr.decode("utf-8", "replace").strip().splitlines()
            raise FabricError("%s exited %d%s" % (shown, proc.returncode, (": " + detail[0]) if detail else ""))
        return proc.stdout.decode("utf-8")

    def version(self):
        out = self.run(["--version"]).strip()
        m = re.match(r"^fabric (\S+)$", out.splitlines()[0] if out else "")
        if not m:
            raise FabricError("fabric --version printed %r, expected 'fabric <version>'" % out)
        return m.group(1)


def crawl(fabric):
    """Build the full command tree: {'fabric_version', 'format', 'global_options', 'root'}."""
    version = fabric.version()

    def page(path):
        shown = " ".join(["fabric"] + path + ["--help"])
        try:
            node = parse_help(fabric.run(path + ["--help"]))
        except HelpParseError as exc:
            raise HelpParseError("%s: %s" % (shown, exc))
        expected = " ".join(["fabric"] + path)
        if not (node["usage"] + " ").startswith(expected + " "):
            raise HelpParseError("%s: usage %r does not start with %r" % (shown, node["usage"], expected))
        return node

    def walk(node, path):
        children = []
        for listed in node["commands"]:
            if listed["name"] == "help":
                continue
            child = page(path + [listed["name"]])
            child["name"] = listed["name"]
            if not child["about"]:
                child["about"] = listed.get("about", "")
            if listed.get("aliases"):
                child["aliases"] = listed["aliases"]
            walk(child, path + [listed["name"]])
            children.append(child)
        node["commands"] = children

    root = page([])
    root["name"] = "fabric"
    walk(root, [])

    # The global options are declared on each appliance group (`fabric agent-gateway`), not on the
    # root, and clap lists them on every command below it: the options every non-root node has.
    every = None
    for node in iter_nodes(root):
        if node is root:
            continue
        longs = set(o["long"] for o in node["options"] if "long" in o)
        every = longs if every is None else every & longs
    globals_ = sorted(every or ())
    return {"fabric_version": version, "format": TREE_FORMAT, "global_options": globals_, "root": root}


def iter_nodes(node, path=()):
    yield node
    for child in node.get("commands", []):
        for sub in iter_nodes(child, path + (child["name"],)):
            yield sub


# --------------------------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------------------------


def render_json(doc):
    return json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _cell(text):
    return " ".join(text.split()).replace("|", "\\|")


def _first_paragraph(text):
    return text.split("\n\n", 1)[0] if text else ""


def _rows(node, path):
    """(path, node) for every command worth a table row: leaves, and groups with their own inputs."""
    rows = []
    has_own = bool(node.get("arguments")) or bool(node.get("_own_options"))
    if not node.get("commands") or has_own:
        rows.append((path, node))
    for child in node.get("commands", []):
        rows.extend(_rows(child, path + [child["name"]]))
    return rows


def _option_list(node, global_longs):
    items = []
    for arg in node.get("arguments", []):
        items.append("`<%s>%s`" % (arg["name"], "..." if arg.get("multiple") else ""))
    for opt in node.get("options", []):
        if opt.get("long") in global_longs:
            continue
        if "long" in opt:
            items.append("`--%s`" % opt["long"])
        else:
            items.append("`-%s`" % opt["short"])
    return ", ".join(items)


def _option_name(opt):
    names = []
    if "short" in opt:
        names.append("-" + opt["short"])
    if "long" in opt:
        names.append("--" + opt["long"])
    return ", ".join(names) + ((" " + opt["value"]) if opt.get("value") else "")


def render_markdown(doc):
    """Every command sits under an appliance group (`fabric agent-gateway`), which declares the
    global options; each group's commands get a section of their own."""
    version = doc["fabric_version"]
    root = doc["root"]
    global_longs = set(doc["global_options"])
    for node in iter_nodes(root):
        node["_own_options"] = [o for o in node.get("options", []) if o.get("long") not in global_longs]
    appliances = root["commands"]
    lead = "fabric %s" % (appliances[0]["name"] if len(appliances) == 1 else "<appliance>")
    out = [
        BANNER.format(version=version),
        "",
        "# fabric command reference",
        "",
        "An index of every `fabric` command and its options, taken from the help of fabric %s. "
        "It is a snapshot of `fabric --help` at the reviewed version: where the installed fabric's "
        "`%s <command> --help` says otherwise, the live help wins. "
        "`%s <command> --help` is the authoritative detail: what each option means, its default "
        "and the values it accepts. This file only lists them." % (version, lead, lead),
        "",
        "Every command is under an appliance group: %s. Before the group, `fabric` takes only %s."
        % (", ".join("`fabric %s`" % a["name"] for a in appliances),
           " and ".join("`%s`" % _option_name(o) for o in root["options"])),
        "",
        "## Global options",
        "",
        "Every command accepts these after its appliance group, `%s`, and after any subcommand, but not "
        "before the group, so the tables below leave them out." % lead,
        "",
        "| Option | What it does |",
        "| --- | --- |",
    ]
    seen = set()
    for appliance in appliances:
        for opt in appliance["options"]:
            if opt.get("long") in global_longs and opt["long"] not in seen:
                seen.add(opt["long"])
                out.append("| `%s` | %s |" % (_option_name(opt), _cell(opt.get("help", ""))))
    for appliance in appliances:
        for top in appliance["commands"]:
            out += [
                "",
                "## %s" % top["name"],
                "",
                _cell(_first_paragraph(top["about"])),
                "",
                "| Command | What it does | Options |",
                "| --- | --- | --- |",
            ]
            for path, node in _rows(top, [appliance["name"], top["name"]]):
                out.append(
                    "| `fabric %s` | %s | %s |"
                    % (" ".join(path), _cell(_first_paragraph(node["about"])), _option_list(node, global_longs))
                )
    for node in iter_nodes(root):
        node.pop("_own_options", None)
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------------------------


def _short_diff(path, old, new):
    diff = list(difflib.unified_diff(old.splitlines(), new.splitlines(), path + " (on disk)", path + " (from fabric)", lineterm="", n=1))
    if len(diff) > MAX_DIFF_LINES:
        diff = diff[:MAX_DIFF_LINES] + ["... (%d more diff lines)" % (len(diff) - MAX_DIFF_LINES)]
    return diff


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Regenerate the fabric CLI snapshot and references/commands.md from the fabric binary's help.",
    )
    parser.add_argument("--fabric", default=os.environ.get("FABRIC") or "fabric",
                        help="fabric binary (default: $FABRIC, else fabric on PATH)")
    parser.add_argument("--root", default=REPO_ROOT, help="repository root (default: %(default)s)")
    parser.add_argument("--check", action="store_true",
                        help="compare with the files on disk instead of writing; exit 1 on drift")
    args = parser.parse_args(argv)

    exe = shutil.which(args.fabric)
    if exe is None:
        print("gen-cli-reference: fabric binary not found: %s (set FABRIC or pass --fabric)" % args.fabric, file=sys.stderr)
        return 2
    fabric = Fabric(os.path.abspath(exe))
    try:
        doc = crawl(fabric)
    except (HelpParseError, FabricError) as exc:
        print("%s: %s" % (args.fabric, exc))
        print("gen-cli-reference: FAILED, could not read the command tree")
        return 2
    finally:
        fabric.close()

    outputs = [(TREE_PATH, render_json(doc)), (COMMANDS_PATH, render_markdown(doc))]
    commands = sum(1 for _ in iter_nodes(doc["root"])) - 1

    if not args.check:
        for rel, content in outputs:
            path = os.path.join(args.root, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(content)
        print("gen-cli-reference: wrote %s and %s (fabric %s, %d commands, %d bytes of Markdown)"
              % (TREE_PATH, COMMANDS_PATH, doc["fabric_version"], commands, len(outputs[1][1].encode("utf-8"))))
        return 0

    problems = 0
    for rel, content in outputs:
        path = os.path.join(args.root, rel)
        try:
            with open(path, encoding="utf-8") as fh:
                old = fh.read()
        except OSError:
            print("%s:1: missing; run make cli-reference" % rel)
            problems += 1
            continue
        if rel == TREE_PATH:
            try:
                old_version = json.loads(old).get("fabric_version")
            except ValueError:
                old_version = None
            if old_version != doc["fabric_version"]:
                print("%s:1: records fabric %s but the binary is fabric %s" % (rel, old_version, doc["fabric_version"]))
                problems += 1
        if old != content:
            print("%s:1: out of date with the fabric binary; run make cli-reference" % rel)
            for line in _short_diff(rel, old, content):
                print("    " + line)
            problems += 1
    if problems:
        print("gen-cli-reference: FAILED, %d file(s) out of date with fabric %s" % (problems, doc["fabric_version"]))
        return 1
    print("gen-cli-reference: OK, %s and %s match fabric %s (%d commands)" % (TREE_PATH, COMMANDS_PATH, doc["fabric_version"], commands))
    return 0


if __name__ == "__main__":
    sys.exit(main())
