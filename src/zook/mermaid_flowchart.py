"""Hand-rolled parser for Mermaid `flowchart`/`graph` syntax (phase 1: the
sequenceDiagram type needs a wholly different, vertical-lifeline rendering
engine and is out of scope here - see the Mermaid import plan).

No third-party Mermaid parser was adopted: the one candidate found
(`mermaid-parser-py`) shells out to a JS engine via PythonMonkey, has low
adoption, and its own author documents that it can break on future Mermaid
grammar changes. A small regex/line-based parser covering the common subset
below is more maintainable for this project.

Supported syntax:
  - Header: `flowchart <TD|TB|BT|LR|RL>` or the legacy `graph <...>` alias
    (direction optional). TD/TB/BT map to a vertical layout, LR/RL to
    horizontal. Missing header or direction defaults to vertical rather than
    erroring. `direction <TD|LR|...>` inside a subgraph sets that
    subgraph's own direction.
  - `;` as a statement separator (`graph TD;` / `A-->B;` / `graph LR; A-->B`),
    as in Mermaid's grammar and GitHub's own examples.
  - `%% ...` full-line comments.
  - Nodes: `id[label]` (rect), `id(label)` (rounded), `id{label}` (diamond),
    `id((label))` (circle), and every other Mermaid shape mapped to the
    closest of those (_SHAPES). Quoted labels may contain brackets/arrows;
    `:::class` is ignored; `<br>`, `#quot;`-style entities and markdown
    strings are converted (_clean_label). Mermaid 11's `id@{ shape: cyl,
    label: "..." }` form is read the same way (_V11_SHAPES). A bare `id`
    used only in an edge is a `rect` labelled with its id; a later explicit
    label/shape wins.
  - Edges: normal/thick/dotted/invisible links with `>`/`x`/`o` heads and
    any length (_LINK_TOKEN), `|label|` or `-- label -->`-style labels,
    `A & B --> C & D`, chained edges, Mermaid 11 edge ids (`A e1@--> B`,
    whose `e1@{ animate: true }` property statements are ignored).
    Dotted/thick styling isn't reproduced.
  - `subgraph <id>[<Title>]` ... `end`, nestable. Without `[<Title>]` the
    subgraph's own text is its title (`subgraph Backend`, `subgraph "AWS
    Cloud"`), as Mermaid draws it. `end` is lowercase-only, so `End`/`END`
    stay usable as node ids. Membership follows Mermaid: the first-closed
    subgraph that mentions a node owns it.
  - A branching scope (fan-out/fan-in) is arranged by rank: same-rank
    members side by side in a borderless row/column (see by_rank).
  - `classDef`/`class`/`style`/`linkStyle`/`click`/`acc*` statements and a
    top-level `direction` are ignored, as are a surrounding ```mermaid code
    fence, `---` front matter and `%%{ }%%` directives. Anything else the
    parser can't read is a DiagramError naming the line, never silently
    dropped.
"""

from __future__ import annotations

import re
from typing import Optional

from .errors import DiagramError

# The header is the keyword plus at most one direction-ish token (a node
# reference like `graph --> B` in a headerless file is not a header). An
# unrecognised token is ignored rather than becoming a node.
_HEADER_RE = re.compile(r"^(?:flowchart-elk|flowchart|graph)(?:\s+(?P<dir>[A-Za-z<>^]+))?$", re.IGNORECASE)
_DIRECTION_RE = re.compile(r"^direction\s+(?P<dir>[A-Za-z<>^]+)$", re.IGNORECASE)
_SUBGRAPH_RE = re.compile(r"^\s*subgraph\s+(.+)$", re.IGNORECASE)
_SUBGRAPH_ID_TITLE_RE = re.compile(r"^([^\s\[]+)\s*\[(.*)\]$")
# Mermaid's keyword is lowercase `end` only; its docs tell authors to write a
# node called "end" as `End`/`END`, which must not close a subgraph.
_END_RE = re.compile(r"^\s*end\s*$")
_COMMENT_RE = re.compile(r"^\s*%%")
_CODE_FENCE_RE = re.compile(r"^\s*```")
# Styling/interaction/accessibility statements zook has nothing to map to;
# ignored (documented), unlike an edge it can't read, which is an error.
_IGNORED_STATEMENT_RE = re.compile(r"^(?:classDef|class|style|linkStyle|click|accTitle|accDescr)\b")
_EDGE_LIKE_RE = re.compile(r"--|==|-\.|~~~")

# One edge token, as Mermaid's lexer reads them (flow.jison LINK/THICK_LINK/
# DOTTED_LINK, with START_LINK...EDGE_TEXT for the `-- text -->` forms):
#   normal  --> --- --x --o <--> x--x o--o ---->    (2+ dashes)
#   thick   ==> === <==>                             (2+ equals)
#   dotted  -.-> -.- -..-> <-.->
#   invisible ~~~
# optionally followed by a `|label|` (spaces allowed before it).
_LINK_TOKEN = r"(?P<l>[xo<]?)(?P<tok>-{2,}[->xo]|={2,}[=>xo]|-\.+-[>xo]?|~{3,})"
_LINK_RE = re.compile(r"\s*" + _LINK_TOKEN + r"(?:\s*\|(?P<label>[^|]*)\|)?\s*")
# `A -- text --> B` / `A == text ==> B` / `A -. text .-> B`
_TEXT_LINK_RE = re.compile(
    r"\s*(?P<l>[xo<]?)(?P<open>--|==|-\.)\s+(?P<text>.+?)\s+(?P<close>-{2,}[->xo]|={2,}[=>xo]|\.+-[>xo]?)\s*"
)
# An id may contain `-`/`.` between word characters (`my-node`, `a.b`), but
# never where an edge starts (`A-->B`, `A-.->B`).
_NODE_ID_RE = re.compile(r"[A-Za-z0-9_]+(?:[.-][A-Za-z0-9_]+)*")
# Node shapes, longest opener first. Each maps to the closest zook shape:
# zook draws rect/rounded/diamond/circle, so the rest are approximations.
_SHAPES = [
    ("(((", ")))", "circle"),  # double circle
    ("((", "))", "circle"),
    ("([", "])", "rounded"),  # stadium
    ("[[", "]]", "rect"),  # subroutine
    ("[(", ")]", "rounded"),  # cylinder (database)
    ("[/", "/]", "rect"),  # parallelogram
    ("[/", "\\]", "rect"),  # trapezoid
    ("[\\", "\\]", "rect"),  # parallelogram (alt)
    ("[\\", "/]", "rect"),  # trapezoid (alt)
    ("{{", "}}", "diamond"),  # hexagon
    ("(", ")", "rounded"),
    ("[", "]", "rect"),
    ("{", "}", "diamond"),
    (">", "]", "rect"),  # asymmetric
]
_CLASS_SUFFIX_RE = re.compile(r":::[A-Za-z0-9_-]+")
# Mermaid 11 `id@{ shape: ... }` names (and their aliases), mapped like the
# bracket forms above: stadium/cylinder -> rounded, hexagon -> diamond, every
# circle variant -> circle; anything else (documents, trapezoids, ...) -> rect.
_V11_SHAPES = {
    **dict.fromkeys(["rounded", "event", "stadium", "pill", "terminal", "cyl", "cylinder", "database", "db",
                     "h-cyl", "das", "horizontal-cylinder", "lin-cyl", "disk", "lined-cylinder"], "rounded"),
    **dict.fromkeys(["diam", "diamond", "decision", "question", "hex", "hexagon", "prepare"], "diamond"),
    **dict.fromkeys(["circle", "circ", "dbl-circ", "double-circle", "sm-circ", "small-circle", "start",
                     "fr-circ", "framed-circle", "stop", "f-circ", "filled-circle", "junction", "cross-circ",
                     "crossed-circle", "summary"], "circle"),
}
# Keys of an edge's own `e1@{ ... }` statement (it styles an edge, not a node).
_EDGE_PROPERTY_KEYS = {"animate", "animation", "curve"}
_EDGE_ID_RE = re.compile(r"\s*[A-Za-z0-9_]+@(?=[-=.~<xo])")

_DIRECTION_TO_LAYOUT = {
    "TD": "vertical",
    "TB": "vertical",
    "BT": "vertical",
    "LR": "horizontal",
    "RL": "horizontal",
    # Mermaid's other direction tokens (flow.jison): v/^ down/up, >/< right/left.
    "V": "vertical",
    "^": "vertical",
    ">": "horizontal",
    "<": "horizontal",
}

_OTHER_DIAGRAM_TYPES = {
    "sequencediagram",
    "classdiagram",
    "classdiagram-v2",
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
    "sankey",
    "sankey-beta",
    "requirementdiagram",
    "requirement",
    "block",
    "block-beta",
    "c4context",
    "c4container",
    "c4component",
    "c4dynamic",
    "c4deployment",
    "xychart",
    "xychart-beta",
    "architecture",
    "architecture-beta",
    "kanban",
    "packet",
    "packet-beta",
    "radar-beta",
    "treemap",
    "treemap-beta",
    "zenuml",
    "info",
}


def _reject_unsupported_diagram_type(first_statement: str) -> None:
    first_word = re.split(r"[\s;:]", first_statement, maxsplit=1)[0]
    # A headerless flowchart may well start with a node called `block` or
    # `info` (`block --> db`); only a bare keyword line declares a type.
    if first_word.lower() in _OTHER_DIAGRAM_TYPES and not _EDGE_LIKE_RE.search(first_statement):
        raise DiagramError(
            f"Unsupported Mermaid diagram type '{first_word}' - zook only "
            "supports 'flowchart'/'graph' (flowchart syntax) in this version. "
            "See docs-site/mermaid-import.md."
        )


def _source_statements(text: str) -> list[tuple[int, str]]:
    """(line number, statement) pairs, with everything that isn't flowchart
    content dropped first: a ```mermaid code fence (an AI often wraps the
    diagram in one), `---` YAML front matter, `%%` comments and multi-line
    `%%{ ... }%%` directives, and accessibility text (`accTitle:` /
    `accDescr:` / `accDescr { ... }`), whose value may itself contain `;`."""
    lines = text.splitlines()
    statements: list[tuple[int, str]] = []
    i = 0
    seen_content = False
    while i < len(lines):
        line_no, line = i + 1, lines[i].strip()
        i += 1
        if not line or _CODE_FENCE_RE.match(line):
            continue
        if line == "---" and not seen_content:  # front matter
            while i < len(lines) and lines[i].strip() != "---":
                i += 1
            i += 1
            continue
        if line.startswith("%%{") and "}%%" not in line:  # multi-line directive
            while i < len(lines) and "}%%" not in lines[i]:
                i += 1
            i += 1
            continue
        if _COMMENT_RE.match(line):
            continue
        if re.match(r"^accDescr\s*\{", line):
            while "}" not in line and i < len(lines):
                line = lines[i]
                i += 1
            continue
        if re.match(r"^acc(?:Title|Descr)\s*:", line):
            continue
        seen_content = True
        statements.extend((line_no, stmt) for stmt in _split_statements(line))
    return statements


def _strip_quotes(text: str) -> str:
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
        return text[1:-1]
    return text


def _split_statements(line: str) -> list[str]:
    """Split one source line on the `;` statement separator, ignoring any `;`
    inside a quoted string, a bracketed label, or an `|edge label|` (where
    Mermaid's `#59;`-style entities also contain one)."""
    parts: list[str] = []
    buf: list[str] = []
    depth = 0
    in_quote = False
    in_edge_label = False
    for ch in line:
        if in_quote:
            in_quote = ch != '"'
        elif ch == '"':
            in_quote = True
        elif ch == "|":
            in_edge_label = not in_edge_label
        elif not in_edge_label and ch in "([{":
            depth += 1
        elif not in_edge_label and ch in ")]}":
            depth = max(0, depth - 1)
        elif ch == ";" and depth == 0 and not in_edge_label:
            parts.append("".join(buf))
            buf = []
            continue
        buf.append(ch)
    parts.append("".join(buf))
    return [part.strip() for part in parts if part.strip()]


def _safe_id(raw: str, used_ids: set[str], fallback: str = "n") -> str:
    # `fallback` names an id whose source text has no ASCII letters/digits
    # at all (e.g. a Japanese subgraph name) - the text itself stays the label.
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", raw).strip("_") or fallback
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
    # Bare `subgraph Backend` / `subgraph My Group` / `subgraph "AWS Cloud"`:
    # Mermaid draws that text as the title, and it is the id too.
    title = _strip_quotes(rest)
    return title, title


def _unsupported_edge_message(line_no: int, text: str) -> str:
    return (
        f"Mermaid parse error at line {line_no}: unsupported edge syntax in '{text}' - "
        "see docs-site/mermaid-import.md for the arrows zook reads"
    )


_ENTITY_RE = re.compile(r"#(\w+);")
_NAMED_ENTITIES = {"quot": '"', "amp": "&", "lt": "<", "gt": ">", "apos": "'", "nbsp": " ", "semi": ";", "num": "#"}


def _clean_label(text: str) -> str:
    """Mermaid label text -> plain text: quotes stripped, `<br>` as a line
    break, `#quot;`/`#35;`-style entities decoded, and a "`markdown`"
    string's backticks and **bold**/*italic* markers dropped."""
    text = _strip_quotes(text.strip())
    if len(text) >= 2 and text[0] == text[-1] == "`":
        text = re.sub(r"\*\*(.+?)\*\*|\*(.+?)\*|_(.+?)_", lambda m: next(g for g in m.groups() if g), text[1:-1])
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)

    def entity(m: re.Match) -> str:
        name = m.group(1)
        if name.isdigit():
            return chr(int(name))
        return _NAMED_ENTITIES.get(name, m.group(0))

    return _ENTITY_RE.sub(entity, text)


class _NodeRef:
    __slots__ = ("raw_id", "shape", "label", "properties")

    def __init__(self, raw_id: str, shape: Optional[str], label: Optional[str], properties: Optional[dict] = None):
        self.raw_id, self.shape, self.label = raw_id, shape, label
        self.properties = properties  # the `@{ ... }` block, if any


def _parse_properties(text: str, pos: int, line_no: int, statement: str) -> tuple[dict, int]:
    """The `{ key: value, ... }` block of Mermaid 11's `id@{ ... }`, starting
    at the `{` at `pos` - a YAML-style flow mapping (quoted values may hold
    commas and braces)."""
    depth, quote, end = 0, None, None
    for i in range(pos, len(text)):
        ch = text[i]
        if quote:
            quote = None if ch == quote else quote
        elif ch in "\"'":
            quote = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    if end is None:
        raise DiagramError(f"Mermaid parse error at line {line_no}: unclosed '@{{' in '{statement}'")
    body = text[pos + 1 : end]
    properties: dict = {}
    for item in re.findall(r"""(?:[^,"']|"[^"]*"|'[^']*')+""", body):
        key, sep, value = item.partition(":")
        if not sep:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        properties[key.strip()] = value
    return properties, end + 1


def _parse_node(text: str, pos: int, line_no: int, statement: str) -> tuple[_NodeRef, int]:
    while pos < len(text) and text[pos] == " ":
        pos += 1
    m = _NODE_ID_RE.match(text, pos)
    if not m:
        raise DiagramError(_bad_reference(line_no, statement))
    raw_id, pos = m.group(0), m.end()
    shape = label = None
    if text.startswith("@{", pos):  # Mermaid 11: id@{ shape: cyl, label: "..." }
        properties, pos = _parse_properties(text, pos + 1, line_no, statement)
        if "shape" in properties:
            shape = _V11_SHAPES.get(properties["shape"].strip().lower(), "rect")
        if "label" in properties:
            label = properties["label"]
        m = _CLASS_SUFFIX_RE.match(text, pos)
        if m:
            pos = m.end()
        return _NodeRef(raw_id, shape, _clean_label(label) if label is not None else None, properties), pos
    for opener, closer, zook_shape in _SHAPES:
        if not text.startswith(opener, pos):
            continue
        start = pos + len(opener)
        if text.startswith('"', start):  # quoted label: brackets inside are text
            end_quote = text.find('"', start + 1)
            if end_quote == -1 or not text.startswith(closer, end_quote + 1):
                continue
            label, pos = text[start : end_quote + 1], end_quote + 1 + len(closer)
        else:
            end = text.find(closer, start)
            if end == -1:
                continue
            label, pos = text[start:end], end + len(closer)
        shape = zook_shape
        break
    m = _CLASS_SUFFIX_RE.match(text, pos)  # `:::className` - styling, ignored
    if m:
        pos = m.end()
    return _NodeRef(raw_id, shape, _clean_label(label) if label is not None else None), pos


def _parse_node_group(text: str, pos: int, line_no: int, statement: str) -> tuple[list[_NodeRef], int]:
    """`A` or `A & B & C` (Mermaid's shorthand for one edge per member)."""
    nodes = []
    while True:
        node, pos = _parse_node(text, pos, line_no, statement)
        nodes.append(node)
        m = re.compile(r"\s*&\s*").match(text, pos)
        if not m:
            return nodes, pos
        pos = m.end()


def _bad_reference(line_no: int, statement: str) -> str:
    if _EDGE_LIKE_RE.search(statement):
        return _unsupported_edge_message(line_no, statement)
    return f"Mermaid parse error at line {line_no}: could not parse node reference in '{statement}'"


def _parse_link(text: str, pos: int) -> Optional[tuple[str, Optional[str], bool, int]]:
    """(arrow, label, visible, new_pos) for the edge starting at `pos`, or None."""
    m = _TEXT_LINK_RE.match(text, pos)
    if m:
        left = m.group("l") != ""
        right = m.group("close")[-1] in ">xo"
        return _arrow(left, right), _clean_label(m.group("text")), True, m.end()
    m = _LINK_RE.match(text, pos)
    if not m:
        return None
    token = m.group("tok")
    if token.startswith("~"):
        return "none", None, False, m.end()  # ~~~ invisible link: layout hint only
    left = m.group("l") != ""
    right = token[-1] in (">", "x", "o")
    label = m.group("label")
    return _arrow(left, right), (_clean_label(label) if label and label.strip() else None), True, m.end()


def _arrow(left: bool, right: bool) -> str:
    if left and right:
        return "both"
    return "end" if right or left else "none"


def _parse_statement(statement: str, line_no: int):
    """A node/edge statement -> (node refs in order, edges as (from, to,
    arrow, label)). Raises DiagramError on anything it can't read, so an
    unsupported construct is never silently dropped."""
    groups, links = [], []
    group, pos = _parse_node_group(statement, 0, line_no, statement)
    groups.append(group)
    while pos < len(statement):
        link = _parse_link(statement, pos)
        edge_id = _EDGE_ID_RE.match(statement, pos)
        if link is None and edge_id:  # Mermaid 11 edge id: `A e1@--> B`
            link = _parse_link(statement, edge_id.end())
        if link is None:
            raise DiagramError(_bad_reference(line_no, statement))
        arrow, label, visible, pos = link
        group, pos = _parse_node_group(statement, pos, line_no, statement)
        groups.append(group)
        links.append((arrow, label, visible))
    edges = []
    for k, (arrow, label, visible) in enumerate(links):
        if not visible:
            continue
        for src in groups[k]:
            for dst in groups[k + 1]:
                edges.append((src.raw_id, dst.raw_id, arrow, label))
    return [n for g in groups for n in g], edges


def parse_flowchart(text: str) -> dict:
    """Parse Mermaid `flowchart`/`graph` source into a dict conforming to
    zook.schema.json (version/canvas/elements/links), ready for
    `zook.validate.validate()`.

    Two passes, as Mermaid itself resolves a graph: first every statement is
    read (node definitions - where a later explicit label/shape wins - the
    nodes each subgraph block mentions, and the edges), then the tree is
    built. A node belongs to the first subgraph *closed* that mentions it -
    so a nested subgraph wins over its parent - and a node only ever
    mentioned at the top level stays there; so `A --> B` followed by
    `subgraph S; B; end` puts B in S, as Mermaid draws it."""
    text = text.lstrip("﻿")  # a UTF-8 BOM would hide the header line
    statements = _source_statements(text)
    if statements:
        _reject_unsupported_diagram_type(statements[0][1])

    root_direction = "vertical"
    # pass 1
    node_defs: dict[str, dict] = {}  # raw id -> {"label", "shape"}
    appearance: list[tuple[str, str]] = []  # ("node"|"subgraph", raw id) in first-appearance order, per scope
    subgraphs: dict[str, dict] = {}  # raw id -> {"title", "direction", "parent", "members": [ids], "closed": int}
    edges: list[tuple[str, str, str, Optional[str]]] = []
    stack: list[Optional[str]] = [None]  # None = top level
    scope_items: dict[Optional[str], list[tuple[str, str]]] = {None: []}
    close_counter = 0
    content_seen = False

    def mention(raw_id: str) -> None:
        scope = stack[-1]
        entry = ("node", raw_id)
        if entry not in scope_items[scope]:
            scope_items[scope].append(entry)

    for line_no, line in statements:
        if not content_seen:
            header_match = _HEADER_RE.match(line)
            if header_match:
                direction = (header_match.group("dir") or "").upper()
                if direction in _DIRECTION_TO_LAYOUT:
                    root_direction = _DIRECTION_TO_LAYOUT[direction]
                continue

        direction_match = _DIRECTION_RE.match(line)
        if direction_match:
            # Mermaid honours `direction` only inside a subgraph (a top-level
            # one is ignored - the header sets the graph's direction).
            direction = direction_match.group("dir").upper()
            if stack[-1] is not None and direction in _DIRECTION_TO_LAYOUT:
                subgraphs[stack[-1]]["direction"] = _DIRECTION_TO_LAYOUT[direction]
            continue

        content_seen = True

        if _END_RE.match(line):
            if stack[-1] is None:
                raise DiagramError(f"Mermaid parse error at line {line_no}: 'end' has no matching 'subgraph'")
            close_counter += 1
            subgraphs[stack.pop()]["closed"] = close_counter
            continue

        subgraph_match = _SUBGRAPH_RE.match(line)
        if subgraph_match:
            raw_id, title = _parse_subgraph_header(subgraph_match.group(1))
            if raw_id in subgraphs:
                raise DiagramError(f"Mermaid parse error at line {line_no}: duplicate subgraph id '{raw_id}'")
            subgraphs[raw_id] = {"title": _clean_label(title) if title else "", "direction": None,
                                 "parent": stack[-1], "closed": 0}
            scope_items[stack[-1]].append(("subgraph", raw_id))
            scope_items[raw_id] = []
            stack.append(raw_id)
            continue

        if _IGNORED_STATEMENT_RE.match(line):
            continue  # classDef/style/click/...: nothing to map (documented)

        nodes, statement_edges = _parse_statement(line, line_no)
        if (
            len(nodes) == 1 and not statement_edges and nodes[0].properties is not None
            and set(nodes[0].properties) <= _EDGE_PROPERTY_KEYS
        ):
            continue  # `e1@{ animate: true }`: styles edge e1, not a node
        for node in nodes:
            definition = node_defs.setdefault(node.raw_id, {"label": None, "shape": None})
            # the latest explicit definition wins, as in Mermaid
            if node.label is not None:
                definition["label"] = node.label
            if node.shape is not None:
                definition["shape"] = node.shape
            mention(node.raw_id)
        edges.extend(statement_edges)

    if len(stack) != 1:
        unclosed = ", ".join(str(sg) for sg in stack[1:])
        raise DiagramError(
            f"Mermaid parse error: unclosed 'subgraph' (missing 'end') for: {unclosed} "
            "- only lowercase `end` closes a subgraph (`End`/`END` are node ids)"
        )
    if not node_defs and not subgraphs:
        raise DiagramError(
            "No nodes or edges found - is this valid 'flowchart'/'graph' Mermaid syntax? "
            "See docs-site/mermaid-import.md."
        )

    # pass 2: who owns each node - the first-closed subgraph that mentions it
    owner: dict[str, Optional[str]] = {}
    for sg_id in sorted(subgraphs, key=lambda k: subgraphs[k]["closed"]):
        for kind, raw_id in scope_items[sg_id]:
            if kind == "node" and raw_id not in subgraphs and raw_id not in owner:
                owner[raw_id] = sg_id

    used_ids: set[str] = set()
    root_id = _safe_id("flowchart", used_ids)
    id_map: dict[str, str] = {}
    for sg_id in subgraphs:
        id_map[sg_id] = _safe_id(sg_id, used_ids, fallback="group")
    for raw_id in node_defs:
        if raw_id not in subgraphs:
            id_map[raw_id] = _safe_id(raw_id, used_ids)

    def unit_in(scope: Optional[str], raw_id: str) -> Optional[str]:
        """The direct member of `scope` that contains `raw_id` (itself, or
        the subgraph it sits in), or None if it lies outside `scope`."""
        current: Optional[str] = raw_id
        while True:
            parent = subgraphs[current]["parent"] if current in subgraphs else owner.get(current)
            if parent == scope:
                return current
            if parent is None:
                return None
            current = parent

    def by_rank(scope: Optional[str], members: list[str], children: list[dict], direction: str) -> list[dict]:
        """Arrange a scope's members by rank - how far along the edges between
        them each one sits - instead of in one line in source order, which
        stacked a branch's arms one after another and ran edges through
        nodes. A rank holding several members becomes a borderless row (a
        column, for LR) of its own; a plain chain is left exactly as is."""
        index = {m: k for k, m in enumerate(members)}
        succ: dict[str, list[str]] = {m: [] for m in members}
        for src, dst, _arrow, _label in edges:
            a, b = unit_in(scope, src), unit_in(scope, dst)
            if a is not None and b is not None and a != b and b not in succ[a]:
                succ[a].append(b)
        # drop back edges (cycles) found by a DFS in source order
        state: dict[str, int] = {}
        forward: dict[str, list[str]] = {m: [] for m in members}

        def dfs(v: str) -> None:
            state[v] = 1
            for w in succ[v]:
                if state.get(w) == 1:
                    continue  # back edge
                forward[v].append(w)
                if w not in state:
                    dfs(w)
            state[v] = 2

        for m in members:
            if m not in state:
                dfs(m)
        rank = {m: 0 for m in members}
        for _ in range(len(members)):  # longest path; the graph is acyclic now
            changed = False
            for v in members:
                for w in forward[v]:
                    if rank[w] < rank[v] + 1:
                        rank[w], changed = rank[v] + 1, True
            if not changed:
                break
        # Only a graph that actually branches (a fan-out or fan-in) needs
        # rank rows; chains stay one line - but in edge order, so a chain
        # written out of order (`J --> K`, then `F --> J`) still reads forward
        # instead of F's edge running back through J and K. Separate chains
        # (and unlinked members) keep their source order.
        preds_count = {m: 0 for m in members}
        for v in members:
            for w in forward[v]:
                preds_count[w] += 1
        if not any(len(forward[m]) > 1 or preds_count[m] > 1 for m in members):
            chain_start: dict[str, int] = {}  # member -> first source index of its chain
            for m in members:
                if m in chain_start:
                    continue
                run, todo = set(), [m]
                while todo:
                    v = todo.pop()
                    if v not in run:
                        run.add(v)
                        todo.extend(forward[v])
                        todo.extend(u for u in members if v in forward[u])
                for v in run:
                    chain_start[v] = index[m]
            order = sorted(members, key=lambda m: (chain_start[m], rank[m], index[m]))
            return [children[index[m]] for m in order]
        levels: dict[int, list[str]] = {}
        for m in members:
            levels.setdefault(rank[m], []).append(m)
        position: dict[str, float] = {}
        arranged = []
        for r in sorted(levels):
            level = levels[r]
            preds = {m: [position[v] for v in members if m in forward[v] and v in position] for m in level}
            level.sort(key=lambda m: (sum(preds[m]) / len(preds[m]) if preds[m] else float(index[m]), index[m]))
            for k, m in enumerate(level):
                position[m] = k - (len(level) - 1) / 2
            if len(level) == 1:
                arranged.append(children[index[level[0]]])
            else:
                row_id = _safe_id(f"{id_map.get(scope, root_id) if scope else root_id}_rank{r + 1}", used_ids)
                arranged.append({
                    "kind": "container",
                    "id": row_id,
                    "type": "group",
                    "layout": {"direction": "horizontal" if direction == "vertical" else "vertical", "padding": 0, "gap": 40},
                    "style": {"borderWidth": 0},
                    "children": [children[index[m]] for m in level],
                })
        return arranged

    def build(scope: Optional[str], direction: str) -> list[dict]:
        children = []
        members: list[str] = []
        for kind, raw_id in scope_items[scope]:
            if kind == "subgraph":
                sg = subgraphs[raw_id]
                container = {"kind": "container", "id": id_map[raw_id], "type": "group"}
                if sg["title"]:
                    container["label"] = sg["title"]
                sub_direction = sg["direction"] or direction
                container["layout"] = {"direction": sub_direction}
                container["children"] = build(raw_id, sub_direction)
                children.append(container)
                members.append(raw_id)
            elif raw_id not in subgraphs and owner.get(raw_id) == scope and not any(
                c.get("id") == id_map[raw_id] for c in children
            ):
                definition = node_defs[raw_id]
                label = definition["label"] if definition["label"] is not None else raw_id
                children.append({
                    "kind": "node",
                    "id": id_map[raw_id],
                    "type": label or raw_id,
                    "label": label,
                    "style": {"shape": definition["shape"] or "rect"},
                })
                members.append(raw_id)
        return by_rank(scope, members, children, direction)

    # The synthetic top-level container only carries the direction; no frame.
    root = {"kind": "container", "id": root_id, "type": "group", "layout": {"direction": root_direction},
            "style": {"borderWidth": 0}, "children": build(None, root_direction)}

    links = []
    for src, dst, arrow, label in edges:
        link = {"from": id_map[src], "to": id_map[dst]}
        if arrow != "end":
            link["arrow"] = arrow
        if label:
            link["label"] = label
        links.append(link)

    return {
        "version": "1.0",
        "canvas": {"aspectRatio": "16:9"},
        "elements": [root],
        "links": links,
    }
