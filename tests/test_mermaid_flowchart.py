from pathlib import Path

import pytest

from archdiagram.errors import DiagramError
from archdiagram.mermaid_flowchart import parse_flowchart
from archdiagram.model import parse_diagram
from archdiagram.validate import validate

FIXTURE = Path(__file__).parent / "fixtures" / "example.mmd"


def _root_children(raw: dict) -> list:
    return raw["elements"][0]["children"]


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

    from archdiagram.cli import main

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

    from archdiagram.cli import main

    src = tmp_path / "in.mmd"
    src.write_text("sequenceDiagram\n  A->>B: hi\n")
    runner = CliRunner()
    result = runner.invoke(main, ["from-mermaid", str(src), "-o", str(tmp_path / "out.yaml"), "--format", "json"])
    assert result.exit_code == 1
    assert "sequenceDiagram" in result.output
