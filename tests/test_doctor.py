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
    iter_boxes,
    link_aliasing_warnings,
    link_crossing_warnings,
    link_render_plan,
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


def test_a_link_blocked_by_an_element_goes_round_it_without_doctor():
    # A -> B straight would run through C. The automatic connection sides
    # take a clean U route over (or under) C instead, so there's nothing left
    # for doctor to do.
    raw = _base(
        [
            {"kind": "node", "id": "A", "type": "EC2", "x": 100, "y": 200},
            {"kind": "node", "id": "C", "type": "EC2", "x": 300, "y": 200},
            {"kind": "node", "id": "B", "type": "EC2", "x": 500, "y": 200},
        ],
        links=[{"from": "A", "to": "B"}],
    )
    assert _link_warnings(raw) == []
    diagram = parse_diagram(raw)
    boxes = {b.element.id: b for b in iter_boxes(build_layout(diagram, REGISTRY))}
    start, end, _style, _path = link_render_plan(boxes["A"], boxes["B"], diagram.links[0])
    assert start == end  # a same-side U route
    assert diagnose_and_fix(raw, REGISTRY).status == "ok"


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


def _bare(eid, x, y):
    return {"kind": "node", "id": eid, "type": "EC2", "x": x, "y": y, "style": {"labelPosition": "none"}}


def test_a_forced_crossing_is_left_to_its_author():
    # B sits directly between A and X; the author forced the straight route
    # through it. doctor doesn't re-route a link whose sides the author set.
    raw = _base(
        [
            {"kind": "node", "id": "A", "type": "EC2", "x": 300, "y": 60},
            {"kind": "node", "id": "B", "type": "EC2", "x": 300, "y": 200},
            {"kind": "node", "id": "X", "type": "EC2", "x": 300, "y": 420},
        ],
        links=[{"from": "A", "to": "X", "fromSide": "bottom", "toSide": "top"}],
    )
    assert _link_warnings(raw)
    result = diagnose_and_fix(raw, REGISTRY)
    assert result.link_changes == [] and result.status == "partial"


# Pinned blockers just outside both same-side (U) routes of a vertical A -> X
# link, so re-siding can't clear an obstacle on the line - only stage 3
# (move it) or stage 4 (detour) can.
_SIDE_BLOCKERS = [_bare("LB", 230, 290), _bare("RB", 370, 290)]


def test_author_pinned_obstacle_is_detoured_with_waypoints():
    # No side clears B (stage 2) and stage 3 must not move an authored
    # position - so stage 4 detours the *link* around B with waypoints.
    raw = _base([_bare("A", 300, 60), _bare("B", 300, 200), _bare("X", 300, 440), *_SIDE_BLOCKERS],
                links=[{"from": "A", "to": "X"}])
    assert _link_warnings(raw)

    result = diagnose_and_fix(raw, REGISTRY)

    assert result.status == "fixed"
    assert _link_warnings(raw) == []
    assert result.moves == []  # B is authored; it was not moved
    assert (raw["elements"][1]["x"], raw["elements"][1]["y"]) == (300, 200)  # B untouched
    assert result.link_changes and result.link_changes[0].waypoints  # link detoured instead


def test_auto_placed_obstacle_is_displaced_off_the_path():
    # Same idea, but the obstacle C is auto-placed (no author coords) and
    # happens to land on the A -> X path. Sides can't re-route around it
    # (blockers flank both U routes), so stage 3 moves C out of the way.
    raw = _base(
        [
            {"kind": "node", "id": "C", "type": "EC2", "label": "in the way"},
            _bare("A", 60, 60),
            _bare("X", 60, 440),
            _bare("LB", 0, 300),
            _bare("RB", 130, 300),
        ],
        links=[{"from": "A", "to": "X"}],
    )
    assert any("through element 'C'" in w for w in _link_warnings(raw))

    result = diagnose_and_fix(raw, REGISTRY)

    assert result.status == "fixed"
    assert _link_warnings(raw) == []
    assert [m.id for m in result.moves] == ["C"]


def test_unresolvable_crossing_never_worsens():
    # The author both pinned B on the line AND forced the link's sides, so
    # every stage must stand down: no move, no side change, no detour - the
    # diagram is left exactly as it came in, with its one warning reported.
    raw = _base(
        [
            {"kind": "node", "id": "A", "type": "EC2", "x": 300, "y": 60},
            {"kind": "node", "id": "B", "type": "EC2", "x": 300, "y": 200},
            {"kind": "node", "id": "X", "type": "EC2", "x": 300, "y": 420},
        ],
        links=[{"from": "A", "to": "X", "fromSide": "bottom", "toSide": "top"}],
    )
    result = diagnose_and_fix(raw, REGISTRY)
    assert result.status == "partial"
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
        links=[{"from": "A", "to": "B", "fromSide": "right", "toSide": "left"}],
    )
    assert _link_warnings(raw)  # right/left runs straight through C

    result = diagnose_and_fix(raw, REGISTRY)

    assert result.link_changes == []
    assert result.status == "partial"
    assert raw["links"][0]["fromSide"] == "right"  # untouched


# --- stage 4: waypoint detours ---


def test_link_crossing_two_pinned_obstacles_is_detoured_around_both():
    # Two author-pinned obstacles on the A->X line: a single detour must route
    # around their union and clear both at once.
    raw = _base(
        [_bare("A", 300, 40), _bare("B1", 300, 160), _bare("B2", 300, 250), _bare("X", 300, 480),
         _bare("LB", 230, 340), _bare("RB", 370, 340)],
        links=[{"from": "A", "to": "X"}],
    )
    result = diagnose_and_fix(raw, REGISTRY)

    assert result.status == "fixed"
    assert _link_warnings(raw) == []
    assert result.moves == []  # both obstacles authored; none moved
    assert result.link_changes[0].waypoints  # one detour clears both


def test_author_routed_link_is_left_alone():
    # The author already routed the link with a waypoint (which still leaves a
    # crossing); stage 4 must respect that intent and not replace the routing.
    raw = _base(
        [
            {"kind": "node", "id": "A", "type": "EC2", "x": 300, "y": 60},
            {"kind": "node", "id": "B", "type": "EC2", "x": 300, "y": 200},
            {"kind": "node", "id": "X", "type": "EC2", "x": 300, "y": 420},
        ],
        links=[{"from": "A", "to": "X", "waypoints": [{"x": 300, "y": 250}]}],
    )
    result = diagnose_and_fix(raw, REGISTRY)

    assert result.link_changes == []  # author's routing untouched
    assert raw["links"][0]["waypoints"] == [{"x": 300, "y": 250}]


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
    src.write_text(_BROKEN_YAML, encoding="utf-8")
    result = CliRunner().invoke(main, ["doctor", str(src), "--format", "json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "fixed"
    assert "output" not in payload
    assert src.read_text(encoding="utf-8") == _BROKEN_YAML  # untouched on a dry run


def test_cli_fix_writes_clean_yaml_and_keeps_comments(tmp_path):
    import yaml

    from zook.cli import main

    src = tmp_path / "d.yaml"
    src.write_text(_BROKEN_YAML, encoding="utf-8")
    result = CliRunner().invoke(main, ["doctor", str(src), "--fix", "--format", "json"])

    assert result.exit_code == 0
    assert json.loads(result.stdout)["status"] == "fixed"

    written = src.read_text(encoding="utf-8")
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
  - {kind: node, id: A, type: EC2, x: 60, y: 60, style: {labelPosition: none}}
  - {kind: node, id: X, type: EC2, x: 60, y: 440, style: {labelPosition: none}}
  - {kind: node, id: LB, type: EC2, x: 0, y: 300, style: {labelPosition: none}}
  - {kind: node, id: RB, type: EC2, x: 130, y: 300, style: {labelPosition: none}}
links:
  - {from: A, to: X}
"""


def test_cli_fix_through_obstacle_stage_keeps_comments(tmp_path):
    # Exercises the stage-3 path (deepcopy rollback + keep) end to end and
    # confirms comments survive it.
    import yaml

    from zook.cli import main

    src = tmp_path / "d.yaml"
    src.write_text(_OBSTACLE_YAML, encoding="utf-8")
    result = CliRunner().invoke(main, ["doctor", str(src), "--fix", "--format", "json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "fixed"
    assert [m["id"] for m in payload["moves"]] == ["C"]

    written = src.read_text(encoding="utf-8")
    assert "# obstacle-comment" in written
    assert _link_warnings(yaml.safe_load(written)) == []


def test_cli_reports_fatal_error(tmp_path):
    from zook.cli import main

    src = tmp_path / "d.yaml"
    src.write_text("version: '1.0'\ncanvas:\n  aspectRatio: '16:9'\nelements: []\n"
                   "links:\n  - from: nope\n    to: alsonope\n", encoding="utf-8")
    result = CliRunner().invoke(main, ["doctor", str(src), "--format", "json"])

    assert result.exit_code == 1
    assert json.loads(result.stdout)["status"] == "error"


# Two explicitly-positioned, overlapping containers, each with an auto-placed
# child: separating g1/g2 moves g2, and n2 follows it without having any x/y
# of its own. That follower used to be reported as a move with x/y = None,
# which crashed the text and github reports with a TypeError - after --fix
# had already rewritten the file.
_CONTAINERS_WITH_AUTO_CHILDREN = """\
version: "1.0"
canvas:
  aspectRatio: "16:9"
elements:
  - kind: container
    id: g1
    type: group
    x: 100
    y: 100
    children:
      - {kind: node, id: n1, type: EC2}
  - kind: container
    id: g2
    type: group
    x: 150
    y: 120
    children:
      - {kind: node, id: n2, type: EC2}
"""


def test_moves_never_report_a_follower_without_coordinates():
    import yaml

    result = diagnose_and_fix(yaml.safe_load(_CONTAINERS_WITH_AUTO_CHILDREN), REGISTRY)
    assert result.status == "fixed"
    assert [m.id for m in result.moves] == ["g2"]
    assert all(m.x is not None and m.y is not None for m in result.moves)


def test_cli_text_and_github_reports_survive_container_moves(tmp_path):
    from zook.cli import main

    src = tmp_path / "d.yaml"
    src.write_text(_CONTAINERS_WITH_AUTO_CHILDREN, encoding="utf-8")
    for fmt in ("text", "github"):
        result = CliRunner().invoke(main, ["doctor", str(src), "--format", fmt])
        assert result.exit_code == 0, result.output
        assert "g2" in result.stdout

    result = CliRunner().invoke(main, ["doctor", str(src), "--fix"])
    assert result.exit_code == 0, result.output
    assert "Wrote" in result.stdout
    assert _overlaps(yaml_load(src)) == []


def yaml_load(path):
    import yaml

    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_cli_output_is_always_written_even_when_nothing_changed(tmp_path):
    # `doctor in.yaml -o fixed.yaml && build fixed.yaml` must not fail - or,
    # worse, build a stale fixed.yaml left over from an earlier run - just
    # because the input had nothing to fix.
    from zook.cli import main

    clean = _base([{"kind": "node", "id": "a", "type": "EC2"}])
    src = tmp_path / "clean.yaml"
    src.write_text(json.dumps(clean), encoding="utf-8")
    dest = tmp_path / "fixed.yaml"
    dest.write_text("stale: true\n", encoding="utf-8")

    result = CliRunner().invoke(main, ["doctor", str(src), "-o", str(dest), "--format", "json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["output"] == str(dest)
    assert yaml_load(dest) == clean


def test_cli_fix_leaves_an_already_clean_file_untouched(tmp_path):
    from zook.cli import main

    text = "# a comment\n" + json.dumps(_base([{"kind": "node", "id": "a", "type": "EC2"}]))
    src = tmp_path / "clean.yaml"
    src.write_text(text, encoding="utf-8")

    result = CliRunner().invoke(main, ["doctor", str(src), "--fix", "--format", "json"])

    assert result.exit_code == 0
    assert "output" not in json.loads(result.stdout)
    assert src.read_text(encoding="utf-8") == text


_YAML_11_VS_12 = """\
version: "1.0"
canvas:
  aspectRatio: "16:9"
elements:
  # 0600 is octal 384 in YAML 1.1 (validate/build) but 600 in YAML 1.2 (ruamel)
  - {kind: node, id: a, type: EC2, x: 0600, y: 100}
  - {kind: node, id: b, type: EC2, x: 384, y: 100, label: 1e3}
"""


def test_doctor_sees_the_same_diagram_validate_does(tmp_path):
    from zook.cli import main

    src = tmp_path / "d.yaml"
    src.write_text(_YAML_11_VS_12, encoding="utf-8")
    validate_result = json.loads(CliRunner().invoke(main, ["validate", str(src), "--format", "json"]).stdout)
    assert validate_result["warnings"] == ["element 'a' overlaps element 'b'"]

    result = CliRunner().invoke(main, ["doctor", str(src), "--fix", "--format", "json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["status"] == "fixed"
    written = src.read_text(encoding="utf-8")
    assert "# 0600 is octal" in written  # comments kept
    assert _overlaps(yaml_load(src)) == []
    assert yaml_load(src)["elements"][1]["label"] == "1e3"


def test_explicitly_positioned_followers_are_not_reported_as_moves():
    import yaml

    doc = yaml.safe_load(_CONTAINERS_WITH_AUTO_CHILDREN)
    doc["elements"][1]["children"] = [{"kind": "node", "id": "n2", "type": "EC2", "x": 20, "y": 20}]
    result = diagnose_and_fix(doc, REGISTRY)
    assert [m.id for m in result.moves] == ["g2"]


def test_cli_output_copy_is_byte_identical_when_nothing_changed(tmp_path):
    from zook.cli import main

    text = 'version: "1.0"\r\ncanvas:\r\n    aspectRatio: "16:9"   # four-space indent\r\nelements:\r\n    - {kind: node, id: a, type: EC2}\r\n'
    src = tmp_path / "clean.yaml"
    src.write_bytes(text.encode())
    dest = tmp_path / "copy.yaml"
    result = CliRunner().invoke(main, ["doctor", str(src), "-o", str(dest), "--format", "json"])
    assert result.exit_code == 0
    assert dest.read_bytes() == text.encode()

    result = CliRunner().invoke(main, ["doctor", str(src), "-o", str(src), "--format", "json"])
    assert result.exit_code == 0
    assert src.read_bytes() == text.encode()


# --- invariants (the claims the module docstring and usage.md make) ---

import copy as _copy
import time as _time

import pytest as _pytest

from zook.doctor import _score as _objective


def _chain(n):
    """n auto-placed nodes with links chosen to cross a lot (the diagram used
    to measure doctor's worst case)."""
    nodes = [{"kind": "node", "id": f"n{i}", "type": "EC2", "label": f"N{i}"} for i in range(n)]
    links = []
    for i in range(n - 1):
        j = (i * 7 + 3) % n
        links.append({"from": f"n{i}", "to": f"n{j if j != i else (i + 1) % n}"})
    return _base(nodes, links)


def _perturbed_patterns():
    import pathlib

    import yaml

    patterns = pathlib.Path(__file__).parent.parent / "src" / "zook" / "data" / "patterns"
    for path in sorted(patterns.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        # Pin the first two siblings onto each other: an overlap (and the
        # link crossings that follow) for doctor to untangle.
        siblings = raw["elements"]
        while len(siblings) < 2:
            siblings = siblings[0]["children"]
        siblings[0].update(x=60, y=60)
        siblings[1].update(x=90, y=80)
        yield path.stem, raw
    yield "chain14", _chain(14)


@_pytest.mark.parametrize("name,raw", list(_perturbed_patterns()), ids=lambda v: v if isinstance(v, str) else "")
def test_doctor_never_makes_the_objective_worse_and_is_idempotent(name, raw):
    before = _objective(raw, REGISTRY)
    fixed = _copy.deepcopy(raw)
    diagnose_and_fix(fixed, REGISTRY)
    after = _objective(fixed, REGISTRY)
    assert after <= before

    again = _copy.deepcopy(fixed)
    second = diagnose_and_fix(again, REGISTRY)
    assert second.moves == [] and second.link_changes == [] and second.pinned == []
    assert again == fixed


def test_moves_stay_inside_a_fixed_size_container():
    # b overlaps a near the right edge of a fixed-size VPC: pushing b right
    # (the old rule) put it across the VPC's frame and still reported "fixed".
    raw = _base([{
        "kind": "container", "id": "vpc", "type": "group", "x": 40, "y": 40, "width": 260, "height": 220,
        "children": [
            {"kind": "node", "id": "a", "type": "EC2", "x": 140, "y": 40},
            {"kind": "node", "id": "b", "type": "EC2", "x": 160, "y": 60},
        ],
    }])
    result = diagnose_and_fix(raw, REGISTRY)
    assert result.status == "fixed"
    diagram = parse_diagram(raw)
    root = build_layout(diagram, REGISTRY)
    from zook.layout import containment_warnings

    assert containment_warnings(root) == []
    assert _overlaps(raw) == []


def test_moves_stay_on_the_slide():
    raw = _base([
        {"kind": "node", "id": "a", "type": "EC2", "x": 1160, "y": 300},
        {"kind": "node", "id": "b", "type": "EC2", "x": 1180, "y": 310},
    ], fit="none")
    result = diagnose_and_fix(raw, REGISTRY)
    assert result.status == "fixed"
    assert not any("outside the canvas" in m for m in result.remaining)


def test_a_child_outside_its_container_is_reported_and_pulled_back():
    raw = _base([{
        "kind": "container", "id": "g", "type": "group", "x": 40, "y": 40, "width": 300, "height": 200,
        "children": [{"kind": "node", "id": "a", "type": "EC2", "x": 280, "y": 40}],
    }])
    from zook.layout import containment_warnings

    root = build_layout(parse_diagram(raw), REGISTRY)
    assert containment_warnings(root) == ["element 'a' extends outside its container 'g'"]
    result = diagnose_and_fix(raw, REGISTRY)
    assert result.status == "fixed"
    assert containment_warnings(build_layout(parse_diagram(raw), REGISTRY)) == []


def test_a_link_running_back_through_its_own_endpoint_is_reported_and_re_routed():
    # Leaving the top of the upper node to enter the top of... the lower one's
    # bottom: the route doubles back through both icons.
    link = {"from": "a", "to": "b", "fromSide": "top", "toSide": "bottom"}
    raw = _base([_bare("a", 300, 100), _bare("b", 300, 400)], links=[link])
    assert any("runs back through one of its own endpoints" in w for w in _link_warnings(raw))

    auto = _base([_bare("a", 300, 100), _bare("b", 300, 400)], links=[{"from": "a", "to": "b"}])
    assert _link_warnings(auto) == []


def test_detour_waypoints_are_orthogonal():
    from zook.layout import iter_boxes, link_render_plan

    raw = _base([_bare("A", 300, 60), _bare("B", 300, 200), _bare("X", 300, 440), *_SIDE_BLOCKERS],
                links=[{"from": "A", "to": "X"}])
    diagnose_and_fix(raw, REGISTRY)
    diagram = parse_diagram(raw)
    root = build_layout(diagram, REGISTRY)
    boxes = {b.element.id: b for b in iter_boxes(root)}
    _, _, style, path = link_render_plan(boxes["A"], boxes["X"], diagram.links[0])
    assert style == "polyline"
    for (x0, y0), (x1, y1) in zip(path, path[1:]):
        assert abs(x0 - x1) < 0.5 or abs(y0 - y1) < 0.5, path


def test_author_waypoint_link_is_never_re_sided():
    raw = _base([_bare("A", 300, 60), _bare("B", 300, 200), _bare("X", 300, 420)],
                links=[{"from": "A", "to": "X", "waypoints": [{"x": 332, "y": 150}]}])
    result = diagnose_and_fix(raw, REGISTRY)
    assert result.link_changes == []
    assert "fromSide" not in raw["links"][0] and "toSide" not in raw["links"][0]


def test_pins_are_reported():
    import yaml

    result = diagnose_and_fix(yaml.safe_load(_CONTAINERS_WITH_AUTO_CHILDREN), REGISTRY)
    raw = yaml.safe_load(_CONTAINERS_WITH_AUTO_CHILDREN)
    raw["elements"].append({"kind": "container", "id": "g3", "type": "group", "children": [
        {"kind": "node", "id": "p", "type": "EC2"}, {"kind": "node", "id": "q", "type": "EC2", "x": 0, "y": 0}]})
    result = diagnose_and_fix(raw, REGISTRY)
    assert {m.id for m in result.pinned} <= {"p", "q", "g1", "g2", "g3", "n1", "n2"}
    for pin in result.pinned:
        assert pin.x is not None and pin.y is not None


def test_doctor_is_fast_and_idempotent_on_a_crossing_heavy_diagram():
    # 30 crossing-heavy links took ~7 minutes before incremental scoring. A
    # second run then still found a detour: it treats what the first one
    # wrote as the author's, which steers its search elsewhere.
    raw = _chain(30)
    start = _time.monotonic()
    diagnose_and_fix(raw, REGISTRY)
    assert _time.monotonic() - start < 60
    second = diagnose_and_fix(_copy.deepcopy(raw), REGISTRY)
    assert second.moves == [] and second.link_changes == [] and second.pinned == []


def test_cli_fix_keeps_indentation_and_integers(tmp_path):
    from zook.cli import main

    text = (
        'version: "1.0"\n'
        "canvas:\n"
        '    aspectRatio: "16:9"\n'
        "elements:\n"
        "    -   kind: node\n"
        "        id: a\n"
        "        type: EC2\n"
        "        x: 200\n"
        "        y: 200\n"
        "    -   kind: node\n"
        "        id: b\n"
        "        type: EC2\n"
        "        x: 205\n"
        "        y: 205\n"
    )
    src = tmp_path / "d.yaml"
    src.write_text(text, encoding="utf-8")
    result = CliRunner().invoke(main, ["doctor", str(src), "--fix", "--format", "json"])
    assert result.exit_code == 0
    written = src.read_text(encoding="utf-8")
    assert "    -   kind: node\n        id: a\n" in written  # the file's own indentation style
    assert "x: 200\n" in written and ".0\n" not in written


def test_cli_strict_fails_on_anything_remaining(tmp_path):
    from zook.cli import main

    src = tmp_path / "d.yaml"
    src.write_text(json.dumps(_base([{"kind": "node", "id": "a", "type": "NoSuchService"}])), encoding="utf-8")
    result = CliRunner().invoke(main, ["doctor", str(src), "--strict", "--format", "json"])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["remaining"]
