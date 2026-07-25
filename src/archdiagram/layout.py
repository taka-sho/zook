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

from .model import Diagram, Element, Layout
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
