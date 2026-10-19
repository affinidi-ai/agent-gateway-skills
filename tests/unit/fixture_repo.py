"""The clean repository the validate.py and gen-cli-reference.py tests start from.

It is built in a temp directory at test time rather than kept in the tree, so that skill discovery
(`gh skill`, plugin loaders) never finds a second SKILL.md in this repository. The CLI snapshot and
references/commands.md are what gen-cli-reference.py produces from the help pages in
fixtures/help/, read here without running any binary.
"""

import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
HELP = os.path.join(HERE, "fixtures", "help")
SKILL = "skills/affinidi-agent-gateway"

_spec = importlib.util.spec_from_file_location("gen_cli_reference", os.path.join(REPO, "scripts", "gen-cli-reference.py"))
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)

FILES = {
    ".claude-plugin/marketplace.json": """{
  "name": "fixture-marketplace",
  "owner": {
    "name": "Fixture Owner"
  },
  "plugins": [
    {
      "name": "affinidi-agent-gateway",
      "source": "./",
      "description": "Fixture plugin for the validate.py unit tests."
    }
  ]
}
""",
    ".claude-plugin/plugin.json": """{
  "name": "affinidi-agent-gateway",
  "description": "Fixture plugin for the validate.py unit tests."
}
""",
    ".github/skill-drift-matrix.json": """{
  "baseline": {
    "docs_read": "2026-03-04",
    "fabric": "9.8.7",
    "fabric_cli": "89abcdef0123456789abcdef0123456789abcdef",
    "gateway": "1.2.3",
    "agent_gateway": "0123456789abcdef0123456789abcdef01234567"
  },
  "pages": {
    "skills/affinidi-agent-gateway/SKILL.md": { "docs": [], "source_paths": ["src/lib.rs"] },
    "skills/affinidi-agent-gateway/references/commands.md": { "docs": [], "source_paths": [] },
    "skills/affinidi-agent-gateway/references/guide.md": { "docs": [], "source_paths": ["src/guide.rs"] },
    "skills/affinidi-agent-gateway/references/known-issues.md": { "docs": [], "source_paths": ["src/issues.rs"] }
  }
}
""",
    SKILL + "/SKILL.md": """---
name: affinidi-agent-gateway
description: Fixture skill for the validate.py unit tests. Use only in tests.
license: Apache-2.0
metadata:
  gateway: "1.2.3"
  gateway_commit: "0123456789ab"
  fabric: "9.8.7"
  checked: "2026-03-04"
---

# Fixture skill

Reviewed against gateway 1.2.3 and fabric 9.8.7 (March 2026).

Read the [guide](references/guide.md), the [command index](references/commands.md) and the
[known issues](references/known-issues.md). One of them is [KI-01](references/known-issues.md).

```bash
fabric --version
fabric agent-gateway -o json surfaces create --name demo --protocol mcp
ID=$(fabric agent-gateway surfaces create --file surface.json -o json | jq -r .id)
fabric agent-gateway runtime show surface-routing --output=json
fabric agent-gateway help surfaces
```

Run `fabric agent-gateway <command> --help` for detail, or `fabric agent-gateway whoami -o json`.
""",
    SKILL + "/references/guide.md": """# Guide

## Getting started

Start with [getting started](#getting-started) and the [known issues](known-issues.md#known-issues). The command
index is `references/commands.md`.
""",
    SKILL + "/references/known-issues.md": """# Known issues

| KI | Issue | Status |
| --- | --- | --- |
| KI-01 | A fixture issue. | open |
""",
}


class HelpPages:
    """Stands in for the fabric binary in gen.crawl: serves the help pages in fixtures/help/."""

    def __init__(self, help_dir=HELP):
        self.help_dir = help_dir

    def version(self):
        with open(os.path.join(self.help_dir, "version.txt"), encoding="utf-8") as fh:
            return fh.read().split()[1]

    def run(self, args):
        with open(os.path.join(self.help_dir, "-".join(["fabric"] + args[:-1]) + ".txt"), encoding="utf-8") as fh:
            return fh.read()


def write(root, rel, text):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def build(root):
    """Write the clean fixture repository into root."""
    for rel, text in FILES.items():
        write(root, rel, text)
    doc = gen.crawl(HelpPages())
    write(root, gen.TREE_PATH, gen.render_json(doc))
    write(root, gen.COMMANDS_PATH, gen.render_markdown(doc))
