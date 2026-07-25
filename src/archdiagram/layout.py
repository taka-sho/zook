"""Auto-layout engine, per docs/yaml-spec.md sec6-7.

Two passes:
  1. measure() - bottom-up. Computes each element's own render size and,
     for containers, positions its children *relative to the container's own
     top-left* (local_x/local_y). Explicit-position children keep the
     author's x/y; auto-placed children are packed by grid/horizontal/
     vertical, without avoiding explicit siblings (first-version behavior
     per spec: overlaps are fixed by hand later).
  2. assign_absolute() - top-down. Converts each element's local_x/local_y
     into slide-absolute logical coordinates by accumulating ancestor
     offsets, since PPTX groups are built with absolute child coordinates
     (chOff/chExt = off/ext, detailed-design-pptx.md sec8.4).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .model import Diagram, Element, Layout, Link
from .registry import Registry

LABEL_RESERVE = 22  # vertical space reserved for a node's below/above label
LABEL_MIN_WIDTH = 90  # footprint width floor so labels have room to sit under an icon
CONTAINER_LABEL_RESERVE = 28  # extra top space inside a container that has its own label


@dataclass
class Box:
    element: Element
    width: float
    height: float
    footprint_w: float
    footprint_h: float
    local_x: float = 0.0
    local_y: float = 0.0
    abs_x: float = 0.0
    abs_y: float = 0.0
    children: list["Box"] = field(default_factory=list)


def content_offset(box: Box) -> tuple[float, float]:
    """Offset from a node's footprint top-left to its icon's top-left."""
    if box.element.kind != "node":
        return (0.0, 0.0)
    label_position = box.element.style.get("labelPosition", "below")
    dx = (box.footprint_w - box.width) / 2
    dy = LABEL_RESERVE if label_position == "above" else 0.0
    return (dx, dy)


def _measure_node(element: Element, registry: Registry) -> Box:
    icon_entry = registry.resolve_icon(element.type)
    default_size = icon_entry.size if (icon_entry and icon_entry.size) else registry.default_size
    width = element.width or default_size
    height = element.height or default_size
    label_position = element.style.get("labelPosition", "below")
    footprint_w = width if label_position == "none" else max(width, LABEL_MIN_WIDTH)
    footprint_h = height + (LABEL_RESERVE if label_position in ("below", "above") else 0)
    return Box(element, width, height, footprint_w, footprint_h)


def _arrange_children(children: list[Box], layout: Layout, content_top: float) -> None:
    """Sets each child's local_x/local_y to its *content* (rendered) top-left.

    Placement math (grid/horizontal/vertical spacing) operates on footprint
    boxes so labels don't collide, but the stored local_x/local_y is always
    where the element itself actually renders - callers (bbox math below,
    render.py) never need to re-derive it.
    """
    explicit = [b for b in children if b.element.has_explicit_position]
    auto = [b for b in children if not b.element.has_explicit_position]

    for b in explicit:
        b.local_x = b.element.x
        b.local_y = b.element.y

    if not auto:
        return

    padding = layout.padding
    gap = layout.gap

    if layout.direction == "horizontal":
        x_cursor = padding
        for b in auto:
            dx, dy = content_offset(b)
            b.local_x = x_cursor + dx
            b.local_y = content_top + dy
            x_cursor += b.footprint_w + gap
    elif layout.direction == "vertical":
        y_cursor = content_top
        for b in auto:
            dx, dy = content_offset(b)
            b.local_x = padding + dx
            b.local_y = y_cursor + dy
            y_cursor += b.footprint_h + gap
    else:  # grid
        columns = layout.columns or max(1, math.ceil(math.sqrt(len(auto))))
        cell_w = max(b.footprint_w for b in auto) + gap
        cell_h = max(b.footprint_h for b in auto) + gap
        for i, b in enumerate(auto):
            col, row = i % columns, i // columns
            dx, dy = content_offset(b)
            b.local_x = padding + col * cell_w + dx
            b.local_y = content_top + row * cell_h + dy


def _bbox(children: list[Box], content_top: float, padding: float) -> tuple[float, float]:
    if not children:
        return padding * 2, content_top + padding
    max_x = 0.0
    max_y = 0.0
    for b in children:
        dx, dy = content_offset(b)
        max_x = max(max_x, (b.local_x - dx) + b.footprint_w)
        max_y = max(max_y, (b.local_y - dy) + b.footprint_h)
    return max_x + padding, max_y + padding


def measure(element: Element, registry: Registry) -> Box:
    if element.kind == "node":
        return _measure_node(element, registry)

    layout = element.layout or Layout()
    children = [measure(c, registry) for c in element.children]
    content_top = layout.padding + (CONTAINER_LABEL_RESERVE if element.label else 0)
    _arrange_children(children, layout, content_top)

    if element.width is not None and element.height is not None:
        width, height = element.width, element.height
    else:
        bbox_w, bbox_h = _bbox(children, content_top, layout.padding)
        width = element.width if element.width is not None else bbox_w
        height = element.height if element.height is not None else bbox_h

    return Box(element, width, height, width, height, children=children)


def assign_absolute(box: Box, parent_abs_x: float = 0.0, parent_abs_y: float = 0.0) -> None:
    box.abs_x = parent_abs_x + box.local_x
    box.abs_y = parent_abs_y + box.local_y
    for child in box.children:
        assign_absolute(child, box.abs_x, box.abs_y)


def build_layout(diagram: Diagram, registry: Registry) -> Box:
    canvas_w, canvas_h = diagram.canvas.size
    root_element = Element(
        kind="container",
        id="__root__",
        type="__canvas__",
        provider="generic",
        layout=Layout(direction="grid", gap=24, padding=diagram.canvas.padding),
        children=diagram.elements,
    )
    root_box = measure(root_element, registry)
    root_box.width = root_box.footprint_w = canvas_w
    root_box.height = root_box.footprint_h = canvas_h
    assign_absolute(root_box)
    return root_box


def iter_boxes(box: Box):
    yield box
    for child in box.children:
        yield from iter_boxes(child)


def _footprint_rect(box: Box) -> tuple[float, float, float, float]:
    """(x, y, w, h) of the element's occupied area, including its label
    reserve for nodes - the same box used for auto-layout spacing, so an
    overlap here is a real visual collision regardless of how the element
    was positioned (explicit x/y or auto-placed)."""
    dx, dy = content_offset(box)
    return box.abs_x - dx, box.abs_y - dy, box.footprint_w, box.footprint_h


def _rects_overlap(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return not (ax + aw <= bx or bx + bw <= ax or ay + ah <= by or by + bh <= ay)


def overlap_warnings(root_box: Box) -> list[str]:
    """Mechanically detect overlapping elements from their computed
    coordinates. Checked at every nesting level among direct siblings only -
    a node legitimately sits inside its parent container, so ancestor/
    descendant pairs are not compared. Applies uniformly to explicit and
    auto-placed children since it operates purely on the final layout boxes.
    """
    messages: list[str] = []

    def check(box: Box) -> None:
        children = box.children
        for i in range(len(children)):
            for j in range(i + 1, len(children)):
                a, b = children[i], children[j]
                if _rects_overlap(_footprint_rect(a), _footprint_rect(b)):
                    messages.append(f"element {a.element.id!r} overlaps element {b.element.id!r}")
        for child in children:
            check(child)

    check(root_box)
    return messages


def choose_connection_indices(from_box: Box, to_box: Box) -> tuple[int, int]:
    """sec8.2: idx 0=top, 1=left, 2=bottom, 3=right. Pick the edge facing the other shape."""
    fcx, fcy = from_box.abs_x + from_box.width / 2, from_box.abs_y + from_box.height / 2
    tcx, tcy = to_box.abs_x + to_box.width / 2, to_box.abs_y + to_box.height / 2
    dx, dy = tcx - fcx, tcy - fcy
    if abs(dx) >= abs(dy):
        return (3, 1) if dx >= 0 else (1, 3)
    return (2, 0) if dy >= 0 else (0, 2)


def connection_point(box: Box, idx: int) -> tuple[float, float]:
    """Exact reproduction of python-pptx's Connector._move_begin_to_cxn/
    _move_end_to_cxn formula (pptx/shapes/connector.py), so a predicted
    endpoint here always matches what python-pptx will actually draw."""
    x, y, cx, cy = box.abs_x, box.abs_y, box.width, box.height
    return {
        0: (x + cx / 2, y),
        1: (x, y + cy / 2),
        2: (x + cx / 2, y + cy),
        3: (x + cx, y + cy / 2),
    }[idx]


def _build_indices(root_box: Box) -> tuple[dict[str, Box], dict[str, str]]:
    by_id: dict[str, Box] = {}
    parent_of: dict[str, str] = {}

    def walk(box: Box, parent: Box | None) -> None:
        by_id[box.element.id] = box
        if parent is not None:
            parent_of[box.element.id] = parent.element.id
        for child in box.children:
            walk(child, box)

    walk(root_box, None)
    return by_id, parent_of


def _segments_intersect(
    p1: tuple[float, float], p2: tuple[float, float], p3: tuple[float, float], p4: tuple[float, float]
) -> bool:
    def ccw(a, b, c):
        return (c[1] - a[1]) * (b[0] - a[0]) > (b[1] - a[1]) * (c[0] - a[0])

    return ccw(p1, p3, p4) != ccw(p2, p3, p4) and ccw(p1, p2, p3) != ccw(p1, p2, p4)


def _segment_intersects_rect(
    p1: tuple[float, float], p2: tuple[float, float], rect: tuple[float, float, float, float]
) -> bool:
    rx, ry, rw, rh = rect
    if rx <= p1[0] <= rx + rw and ry <= p1[1] <= ry + rh:
        return True
    if rx <= p2[0] <= rx + rw and ry <= p2[1] <= ry + rh:
        return True
    corners = [(rx, ry), (rx + rw, ry), (rx + rw, ry + rh), (rx, ry + rh)]
    edges = list(zip(corners, corners[1:] + corners[:1]))
    return any(_segments_intersect(p1, p2, a, b) for a, b in edges)


LINK_LABEL_SIZE = (60, 18)  # logical units; matches render.py's midpoint label textbox


def link_crossing_warnings(root_box: Box, links: list[Link]) -> list[str]:
    """Mechanically detect a link's straight-line path running through an
    unrelated element or another link's label, using the exact same
    connection-point geometry python-pptx will render (connection_point()
    above). Ancestors/descendants of either endpoint are excluded, since a
    link legitimately touches its own endpoint's containers on the way in.

    Exact for `style: straight` (the default and by far the most common).
    For `elbow`/`curved` links the real path may bend away from this
    straight-line approximation, so a clean result here is not a full
    guarantee for those styles - documented in docs-site/limitations.md.
    """
    by_id, parent_of = _build_indices(root_box)

    def ancestors(element_id: str) -> set[str]:
        result: set[str] = set()
        cur = parent_of.get(element_id)
        while cur is not None:
            result.add(cur)
            cur = parent_of.get(cur)
        return result

    def descendants(element_id: str) -> set[str]:
        box = by_id.get(element_id)
        return {b.element.id for b in iter_boxes(box)} if box else set()

    obstacles = [(eid, _footprint_rect(b)) for eid, b in by_id.items() if eid != "__root__"]

    endpoints: dict[int, tuple[tuple[float, float], tuple[float, float]] | None] = {}
    for i, link in enumerate(links):
        from_box, to_box = by_id.get(link.from_id), by_id.get(link.to_id)
        if from_box is None or to_box is None:
            endpoints[i] = None  # dangling refs are Fatal elsewhere; defensive only
            continue
        s_idx, e_idx = choose_connection_indices(from_box, to_box)
        endpoints[i] = (connection_point(from_box, s_idx), connection_point(to_box, e_idx))

    label_rects: dict[int, tuple[float, float, float, float]] = {}
    lw, lh = LINK_LABEL_SIZE
    for i, link in enumerate(links):
        pts = endpoints[i]
        if not link.label or pts is None:
            continue
        p1, p2 = pts
        mx, my = (p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2
        label_rects[i] = (mx - lw / 2, my - lh / 2, lw, lh)

    messages: list[str] = []
    for i, link in enumerate(links):
        pts = endpoints[i]
        if pts is None:
            continue
        p1, p2 = pts
        exclude = (
            {link.from_id, link.to_id}
            | ancestors(link.from_id)
            | ancestors(link.to_id)
            | descendants(link.from_id)
            | descendants(link.to_id)
        )

        for eid, rect in obstacles:
            if eid in exclude:
                continue
            if _segment_intersects_rect(p1, p2, rect):
                messages.append(f"link {link.from_id!r} -> {link.to_id!r} passes through element {eid!r}")

        for j, rect in label_rects.items():
            if j == i:
                continue
            if _segment_intersects_rect(p1, p2, rect):
                other = links[j]
                messages.append(
                    f"link {link.from_id!r} -> {link.to_id!r} passes through the label of link "
                    f"{other.from_id!r} -> {other.to_id!r}"
                )

    return messages


def out_of_canvas_warnings(root_box: Box, canvas_w: float, canvas_h: float) -> list[str]:
    """sec9: coordinates outside the canvas are a Warning, not clamped."""
    messages = []
    for box in iter_boxes(root_box):
        if box.element.id == "__root__":
            continue
        if box.abs_x < 0 or box.abs_y < 0 or box.abs_x + box.width > canvas_w or box.abs_y + box.height > canvas_h:
            messages.append(
                f"element {box.element.id!r} is positioned outside the canvas bounds "
                f"(x={box.abs_x:.0f}, y={box.abs_y:.0f}, w={box.width:.0f}, h={box.height:.0f})"
            )
    return messages
