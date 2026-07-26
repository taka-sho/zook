from archdiagram.layout import (
    LABEL_BOX_HEIGHT,
    LABEL_GAP_DEFAULT,
    build_layout,
    connection_point,
    content_offset,
    effective_connector_style,
    link_crossing_warnings,
    link_render_plan,
    out_of_canvas_warnings,
    overlap_warnings,
)
from archdiagram.model import Canvas, Diagram, Element, Layout, Link
from archdiagram.registry import load_registries

REGISTRY = load_registries()


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


def test_auto_child_is_nudged_clear_of_an_overlapping_explicit_sibling():
    explicit = Element(kind="node", id="fixed", type="EC2", provider="aws", x=0, y=0)
    auto = Element(kind="node", id="auto", type="S3", provider="aws")
    container = Element(
        kind="container", id="c", type="vpc", provider="aws", layout=Layout(direction="grid"), children=[explicit, auto]
    )
    diagram = _diagram([container])
    root = build_layout(diagram, REGISTRY)
    assert overlap_warnings(root, REGISTRY) == []


def test_avoidance_never_moves_the_explicit_sibling_itself():
    explicit = Element(kind="node", id="fixed", type="EC2", provider="aws", x=0, y=0)
    auto = Element(kind="node", id="auto", type="S3", provider="aws")
    container = Element(kind="container", id="c", type="vpc", provider="aws", children=[explicit, auto])
    diagram = _diagram([container])
    root = build_layout(diagram, REGISTRY)
    boxes = _boxes_by_id(root)
    assert boxes["fixed"].abs_x == boxes["c"].abs_x
    assert boxes["fixed"].abs_y == boxes["c"].abs_y


def test_avoidance_does_not_move_auto_children_that_were_never_overlapping():
    from archdiagram.layout import measure

    auto_alone = Element(kind="node", id="auto", type="S3", provider="aws")
    container_alone = Element(kind="container", id="c", type="vpc", provider="aws", children=[auto_alone])
    box_alone = measure(container_alone, REGISTRY)
    alone_local = (box_alone.children[0].local_x, box_alone.children[0].local_y)

    explicit = Element(kind="node", id="fixed", type="EC2", provider="aws", x=1000, y=1000)
    auto_with_neighbor = Element(kind="node", id="auto", type="S3", provider="aws")
    container_with_neighbor = Element(
        kind="container", id="c", type="vpc", provider="aws", children=[explicit, auto_with_neighbor]
    )
    box_with_neighbor = measure(container_with_neighbor, REGISTRY)
    auto_box = next(b for b in box_with_neighbor.children if b.element.id == "auto")

    # a far-off explicit sibling shouldn't nudge the auto child at all
    assert (auto_box.local_x, auto_box.local_y) == alone_local


def test_avoidance_handles_multiple_stacked_explicit_obstacles():
    e1 = Element(kind="node", id="e1", type="EC2", provider="aws", x=0, y=0)
    e2 = Element(kind="node", id="e2", type="EC2", provider="aws", x=0, y=90)
    auto = Element(kind="node", id="auto", type="S3", provider="aws")
    container = Element(
        kind="container", id="c", type="vpc", provider="aws", layout=Layout(direction="grid"), children=[e1, e2, auto]
    )
    diagram = _diagram([container])
    root = build_layout(diagram, REGISTRY)
    assert overlap_warnings(root, REGISTRY) == []


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
    warnings = overlap_warnings(root, REGISTRY)
    assert len(warnings) == 1
    assert "'a'" in warnings[0] and "'b'" in warnings[0]


def test_non_overlapping_explicit_siblings_are_not_flagged():
    a = Element(kind="node", id="a", type="EC2", provider="aws", x=100, y=100)
    b = Element(kind="node", id="b", type="EC2", provider="aws", x=400, y=400)
    diagram = _diagram([a, b])
    root = build_layout(diagram, REGISTRY)
    assert overlap_warnings(root, REGISTRY) == []


def test_auto_placed_siblings_never_overlap():
    # Same mechanism the grid/horizontal/vertical placement uses internally -
    # auto layout should never trip its own overlap detector.
    children = [Element(kind="node", id=f"n{i}", type="EC2", provider="aws") for i in range(6)]
    container = Element(kind="container", id="c", type="vpc", provider="aws", children=children)
    diagram = _diagram([container])
    root = build_layout(diagram, REGISTRY)
    assert overlap_warnings(root, REGISTRY) == []


def test_parent_and_child_are_not_falsely_flagged_as_overlapping():
    child = Element(kind="node", id="child", type="EC2", provider="aws")
    parent = Element(kind="container", id="parent", type="vpc", provider="aws", children=[child])
    diagram = _diagram([parent])
    root = build_layout(diagram, REGISTRY)
    assert overlap_warnings(root, REGISTRY) == []


def test_overlap_check_applies_within_nested_containers_too():
    a = Element(kind="node", id="a", type="EC2", provider="aws", x=10, y=10)
    b = Element(kind="node", id="b", type="EC2", provider="aws", x=12, y=12)
    inner = Element(kind="container", id="inner", type="az", provider="aws", children=[a, b])
    diagram = _diagram([inner])
    root = build_layout(diagram, REGISTRY)
    warnings = overlap_warnings(root, REGISTRY)
    assert len(warnings) == 1


def test_straight_link_crossing_an_unrelated_box_is_flagged():
    a = Element(kind="node", id="a", type="EC2", provider="aws", x=0, y=100)
    b = Element(kind="node", id="b", type="EC2", provider="aws", x=150, y=100)  # sits between a and c
    c = Element(kind="node", id="c", type="EC2", provider="aws", x=300, y=100)
    diagram = _diagram([a, b, c], links=[Link(from_id="a", to_id="c")])
    root = build_layout(diagram, REGISTRY)
    warnings = link_crossing_warnings(root, diagram.links, REGISTRY)
    assert len(warnings) == 1
    assert "'a'" in warnings[0] and "'c'" in warnings[0] and "'b'" in warnings[0]


def test_straight_link_with_clear_path_is_not_flagged():
    a = Element(kind="node", id="a", type="EC2", provider="aws", x=0, y=0)
    c = Element(kind="node", id="c", type="EC2", provider="aws", x=300, y=0)
    b = Element(kind="node", id="b", type="EC2", provider="aws", x=150, y=400)  # well clear of the a->c line
    diagram = _diagram([a, b, c], links=[Link(from_id="a", to_id="c")])
    root = build_layout(diagram, REGISTRY)
    assert link_crossing_warnings(root, diagram.links, REGISTRY) == []


def test_link_between_container_siblings_does_not_flag_shared_parent():
    a = Element(kind="node", id="a", type="EC2", provider="aws")
    b = Element(kind="node", id="b", type="EC2", provider="aws")
    parent = Element(kind="container", id="parent", type="vpc", provider="aws", children=[a, b])
    diagram = _diagram([parent], links=[Link(from_id="a", to_id="b")])
    root = build_layout(diagram, REGISTRY)
    assert link_crossing_warnings(root, diagram.links, REGISTRY) == []


def test_link_to_a_container_does_not_flag_its_own_descendants():
    inner_node = Element(kind="node", id="inner_node", type="EC2", provider="aws")
    cloud = Element(
        kind="container", id="cloud", type="cloud", provider="generic", x=200, y=0, children=[inner_node]
    )
    actor = Element(kind="node", id="actor", type="User", provider="aws", x=0, y=0)
    diagram = _diagram([actor, cloud], links=[Link(from_id="actor", to_id="cloud")])
    root = build_layout(diagram, REGISTRY)
    assert link_crossing_warnings(root, diagram.links, REGISTRY) == []


def test_link_crossing_another_links_label_is_flagged():
    # Two horizontal links stacked closely enough that the top one's straight
    # path runs right through the bottom one's midpoint label box.
    a = Element(kind="node", id="a", type="EC2", provider="aws", x=0, y=100)
    b = Element(kind="node", id="b", type="EC2", provider="aws", x=300, y=100)
    c = Element(kind="node", id="c", type="EC2", provider="aws", x=0, y=105)
    d = Element(kind="node", id="d", type="EC2", provider="aws", x=300, y=105)
    diagram = _diagram(
        [a, b, c, d],
        links=[
            Link(from_id="c", to_id="d", label="labeled"),
            Link(from_id="a", to_id="b"),
        ],
    )
    root = build_layout(diagram, REGISTRY)
    warnings = link_crossing_warnings(root, diagram.links, REGISTRY)
    assert any("label of link" in w for w in warnings)


def test_default_label_gap_matches_LABEL_GAP_DEFAULT():
    el = Element(kind="node", id="a", type="EC2", provider="aws", x=0, y=0)
    diagram = _diagram([el])
    root = build_layout(diagram, REGISTRY)
    box = _boxes_by_id(root)["a"]
    assert box.footprint_h == box.height + LABEL_GAP_DEFAULT + LABEL_BOX_HEIGHT


def test_custom_label_gap_widens_footprint_and_offsets_below_label():
    el = Element(kind="node", id="a", type="EC2", provider="aws", x=0, y=0, style={"labelGap": 40})
    diagram = _diagram([el])
    root = build_layout(diagram, REGISTRY)
    box = _boxes_by_id(root)["a"]
    assert box.footprint_h == box.height + 40 + LABEL_BOX_HEIGHT


def test_custom_label_gap_offsets_above_label():
    el = Element(
        kind="node", id="a", type="EC2", provider="aws", x=0, y=0, style={"labelPosition": "above", "labelGap": 40}
    )
    diagram = _diagram([el])
    root = build_layout(diagram, REGISTRY)
    box = _boxes_by_id(root)["a"]
    # the icon is pushed down by the full reserve so the label fits above it
    dx, dy = content_offset(box)
    assert dy == 40 + LABEL_BOX_HEIGHT


def test_label_gap_does_not_apply_when_label_position_is_none():
    el = Element(
        kind="node", id="a", type="EC2", provider="aws", x=0, y=0, style={"labelPosition": "none", "labelGap": 40}
    )
    diagram = _diagram([el])
    root = build_layout(diagram, REGISTRY)
    box = _boxes_by_id(root)["a"]
    assert box.footprint_h == box.height


# --- overlapMargin ---------------------------------------------------------


def test_overlap_margin_zero_does_not_flag_a_near_miss():
    a = Element(kind="node", id="a", type="EC2", provider="aws", x=100, y=100)
    b = Element(kind="node", id="b", type="EC2", provider="aws", x=250, y=100)
    diagram = _diagram([a, b])
    root = build_layout(diagram, REGISTRY)
    assert overlap_warnings(root, REGISTRY, margin=0) == []


def test_overlap_margin_flags_elements_that_are_merely_close():
    # footprints are 60 logical units apart (a's right edge at 177, b's left
    # edge at 237); a margin comfortably bigger than the gap must flag it.
    a = Element(kind="node", id="a", type="EC2", provider="aws", x=100, y=100)
    b = Element(kind="node", id="b", type="EC2", provider="aws", x=250, y=100)
    diagram = _diagram([a, b])
    root = build_layout(diagram, REGISTRY)
    assert overlap_warnings(root, REGISTRY, margin=70) != []


def test_link_crossing_margin_flags_a_near_miss():
    a = Element(kind="node", id="a", type="EC2", provider="aws", x=0, y=100)
    b = Element(kind="node", id="b", type="EC2", provider="aws", x=150, y=160)  # just under the a->c line
    c = Element(kind="node", id="c", type="EC2", provider="aws", x=300, y=100)
    diagram = _diagram([a, b, c], links=[Link(from_id="a", to_id="c")])
    root = build_layout(diagram, REGISTRY)
    assert link_crossing_warnings(root, diagram.links, REGISTRY, margin=0) == []
    assert link_crossing_warnings(root, diagram.links, REGISTRY, margin=40) != []


# --- label-aware connection points ------------------------------------------


def test_bottom_exit_attaches_below_a_below_label():
    el = Element(kind="node", id="a", type="EC2", provider="aws", x=0, y=0)
    diagram = _diagram([el])
    root = build_layout(diagram, REGISTRY)
    box = _boxes_by_id(root)["a"]
    _, bottom_y = connection_point(box, 2)
    assert bottom_y == box.abs_y + box.height + LABEL_GAP_DEFAULT + LABEL_BOX_HEIGHT


def test_top_exit_attaches_above_an_above_label():
    el = Element(kind="node", id="a", type="EC2", provider="aws", x=0, y=0, style={"labelPosition": "above"})
    diagram = _diagram([el])
    root = build_layout(diagram, REGISTRY)
    box = _boxes_by_id(root)["a"]
    _, top_y = connection_point(box, 0)
    assert top_y == box.abs_y - (LABEL_GAP_DEFAULT + LABEL_BOX_HEIGHT)


def test_side_exit_is_unaffected_by_a_below_label():
    el = Element(kind="node", id="a", type="EC2", provider="aws", x=0, y=0)
    diagram = _diagram([el])
    root = build_layout(diagram, REGISTRY)
    box = _boxes_by_id(root)["a"]
    _, right_y = connection_point(box, 3)
    assert right_y == box.abs_y + box.height / 2


def test_bottom_exit_ignores_label_when_label_position_is_none():
    el = Element(kind="node", id="a", type="EC2", provider="aws", x=0, y=0, style={"labelPosition": "none"})
    diagram = _diagram([el])
    root = build_layout(diagram, REGISTRY)
    box = _boxes_by_id(root)["a"]
    _, bottom_y = connection_point(box, 2)
    assert bottom_y == box.abs_y + box.height


# --- auto-elbow for diagonal straight links --------------------------------


def test_diagonal_straight_link_is_upgraded_to_elbow():
    assert effective_connector_style("straight", (0, 0), (100, 50)) == "elbow"


def test_axis_aligned_straight_link_stays_straight():
    assert effective_connector_style("straight", (0, 0), (100, 0)) == "straight"
    assert effective_connector_style("straight", (0, 0), (0, 100)) == "straight"


def test_explicit_style_is_never_overridden():
    assert effective_connector_style("curved", (0, 0), (100, 50)) == "curved"
    assert effective_connector_style("elbow", (0, 0), (100, 0)) == "elbow"


def test_diagonal_link_renders_as_elbow_end_to_end():
    a = Element(kind="node", id="a", type="EC2", provider="aws", x=0, y=0)
    b = Element(kind="node", id="b", type="EC2", provider="aws", x=300, y=300)
    diagram = _diagram([a, b], links=[Link(from_id="a", to_id="b")])
    root = build_layout(diagram, REGISTRY)
    boxes = _boxes_by_id(root)
    _, _, eff_style, path = link_render_plan(boxes["a"], boxes["b"], "straight")
    assert eff_style == "elbow"
    assert len(path) == 4  # two right-angle bends, matching bentConnector3


# --- elbow-aware crossing detection -----------------------------------------


def test_elbow_crossing_check_catches_a_hit_a_straight_approximation_would_miss():
    # a->b is diagonal enough to auto-upgrade to elbow: exit (164,132), bend
    # at x=332, entry (500,432). `obstacle` sits squarely on the first
    # (horizontal, y=132) segment near the bend, at x=280-344, y=100-164 -
    # but the straight diagonal chord's y there is 235-282, well clear of
    # it. The elbow-aware check must catch this; a naive straight-line
    # approximation would have missed it entirely.
    a = Element(kind="node", id="a", type="EC2", provider="aws", x=100, y=100)
    b = Element(kind="node", id="b", type="EC2", provider="aws", x=500, y=400)
    obstacle = Element(kind="node", id="obstacle", type="RDS", provider="aws", x=280, y=100, style={"labelPosition": "none"})
    diagram = _diagram([a, b, obstacle], links=[Link(from_id="a", to_id="b")])
    root = build_layout(diagram, REGISTRY)

    warnings = link_crossing_warnings(root, diagram.links, REGISTRY)
    assert any("obstacle" in w for w in warnings)


def test_elbow_crossing_check_does_not_flag_the_unused_diagonal_chord():
    # Same shapes as above, but `obstacle` sits on the *diagonal chord*
    # between a's exit (164,132) and b's entry (500,432) - at roughly
    # (200-264, 160-224) the chord passes right through it - while staying
    # clear of all three real elbow segments (y=132 / x=332 / y=432). A
    # correct elbow-aware check must clear it; a naive straight-line
    # approximation would have flagged it.
    a = Element(kind="node", id="a", type="EC2", provider="aws", x=100, y=100)
    b = Element(kind="node", id="b", type="EC2", provider="aws", x=500, y=400)
    obstacle = Element(
        kind="node", id="obstacle", type="RDS", provider="aws", x=200, y=160, style={"labelPosition": "none"}
    )
    diagram = _diagram([a, b, obstacle], links=[Link(from_id="a", to_id="b")])
    root = build_layout(diagram, REGISTRY)

    warnings = link_crossing_warnings(root, diagram.links, REGISTRY)
    assert not any("obstacle" in w for w in warnings)


# --- container label vs. children -------------------------------------------


def test_child_overlapping_container_label_is_flagged():
    # Sitting right at the container's own top-left corner puts this child
    # squarely on top of the container's label text.
    child = Element(kind="node", id="child", type="EC2", provider="aws", x=0, y=0)
    parent = Element(kind="container", id="parent", type="vpc", provider="aws", label="My VPC", children=[child])
    diagram = _diagram([parent])
    root = build_layout(diagram, REGISTRY)
    warnings = overlap_warnings(root, REGISTRY)
    assert any("label of container 'parent'" in w for w in warnings)


def test_auto_placed_child_does_not_overlap_container_label():
    # Auto-layout already clears CONTAINER_LABEL_RESERVE for a labeled
    # container (measure()'s content_top), so this must stay clean.
    child = Element(kind="node", id="child", type="EC2", provider="aws")
    parent = Element(kind="container", id="parent", type="vpc", provider="aws", label="My VPC", children=[child])
    diagram = _diagram([parent])
    root = build_layout(diagram, REGISTRY)
    assert overlap_warnings(root, REGISTRY) == []


def test_container_label_overlap_respects_bottom_position():
    child = Element(
        kind="node", id="child", type="EC2", provider="aws", x=0, y=400, style={"labelPosition": "none"}
    )
    parent = Element(
        kind="container",
        id="parent",
        type="vpc",
        provider="aws",
        label="My VPC",
        style={"labelPosition": "bottom-left"},
        width=200,
        height=450,
        children=[child],
    )
    diagram = _diagram([parent])
    root = build_layout(diagram, REGISTRY)
    warnings = overlap_warnings(root, REGISTRY)
    assert any("label of container 'parent'" in w for w in warnings)


def test_container_label_no_overlap_when_child_stays_clear_at_the_bottom():
    child = Element(
        kind="node", id="child", type="EC2", provider="aws", x=0, y=100, style={"labelPosition": "none"}
    )
    parent = Element(
        kind="container",
        id="parent",
        type="vpc",
        provider="aws",
        label="My VPC",
        style={"labelPosition": "bottom-left"},
        width=200,
        height=450,
        children=[child],
    )
    diagram = _diagram([parent])
    root = build_layout(diagram, REGISTRY)
    assert overlap_warnings(root, REGISTRY) == []


# --- link labels vs. elements / other labels --------------------------------


def test_link_label_overlapping_unrelated_element_is_flagged():
    a = Element(kind="node", id="a", type="EC2", provider="aws", x=0, y=100)
    b = Element(kind="node", id="b", type="EC2", provider="aws", x=300, y=100)
    obstacle = Element(
        kind="node", id="obstacle", type="RDS", provider="aws", x=140, y=90, style={"labelPosition": "none"}
    )
    diagram = _diagram([a, b, obstacle], links=[Link(from_id="a", to_id="b", label="lbl")])
    root = build_layout(diagram, REGISTRY)
    warnings = link_crossing_warnings(root, diagram.links, REGISTRY)
    assert any("the label of link 'a' -> 'b' overlaps element 'obstacle'" in w for w in warnings)


def test_two_link_labels_on_the_same_pair_overlap():
    # Two labeled links between the same endpoints compute identical
    # midpoints - a guaranteed, deterministic label/label overlap.
    a = Element(kind="node", id="a", type="EC2", provider="aws", x=0, y=100)
    b = Element(kind="node", id="b", type="EC2", provider="aws", x=300, y=100)
    diagram = _diagram(
        [a, b],
        links=[Link(from_id="a", to_id="b", label="one"), Link(from_id="a", to_id="b", label="two")],
    )
    root = build_layout(diagram, REGISTRY)
    warnings = link_crossing_warnings(root, diagram.links, REGISTRY)
    assert any("overlaps the label of link" in w for w in warnings)


def test_link_label_does_not_overlap_a_distant_element():
    a = Element(kind="node", id="a", type="EC2", provider="aws", x=0, y=100)
    b = Element(kind="node", id="b", type="EC2", provider="aws", x=300, y=100)
    far = Element(kind="node", id="far", type="RDS", provider="aws", x=800, y=800)
    diagram = _diagram([a, b, far], links=[Link(from_id="a", to_id="b", label="lbl")])
    root = build_layout(diagram, REGISTRY)
    warnings = link_crossing_warnings(root, diagram.links, REGISTRY)
    assert not any("the label of link" in w and "'far'" in w for w in warnings)


# --- link path/label vs. container label (proposed addition) ---------------


def test_link_path_crossing_its_own_ancestor_containers_label_is_flagged():
    # a and b are the container's own children, so the container's *body*
    # is correctly excluded from the ordinary obstacle check (a link is
    # expected to pass through its own ancestor). Its label text is a
    # different matter - visually crossing straight through "Production
    # VPC" still looks wrong, so the lighter (endpoint-id-only) exclusion
    # used for container labels must still catch this.
    a = Element(kind="node", id="a", type="EC2", provider="aws", x=0, y=0, width=20, height=20, style={"labelPosition": "none"})
    b = Element(kind="node", id="b", type="EC2", provider="aws", x=300, y=0, width=20, height=20, style={"labelPosition": "none"})
    vpc = Element(kind="container", id="vpc", type="vpc", provider="aws", label="Production VPC", children=[a, b])
    diagram = _diagram([vpc], links=[Link(from_id="a", to_id="b")])
    root = build_layout(diagram, REGISTRY)

    warnings = link_crossing_warnings(root, diagram.links, REGISTRY)
    assert any("passes through the label of container 'vpc'" in w for w in warnings)
    # and confirm the body-exclusion still holds - no generic "through element 'vpc'" noise
    assert not any("passes through element 'vpc'" in w for w in warnings)


def test_link_path_does_not_cross_ancestor_label_when_routed_below_it():
    a = Element(kind="node", id="a", type="EC2", provider="aws", x=0, y=200, style={"labelPosition": "none"})
    b = Element(kind="node", id="b", type="EC2", provider="aws", x=300, y=200, style={"labelPosition": "none"})
    vpc = Element(kind="container", id="vpc", type="vpc", provider="aws", label="Production VPC", children=[a, b])
    diagram = _diagram([vpc], links=[Link(from_id="a", to_id="b")])
    root = build_layout(diagram, REGISTRY)

    warnings = link_crossing_warnings(root, diagram.links, REGISTRY)
    assert not any("label of container" in w for w in warnings)
