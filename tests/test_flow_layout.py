"""layout.order: flow - children arranged along the links between them -
and the automatic U route that takes a link round an element in its way."""

import copy

import pytest
from click.testing import CliRunner

from zook.doctor import diagnose_and_fix
from zook.errors import DiagramError
from zook.layout import build_layout, diagram_warnings, flow_ranks, iter_boxes, link_render_plan
from zook.model import parse_diagram
from zook.registry import load_registries
from zook.validate import validate

REGISTRY = load_registries()


def _node(eid, **extra):
    return {"kind": "node", "id": eid, "type": "EC2", "label": eid.upper(), **extra}


def _doc(children, links, direction="horizontal", order="flow", **layout):
    doc = {
        "version": "1.0",
        "canvas": {"aspectRatio": "16:9"},
        "elements": [{"kind": "container", "id": "g", "type": "group",
                      "layout": {"direction": direction, "order": order, **layout}, "children": children}],
        "links": links,
    }
    validate(doc)
    return doc


def _boxes(doc):
    diagram = parse_diagram(doc)
    root = build_layout(diagram, REGISTRY)
    return diagram, root, {b.element.id: b for b in iter_boxes(root)}


def _links(*pairs):
    return [{"from": a, "to": b} for a, b in pairs]


def test_a_chain_written_out_of_order_runs_along_its_links():
    doc = _doc([_node(i) for i in "dbca"], _links(("a", "b"), ("b", "c"), ("c", "d")))
    diagram, root, boxes = _boxes(doc)
    xs = [boxes[i].abs_x for i in "abcd"]
    assert xs == sorted(xs) and len(set(xs)) == 4
    assert len({boxes[i].abs_y for i in "abcd"}) == 1  # one straight line
    assert diagram_warnings(diagram, root, REGISTRY) == []


@pytest.mark.parametrize("direction, along, across", [("horizontal", "abs_x", "abs_y"), ("vertical", "abs_y", "abs_x")])
def test_a_fan_out_puts_its_arms_side_by_side(direction, along, across):
    doc = _doc([_node(i) for i in ["join", "b1", "src", "b2", "b3"]],
               _links(("src", "b1"), ("src", "b2"), ("src", "b3"), ("b1", "join"), ("b2", "join"), ("b3", "join")),
               direction)
    diagram, root, boxes = _boxes(doc)
    arms = [boxes[i] for i in ("b1", "b2", "b3")]
    assert len({getattr(b, along) for b in arms}) == 1  # one rank
    assert len({getattr(b, across) for b in arms}) == 3  # stacked across it
    assert getattr(boxes["src"], along) < getattr(arms[0], along) < getattr(boxes["join"], along)
    assert diagram_warnings(diagram, root, REGISTRY) == []


def test_a_cycle_is_ranked_by_setting_aside_the_link_that_closes_it():
    ranks, forward = flow_ranks(3, [(0, 1), (1, 2), (2, 0)])
    assert ranks == [0, 1, 2] and forward[2] == []


def test_a_grid_is_filled_in_flow_order():
    doc = _doc([_node(i) for i in "cab"], _links(("a", "b"), ("b", "c")), direction="grid", columns=3)
    _, _, boxes = _boxes(doc)
    assert boxes["a"].abs_x < boxes["b"].abs_x < boxes["c"].abs_x


def test_explicitly_positioned_children_stay_put():
    doc = _doc([_node("a"), _node("b", x=400, y=300), _node("c")], _links(("c", "a"), ("a", "b")))
    _, _, boxes = _boxes(doc)
    g = boxes["g"]
    assert (boxes["b"].abs_x - g.abs_x, boxes["b"].abs_y - g.abs_y) == (400, 300)
    assert boxes["c"].abs_x < boxes["a"].abs_x


def test_containers_in_a_flow_line_up_at_the_top():
    group = lambda cid, nid: {"kind": "container", "id": cid, "type": "group", "children": [_node(nid)]}
    tall = {"kind": "container", "id": "tall", "type": "group", "layout": {"direction": "vertical"},
            "children": [_node("t1"), _node("t2"), _node("t3")]}
    doc = _doc([group("left", "l"), tall], _links(("l", "t1")))
    _, _, boxes = _boxes(doc)
    assert boxes["left"].abs_y == boxes["tall"].abs_y


def test_the_top_level_can_be_arranged_by_flow():
    doc = {"version": "1.0", "canvas": {"aspectRatio": "16:9", "layout": {"direction": "horizontal", "order": "flow"}},
           "elements": [_node("c"), _node("a"), _node("b")], "links": _links(("a", "b"), ("b", "c"))}
    validate(doc)
    _, _, boxes = _boxes(doc)
    assert boxes["a"].abs_x < boxes["b"].abs_x < boxes["c"].abs_x


def test_an_unknown_order_is_a_schema_error():
    with pytest.raises(DiagramError, match="order"):
        _doc([_node("a")], [], order="random")


def test_doctor_arranges_a_shuffled_diagram_by_flow_and_says_so(tmp_path):
    import json

    from zook.cli import main

    doc = _doc([_node(i) for i in "ecadb"], _links(("a", "b"), ("b", "c"), ("c", "d"), ("d", "e")), order="source")
    path = tmp_path / "d.yaml"
    import yaml

    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    result = CliRunner().invoke(main, ["doctor", str(path), "--format", "json"])
    payload = json.loads(result.stdout)
    assert {"id": "g", "order": "flow"} in payload["layoutChanges"]
    text = CliRunner().invoke(main, ["doctor", str(path)]).stdout
    assert "Arranged g along its links" in text

    fixed = copy.deepcopy(doc)
    diagnose_and_fix(fixed, REGISTRY)
    assert fixed["elements"][0]["layout"]["order"] == "flow"
    again = diagnose_and_fix(copy.deepcopy(fixed), REGISTRY)
    assert again.layout_changes == [] and again.moves == [] and again.link_changes == []


def test_a_link_with_an_element_in_its_way_goes_round_it():
    doc = _doc([_node("a"), _node("b"), _node("c")], _links(("a", "c")), order="source")
    diagram, root, boxes = _boxes(doc)
    start, end, _style, _path = link_render_plan(boxes["a"], boxes["c"], diagram.links[0])
    assert start == end  # a same-side U route over (or under) b
    assert diagram_warnings(diagram, root, REGISTRY) == []


def test_a_u_route_that_would_still_hit_something_is_left_to_doctor():
    # blockers above and below b: going round still hits one, so the link
    # keeps its straight route (and its Warning) for doctor to weigh up.
    bare = lambda eid, x, y: {"kind": "node", "id": eid, "type": "EC2", "x": x, "y": y, "style": {"labelPosition": "none"}}
    doc = {"version": "1.0", "canvas": {"aspectRatio": "16:9"},
           "elements": [bare("a", 100, 300), bare("b", 300, 300), bare("c", 500, 300),
                        bare("up", 300, 220), bare("down", 300, 380)],
           "links": _links(("a", "c"))}
    diagram, root, boxes = _boxes(doc)
    start, end, _style, _path = link_render_plan(boxes["a"], boxes["c"], diagram.links[0])
    assert start != end
