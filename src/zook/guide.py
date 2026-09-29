"""What `zook guide`, `zook patterns` and `zook init` serve from inside the
package - so an AI working in its own repository, with zook installed by
pip/pipx rather than cloned, can still read the workflow, the YAML spec and
the reference patterns (they used to exist only as repository files).

The guide texts are byte-identical copies of repository docs
(BUNDLED_DOCS; scripts/sync_bundled_docs.py refreshes them and
tests/test_bundled_data.py checks they are current). The patterns live only
in the package (src/zook/data/patterns/).
"""

from __future__ import annotations

import importlib.resources as resources
import re

from .errors import DiagramError

# bundled file name -> repository source it mirrors
BUNDLED_DOCS = {
    "AGENTS.md": "AGENTS.md",
    "yaml-spec.md": "docs/yaml-spec.md",
    "usage.md": "docs-site/usage.md",
    "limitations.md": "docs-site/limitations.md",
    "mermaid-import.md": "docs-site/mermaid-import.md",
    "drawio-sync.md": "docs-site/drawio-sync.md",
}

# topic -> (package, file, one-line description)
TOPICS = {
    "workflow": ("zook.data.guide", "AGENTS.md", "from a request to a validated diagram, step by step (start here)"),
    "yaml": ("zook.data.guide", "yaml-spec.md", "the full YAML format: every field, default and check"),
    "patterns": ("zook.data.patterns", "README.md", "which reference pattern fits which requirement"),
    "usage": ("zook.data.guide", "usage.md", "every command and option, doctor and diff in detail"),
    "limitations": ("zook.data.guide", "limitations.md", "what zook doesn't do, and what to do instead"),
    "mermaid": ("zook.data.guide", "mermaid-import.md", "converting a Mermaid flowchart"),
    "drawio": ("zook.data.guide", "drawio-sync.md", "hand-tuning in draw.io and syncing it back"),
}

# The docs site's language-switch button; meaningless in a terminal.
_SITE_ONLY_LINE = re.compile(r"^\[[^\]]*\]\([^)]*\)\{ \.md-button \}\n\n?", re.MULTILINE)


def _read(package: str, name: str) -> str:
    return resources.files(package).joinpath(name).read_text(encoding="utf-8")


def guide_text(topic: str) -> str:
    if topic not in TOPICS:
        raise DiagramError(f"unknown guide topic {topic!r} - one of: {', '.join(TOPICS)}")
    package, name, _ = TOPICS[topic]
    text = _SITE_ONLY_LINE.sub("", _read(package, name))
    if topic == "workflow":
        # AGENTS.md's agent-facing part: the steps and the Mermaid path, not
        # the repository map and contributor notes that follow them.
        start = text.index("## From Architecture Proposal")
        end = text.index("## Key References")
        text = text[start:end].rstrip() + "\n"
    return text


def _pattern_files() -> dict[str, object]:
    root = resources.files("zook.data.patterns")
    return {p.name[: -len(".yaml")]: p for p in sorted(root.iterdir(), key=lambda p: p.name) if p.name.endswith(".yaml")}


def pattern_names() -> list[str]:
    return list(_pattern_files())


def pattern_text(name: str) -> str:
    files = _pattern_files()
    key = name[: -len(".yaml")] if name.endswith(".yaml") else name
    if key not in files:
        raise DiagramError(f"unknown pattern {name!r} - one of: {', '.join(files)} (see `zook patterns list`)")
    return files[key].read_text(encoding="utf-8")


def pattern_summaries() -> list[dict]:
    """Each pattern's name and the comment block at the top of its file."""
    summaries = []
    for name in pattern_names():
        text = pattern_text(name)
        comment = []
        for line in text.splitlines()[1:]:
            if not line.startswith("#"):
                break
            comment.append(line.lstrip("# ").rstrip())
        providers = sorted(set(re.findall(r"^\s*provider:\s*(\w+)", text, re.MULTILINE)) or {"aws"})
        summaries.append({"name": name, "summary": " ".join(comment), "providers": providers})
    return summaries


STARTER = '''version: "1.0"
# A starting point - replace the example nodes with your own. `zook guide`
# walks through the whole workflow; `zook patterns list` has complete
# reference architectures to start from instead (`zook init --pattern NAME`),
# and `zook icons list` every usable `type`.

canvas:
  aspectRatio: "16:9"

elements:
  - kind: node
    id: user
    type: User
    label: "User"

  - kind: container
    id: aws
    type: cloud
    label: "AWS Cloud"
    layout:
      direction: horizontal
    children:
      - kind: node
        id: api
        type: APIGateway
        label: "API"
      - kind: node
        id: fn
        type: Lambda
        label: "Handler"
      - kind: node
        id: table
        type: DynamoDB
        label: "Table"

links:
  - { from: user, to: api, label: "HTTPS" }
  - { from: api, to: fn }
  - { from: fn, to: table }
'''
