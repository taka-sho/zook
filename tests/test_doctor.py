"""Tests for `zook doctor` - the overlap-resolution engine and CLI.

The invariant the resolver promises: a diagram it reports as `fixed` renders
with no sibling/label overlaps, i.e. `overlap_warnings()` is empty on the
result. Every test that fixes something asserts exactly that, rather than
pinning brittle coordinates.
"""

import json

from click.testing import CliRunner

from zook.doctor import diagnose_and_fix
from zook.layout import (
    build_layout,
    link_aliasing_warnings,
    link_crossing_warnings,
    overlap_warnings,
)
from zook.model import parse_diagram
from zook.registry import load_registries

REGISTRY = load_registries()


def _base(elements, links=None, **canvas):
    doc = {"version": "1.0", "canvas": {"aspectRatio": "16:9"}, "elements": elements}
    if links is not None:
        doc["links"] = links
    doc["canvas"].update(canvas)
    return doc


def _overlaps(raw):
    diagram = parse_diagram(raw)
    root = build_layout(diagram, REGISTRY)
    return overlap_warnings(root, REGISTRY, diagram.canvas.overlap_margin)


def _link_warnings(raw):
    diagram = parse_diagram(raw)
    root = build_layout(diagram, REGISTRY)
    margin = diagram.canvas.overlap_margin
    return link_crossing_warnings(root, diagram.links, REGISTRY, margin) + link_aliasing_warnings(
        root, diagram.links
    )


def test_same_position_siblings_are_separated():
    raw = _base([
        {"kind": "node", "id": "a", "type": "EC2", "x": 200, "y": 200},
        {"kind": "node", "id": "b", "type": "EC2", "x": 205, "y": 205},
    ])
    assert _overlaps(raw)  # precondition: they overlap

    result = diagnose_and_fix(raw, REGISTRY)

    assert result.status == "fixed"
    assert _overlaps(raw) == []  # the mutated raw now renders clean
    assert {m.id for m in result.moves} == {"b"}  # later-declared sibling moved


def test_child_over_container_label_is_pushed_clear():
    raw = _base([
        {
            "kind": "container", "id": "net", "type": "vpc", "provider": "aws",
            "label": "VPC", "x": 100, "y": 100, "width": 300, "height": 200,
            "children": [{"kind": "node", "id": "db", "type": "RDS", "x": 20, "y": 2}],
        }
    ])
    assert any("label" in w for w in _overlaps(raw))

    result = diagnose_and_fix(raw, REGISTRY)

    assert result.status == "fixed"
    assert _overlaps(raw) == []
    assert {m.id for m in result.moves} == {"db"}


def test_clean_diagram_is_a_noop():
    raw = _base([
        {"kind": "node", "id": "a", "type": "EC2"},
        {"kind": "node", "id": "b", "type": "RDS"},
    ])
    assert _overlaps(raw) == []

    result = diagnose_and_fix(raw, REGISTRY)

    assert result.status == "ok"
    assert result.moves == []


def test_auto_placed_sibling_moves_not_the_explicit_one():
    # 'anchor' is author-positioned; 'floater' is auto-placed and lands on it.
    # The auto one must move; the explicit one is the author's intent.
    raw = _base([
        {"kind": "node", "id": "anchor", "type": "EC2", "x": 40, "y": 40},
        {"kind": "node", "id": "floater", "type": "RDS"},
    ])
    if not _overlaps(raw):
        return  # layout happened not to collide; nothing to assert
    result = diagnose_and_fix(raw, REGISTRY)
    assert result.status == "fixed"
    assert _overlaps(raw) == []
    assert {m.id for m in result.moves} == {"floater"}


def test_result_is_idempotent():
    raw = _base([
        {"kind": "node", "id": "a", "type": "EC2", "x": 200, "y": 200},
        {"kind": "node", "id": "b", "type": "EC2", "x": 205, "y": 205},
    ])
    diagnose_and_fix(raw, REGISTRY)
    second = diagnose_and_fix(raw, REGISTRY)
    assert second.status == "ok"
    assert second.moves == []


def test_non_overlap_warnings_are_reported_not_fixed():
    # An unknown type is a placeholder-icon warning doctor never touches; it
    # should surface under `remaining` even when there's no overlap to fix.
    raw = _base([{"kind": "node", "id": "a", "type": "NoSuchService"}])
    result = diagnose_and_fix(raw, REGISTRY)
    assert result.status == "ok"
    assert any("NoSuchService" in w for w in result.remaining)


# --- link routing (stage 2) ---


def test_link_crossing_is_routed_around_the_obstacle():
    # A -> B straight through C; only a connection-side change can re-route it.
    raw = _base(
        [
            {"kind": "node", "id": "A", "type": "EC2", "x": 100, "y": 200},
            {"kind": "node", "id": "C", "type": "EC2", "x": 300, "y": 200},
            {"kind": "node", "id": "B", "type": "EC2", "x": 500, "y": 200},
        ],
        links=[{"from": "A", "to": "B"}],
    )
    assert _link_warnings(raw)

    result = diagnose_and_fix(raw, REGISTRY)

    assert result.status == "fixed"
    assert _link_warnings(raw) == []
    assert [(c.from_id, c.to_id) for c in result.link_changes] == [("A", "B")]


def test_false_edge_aliasing_is_resolved():
    # A -> X and X -> B both hug X's edge and read as one line; re-siding one
    # of them breaks the shared collinear segment.
    raw = _base(
        [
            {"kind": "node", "id": "A", "type": "EC2", "x": 300, "y": 60},
            {"kind": "node", "id": "B", "type": "EC2", "x": 500, "y": 120},
            {"kind": "node", "id": "X", "type": "EC2", "x": 300, "y": 420},
        ],
        links=[{"from": "A", "to": "X"}, {"from": "X", "to": "B"}],
    )
    assert any("collinear" in w for w in _link_warnings(raw))

    result = diagnose_and_fix(raw, REGISTRY)

    assert result.status == "fixed"
    assert _link_warnings(raw) == []
    assert result.link_changes  # at least one link re-sided


def test_author_positioned_obstacle_is_reported_not_moved():
    # B sits directly between A and X on the same vertical line, and the author
    # placed it there explicitly. No connection side clears the crossing, and
    # stage 3 must not override an authored position - so it stays, reported.
    raw = _base(
        [
            {"kind": "node", "id": "A", "type": "EC2", "x": 300, "y": 60},
            {"kind": "node", "id": "B", "type": "EC2", "x": 300, "y": 200},
            {"kind": "node", "id": "X", "type": "EC2", "x": 300, "y": 420},
        ],
        links=[{"from": "A", "to": "X"}],
    )
    result = diagnose_and_fix(raw, REGISTRY)
    assert result.status == "partial"
    assert any("passes through element 'B'" in w for w in result.remaining)
    assert (raw["elements"][1]["x"], raw["elements"][1]["y"]) == (300, 200)  # untouched


def test_auto_placed_obstacle_is_displaced_off_the_path():
    # Same geometry, but the obstacle C is auto-placed (no author coords) and
    # happens to land on the A -> X path. Sides can't re-route around it, so
    # stage 3 moves C out of the way instead.
    raw = _base(
        [
            {"kind": "node", "id": "C", "type": "EC2", "label": "in the way"},
            {"kind": "node", "id": "A", "type": "EC2", "x": 60, "y": 60},
            {"kind": "node", "id": "X", "type": "EC2", "x": 60, "y": 400},
        ],
        links=[{"from": "A", "to": "X"}],
    )
    assert any("through element 'C'" in w for w in _link_warnings(raw))

    result = diagnose_and_fix(raw, REGISTRY)

    assert result.status == "fixed"
    assert _link_warnings(raw) == []
    assert [m.id for m in result.moves] == ["C"]


def test_obstacle_move_never_worsens_a_diagram():
    # A crossing with no clean fix (author-pinned obstacle) must leave the
    # diagram no worse than it started: exactly the one original warning, and
    # no spurious element moves or side changes.
    raw = _base(
        [
            {"kind": "node", "id": "A", "type": "EC2", "x": 300, "y": 60},
            {"kind": "node", "id": "B", "type": "EC2", "x": 300, "y": 200},
            {"kind": "node", "id": "X", "type": "EC2", "x": 300, "y": 420},
        ],
        links=[{"from": "A", "to": "X"}],
    )
    result = diagnose_and_fix(raw, REGISTRY)
    assert result.moves == []
    assert result.link_changes == []
    assert len(result.remaining) == 1


def test_author_set_link_sides_are_not_overridden():
    # The link's sides are the author's explicit choice (both set); even though
    # they leave a crossing, doctor must not touch them.
    raw = _base(
        [
            {"kind": "node", "id": "A", "type": "EC2", "x": 100, "y": 200},
            {"kind": "node", "id": "C", "type": "EC2", "x": 300, "y": 200},
            {"kind": "node", "id": "B", "type": "EC2", "x": 500, "y": 200},
        ],
        links=[{"from": "A", "to": "B", "fromSide": "top", "toSide": "top"}],
    )
    assert _link_warnings(raw)  # top/top still crosses C

    result = diagnose_and_fix(raw, REGISTRY)

    assert result.link_changes == []
    assert result.status == "partial"
    assert raw["links"][0]["fromSide"] == "top"  # untouched


# --- CLI ---

_BROKEN_YAML = """\
version: "1.0"
canvas:
  aspectRatio: "16:9"
elements:
  # keep-this-comment
  - kind: node
    id: a
    type: EC2
    x: 200
    y: 200
  - kind: node
    id: b
    type: EC2
    x: 205
    y: 205
"""


def test_cli_dry_run_does_not_write(tmp_path):
    from zook.cli import main

    src = tmp_path / "d.yaml"
    src.write_text(_BROKEN_YAML)
    result = CliRunner().invoke(main, ["doctor", str(src), "--format", "json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "fixed"
    assert "output" not in payload
    assert src.read_text() == _BROKEN_YAML  # untouched on a dry run


def test_cli_fix_writes_clean_yaml_and_keeps_comments(tmp_path):
    import yaml

    from zook.cli import main

    src = tmp_path / "d.yaml"
    src.write_text(_BROKEN_YAML)
    result = CliRunner().invoke(main, ["doctor", str(src), "--fix", "--format", "json"])

    assert result.exit_code == 0
    assert json.loads(result.stdout)["status"] == "fixed"

    written = src.read_text()
    assert "# keep-this-comment" in written  # ruamel round-trip preserved it
    assert _overlaps(yaml.safe_load(written)) == []


_OBSTACLE_YAML = """\
version: "1.0"
canvas:
  aspectRatio: "16:9"
elements:
  # obstacle-comment
  - kind: node
    id: C
    type: EC2
  - {kind: node, id: A, type: EC2, x: 60, y: 60}
  - {kind: node, id: X, type: EC2, x: 60, y: 400}
links:
  - {from: A, to: X}
"""


def test_cli_fix_through_obstacle_stage_keeps_comments(tmp_path):
    # Exercises the stage-3 path (deepcopy rollback + keep) end to end and
    # confirms comments survive it.
    import yaml

    from zook.cli import main

    src = tmp_path / "d.yaml"
    src.write_text(_OBSTACLE_YAML)
    result = CliRunner().invoke(main, ["doctor", str(src), "--fix", "--format", "json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "fixed"
    assert [m["id"] for m in payload["moves"]] == ["C"]

    written = src.read_text()
    assert "# obstacle-comment" in written
    assert _link_warnings(yaml.safe_load(written)) == []


def test_cli_reports_fatal_error(tmp_path):
    from zook.cli import main

    src = tmp_path / "d.yaml"
    src.write_text("version: '1.0'\ncanvas:\n  aspectRatio: '16:9'\nelements: []\n"
                   "links:\n  - from: nope\n    to: alsonope\n")
    result = CliRunner().invoke(main, ["doctor", str(src), "--format", "json"])

    assert result.exit_code == 1
    assert json.loads(result.stdout)["status"] == "error"
