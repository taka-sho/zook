from archdiagram.layout import build_layout, out_of_canvas_warnings, overlap_warnings
from archdiagram.model import Canvas, Diagram, Element, Layout
from archdiagram.registry import load_registry

REGISTRY = load_registry("aws")


def _diagram(elements, links=None, aspect_ratio="16:9"):
    return Diagram(canvas=Canvas(aspect_ratio=aspect_ratio), elements=elements, links=links or [])


def _boxes_by_id(root_box):
    from archdiagram.layout import iter_boxes

    return {b.element.id: b for b in iter_boxes(root_box)}


def test_explicit_position_is_respected():
    el = Element(kind="node", id="a", type="EC2", provider="aws", x=100, y=50)
    diagram = _diagram([el])
    root = build_layout(diagram, REGISTRY)
    box = _boxes_by_id(root)["a"]
    assert box.abs_x == 100
    assert box.abs_y == 50


def test_horizontal_auto_layout_places_children_in_a_row():
    children = [Element(kind="node", id=f"n{i}", type="EC2", provider="aws") for i in range(3)]
    container = Element(
        kind="container",
        id="c",
        type="vpc",
        provider="aws",
        layout=Layout(direction="horizontal", gap=10, padding=5),
        children=children,
    )
    diagram = _diagram([container])
    root = build_layout(diagram, REGISTRY)
    boxes = _boxes_by_id(root)
    assert boxes["n0"].abs_y == boxes["n1"].abs_y == boxes["n2"].abs_y
    assert boxes["n0"].abs_x < boxes["n1"].abs_x < boxes["n2"].abs_x


def test_vertical_auto_layout_places_children_in_a_column():
    children = [Element(kind="node", id=f"n{i}", type="EC2", provider="aws") for i in range(3)]
    container = Element(
        kind="container",
        id="c",
        type="vpc",
        provider="aws",
        layout=Layout(direction="vertical", gap=10, padding=5),
        children=children,
    )
    diagram = _diagram([container])
    root = build_layout(diagram, REGISTRY)
    boxes = _boxes_by_id(root)
    assert boxes["n0"].abs_x == boxes["n1"].abs_x == boxes["n2"].abs_x
    assert boxes["n0"].abs_y < boxes["n1"].abs_y < boxes["n2"].abs_y


def test_explicit_and_auto_children_coexist():
    explicit = Element(kind="node", id="fixed", type="EC2", provider="aws", x=5, y=5)
    auto = Element(kind="node", id="auto", type="S3", provider="aws")
    container = Element(kind="container", id="c", type="vpc", provider="aws", children=[explicit, auto])
    diagram = _diagram([container])
    root = build_layout(diagram, REGISTRY)
    boxes = _boxes_by_id(root)
    # explicit child keeps author-specified local position (relative to parent)
    assert boxes["fixed"].abs_x == boxes["c"].abs_x + 5
    assert boxes["fixed"].abs_y == boxes["c"].abs_y + 5


def test_container_without_explicit_size_wraps_its_children():
    child = Element(kind="node", id="n", type="EC2", provider="aws")
    container = Element(kind="container", id="c", type="vpc", provider="aws", children=[child])
    diagram = _diagram([container])
    root = build_layout(diagram, REGISTRY)
    boxes = _boxes_by_id(root)
    assert boxes["c"].width > boxes["n"].width
    assert boxes["c"].height > boxes["n"].height


def test_nested_containers_accumulate_absolute_offsets():
    leaf = Element(kind="node", id="leaf", type="EC2", provider="aws", x=1, y=1)
    inner = Element(kind="container", id="inner", type="az", provider="aws", x=10, y=10, children=[leaf])
    outer = Element(kind="container", id="outer", type="vpc", provider="aws", x=100, y=100, children=[inner])
    diagram = _diagram([outer])
    root = build_layout(diagram, REGISTRY)
    boxes = _boxes_by_id(root)
    assert boxes["leaf"].abs_x == 100 + 10 + 1
    assert boxes["leaf"].abs_y == 100 + 10 + 1


def test_out_of_canvas_element_is_flagged():
    el = Element(kind="node", id="far", type="EC2", provider="aws", x=5000, y=5000)
    diagram = _diagram([el])
    root = build_layout(diagram, REGISTRY)
    warnings = out_of_canvas_warnings(root, *diagram.canvas.size)
    assert any("far" in w for w in warnings)


def test_in_bounds_element_has_no_warning():
    el = Element(kind="node", id="ok", type="EC2", provider="aws", x=50, y=50)
    diagram = _diagram([el])
    root = build_layout(diagram, REGISTRY)
    warnings = out_of_canvas_warnings(root, *diagram.canvas.size)
    assert warnings == []


def test_overlapping_explicit_siblings_are_flagged():
    a = Element(kind="node", id="a", type="EC2", provider="aws", x=100, y=100)
    b = Element(kind="node", id="b", type="EC2", provider="aws", x=105, y=105)  # near-identical position
    diagram = _diagram([a, b])
    root = build_layout(diagram, REGISTRY)
    warnings = overlap_warnings(root)
    assert len(warnings) == 1
    assert "'a'" in warnings[0] and "'b'" in warnings[0]


def test_non_overlapping_explicit_siblings_are_not_flagged():
    a = Element(kind="node", id="a", type="EC2", provider="aws", x=100, y=100)
    b = Element(kind="node", id="b", type="EC2", provider="aws", x=400, y=400)
    diagram = _diagram([a, b])
    root = build_layout(diagram, REGISTRY)
    assert overlap_warnings(root) == []


def test_auto_placed_siblings_never_overlap():
    # Same mechanism the grid/horizontal/vertical placement uses internally -
    # auto layout should never trip its own overlap detector.
    children = [Element(kind="node", id=f"n{i}", type="EC2", provider="aws") for i in range(6)]
    container = Element(kind="container", id="c", type="vpc", provider="aws", children=children)
    diagram = _diagram([container])
    root = build_layout(diagram, REGISTRY)
    assert overlap_warnings(root) == []


def test_parent_and_child_are_not_falsely_flagged_as_overlapping():
    child = Element(kind="node", id="child", type="EC2", provider="aws")
    parent = Element(kind="container", id="parent", type="vpc", provider="aws", children=[child])
    diagram = _diagram([parent])
    root = build_layout(diagram, REGISTRY)
    assert overlap_warnings(root) == []


def test_overlap_check_applies_within_nested_containers_too():
    a = Element(kind="node", id="a", type="EC2", provider="aws", x=10, y=10)
    b = Element(kind="node", id="b", type="EC2", provider="aws", x=12, y=12)
    inner = Element(kind="container", id="inner", type="az", provider="aws", children=[a, b])
    diagram = _diagram([inner])
    root = build_layout(diagram, REGISTRY)
    warnings = overlap_warnings(root)
    assert len(warnings) == 1
