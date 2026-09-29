from pathlib import Path

import pytest

from zook.errors import DiagramError
from zook.mermaid_flowchart import parse_flowchart
from zook.model import parse_diagram
from zook.validate import validate

FIXTURE = Path(__file__).parent / "fixtures" / "example.mmd"


def _root_children(raw: dict) -> list:
    return raw["elements"][0]["children"]


def _node_ids(elements: list) -> list:
    ids = []
    for el in elements:
        if el["kind"] == "node":
            ids.append(el["id"])
        ids.extend(_node_ids(el.get("children", [])))
    return ids


def _by_id(elements: list, element_id: str) -> dict:
    for el in elements:
        if el["id"] == element_id:
            return el
    raise KeyError(element_id)


def test_header_direction_maps_to_layout():
    vertical = parse_flowchart("flowchart TD\nA[a] --> B[b]\n")
    assert vertical["elements"][0]["layout"]["direction"] == "vertical"

    horizontal = parse_flowchart("flowchart LR\nA[a] --> B[b]\n")
    assert horizontal["elements"][0]["layout"]["direction"] == "horizontal"

    legacy_graph = parse_flowchart("graph TB\nA[a] --> B[b]\n")
    assert legacy_graph["elements"][0]["layout"]["direction"] == "vertical"


def test_missing_header_defaults_to_vertical():
    raw = parse_flowchart("A[a] --> B[b]\n")
    assert raw["elements"][0]["layout"]["direction"] == "vertical"


@pytest.mark.parametrize(
    "src,expected_shape,expected_label",
    [
        ("A[Rect]", "rect", "Rect"),
        ("A(Rounded)", "rounded", "Rounded"),
        ("A{Diamond}", "diamond", "Diamond"),
        ("A((Circle))", "circle", "Circle"),
    ],
)
def test_each_node_shape_is_parsed(src, expected_shape, expected_label):
    raw = parse_flowchart(f"flowchart TD\n{src} --> Z[z]\n")
    node = _by_id(_root_children(raw), "A")
    assert node["style"]["shape"] == expected_shape
    assert node["label"] == expected_label


def test_bare_id_with_no_declaration_is_auto_registered_as_rect_using_id_as_label():
    raw = parse_flowchart("flowchart TD\nA --> B\n")
    node = _by_id(_root_children(raw), "A")
    assert node["style"]["shape"] == "rect"
    assert node["label"] == "A"


@pytest.mark.parametrize(
    "arrow,expected_arrow_key",
    [
        ("-->", None),  # default "end" - omitted from output
        ("---", "none"),
        ("<-->", "both"),
        ("-.->", None),  # dashed styling not modeled - same as "-->"
        ("==>", None),  # thick styling not modeled - same as "-->"
    ],
)
def test_arrow_kinds(arrow, expected_arrow_key):
    raw = parse_flowchart(f"flowchart TD\nA[a] {arrow} B[b]\n")
    link = raw["links"][0]
    if expected_arrow_key is None:
        assert "arrow" not in link
    else:
        assert link["arrow"] == expected_arrow_key


def test_edge_label_via_pipe_syntax():
    raw = parse_flowchart("flowchart TD\nA[a] -->|yes| B[b]\n")
    assert raw["links"][0]["label"] == "yes"


def test_chained_edges_on_one_line():
    raw = parse_flowchart("flowchart TD\nA[a] --> B[b] --> C[c]\n")
    links = raw["links"]
    assert len(links) == 2
    assert (links[0]["from"], links[0]["to"]) == ("A", "B")
    assert (links[1]["from"], links[1]["to"]) == ("B", "C")


def test_full_line_comments_are_ignored():
    raw = parse_flowchart("flowchart TD\n%% comment\nA[a] --> B[b]\n%% trailing\n")
    assert len(_root_children(raw)) == 2
    assert len(raw["links"]) == 1


def test_subgraph_with_title_becomes_labeled_container():
    raw = parse_flowchart(
        """flowchart TD
        A[a]
        subgraph grp[My Group]
          B[b]
        end
        """
    )
    children = _root_children(raw)
    group = _by_id(children, "grp")
    assert group["kind"] == "container"
    assert group["label"] == "My Group"
    assert group["children"][0]["id"] == "B"


def test_nested_subgraphs():
    raw = parse_flowchart(
        """flowchart TD
        subgraph outer[Outer]
          subgraph inner[Inner]
            A[a]
          end
        end
        """
    )
    outer = _by_id(_root_children(raw), "outer")
    inner = _by_id(outer["children"], "inner")
    assert inner["label"] == "Inner"
    assert inner["children"][0]["id"] == "A"


def test_node_order_follows_first_appearance():
    raw = parse_flowchart("flowchart TD\nC[c] --> A[a]\nA --> B[b]\n")
    ids = [el["id"] for el in _root_children(raw)]
    assert ids == ["C", "A", "B"]


def test_unsupported_diagram_type_raises_diagram_error():
    with pytest.raises(DiagramError, match="sequenceDiagram"):
        parse_flowchart("sequenceDiagram\n  A->>B: hi\n")


def test_empty_flowchart_raises_diagram_error():
    with pytest.raises(DiagramError, match="No nodes or edges"):
        parse_flowchart("flowchart TD\n%% just a comment\n")


def test_end_without_subgraph_raises_diagram_error():
    with pytest.raises(DiagramError, match="no matching 'subgraph'"):
        parse_flowchart("flowchart TD\nA[a]\nend\n")


def test_unclosed_subgraph_raises_diagram_error():
    with pytest.raises(DiagramError, match="unclosed 'subgraph'"):
        parse_flowchart("flowchart TD\nsubgraph grp[G]\nA[a]\n")


def test_output_conforms_to_schema_and_parses_into_a_diagram():
    raw = parse_flowchart(FIXTURE.read_text())
    validate(raw)
    diagram = parse_diagram(raw)
    assert len(diagram.elements) == 1
    assert len(diagram.links) == 4


def test_cli_from_mermaid_writes_valid_yaml(tmp_path):
    from click.testing import CliRunner

    from zook.cli import main

    out_path = tmp_path / "out.yaml"
    runner = CliRunner()
    result = runner.invoke(main, ["from-mermaid", str(FIXTURE), "-o", str(out_path)])
    assert result.exit_code == 0, result.output
    assert out_path.exists()

    import yaml

    with open(out_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    assert raw["canvas"]["aspectRatio"] == "16:9"
    validate(raw)


def test_cli_from_mermaid_rejects_sequence_diagram(tmp_path):
    from click.testing import CliRunner

    from zook.cli import main

    src = tmp_path / "in.mmd"
    src.write_text("sequenceDiagram\n  A->>B: hi\n")
    runner = CliRunner()
    result = runner.invoke(main, ["from-mermaid", str(src), "-o", str(tmp_path / "out.yaml"), "--format", "json"])
    assert result.exit_code == 1
    assert "sequenceDiagram" in result.output


def test_semicolon_separated_statements_as_in_githubs_own_example():
    # docs.github.com "Creating diagrams" uses exactly this form.
    raw = parse_flowchart("graph TD;\n    A-->B;\n    A-->C;\n    B-->D;\n    C-->D;\n")
    assert sorted(_node_ids(raw["elements"])) == ["A", "B", "C", "D"]
    assert len(raw["links"]) == 4
    validate(raw)


def test_header_and_statements_on_one_line():
    raw = parse_flowchart("graph LR; A-->B; B-->C\n")
    assert raw["elements"][0]["layout"]["direction"] == "horizontal"
    assert len(raw["links"]) == 2


def test_semicolons_inside_labels_are_not_separators():
    raw = parse_flowchart('flowchart TD\n  A["x; y"] -->|a;b| B[c;d]\n')
    assert _by_id(_root_children(raw), "A")["label"] == "x; y"
    assert _by_id(_root_children(raw), "B")["label"] == "c;d"
    assert raw["links"][0]["label"] == "a;b"


def test_header_without_direction_is_not_a_node():
    raw = parse_flowchart("flowchart\n  A --> B\n")
    assert [el["id"] for el in _root_children(raw)] == ["A", "B"]
    assert raw["elements"][0]["layout"]["direction"] == "vertical"


def test_direction_statement_inside_subgraph():
    raw = parse_flowchart("flowchart TD\n  subgraph s[S]\n    direction LR\n    A --> B\n  end\n")
    assert _by_id(_root_children(raw), "s")["layout"]["direction"] == "horizontal"
    assert raw["elements"][0]["layout"]["direction"] == "vertical"


@pytest.mark.parametrize(
    "header,expected_id,expected_label",
    [
        ("subgraph Backend", "Backend", "Backend"),
        ("subgraph My Group", "My_Group", "My Group"),
        ('subgraph "AWS Cloud"', "AWS_Cloud", "AWS Cloud"),
        ("subgraph VPC[VPC]", "VPC", "VPC"),
        ('subgraph S["Quoted [x]"]', "S", "Quoted [x]"),
        ("subgraph バックエンド", "group", "バックエンド"),
    ],
)
def test_subgraph_title_is_always_kept(header, expected_id, expected_label):
    # Mermaid draws a bare subgraph's own text as its title; zook dropped it
    # whenever there was no separate [Title] (or it equalled the id).
    raw = parse_flowchart(f"flowchart TD\n  {header}\n    A\n  end\n")
    group = _by_id(_root_children(raw), expected_id)
    assert group["label"] == expected_label
    validate(raw)


def test_capitalised_end_is_a_node_not_a_subgraph_terminator():
    raw = parse_flowchart("flowchart TD\n  subgraph s[S]\n    A --> End\n  end\n")
    group = _by_id(_root_children(raw), "s")
    assert [el["id"] for el in group["children"]] == ["A", "End"]


def test_end_with_semicolon_closes_the_subgraph():
    raw = parse_flowchart("flowchart TD\n  subgraph s[S]\n    A\n  end;\n  B\n")
    assert [el["id"] for el in _root_children(raw)] == ["s", "B"]


def test_utf8_bom_does_not_hide_the_header():
    raw = parse_flowchart("﻿flowchart LR\n  A --> B\n")
    assert raw["elements"][0]["layout"]["direction"] == "horizontal"
    assert [el["id"] for el in _root_children(raw)] == ["A", "B"]


@pytest.mark.parametrize("keyword", ["architecture-beta", "C4Container", "block", "kanban", "packet-beta", "xychart"])
def test_other_mermaid_diagram_types_are_rejected(keyword):
    with pytest.raises(DiagramError, match="Unsupported Mermaid diagram type"):
        parse_flowchart(f"{keyword}\n  foo\n")


@pytest.mark.parametrize(
    "source",
    [
        "```mermaid\nflowchart LR\n  A --> B\n```\n",
        '%%{\n  init: {\n    "theme": "dark"\n  }\n}%%\nflowchart LR\n  A --> B\n',
        "---\ntitle: Checkout\n---\nflowchart LR\n  A --> B\n",
    ],
)
def test_header_after_fence_directive_or_front_matter(source):
    raw = parse_flowchart(source)
    assert raw["elements"][0]["layout"]["direction"] == "horizontal"
    assert [el["id"] for el in _root_children(raw)] == ["A", "B"]


@pytest.mark.parametrize("statement", ["A[Client] -- retry; backoff --> B[API]", "A -- B", "A ==> ", "A --> B C"])
def test_unreadable_edge_syntax_is_an_error_not_a_silent_drop(statement):
    with pytest.raises(DiagramError, match="line 2"):
        parse_flowchart(f"flowchart LR\n  {statement}\n")


@pytest.mark.parametrize(
    "statement,arrow,label",
    [
        ("A -.- B", "none", None),
        ("A --x B", None, None),
        ("A --o B", None, None),
        ("A x--x B", "both", None),
        ("A <==> B", "both", None),
        ("A === B", "none", None),
        ("A ----> B", None, None),
        ("A -..-> B", None, None),
        ("A -- text --> B", None, "text"),
        ("A == heavy ==> B", None, "heavy"),
        ("A -. maybe .-> B", None, "maybe"),
        ("A --> |spaced| B", None, "spaced"),
        ("A-->|tight|B", None, "tight"),
        ("A-->B", None, None),
        ("my-node --> B", None, None),
    ],
)
def test_every_mermaid_edge_form(statement, arrow, label):
    # These used to be dropped silently (the whole line, nodes included).
    raw = parse_flowchart(f"flowchart LR\n  {statement}\n")
    (link,) = raw["links"]
    assert link.get("arrow") == arrow
    assert link.get("label") == label
    assert link["to"] == "B"


def test_invisible_link_keeps_the_nodes_but_draws_nothing():
    raw = parse_flowchart("flowchart LR\n  A ~~~ B\n")
    assert [el["id"] for el in _root_children(raw)] == ["A", "B"]
    assert raw["links"] == []


def test_ampersand_expands_to_one_edge_per_pair():
    raw = parse_flowchart("flowchart LR\n  A & B --> C & D\n")
    assert sorted((l["from"], l["to"]) for l in raw["links"]) == [("A", "C"), ("A", "D"), ("B", "C"), ("B", "D")]


@pytest.mark.parametrize(
    "decl,shape,label",
    [
        ("A([Stadium])", "rounded", "Stadium"),
        ("A[[Sub]]", "rect", "Sub"),
        ("A[(Database)]", "rounded", "Database"),
        ("A(((Double)))", "circle", "Double"),
        ("A>Flag]", "rect", "Flag"),
        ("A{{Hex}}", "diamond", "Hex"),
        ("A[/Para/]", "rect", "Para"),
        ("A[\\Alt\\]", "rect", "Alt"),
        ("A[/Trap\\]", "rect", "Trap"),
        ('A["quoted [brackets] and --> arrows"]', "rect", "quoted [brackets] and --> arrows"),
        ("A[Styled]:::important", "rect", "Styled"),
    ],
)
def test_every_mermaid_node_shape(decl, shape, label):
    raw = parse_flowchart(f"flowchart LR\n  {decl} --> B\n")
    node = _by_id(_root_children(raw), "A")
    assert node["style"]["shape"] == shape
    assert node["label"] == label


@pytest.mark.parametrize(
    "decl,label",
    [
        ('A["line one<br/>line two"]', "line one\nline two"),
        ('A["He said #quot;hi#quot; #35;1"]', 'He said "hi" #1'),
        ('A["`**Bold** and *it*`"]', "Bold and it"),
    ],
)
def test_label_markup_is_converted(decl, label):
    raw = parse_flowchart(f"flowchart LR\n  {decl}\n")
    assert _by_id(_root_children(raw), "A")["label"] == label


def test_node_referenced_first_then_placed_in_a_subgraph_moves_there():
    # Mermaid's own "Edges to and from subgraphs" example shape.
    raw = parse_flowchart(
        "flowchart TB\n  c1-->a2\n  subgraph one\n    a1-->a2\n  end\n  subgraph two\n    b1-->b2\n  end\n"
    )
    children = _root_children(raw)
    assert [el["id"] for el in children] == ["c1", "one", "two"]
    one = _by_id(children, "one")
    assert [el["id"] for el in one["children"]] == ["a2", "a1"] or [el["id"] for el in one["children"]] == ["a1", "a2"]


def test_later_declaration_sets_the_label_and_shape():
    raw = parse_flowchart("flowchart LR\n  A --> B\n  B{Decision}\n")
    node = _by_id(_root_children(raw), "B")
    assert (node["label"], node["style"]["shape"]) == ("Decision", "diamond")


def test_inner_subgraph_wins_a_shared_node():
    raw = parse_flowchart("flowchart LR\n  subgraph outer\n    subgraph inner\n      X\n    end\n    X --> Y\n  end\n")
    outer = _by_id(_root_children(raw), "outer")
    inner = _by_id(outer["children"], "inner")
    assert [el["id"] for el in inner["children"]] == ["X"]
    assert [el["id"] for el in outer["children"]] == ["inner", "Y"]


def test_link_to_a_subgraph_declared_later():
    raw = parse_flowchart("flowchart LR\n  A --> S\n  subgraph S\n    B\n  end\n")
    assert raw["links"] == [{"from": "A", "to": "S"}]
    assert _by_id(_root_children(raw), "S")["kind"] == "container"


def test_accessibility_text_with_semicolons_adds_no_nodes():
    raw = parse_flowchart("flowchart LR\n  accTitle: Checkout flow; v2\n  accDescr: a; b\n  accDescr {\n  multi; line\n  }\n  A --> B\n")
    assert [el["id"] for el in _root_children(raw)] == ["A", "B"]


@pytest.mark.parametrize("header,expected", [("graph v", "vertical"), ("graph >", "horizontal"), ("flowchart LRX", "vertical")])
def test_unknown_or_symbolic_header_direction_adds_no_node(header, expected):
    raw = parse_flowchart(f"{header}\n  A --> B\n")
    assert raw["elements"][0]["layout"]["direction"] == expected
    assert [el["id"] for el in _root_children(raw)] == ["A", "B"]


def test_top_level_direction_statement_is_ignored_like_mermaid():
    raw = parse_flowchart("flowchart TD\n  subgraph a[F]\n    X\n  end\n  direction LR\n  subgraph b[B]\n    Y\n  end\n")
    assert raw["elements"][0]["layout"]["direction"] == "vertical"
    assert all(c["layout"]["direction"] == "vertical" for c in _root_children(raw))


@pytest.mark.parametrize("source", ["block --> db\n", "info --> B\n"])
def test_headerless_flowchart_starting_with_a_diagram_keyword_node(source):
    raw = parse_flowchart(source)
    assert len(raw["links"]) == 1


def test_unclosed_subgraph_error_mentions_lowercase_end():
    with pytest.raises(DiagramError, match="only lowercase `end`"):
        parse_flowchart("flowchart LR\n  Subgraph s[S]\n    A\n  End\n")


def test_a_branching_flowchart_is_laid_out_by_rank():
    # One column in source order put Reject under Process, so Check->Reject
    # and Process->Store ran straight through other nodes and read as a chain.
    from zook.layout import build_layout, diagram_warnings
    from zook.model import parse_diagram
    from zook.registry import load_registries

    raw = parse_flowchart(
        "flowchart TD\n  Start --> Check{OK?}\n  Check -->|yes| Process\n  Check -->|no| Reject\n"
        "  Process --> Store\n  Reject --> Notify\n"
    )
    root = raw["elements"][0]
    ranks = [[c["id"]] if c["kind"] == "node" else [n["id"] for n in c["children"]] for c in root["children"]]
    assert ranks == [["Start"], ["Check"], ["Process", "Reject"], ["Store", "Notify"]]
    rows = [c for c in root["children"] if c["kind"] == "container"]
    assert all(r["style"] == {"borderWidth": 0} and r["layout"]["direction"] == "horizontal" for r in rows)
    assert root["style"] == {"borderWidth": 0}  # no frame around the whole diagram

    validate(raw)
    registry = load_registries()
    diagram = parse_diagram(raw)
    assert diagram_warnings(diagram, build_layout(diagram, registry), registry) == []


def test_a_cycle_does_not_break_ranking():
    raw = parse_flowchart("flowchart LR\n  A --> B\n  B --> C\n  C --> A\n  B --> D\n  A --> D\n")
    validate(raw)
    assert sorted(_node_ids(raw["elements"])) == ["A", "B", "C", "D"]


@pytest.mark.parametrize(
    "decl, shape, label",
    [
        ('A@{ shape: cyl, label: "Orders DB" }', "rounded", "Orders DB"),
        ("A@{ shape: hex }", "diamond", "A"),
        ("A@{ shape: sm-circ }", "circle", "A"),
        ("A@{ shape: doc, label: Report }", "rect", "Report"),
        ('A@{ label: "Commas, {braces} and: colons" }', "rect", "Commas, {braces} and: colons"),
    ],
)
def test_mermaid_11_shape_blocks(decl, shape, label):
    raw = parse_flowchart(f"flowchart LR\n{decl}\nA --> B\n")
    validate(raw)
    node = _by_id(_root_children(raw), "A")
    assert node["style"]["shape"] == shape
    assert node["label"] == label


def test_mermaid_11_edge_ids_and_their_property_statements():
    raw = parse_flowchart("flowchart LR\nA e1@--> B\ne1@{ animate: true }\nB e2@-.->|async| C\n")
    validate(raw)
    assert _node_ids(raw["elements"]) == ["A", "B", "C"]
    assert [(l["from"], l["to"], l.get("label")) for l in raw["links"]] == [("A", "B", None), ("B", "C", "async")]


def test_a_chain_written_out_of_order_is_laid_out_forward():
    # J --> K is written first, so source order put F after K; its edge ran
    # back through J and K.
    raw = parse_flowchart("flowchart LR\nJ --> K\nM --> N\nF --> J\n")
    assert _node_ids(raw["elements"]) == ["F", "J", "K", "M", "N"]


def test_dotted_and_thick_links_and_link_style_are_kept():
    raw = parse_flowchart(
        "flowchart LR\n"
        "A --> B\n"
        "B -.-> C\n"
        "C ==> D\n"
        "D ~~~ E\n"
        "E --> F\n"
        "linkStyle 4 stroke:#f00,stroke-width:4px,stroke-dasharray: 2, 2\n"
        "linkStyle default stroke:green\n"
    )
    validate(raw)
    links = {(l["from"], l["to"]): l for l in raw["links"]}
    assert ("D", "E") not in links  # invisible: no line, but it still counts for linkStyle numbering
    assert links[("B", "C")]["line"] == "dashed"
    assert links[("C", "D")]["width"] == 2.5
    assert links[("A", "B")]["color"] == "#008000"  # linkStyle default
    assert links[("E", "F")] == {"from": "E", "to": "F", "color": "#FF0000", "width": 3.0, "line": "dotted"}
