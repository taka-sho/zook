"""Hand-rolled parser for Mermaid `flowchart`/`graph` syntax (phase 1: the
sequenceDiagram type needs a wholly different, vertical-lifeline rendering
engine and is out of scope here - see the Mermaid import plan).

No third-party Mermaid parser was adopted: the one candidate found
(`mermaid-parser-py`) shells out to a JS engine via PythonMonkey, has low
adoption, and its own author documents that it can break on future Mermaid
grammar changes. A small regex/line-based parser covering the common subset
below is more maintainable for this project.

Supported syntax:
  - Header: `flowchart <TD|TB|BT|LR|RL>` or the legacy `graph <...>` alias.
    TD/TB/BT map to a vertical layout, LR/RL to horizontal. Missing/unknown
    headers default to vertical rather than erroring.
  - `%% ...` full-line comments.
  - Node shapes: `id[label]` (rect), `id(label)` (rounded), `id{label}`
    (diamond), `id((label))` (circle). A bare `id` used only in an edge
    (never declared with a shape) is auto-registered as a `rect` using the
    id itself as the label.
  - Edges: `-->` (arrow: end), `---` (none), `<-->` (both), and `-.->`/`==>`
    (rendered identically to `-->` - dashed/thick styling is not
    reproduced). Edge labels via `-->|label|`; the `-- label -->` form is
    not supported. Chained edges on one line (`A --> B --> C`) work.
  - `subgraph <id>[<Title>]` ... `end`, nestable, title optional.

Known v1 limitations (see docs-site/mermaid-import.md):
  - Node/subgraph order in the output YAML follows source first-appearance
    order; no crossing-minimizing graph layout is attempted. Use the
    existing draw.io export/sync loop to manually fix a messy auto-layout.
  - Quoted labels (`A["text with [brackets]"]`) and nested brackets are not
    unescaped/parsed specially.
  - `classDef`/`class`/`style`/`click` and any other directive not listed
    above is silently ignored.
"""

from __future__ import annotations

import re
from typing import Optional

from .errors import DiagramError

_HEADER_RE = re.compile(r"^\s*(?:flowchart|graph)\s+(TD|TB|BT|LR|RL)\b", re.IGNORECASE)
_SUBGRAPH_RE = re.compile(r"^\s*subgraph\s+(.+)$", re.IGNORECASE)
_SUBGRAPH_ID_TITLE_RE = re.compile(r"^(\S+)\s*\[(.*)\]$")
_END_RE = re.compile(r"^\s*end\s*$", re.IGNORECASE)
_COMMENT_RE = re.compile(r"^\s*%%")

_ARROW_RE = re.compile(r"(<-->|-\.->|==+>|-->|---)(?:\|(?P<label>[^|]*)\|)?")
_ARROW_KIND = {"<-->": "both", "-.->": "end", "-->": "end", "---": "none"}


def _arrow_kind(token: str) -> str:
    # "==+>" (thick arrow) matches any run of 2+ "=" - not just the literal
    # "==>" example key above - so it's resolved by shape, not a dict lookup.
    if token.startswith("=") and token.endswith(">"):
        return "end"
    return _ARROW_KIND[token]

_NODE_RE = re.compile(
    r"^(?P<id>[A-Za-z0-9_-]+)(?:"
    r"\(\((?P<circle>[^)]*)\)\)"
    r"|\[(?P<rect>[^\]]*)\]"
    r"|\((?P<rounded>[^)]*)\)"
    r"|\{(?P<diamond>[^}]*)\}"
    r")?$"
)

_DIRECTION_TO_LAYOUT = {
    "TD": "vertical",
    "TB": "vertical",
    "BT": "vertical",
    "LR": "horizontal",
    "RL": "horizontal",
}

_OTHER_DIAGRAM_TYPES = {
    "sequencediagram",
    "classdiagram",
    "statediagram",
    "statediagram-v2",
    "erdiagram",
    "journey",
    "gantt",
    "pie",
    "gitgraph",
    "mindmap",
    "timeline",
    "quadrantchart",
    "sankey-beta",
    "requirementdiagram",
    "block-beta",
    "c4context",
    "xychart-beta",
}


def _reject_unsupported_diagram_type(text: str) -> None:
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or _COMMENT_RE.match(line):
            continue
        first_word = re.split(r"\s", line, maxsplit=1)[0]
        if first_word.lower() in _OTHER_DIAGRAM_TYPES:
            raise DiagramError(
                f"Unsupported Mermaid diagram type '{first_word}' - zook only "
                "supports 'flowchart'/'graph' (flowchart syntax) in this version. "
                "See docs-site/mermaid-import.md."
            )
        return


def _strip_quotes(text: str) -> str:
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
        return text[1:-1]
    return text


def _safe_id(raw: str, used_ids: set[str]) -> str:
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", raw).strip("_") or "n"
    if not slug[0].isalpha():
        slug = f"n_{slug}"
    candidate = slug
    i = 2
    while candidate in used_ids:
        candidate = f"{slug}_{i}"
        i += 1
    used_ids.add(candidate)
    return candidate


def _parse_subgraph_header(rest: str) -> tuple[str, Optional[str]]:
    rest = rest.strip()
    m = _SUBGRAPH_ID_TITLE_RE.match(rest)
    if m:
        return m.group(1), _strip_quotes(m.group(2))
    return rest, rest  # bare `subgraph Some Title` - id and title are the same text


def _register_or_get(ref_text: str, children: list, id_map: dict[str, str], used_ids: set[str], line_no: int) -> str:
    m = _NODE_RE.match(ref_text)
    if not m:
        raise DiagramError(f"Mermaid parse error at line {line_no}: could not parse node reference '{ref_text}'")
    raw_id = m.group("id")
    if raw_id in id_map:
        return id_map[raw_id]

    shape, label_raw = "rect", None
    if m.group("circle") is not None:
        shape, label_raw = "circle", m.group("circle")
    elif m.group("rect") is not None:
        shape, label_raw = "rect", m.group("rect")
    elif m.group("rounded") is not None:
        shape, label_raw = "rounded", m.group("rounded")
    elif m.group("diamond") is not None:
        shape, label_raw = "diamond", m.group("diamond")

    label = _strip_quotes(label_raw) if label_raw is not None else raw_id
    safe_id = _safe_id(raw_id, used_ids)
    id_map[raw_id] = safe_id
    children.append(
        {
            "kind": "node",
            "id": safe_id,
            "type": label or raw_id,
            "label": label,
            "style": {"shape": shape},
        }
    )
    return safe_id


def parse_flowchart(text: str) -> dict:
    """Parse Mermaid `flowchart`/`graph` source into a dict conforming to
    zook.schema.json (version/canvas/elements/links), ready for
    `zook.validate.validate()`."""
    _reject_unsupported_diagram_type(text)

    used_ids: set[str] = set()
    id_map: dict[str, str] = {}
    links: list[dict] = []

    root_id = _safe_id("flowchart", used_ids)
    root = {"kind": "container", "id": root_id, "type": "group", "layout": {"direction": "vertical"}, "children": []}
    stack = [root]
    direction_set = False

    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or _COMMENT_RE.match(line):
            continue

        header_match = _HEADER_RE.match(line)
        if header_match:
            if not direction_set:
                root["layout"]["direction"] = _DIRECTION_TO_LAYOUT[header_match.group(1).upper()]
                direction_set = True
            continue

        if _END_RE.match(line):
            if len(stack) == 1:
                raise DiagramError(f"Mermaid parse error at line {line_no}: 'end' has no matching 'subgraph'")
            stack.pop()
            continue

        subgraph_match = _SUBGRAPH_RE.match(line)
        if subgraph_match:
            raw_id, title = _parse_subgraph_header(subgraph_match.group(1))
            if raw_id in id_map:
                raise DiagramError(f"Mermaid parse error at line {line_no}: duplicate id '{raw_id}'")
            safe_id = _safe_id(raw_id, used_ids)
            id_map[raw_id] = safe_id
            container = {
                "kind": "container",
                "id": safe_id,
                "type": "group",
                "layout": {"direction": root["layout"]["direction"]},
                "children": [],
            }
            if title and title != raw_id:
                container["label"] = title
            stack[-1]["children"].append(container)
            stack.append(container)
            continue

        arrow_matches = list(_ARROW_RE.finditer(line))
        if arrow_matches:
            node_texts = []
            prev_end = 0
            for m in arrow_matches:
                node_texts.append(line[prev_end : m.start()].strip())
                prev_end = m.end()
            node_texts.append(line[prev_end:].strip())

            endpoint_ids = [
                _register_or_get(text_, stack[-1]["children"], id_map, used_ids, line_no) for text_ in node_texts
            ]
            for i, m in enumerate(arrow_matches):
                arrow_kind = _arrow_kind(m.group(1))
                label = m.group("label")
                link = {"from": endpoint_ids[i], "to": endpoint_ids[i + 1]}
                if arrow_kind != "end":
                    link["arrow"] = arrow_kind
                if label:
                    link["label"] = _strip_quotes(label)
                links.append(link)
            continue

        if _NODE_RE.match(line):
            _register_or_get(line, stack[-1]["children"], id_map, used_ids, line_no)
            continue

        # Unrecognized construct (classDef/style/click/direction/...) - ignored.
        # See docs-site/mermaid-import.md for the exact supported syntax list.

    if len(stack) != 1:
        unclosed = ", ".join(c["id"] for c in stack[1:])
        raise DiagramError(f"Mermaid parse error: unclosed 'subgraph' (missing 'end') for: {unclosed}")

    if not root["children"] and not links:
        raise DiagramError(
            "No nodes or edges found - is this valid 'flowchart'/'graph' Mermaid syntax? "
            "See docs-site/mermaid-import.md."
        )

    return {
        "version": "1.0",
        "canvas": {"aspectRatio": "16:9"},
        "elements": [root],
        "links": links,
    }
