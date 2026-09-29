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
from typing import Optional

from .errors import Finding
from .model import TOP_LEVEL_GAP_DEFAULT, Diagram, Element, Layout, Link
from .registry import MultiRegistry, icon_png
from .text import line_height, longest_word_width, natural_width, text_block_height, wrap_lines

LABEL_GAP_DEFAULT = 4  # default spacing between an icon and its label; overridable per-node via style.labelGap
NODE_LABEL_FONT_SIZE_DEFAULT = 9  # points; overridable per-node via style.labelFontSize
CONTAINER_LABEL_FONT_SIZE_DEFAULT = 10  # points; overridable per-container via style.labelFontSize
LINK_LABEL_FONT_SIZE_DEFAULT = 8  # points; overridable per-link via labelFontSize
LABEL_MIN_WIDTH = 90  # footprint width floor so labels have room to sit under an icon
LABEL_MAX_WIDTH = 150  # a below/above/right label widens its node's footprint up to this, then wraps
LABEL_TEXT_SLACK = 4  # spare width kept beside a measured label, for estimate error
CONTAINER_LABEL_RESERVE = 28  # band a container reserves for a one-line label, at the default font size
CONTAINER_LABEL_MAX_WIDTH = 260  # an auto-sized container widens for its label up to this, then it wraps
CONTAINER_LABEL_INSET = 4 * 4 / 3  # render.py's 4pt text-frame margin, in logical units
CORNER_BADGE_ROOM = 26  # render.py's corner badge (20) + its padding (6), beside a left-aligned label
# Top-level elements are usually an actor and the boundary it talks to (a
# cloud, a VPC), with an arrow and its label between them - they need more
# room than siblings packed inside a container (model.TOP_LEVEL_GAP_DEFAULT).
SHAPE_TEXT_INSET = 9.6  # PowerPoint's default 0.1in text-frame side inset inside a `shape` node
SHAPE_TEXT_INSET_Y = 4.8  # ... and its 0.05in top/bottom inset


def label_box_height(font_size: float, line_count: int = 1) -> float:
    """Height of a label textbox holding `line_count` lines at `font_size`
    points: 1.2x line spacing per line plus a little padding. One line at the
    default 9pt is 18 logical units."""
    return text_block_height(line_count, font_size)


LABEL_BOX_HEIGHT = label_box_height(NODE_LABEL_FONT_SIZE_DEFAULT)  # 18, for callers that want the default


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
    # The element's own label, as measured: the text, the lines it wraps to,
    # and the box it's drawn in. For a node, label_reserve is the space the
    # label takes above/below the icon (gap included); for a container, the
    # height of the band its label occupies at the top or bottom edge.
    label_text: str = ""
    label_lines: list[str] = field(default_factory=list)
    label_w: float = 0.0
    label_h: float = 0.0
    label_reserve: float = 0.0
    # The laid-out tree this box belongs to (set by build_layout), so link
    # routing can look at the other elements without every caller having to
    # pass the tree along - render and every check then route identically.
    root: Optional["Box"] = field(default=None, repr=False, compare=False)
    _routing_index: Optional[dict] = field(default=None, repr=False, compare=False)


def label_gap(element: Element) -> float:
    """style.labelGap (yaml-spec.md sec5.2): spacing between a node's icon and its label."""
    return element.style.get("labelGap", LABEL_GAP_DEFAULT)


def node_label_font_size(element: Element) -> float:
    """style.labelFontSize (points): a node's own label text size."""
    return element.style.get("labelFontSize", NODE_LABEL_FONT_SIZE_DEFAULT)


def container_label_font_size(element: Element) -> float:
    """style.labelFontSize (points): a container's own label text size."""
    return element.style.get("labelFontSize", CONTAINER_LABEL_FONT_SIZE_DEFAULT)


def container_label_reserve(font_size: float, line_count: int = 1) -> float:
    """Band a labeled container reserves for its own label: CONTAINER_LABEL_
    RESERVE for one line (scaled with `font_size` from the default 10pt, so a
    bigger labelFontSize gets proportionally more room), plus a line height
    per extra line."""
    one_line = CONTAINER_LABEL_RESERVE * (font_size / CONTAINER_LABEL_FONT_SIZE_DEFAULT)
    return one_line + max(0, line_count - 1) * line_height(font_size)


def node_label_text(element: Element, registry: MultiRegistry) -> str:
    """The text drawn as a node's label: its own `label`, else the registry
    entry's default label, else the `type` itself - render/preview/drawio all
    draw exactly this, so layout measures exactly this."""
    if element.label is not None:
        return element.label
    if is_shape_node(element):
        return element.type
    icon_entry = registry.resolve_icon(element.type, element.provider)
    return icon_entry.label if (icon_entry and icon_entry.label) else element.type


def _label_reserve(element: Element) -> float:
    """Space a one-line label takes (gap + box). Only for callers without a
    measured Box; Box.label_reserve is the real, text-aware value."""
    return label_gap(element) + label_box_height(node_label_font_size(element))


# Default (width, height) for a `shape` node (logical units), per shape:
# rect/rounded default to a landscape box (typical flowchart look); diamond/
# circle default a bit larger since their usable interior for text is
# smaller than their bounding box.
SHAPE_DEFAULT_SIZE = {
    "rect": (140, 60),
    "rounded": (140, 60),
    "diamond": (120, 90),
    "circle": (120, 90),
}
# Share of a shape's bounding box (per axis) that its OOXML preset gives the
# text: a diamond's text rectangle is the middle half (w/4..3w/4, h/4..3h/4),
# an ellipse's the inscribed square (cos 45 deg). The 0.1in/0.05in insets
# apply inside that.
_SHAPE_TEXT_AREA = {"rect": 1.0, "rounded": 1.0, "diamond": 0.5, "circle": 0.7071}
# A roundRect's text rectangle is inset on every side by 0.29289 x its corner
# radius, which defaults to 1/6 of the shorter side.
_ROUNDED_TEXT_INSET = 0.29289 / 6
SHAPE_MAX_AUTO_WIDTH_FACTOR = 2  # an auto-sized shape widens for its longest word up to this x its default width


def is_shape_node(element: Element) -> bool:
    """True for a node rendered as a plain shape (rect/rounded/diamond/
    circle) with its label centered inside, instead of resolving `type` to
    an icon with a separate label below/above/beside it."""
    return element.kind == "node" and element.style.get("shape") is not None


def content_offset(box: Box) -> tuple[float, float]:
    """Offset from a node's footprint top-left to its icon's top-left."""
    if box.element.kind != "node" or is_shape_node(box.element):
        return (0.0, 0.0)
    label_position = box.element.style.get("labelPosition", "below")
    if label_position == "right":
        return (0.0, (box.footprint_h - box.height) / 2)
    dx = (box.footprint_w - box.width) / 2
    dy = box.label_reserve if label_position == "above" else 0.0
    return (dx, dy)


def _measure_shape_node(element: Element) -> Box:
    shape = element.style["shape"]
    default_w, default_h = SHAPE_DEFAULT_SIZE[shape]
    width = element.width or element.size or default_w
    height = element.height or element.size or default_h
    text = element.label if element.label is not None else element.type
    font = node_label_font_size(element)
    area = _SHAPE_TEXT_AREA[shape]
    if element.width is None and element.size is None:
        # Widen for the longest word, so "Gateway" in a diamond isn't broken
        # into "Gatew" / "ay" (PowerPoint breaks a word wider than the line).
        corner = 2 * _ROUNDED_TEXT_INSET * min(width, height) if shape == "rounded" else 0.0
        needed_w = (longest_word_width(text, font) + LABEL_TEXT_SLACK + 2 * SHAPE_TEXT_INSET + corner) / area
        width = max(width, min(needed_w, default_w * SHAPE_MAX_AUTO_WIDTH_FACTOR))
    auto_height = element.height is None and element.size is None
    for _ in range(3):  # a rounded corner's inset follows the (possibly grown) height
        corner = 2 * _ROUNDED_TEXT_INSET * min(width, height) if shape == "rounded" else 0.0
        lines = wrap_lines(text, font, max(1.0, width * area - corner - 2 * SHAPE_TEXT_INSET))
        needed_h = (label_box_height(font, len(lines)) + 2 * SHAPE_TEXT_INSET_Y + corner) / area
        if not auto_height or needed_h <= height + 0.01:
            break
        height = needed_h  # grow to fit the text, never shrink the default
    box = Box(element, width, height, width, height)
    box.label_text, box.label_lines = text, lines
    box.label_w, box.label_h = width, label_box_height(font, len(lines))
    return box


def _measure_node(element: Element, registry: MultiRegistry) -> Box:
    if is_shape_node(element):
        return _measure_shape_node(element)

    icon_entry = registry.resolve_icon(element.type, element.provider)
    default_size = icon_entry.size if (icon_entry and icon_entry.size) else registry.default_size(element.provider)
    width = element.width or element.size or default_size
    height = element.height or element.size or default_size
    label_position = element.style.get("labelPosition", "below")
    if label_position == "none":
        return Box(element, width, height, width, height)

    text = node_label_text(element, registry)
    font = node_label_font_size(element)
    gap = label_gap(element)
    wanted = natural_width(text, font) + LABEL_TEXT_SLACK
    if label_position == "right":
        label_w = min(max(wanted, 1.0), LABEL_MAX_WIDTH)
        lines = wrap_lines(text, font, label_w - LABEL_TEXT_SLACK)
        label_h = label_box_height(font, len(lines))
        box = Box(element, width, height, width + gap + label_w, max(height, label_h))
    else:  # below / above
        footprint_w = max(width, LABEL_MIN_WIDTH, min(wanted, LABEL_MAX_WIDTH))
        label_w = footprint_w
        lines = wrap_lines(text, font, footprint_w - LABEL_TEXT_SLACK)
        label_h = label_box_height(font, len(lines))
        box = Box(element, width, height, footprint_w, height + gap + label_h)
        box.label_reserve = gap + label_h
    box.label_text, box.label_lines, box.label_w, box.label_h = text, lines, label_w, label_h
    return box


def node_label_rect(box: Box) -> tuple[float, float, float, float] | None:
    """Where a node's label textbox is drawn (absolute), or None if it has none.
    render.py and preview.py draw it here; it lies inside the footprint."""
    element = box.element
    if element.kind != "node" or is_shape_node(element):
        return None
    position = element.style.get("labelPosition", "below")
    if position == "none" or not box.label_lines:
        return None
    dx, dy = content_offset(box)
    footprint_x, footprint_y = box.abs_x - dx, box.abs_y - dy
    if position == "below":
        return (footprint_x, box.abs_y + box.height + label_gap(element), box.footprint_w, box.label_h)
    if position == "above":
        return (footprint_x, footprint_y, box.footprint_w, box.label_h)
    # right: vertically centered on the icon
    return (box.abs_x + box.width + label_gap(element), box.abs_y + (box.height - box.label_h) / 2, box.label_w, box.label_h)


def _cross_align(boxes: list[Box], axis: int) -> tuple[float, list[float]]:
    """Align boxes across a row (axis=1, vertical placement) or a column
    (axis=0, horizontal placement). Returns the band length and each box's
    offset within it.

    A band of nodes only is aligned on the icons' centres, so icons of
    different sizes (or labels of different line counts) line up and the
    link between neighbours is straight instead of a staircase. A band that
    holds a container keeps every member at the band's start edge: a node
    next to a tall container belongs beside its top (where the entry point
    usually is), not halfway down it."""
    lengths = [b.footprint_w if axis == 0 else b.footprint_h for b in boxes]
    if axis == 1 and any(b.element.kind != "node" for b in boxes):
        return max(lengths), [0.0] * len(boxes)
    centres = [_center_offsets(b)[axis] for b in boxes]
    before = max(centres)
    after = max(length - c for c, length in zip(centres, lengths))
    return before + after, [before - c for c in centres]


def _center_offsets(box: Box) -> tuple[float, float]:
    """(x, y) distance from a box's footprint top-left to its content centre."""
    dx, dy = content_offset(box)
    return dx + box.width / 2, dy + box.height / 2


def _grid_tracks(auto: list[Box], columns: int, gap: float):
    """Non-uniform grid: each column is as wide as its widest member and each
    row as tall as its tallest (a uniform cell sized to the largest element
    pushed a small actor's neighbour - a whole VPC - off the canvas)."""
    rows = math.ceil(len(auto) / columns)
    col_bands = []
    for c in range(columns):
        members = auto[c::columns]
        col_bands.append(_cross_align(members, axis=0))
    row_bands = []
    for r in range(rows):
        members = auto[r * columns : (r + 1) * columns]
        row_bands.append(_cross_align(members, axis=1))
    width = sum(w for w, _ in col_bands) + gap * (columns - 1)
    height = sum(h for h, _ in row_bands) + gap * (rows - 1)
    return col_bands, row_bands, width, height


def _choose_columns(auto: list[Box], gap: float, available: tuple[float, float]) -> int:
    """Column count for a grid with no explicit `columns`, given the space it
    has to fit (the canvas, for the top level): the arrangement that
    overflows the least, then the one whose shape best matches the space."""
    avail_w, avail_h = available
    target = avail_w / avail_h if avail_h > 0 else 1.0
    best, best_key = 1, None
    for columns in range(1, len(auto) + 1):
        _, _, width, height = _grid_tracks(auto, columns, gap)
        overflow = max(0.0, width - avail_w) / avail_w + max(0.0, height - avail_h) / avail_h
        shape = abs(math.log((width / height if height else 1.0) / target))
        key = (round(overflow, 6), shape)
        if best_key is None or key < best_key:
            best, best_key = columns, key
    return best


def _arrange_children(
    children: list[Box],
    layout: Layout,
    content_top: float,
    available: tuple[float, float] | None = None,
    flow_edges: list[tuple[int, int]] | None = None,
) -> None:
    """Sets each child's local_x/local_y to its *content* (rendered) top-left.

    Placement math (grid/horizontal/vertical spacing) operates on footprint
    boxes so labels don't collide, but the stored local_x/local_y is always
    where the element itself actually renders - callers (bbox math below,
    render.py) never need to re-derive it. On the cross axis, children are
    aligned by their content centre (see _cross_align). `available` is the
    space a grid should fit, used to pick its column count when none is given.
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

    if flow_edges is not None:
        # indexes among all children -> among the auto-placed ones
        auto_index = {id(b): k for k, b in enumerate(auto)}
        edges = [
            (auto_index[id(children[a])], auto_index[id(children[b])])
            for a, b in flow_edges
            if id(children[a]) in auto_index and id(children[b]) in auto_index
        ]
        if edges and layout.direction in ("horizontal", "vertical"):
            _arrange_layered(auto, edges, layout, content_top)
            _avoid_explicit_overlaps(auto, explicit, gap)
            return
        if edges:  # grid: the flow decides the order the grid is filled in
            auto[:] = [auto[k] for level in _flow_levels(len(auto), edges) for k in level]

    if layout.direction == "horizontal":
        _, offsets = _cross_align(auto, axis=1)
        x_cursor = padding
        for b, off in zip(auto, offsets):
            dx, dy = content_offset(b)
            b.local_x = x_cursor + dx
            b.local_y = content_top + off + dy
            x_cursor += b.footprint_w + gap
    elif layout.direction == "vertical":
        _, offsets = _cross_align(auto, axis=0)
        y_cursor = content_top
        for b, off in zip(auto, offsets):
            dx, dy = content_offset(b)
            b.local_x = padding + off + dx
            b.local_y = y_cursor + dy
            y_cursor += b.footprint_h + gap
    else:  # grid
        if layout.columns:
            columns = min(layout.columns, len(auto))  # more columns than children: the extra ones stay empty
        elif available is not None:
            columns = _choose_columns(auto, gap, available)
        else:
            columns = max(1, math.ceil(math.sqrt(len(auto))))
        col_bands, row_bands, _, _ = _grid_tracks(auto, columns, gap)
        col_x = [padding]
        for w, _ in col_bands[:-1]:
            col_x.append(col_x[-1] + w + gap)
        row_y = [content_top]
        for h, _ in row_bands[:-1]:
            row_y.append(row_y[-1] + h + gap)
        for i, b in enumerate(auto):
            col, row = i % columns, i // columns
            within_col = col_bands[col][1][row]
            within_row = row_bands[row][1][col]
            dx, dy = content_offset(b)
            b.local_x = col_x[col] + within_col + dx
            b.local_y = row_y[row] + within_row + dy

    _avoid_explicit_overlaps(auto, explicit, gap)


def _flow_edges(element: Element, links: list[Link]) -> list[tuple[int, int]]:
    """The links inside `element` as (from, to) pairs of its direct children
    - a link to something nested in a child counts for that child."""
    owner: dict[str, int] = {}

    def claim(e: Element, index: int) -> None:
        owner[e.id] = index
        for c in e.children:
            claim(c, index)

    for index, child in enumerate(element.children):
        claim(child, index)
    edges = []
    for link in links:
        a, b = owner.get(link.from_id), owner.get(link.to_id)
        if a is not None and b is not None and a != b:
            edges.append((a, b))
    return edges


def flow_ranks(n: int, edges: list[tuple[int, int]]) -> tuple[list[int], dict[int, list[int]]]:
    """Each of n members' rank - how far along the links it sits (longest
    path from a member nothing points to) - once the links that close a
    cycle are set aside (found depth-first in source order). Also returns
    the remaining forward links, member -> successors."""
    succ: dict[int, list[int]] = {i: [] for i in range(n)}
    for a, b in edges:
        if b not in succ[a]:
            succ[a].append(b)
    forward: dict[int, list[int]] = {i: [] for i in range(n)}
    state: dict[int, int] = {}
    for start in range(n):
        if start in state:
            continue
        stack = [(start, iter(succ[start]))]
        state[start] = 1
        while stack:
            v, it = stack[-1]
            w = next(it, None)
            if w is None:
                state[v] = 2
                stack.pop()
            elif state.get(w) == 1:
                continue  # back edge: part of a cycle
            else:
                forward[v].append(w)
                if w not in state:
                    state[w] = 1
                    stack.append((w, iter(succ[w])))
    rank = [0] * n
    for _ in range(n):  # longest path; the forward graph is acyclic
        changed = False
        for v in range(n):
            for w in forward[v]:
                if rank[w] < rank[v] + 1:
                    rank[w], changed = rank[v] + 1, True
        if not changed:
            break
    return rank, forward


FLOW_SWEEPS = 4  # barycenter passes (down and up) ordering each rank


def _flow_levels(n: int, edges: list[tuple[int, int]]) -> list[list[int]]:
    """Members grouped by rank, each rank ordered to keep links short and
    uncrossed: repeatedly sort a rank by the mean position of its members'
    neighbours in the rank before (then after) it - the barycenter
    heuristic. Ties, and members with no neighbour there, keep source
    order."""
    rank, forward = flow_ranks(n, edges)
    preds: dict[int, list[int]] = {i: [] for i in range(n)}
    for v, ws in forward.items():
        for w in ws:
            preds[w].append(v)
    levels: list[list[int]] = [[] for _ in range(max(rank) + 1)]
    for i in range(n):
        levels[rank[i]].append(i)

    def position() -> dict[int, float]:
        return {m: k - (len(level) - 1) / 2 for level in levels for k, m in enumerate(level)}

    for sweep in range(FLOW_SWEEPS):
        down = sweep % 2 == 0
        for r in (range(1, len(levels)) if down else range(len(levels) - 2, -1, -1)):
            pos = position()
            neighbours = preds if down else forward

            def key(m: int, pos=pos, neighbours=neighbours):
                near = [pos[v] for v in neighbours[m] if rank[v] == r + (-1 if down else 1)]
                return (sum(near) / len(near) if near else pos[m], pos[m])

            levels[r].sort(key=key)
    return levels


def _arrange_layered(auto: list[Box], edges: list[tuple[int, int]], layout: Layout, content_top: float) -> None:
    """`order: flow` on a horizontal (vertical) container: one column (row)
    per rank, left to right (top to bottom), the members of a rank stacked
    across it and every rank centred on the widest one - so a chain is a
    straight line and a fork's arms sit side by side. Ranks are twice the
    usual gap apart, room for a link and its label between them."""
    levels = [[auto[k] for k in level] for level in _flow_levels(len(auto), edges)]
    gap, rank_gap = layout.gap, 2 * layout.gap
    horizontal = layout.direction == "horizontal"
    stack_axis = 1 if horizontal else 0  # members of a rank stack along this axis

    def extent(b: Box, axis: int) -> float:
        return b.footprint_h if axis == 1 else b.footprint_w

    spans = [sum(extent(b, stack_axis) for b in level) + gap * (len(level) - 1) for level in levels]
    widest = max(spans)
    # Ranks of nodes are centred on each other, so a chain runs straight; a
    # container starts at the leading edge instead, like a row holding one
    # does (_cross_align) - AZs side by side, not staggered by their heights.
    centred = all(b.element.kind == "node" for b in auto)
    along = layout.padding if horizontal else content_top  # position of the current rank
    for level, span in zip(levels, spans):
        band, offsets = _cross_align(level, axis=1 - stack_axis)
        cursor = (content_top if horizontal else layout.padding) + ((widest - span) / 2 if centred else 0.0)
        for b, off in zip(level, offsets):
            dx, dy = content_offset(b)
            if horizontal:
                b.local_x, b.local_y = along + off + dx, cursor + dy
            else:
                b.local_x, b.local_y = cursor + dx, along + off + dy
            cursor += extent(b, stack_axis) + gap
        along += band + rank_gap


def _local_footprint_rect(box: Box) -> tuple[float, float, float, float]:
    """Same shape as _footprint_rect() below, but before assign_absolute()
    has run - operates on local_x/local_y instead of abs_x/abs_y, for use
    while _arrange_children() is still placing children within one parent."""
    dx, dy = content_offset(box)
    return box.local_x - dx, box.local_y - dy, box.footprint_w, box.footprint_h


def _avoid_explicit_overlaps(auto: list[Box], explicit: list[Box], gap: float) -> None:
    """First-version overlap avoidance: an auto-placed child that ends up
    overlapping an *explicitly* positioned sibling is nudged straight down
    until clear - and a push that lands it on another auto-placed sibling
    pushes that one on in turn (the packed siblings only start out
    collision-free). Explicit positions are never silently moved (the
    author stated them on purpose). This closes the one documented gap
    (yaml-spec.md sec6): auto layout didn't used to look at explicit
    siblings at all. overlap_warnings() remains authoritative and still
    flags anything this simple push doesn't fully resolve.
    """
    if not explicit:
        return
    placed = list(explicit)  # what a later auto sibling must clear: explicit ones, then the autos settled so far
    for a in auto:
        for _ in range(len(placed) + 1):
            hit = next((o for o in placed if _rects_overlap(_local_footprint_rect(a), _local_footprint_rect(o))), None)
            if hit is None:
                break
            _, hit_y, _, hit_h = _local_footprint_rect(hit)
            dx, dy = content_offset(a)
            a.local_y = (hit_y + hit_h + gap) + dy
        placed.append(a)


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


def container_label_text(element: Element, registry: MultiRegistry) -> str:
    """The label a container actually shows: its own `label`, else its
    registry group's default label (e.g. "AWS Cloud")."""
    if element.label is not None:
        return element.label
    group_style = registry.resolve_group(element.type, element.provider)
    return group_style.label if group_style else ""


def _container_label_needs(element: Element, registry: MultiRegistry) -> tuple[str, float, float]:
    """(text, font size, width the label wants on one line incl. insets/badge)."""
    text = container_label_text(element, registry)
    if not text:
        return "", 0.0, 0.0
    font = container_label_font_size(element)
    group_style = registry.resolve_group(element.type, element.provider)
    position = resolve_container_label_position(element, registry)
    badge = CORNER_BADGE_ROOM if (group_style and group_style.icon and "left" in position) else 0.0
    return text, font, natural_width(text, font) + 2 * CONTAINER_LABEL_INSET + badge + LABEL_TEXT_SLACK


def measure(
    element: Element,
    registry: MultiRegistry,
    available: tuple[float, float] | None = None,
    room: dict[str, tuple[float, float]] | None = None,
    links: list[Link] | None = None,
) -> Box:
    """Size an element (a container from its children, recursively).
    `room` gives auto-sized containers extra (width, height) at their right
    and bottom - see build_layout: a link label that didn't fit inside.
    `links` are the diagram's links, which a `layout.order: flow` container
    arranges its children by."""
    if element.kind == "node":
        return _measure_node(element, registry)

    layout = element.layout or Layout()
    children = [measure(c, registry, room=room, links=links) for c in element.children]
    flow_edges = _flow_edges(element, links or []) if layout.order == "flow" else None
    extra_w, extra_h = (room or {}).get(element.id, (0.0, 0.0))
    text, font, label_wants = _container_label_needs(element, registry)
    label_at_bottom = bool(text) and "bottom" in resolve_container_label_position(element, registry)

    # A one-line band first; if the label turns out to need more lines at the
    # container's final width, lay the children out again with a taller band.
    lines = 1
    for _attempt in range(2):
        band = container_label_reserve(font, lines) if text else 0.0
        content_top = layout.padding + (0.0 if label_at_bottom else band)
        _arrange_children(children, layout, content_top, available, flow_edges)
        bbox_w, bbox_h = _bbox(children, content_top, layout.padding)
        bbox_w, bbox_h = bbox_w + extra_w, bbox_h + extra_h
        if element.width is not None:
            width = element.width
        else:
            width = max(bbox_w, min(label_wants, max(bbox_w, CONTAINER_LABEL_MAX_WIDTH)))
        height = element.height if element.height is not None else bbox_h + (band if label_at_bottom else 0.0)
        wrapped = (
            wrap_lines(text, font, max(1.0, width - (label_wants - natural_width(text, font) - LABEL_TEXT_SLACK)))
            if text
            else []
        )
        if len(wrapped) <= lines:
            break
        lines = len(wrapped)

    box = Box(element, width, height, width, height, children=children)
    if text:
        box.label_text, box.label_lines = text, wrapped
        box.label_w, box.label_h, box.label_reserve = width, band, band
    return box


def assign_absolute(box: Box, parent_abs_x: float = 0.0, parent_abs_y: float = 0.0) -> None:
    box.abs_x = parent_abs_x + box.local_x
    box.abs_y = parent_abs_y + box.local_y
    for child in box.children:
        assign_absolute(child, box.abs_x, box.abs_y)


LABEL_ROOM_MARGIN = 6  # clearance an auto-sized container keeps around a link label it grew for


def build_layout(diagram: Diagram, registry: MultiRegistry) -> Box:
    """Lay the diagram out. An auto-sized container that a link label
    would stick out of (a long label beside the link between two stacked
    icons) is grown at its right/bottom until the label fits, a few passes
    at most - the label's spot depends on the layout it changes."""
    room: dict[str, tuple[float, float]] = {}
    for _ in range(3):
        root = _layout_pass(diagram, registry, room)
        grown = False
        for container_id, (need_w, need_h) in _label_overflow(root, diagram.links).items():
            have_w, have_h = room.get(container_id, (0.0, 0.0))
            if need_w > 0.5 or need_h > 0.5:
                room[container_id] = (have_w + need_w, have_h + need_h)
                grown = True
        if not grown:
            break
    return root


def _label_overflow(root: Box, links: list[Link]) -> dict[str, tuple[float, float]]:
    """How much wider/taller each auto-sized container must be for the
    labels of the links inside it to fit (right/bottom only)."""
    by_id = _routing_index(root)["by_id"]
    need: dict[str, tuple[float, float]] = {}
    for link in links:
        from_box, to_box = by_id.get(link.from_id), by_id.get(link.to_id)
        if not link.label or from_box is None or to_box is None:
            continue
        container = _enclosing_container(from_box, to_box)
        if container is None:
            continue
        path = link_render_plan(from_box, to_box, link)[3]
        x, y, w, h = link_label_rect_for(from_box, to_box, path, link)
        over_w = x + w + LABEL_ROOM_MARGIN - (container.abs_x + container.width) if container.element.width is None else 0.0
        over_h = y + h + LABEL_ROOM_MARGIN - (container.abs_y + container.height) if container.element.height is None else 0.0
        if over_w > 0.5 or over_h > 0.5:
            old_w, old_h = need.get(container.element.id, (0.0, 0.0))
            need[container.element.id] = (max(old_w, over_w, 0.0), max(old_h, over_h, 0.0))
    return need


def _layout_pass(diagram: Diagram, registry: MultiRegistry, room: dict[str, tuple[float, float]]) -> Box:
    canvas_w, canvas_h = diagram.canvas.size
    padding = diagram.canvas.padding
    top = diagram.canvas.layout or Layout(direction="grid", gap=TOP_LEVEL_GAP_DEFAULT)
    root_element = Element(
        kind="container",
        id="__root__",
        type="__canvas__",
        provider="generic",
        layout=Layout(direction=top.direction, columns=top.columns, gap=top.gap, padding=padding, order=top.order),
        children=diagram.elements,
    )
    available = (max(1.0, canvas_w - 2 * padding), max(1.0, canvas_h - 2 * padding))
    root_box = measure(root_element, registry, available, room, diagram.links)
    root_box.width = root_box.footprint_w = canvas_w
    root_box.height = root_box.footprint_h = canvas_h
    assign_absolute(root_box)
    for box in iter_boxes(root_box):
        box.root = root_box
    _assign_lanes(diagram.links)
    return root_box


def _assign_lanes(links: list[Link]) -> None:
    """Links joining the same two elements (A->B twice, or A->B and B->A)
    were drawn on exactly one line, labels stacked: number them so
    link_render_plan() can set them side by side. Author-routed links
    (waypoints) keep their own path and don't take a lane."""
    groups: dict[frozenset, list[Link]] = {}
    for link in links:
        if not link.waypoints and link.from_id != link.to_id:
            groups.setdefault(frozenset((link.from_id, link.to_id)), []).append(link)
    for group in groups.values():
        for lane, link in enumerate(group):
            link.lane, link.lanes = lane, len(group)


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


def _inflate_rect(rect: tuple[float, float, float, float], margin: float) -> tuple[float, float, float, float]:
    x, y, w, h = rect
    return x - margin, y - margin, w + 2 * margin, h + 2 * margin


def resolve_container_label_position(element: Element, registry: MultiRegistry) -> str:
    """Same precedence render.py uses to pick a container's label position:
    the element's own style wins, then the registry's group default, then
    the schema's own "top-left" default. Shared so the overlap check can
    never disagree with what's actually drawn."""
    group_style = registry.resolve_group(element.type, element.provider)
    return element.style.get("labelPosition") or (group_style.label_position if group_style else "top-left")


@dataclass
class ResolvedContainerStyle:
    border_color: str
    fill_color: Optional[str]
    border_width: float
    dashed: bool
    label_position: str
    label_text: str
    label_font_size: float
    corner_icon: Optional[object]  # Path | None; typed loosely to avoid importing pathlib here


def resolve_container_style(element: Element, registry: MultiRegistry) -> ResolvedContainerStyle:
    """Every visual property of a container's own frame, resolved with the
    same element.style > registry group > hardcoded-default precedence.
    Shared by render.py (pptx) and preview.py (PNG) so the two renderers
    can't drift apart."""
    group_style = registry.resolve_group(element.type, element.provider)
    style = element.style or {}
    return ResolvedContainerStyle(
        border_color=style.get("borderColor") or (group_style.border_color if group_style else "#5A6B86"),
        fill_color=style.get("fillColor") or (group_style.fill_color if group_style else None),
        border_width=style.get("borderWidth", group_style.border_width if group_style else 1),
        dashed=group_style.dashed if group_style else False,
        label_position=resolve_container_label_position(element, registry),
        label_text=container_label_text(element, registry),
        label_font_size=container_label_font_size(element),
        corner_icon=group_style.icon if group_style else None,
    )


def _luminance(color: str) -> float:
    """WCAG relative luminance of a #RRGGBB colour."""
    channels = [int(color.lstrip("#")[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    r, g, b = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def readable_on(color: str, backdrop: str) -> str:
    """`color`, or - when it would be hard to read on `backdrop` (contrast
    below 3:1, e.g. black labels on a dark canvas.background) - white or
    near-black, whichever the backdrop needs."""
    a, b = _luminance(color), _luminance(backdrop)
    if (max(a, b) + 0.05) / (min(a, b) + 0.05) >= 3:
        return color
    return "#FFFFFF" if b < 0.18 else "#1E1E1E"


DEFAULT_BACKDROP = "#FFFFFF"


def backdrops(root_box: Box, registry: MultiRegistry, canvas_background: str | None) -> dict[str, str]:
    """The colour behind each element (its nearest enclosing container's
    fill, else the canvas background, else white), and for a container
    under the key `(id, "inside")` the colour inside it - what its label
    and children are drawn on. render.py and preview.py pick text and line
    colours from this with readable_on()."""
    colors: dict = {}

    def walk(box: Box, behind: str) -> None:
        for child in box.children:
            colors[child.element.id] = behind
            if child.element.kind == "container":
                inside = resolve_container_style(child.element, registry).fill_color or behind
                colors[(child.element.id, "inside")] = inside
                walk(child, inside)

    walk(root_box, canvas_background or DEFAULT_BACKDROP)
    return colors


def container_label_rect(box: Box, registry: MultiRegistry) -> tuple[float, float, float, float] | None:
    """Where a container's own label text is drawn: its measured label band
    spanning the full width, at the top or bottom edge per
    resolve_container_label_position(). None if the container shows no label
    - but a label that comes from the registry default (e.g. "AWS Cloud"
    when `label` is omitted) is drawn, so it counts here too."""
    if box.element.kind != "container" or not box.label_text:
        return None
    position = resolve_container_label_position(box.element, registry)
    label_h = min(box.label_reserve, box.height)
    y = box.abs_y + box.height - label_h if "bottom" in position else box.abs_y
    return (box.abs_x, y, box.width, label_h)


def overlap_warnings(root_box: Box, registry: MultiRegistry, margin: float = 0) -> list[str]:
    """Mechanically detect overlapping (or, with `margin` > 0, too-close)
    elements from their computed coordinates.

    Two kinds of pairs are checked:
      - Direct siblings, at every nesting level. A node legitimately sits
        inside its parent container, so ancestor/descendant pairs are never
        compared here. Applies uniformly to explicit and auto-placed
        children since it operates purely on the final layout boxes.
      - A container's own label text against each of its *direct* children -
        deliberately excluded from the sibling rule above (a child is
        expected to sit inside its parent's box), but a child overlapping
        the parent's own label specifically is a real, distinct defect an
        author should see.

    `margin` (canvas.overlapMargin, logical units) inflates one side of each
    pair before testing, so elements/labels that come within `margin` of
    each other are flagged even if they don't literally touch.
    """
    messages: list[str] = []

    def check(box: Box) -> None:
        children = box.children
        for i in range(len(children)):
            for j in range(i + 1, len(children)):
                a, b = children[i], children[j]
                if _rects_overlap(_inflate_rect(_footprint_rect(a), margin), _footprint_rect(b)):
                    messages.append(Finding(
                        f"element {a.element.id!r} overlaps element {b.element.id!r}",
                        "element-overlap", [a.element.id, b.element.id],
                    ))

        label_rect = container_label_rect(box, registry)
        if label_rect is not None:
            for child in children:
                if _rects_overlap(_inflate_rect(label_rect, margin), _footprint_rect(child)):
                    messages.append(Finding(
                        f"element {child.element.id!r} overlaps the label of container {box.element.id!r}",
                        "container-label-overlap", [child.element.id, box.element.id],
                    ))

        for child in children:
            check(child)

    check(root_box)
    return messages


_SIDE_TO_IDX = {"top": 0, "left": 1, "bottom": 2, "right": 3}
_IDX_AXIS = {0: "vertical", 2: "vertical", 1: "horizontal", 3: "horizontal"}


def _side_toward(box: Box, point: tuple[float, float]) -> int:
    """Connection-point index (0=top,1=left,2=bottom,3=right) of the box edge
    that faces `point`, by dominant direction from the box centre - used to
    attach a waypoint link's endpoint toward its first/last via."""
    cx, cy = box.abs_x + box.width / 2, box.abs_y + box.height / 2
    dx, dy = point[0] - cx, point[1] - cy
    if abs(dx) >= abs(dy):
        return 3 if dx >= 0 else 1
    return 2 if dy >= 0 else 0

# How much shorter the non-dominant axis's path must be, relative to the
# dominant axis's, before auto-selection switches to it (sec8.2). Without
# this, a near-tie (a couple of percent, easily produced by label-avoidance
# offsets) could flip the axis choice on what's visually an obviously
# horizontal- or vertical-leaning pair, which read as unstable/unnatural.
_AXIS_SWITCH_MARGIN = 0.2


def _path_length(path: list[tuple[float, float]]) -> float:
    return sum(math.dist(p1, p2) for p1, p2 in zip(path, path[1:]))


def choose_connection_indices(from_box: Box, to_box: Box, link: Optional[Link] = None) -> tuple[int, int]:
    """sec8.2: idx 0=top, 1=left, 2=bottom, 3=right.

    - Both `link.from_side`/`link.to_side` set: used as-is (validate.py has
      already rejected any axis-mismatched combination as Fatal, so this
      always yields a same-axis pair).
    - Only one set: it fixes the axis (top/bottom = vertical, left/right =
      horizontal); the other endpoint auto-picks its side on that same
      axis from the two boxes' relative position, same rule as the fully
      automatic case below.
    - Neither set (default): the dominant axis (whichever of |dx|/|dy| is
      larger) is used unless the *other* axis's actual rendered path
      (connection points, label-avoidance offsets, and elbow routing all
      included) is shorter by more than _AXIS_SWITCH_MARGIN - a plain
      "always pick whichever is shorter" flips on near-ties (a couple of
      percent, easily produced by label offsets) in cases that read as
      obviously horizontal- or vertical-leaning, which looked unstable and
      unnatural in practice.
    """
    from_side = link.from_side if link else None
    to_side = link.to_side if link else None

    # Waypoints route explicitly, so each endpoint just attaches on the side
    # facing its nearest waypoint (unless the author fixed a side). The axis-
    # match rule that constrains a plain elbow doesn't apply here.
    if link and link.waypoints:
        s = _SIDE_TO_IDX[from_side] if from_side else _side_toward(from_box, link.waypoints[0])
        e = _SIDE_TO_IDX[to_side] if to_side else _side_toward(to_box, link.waypoints[-1])
        return s, e

    fcx, fcy = from_box.abs_x + from_box.width / 2, from_box.abs_y + from_box.height / 2
    tcx, tcy = to_box.abs_x + to_box.width / 2, to_box.abs_y + to_box.height / 2
    dx, dy = tcx - fcx, tcy - fcy
    horizontal_pair = (3, 1) if dx >= 0 else (1, 3)
    vertical_pair = (2, 0) if dy >= 0 else (0, 2)

    if from_side and to_side:
        return _SIDE_TO_IDX[from_side], _SIDE_TO_IDX[to_side]
    if from_side:
        from_idx = _SIDE_TO_IDX[from_side]
        return (from_idx, horizontal_pair[1]) if _IDX_AXIS[from_idx] == "horizontal" else (from_idx, vertical_pair[1])
    if to_side:
        to_idx = _SIDE_TO_IDX[to_side]
        return (horizontal_pair[0], to_idx) if _IDX_AXIS[to_idx] == "horizontal" else (vertical_pair[0], to_idx)

    style = link.style if link else "straight"

    def path(idx_pair: tuple[int, int]) -> list[tuple[float, float]]:
        p1, p2 = connection_point(from_box, idx_pair[0]), connection_point(to_box, idx_pair[1])
        eff_style = effective_connector_style(style, p1, p2)
        return connector_path(eff_style, p1, p2, idx_pair[0], idx_pair[1])

    dominant, other = (horizontal_pair, vertical_pair) if abs(dx) >= abs(dy) else (vertical_pair, horizontal_pair)
    # Prefer the axis whose path doesn't run through other elements: with the
    # endpoints close together, the dominant-axis Z-route often cuts through a
    # neighbour (an actor's link into a cloud diving across the first service
    # to reach the second) while the other axis is clear.
    obstacles = _routing_obstacles(from_box, to_box) + own_endpoint_rects(from_box, to_box)
    if obstacles:
        hits_dominant = _count_hits(path(dominant), obstacles)
        hits_other = _count_hits(path(other), obstacles)
        best_hits = min(hits_dominant, hits_other)
        if best_hits > 0:
            # Both straight-ish routes cut through something (a link skipping
            # past a whole row, e.g. to a node several steps along a flow):
            # a U route out and around - over, under, or beside both ends -
            # may get past clean.
            around = []
            for idx in (0, 2, 1, 3):
                u_path = _same_side_path(connection_point(from_box, idx), connection_point(to_box, idx), idx)
                around.append((_count_hits(u_path, obstacles), _path_length(u_path), (idx, idx)))
            hits_u, _, pair_u = min(around)
            if hits_u == 0:  # only a clean way round: a U that still hits something is doctor's call
                return pair_u
        if hits_other != hits_dominant:
            return other if hits_other < hits_dominant else dominant
    if _path_length(path(other)) < _path_length(path(dominant)) * (1 - _AXIS_SWITCH_MARGIN):
        return other
    return dominant


def _routing_index(root: Box) -> dict:
    if root._routing_index is None:
        by_id, parent_of = _build_indices(root)
        root._routing_index = {"by_id": by_id, "parent_of": parent_of}
    return root._routing_index


def _related_ids(index: dict, element_id: str) -> set[str]:
    """The element, its ancestors and its descendants - what a link to or
    from it is expected to touch."""
    related = {element_id}
    cur = index["parent_of"].get(element_id)
    while cur is not None:
        related.add(cur)
        cur = index["parent_of"].get(cur)
    box = index["by_id"].get(element_id)
    if box is not None:
        related.update(b.element.id for b in iter_boxes(box))
    return related


def _routing_obstacles(from_box: Box, to_box: Box) -> list[tuple[float, float, float, float]]:
    """Footprints a path between the two boxes shouldn't cross: every element
    except the endpoints and their ancestors/descendants (the same exclusion
    link_crossing_warnings applies)."""
    root = from_box.root
    if root is None or to_box.root is not root:
        return []
    index = _routing_index(root)
    related = index.setdefault("related", {})
    for eid in (from_box.element.id, to_box.element.id):
        if eid not in related:
            related[eid] = _related_ids(index, eid)
    exclude = related[from_box.element.id] | related[to_box.element.id] | {"__root__"}
    if "rects" not in index:
        index["rects"] = {eid: _footprint_rect(b) for eid, b in index["by_id"].items()}
    return [rect for eid, rect in index["rects"].items() if eid not in exclude]


def own_endpoint_rects(from_box: Box, to_box: Box) -> list[tuple[float, float, float, float]]:
    """The icons (and labels) of a link's own endpoint nodes, shrunk by a unit
    so a path that merely attaches to an edge doesn't touch them: a route
    that enters one of them runs back through its own endpoint."""
    rects = []
    for box in {id(from_box): from_box, id(to_box): to_box}.values():
        if box.element.kind != "node":
            continue  # a link to a container legitimately runs inside it
        rects.append(_inflate_rect((box.abs_x, box.abs_y, box.width, box.height), -1.0))
        label = node_label_rect(box)
        if label is not None:
            rects.append(_inflate_rect(label, -1.0))
    return rects


def _count_hits(path: list[tuple[float, float]], obstacles: list[tuple[float, float, float, float]]) -> int:
    segments = list(zip(path, path[1:]))
    return sum(1 for rect in obstacles if any(_segment_intersects_rect(a, b, rect) for a, b in segments))


def connection_point(box: Box, idx: int) -> tuple[float, float]:
    """Exact reproduction of python-pptx's Connector._move_begin_to_cxn/
    _move_end_to_cxn formula (pptx/shapes/connector.py), so a predicted
    endpoint here always matches what python-pptx will actually draw -
    except that a node's own label pushes its top/bottom connection point
    out past the label instead of into it, when the arrow exits on the
    same side the label sits on (a bottom-exit arrow on a node with a
    below-label attaches under the label, not through it; symmetric for a
    top-exit arrow with an above-label)."""
    x, y, cx, cy = box.abs_x, box.abs_y, box.width, box.height
    icon_cx, icon_cy = x + cx / 2, y + cy / 2

    # Past the node's own label on the side it sits: exactly the middle of
    # that side of the label box, which is where render.py glues the
    # connector (to the label textbox), so a viewer that re-snaps glued ends
    # lands on the same point.
    label = node_label_rect(box)
    position = box.element.style.get("labelPosition", "below")
    if idx == 0:
        return (icon_cx, label[1] if label and position == "above" else y)
    if idx == 2:
        return (icon_cx, label[1] + label[3] if label and position == "below" else y + cy)
    if idx == 1:
        return (x, icon_cy)
    if label and position == "right":
        return (label[0] + label[2], icon_cy)  # past a right-hand label, not through it
    return (x + cx, icon_cy)  # idx == 3


def _is_axis_aligned(p1: tuple[float, float], p2: tuple[float, float], epsilon: float = 0.5) -> bool:
    return abs(p1[0] - p2[0]) < epsilon or abs(p1[1] - p2[1]) < epsilon


def effective_connector_style(style: str, p1: tuple[float, float], p2: tuple[float, float]) -> str:
    """A literal diagonal line reads as broken next to AWS-diagram-style
    orthogonal routing, so an unstyled/`straight` link whose two connection
    points aren't axis-aligned is auto-upgraded to `elbow`. An explicit
    `elbow`/`curved` choice is always left untouched."""
    if style == "straight" and not _is_axis_aligned(p1, p2):
        return "elbow"
    return style


SAME_SIDE_CLEARANCE = 20  # how far a same-side (top/top, ...) route stands off both endpoints


def connector_path(
    style: str, p1: tuple[float, float], p2: tuple[float, float], start_idx: int, end_idx: int | None = None
) -> list[tuple[float, float]]:
    """Waypoints matching what python-pptx actually renders.

    - straight (and curved, approximated): the two endpoints.
    - elbow: exact reproduction of the OOXML "bentConnector3" preset that
      MSO_CONNECTOR.ELBOW always uses (confirmed empirically by rendering
      probe connectors through LibreOffice - see detailed-design-pptx.md):
      it exits perpendicular to the start shape's connected edge, bends
      once at the midpoint of the bridging axis, and enters perpendicular
      to the end shape's edge. Since choose_connection_indices() only ever
      pairs same-axis indices (both horizontal: 1/3, or both vertical:
      0/2), start_idx alone tells us which axis the exit/entry use.
    - both ends on the *same* side (top/top, right/right, ...), whatever the
      style: a U - out from both endpoints by SAME_SIDE_CLEARANCE beyond the
      outermost one, then across. (A Z bending halfway between them, as
      before, ran straight through the endpoints' own icons and wasn't what
      any viewer drew.) render.py draws it as a polyline, like waypoints.
    """
    if end_idx is not None and end_idx == start_idx:
        return _same_side_path(p1, p2, start_idx)
    if style != "elbow":
        return [p1, p2]
    if start_idx in (1, 3):  # horizontal exit/entry
        mid_x = (p1[0] + p2[0]) / 2
        return [p1, (mid_x, p1[1]), (mid_x, p2[1]), p2]
    mid_y = (p1[1] + p2[1]) / 2  # vertical exit/entry
    return [p1, (p1[0], mid_y), (p2[0], mid_y), p2]


def _same_side_path(p1: tuple[float, float], p2: tuple[float, float], side_idx: int) -> list[tuple[float, float]]:
    c = SAME_SIDE_CLEARANCE
    if side_idx == 0:  # top
        y = min(p1[1], p2[1]) - c
        return [p1, (p1[0], y), (p2[0], y), p2]
    if side_idx == 2:  # bottom
        y = max(p1[1], p2[1]) + c
        return [p1, (p1[0], y), (p2[0], y), p2]
    if side_idx == 1:  # left
        x = min(p1[0], p2[0]) - c
        return [p1, (x, p1[1]), (x, p2[1]), p2]
    x = max(p1[0], p2[0]) + c  # right
    return [p1, (x, p1[1]), (x, p2[1]), p2]


def is_same_side(start_idx: int, end_idx: int) -> bool:
    return start_idx == end_idx


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
    # Quick reject: the segment's bounding box misses the rect entirely.
    if (p1[0] < rx and p2[0] < rx) or (p1[0] > rx + rw and p2[0] > rx + rw) or (
        p1[1] < ry and p2[1] < ry
    ) or (p1[1] > ry + rh and p2[1] > ry + rh):
        return False
    if rx <= p1[0] <= rx + rw and ry <= p1[1] <= ry + rh:
        return True
    if rx <= p2[0] <= rx + rw and ry <= p2[1] <= ry + rh:
        return True
    corners = [(rx, ry), (rx + rw, ry), (rx + rw, ry + rh), (rx, ry + rh)]
    edges = list(zip(corners, corners[1:] + corners[:1]))
    return any(_segments_intersect(p1, p2, a, b) for a, b in edges)


LINK_LABEL_SIZE = (60, 18)  # legacy fixed box at LINK_LABEL_FONT_SIZE_DEFAULT, for a size with no text to measure
LINK_LABEL_MAX_WIDTH = 120  # a link label wraps beyond this
LINK_LABEL_PAD = 3  # horizontal breathing room inside the label box
ARROW_CLEARANCE = 12  # length at each end of a link the label must leave visible (the arrowhead)
LINK_LABEL_OFFSET = 3  # gap between the line and a label moved beside it
LINK_LABEL_MAX_SHIFT = 60  # a moved label further than this from its line would read as another link's


def link_label_size(font_size: float, text: str | None = None) -> tuple[float, float]:
    """(width, height) of a link's label box: measured from `text` (wrapped
    past LINK_LABEL_MAX_WIDTH), or - with no text - the legacy fixed estimate
    scaled from LINK_LABEL_SIZE."""
    if text is None:
        base_w, base_h = LINK_LABEL_SIZE
        ratio = font_size / LINK_LABEL_FONT_SIZE_DEFAULT
        return base_w * ratio, base_h * ratio
    return link_label_box(text, font_size)[:2]


def link_label_box(text: str, font_size: float) -> tuple[float, float, list[str]]:
    width = min(natural_width(text, font_size) + 2 * LINK_LABEL_PAD, LINK_LABEL_MAX_WIDTH)
    lines = wrap_lines(text, font_size, width - 2 * LINK_LABEL_PAD)
    return width, label_box_height(font_size, len(lines)), lines


def _point_along(path: list[tuple[float, float]], distance: float) -> tuple[float, float]:
    covered = 0.0
    for a, b in zip(path, path[1:]):
        length = math.dist(a, b)
        if length and covered + length >= distance:
            t = (distance - covered) / length
            return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
        covered += length
    return path[-1]


def _anchor_segment(path: list[tuple[float, float]]) -> tuple[tuple[float, float], tuple[float, float]]:
    """The path segment the arc-length midpoint falls on."""
    lengths = [math.dist(a, b) for a, b in zip(path, path[1:])]
    half = sum(lengths) / 2
    covered = 0.0
    for (a, b), length in zip(zip(path, path[1:]), lengths):
        if covered + length >= half:
            return a, b
        covered += length
    return path[-2], path[-1]


def _contains(rect: tuple[float, float, float, float], point: tuple[float, float]) -> bool:
    x, y, w, h = rect
    return x <= point[0] <= x + w and y <= point[1] <= y + h


def link_label_rect(
    path: list[tuple[float, float]],
    text: str,
    font_size: float,
    avoid: list[tuple[float, float, float, float]] = (),
    bounds: tuple[float, float, float, float] | None = None,
) -> tuple[float, float, float, float]:
    """Where a link's label box is drawn: centred on the path's arc-length
    midpoint - unless that would cover an end of the link (its arrowhead), as
    it did on the short link between two neighbouring icons, where the white
    label box hid the whole line and its direction, or one of the `avoid`
    rects (the link's own endpoint icons and labels, own_endpoint_rects()).
    Then it moves to the nearest free spot beside the line: just above/below
    a horizontal stretch (right/left of a vertical one), else just past the
    endpoint icons it would cover - but never further than
    LINK_LABEL_MAX_SHIFT, where it would read as another link's label.
    Shared by render.py, preview.py and the overlap checks
    (link_label_rect_for() supplies `avoid`)."""
    width, height, _ = link_label_box(text, font_size)
    ax, ay = link_label_anchor(path)
    centred = (ax - width / 2, ay - height / 2, width, height)
    total = sum(math.dist(a, b) for a, b in zip(path, path[1:]))
    ends = [path[0], path[-1], _point_along(path, min(ARROW_CLEARANCE, total)), _point_along(path, max(0.0, total - ARROW_CLEARANCE))]

    def covers_end(rect: tuple[float, float, float, float]) -> bool:
        return any(_contains(rect, p) for p in ends)

    def inside(rect: tuple[float, float, float, float]) -> bool:
        return bounds is None or _contains_rect(bounds, rect)

    def clear(rect: tuple[float, float, float, float]) -> bool:
        return not covers_end(rect) and not any(_rects_overlap(rect, a) for a in avoid)

    if clear(centred) and inside(centred):
        return centred
    left, top = ax - width / 2, ay - height / 2
    above, below = (left, ay - height - LINK_LABEL_OFFSET, width, height), (left, ay + LINK_LABEL_OFFSET, width, height)
    right, left_of = (ax + LINK_LABEL_OFFSET, top, width, height), (ax - LINK_LABEL_OFFSET - width, top, width, height)
    (sx, sy), (ex, ey) = _anchor_segment(path)
    horizontal = abs(ey - sy) <= abs(ex - sx)
    candidates = [above, below] if horizontal else [right, left_of]  # beside the line, not on it
    # ... or past whichever endpoint icons/labels are in the way, on either axis
    columns = [a for a in avoid if a[0] < left + width and left < a[0] + a[2]]
    if columns:
        candidates.append((left, min(a[1] for a in columns) - height - LINK_LABEL_OFFSET, width, height))
        candidates.append((left, max(a[1] + a[3] for a in columns) + LINK_LABEL_OFFSET, width, height))
    rows = [a for a in avoid if a[1] < top + height and top < a[1] + a[3]]
    if rows:
        candidates.append((max(a[0] + a[2] for a in rows) + LINK_LABEL_OFFSET, top, width, height))
        candidates.append((min(a[0] for a in rows) - LINK_LABEL_OFFSET - width, top, width, height))
    # The nearest free spot, preferring one inside the link's container; a
    # spot sticking out of it (reported as a Warning) beats covering an
    # icon, and anything further than LINK_LABEL_MAX_SHIFT reads as some
    # other link's label, which is worse than either.
    near = [
        (not inside(r), round(_distance_to_rect((ax, ay), r), 1), i, r)
        for i, r in enumerate([centred, *candidates])
        if clear(r) and _distance_to_rect((ax, ay), r) <= LINK_LABEL_MAX_SHIFT
    ]
    if near:
        return min(near)[3]
    return centred if not covers_end(centred) else candidates[0]


def _contains_rect(outer: tuple[float, float, float, float], inner: tuple[float, float, float, float]) -> bool:
    ox, oy, ow, oh = outer
    ix, iy, iw, ih = inner
    return ix >= ox - 0.5 and iy >= oy - 0.5 and ix + iw <= ox + ow + 0.5 and iy + ih <= oy + oh + 0.5


def _enclosing_container(from_box: Box, to_box: Box) -> Box | None:
    """The innermost container holding both ends of a link (for a link
    between a container and something inside it, that container) - where
    its label belongs; None at the top level."""
    root = from_box.root
    if root is None or to_box.root is not root:
        return None
    index = _routing_index(root)
    parent_of, by_id = index["parent_of"], index["by_id"]

    def chain(box: Box) -> list[str]:
        ids = [box.element.id] if box.element.kind == "container" else []
        cur = parent_of.get(box.element.id)
        while cur is not None:
            ids.append(cur)
            cur = parent_of.get(cur)
        return ids

    to_chain = set(chain(to_box))
    common = next((eid for eid in chain(from_box) if eid in to_chain), None)
    if common is None or common == "__root__":
        return None
    return by_id[common]


def _distance_to_rect(point: tuple[float, float], rect: tuple[float, float, float, float]) -> float:
    x, y, w, h = rect
    dx = max(x - point[0], 0.0, point[0] - (x + w))
    dy = max(y - point[1], 0.0, point[1] - (y + h))
    return math.hypot(dx, dy)


def link_label_rect_for(from_box: Box, to_box: Box, path: list[tuple[float, float]], link: Link) -> tuple[float, float, float, float]:
    """link_label_rect() for `link` drawn along `path`, kept off its own
    endpoint icons and their labels, and inside the container the link
    lives in (an opaque label box sticking out cut through its frame)."""
    return link_label_rect(
        path, link.label, link.label_font_size, own_endpoint_rects(from_box, to_box), _label_bounds(from_box, to_box)
    )


def _label_bounds(from_box: Box, to_box: Box) -> tuple[float, float, float, float] | None:
    container = _enclosing_container(from_box, to_box)
    return None if container is None else (container.abs_x, container.abs_y, container.width, container.height)


def link_label_anchor(path: list[tuple[float, float]]) -> tuple[float, float]:
    """Where a link's midpoint label sits: the point half-way along the drawn
    path *by arc length*. For a straight or a (symmetric) elbow path this is
    exactly the chord midpoint of the two endpoints it replaced, so those are
    unchanged; for a waypoint polyline it lands on the line actually drawn
    instead of on the straight chord (which can cut across the very obstacle
    the detour avoids). Shared by render.py, preview.py and the link-label
    overlap check so all three agree on the label's position."""
    seg_lengths = [math.dist(a, b) for a, b in zip(path, path[1:])]
    total = sum(seg_lengths)
    if total == 0:
        return path[0]
    half = total / 2
    covered = 0.0
    for (a, b), length in zip(zip(path, path[1:]), seg_lengths):
        if covered + length >= half:
            t = (half - covered) / length if length else 0.0
            return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
        covered += length
    return path[-1]


def link_render_plan(from_box: Box, to_box: Box, link: Link) -> tuple[int, int, str, list[tuple[float, float]]]:
    """Single source of truth for how a link will actually be drawn: which
    connection-point indices, the effective style (straight auto-upgrades
    to elbow when diagonal), and the resulting waypoints. render.py and
    link_crossing_warnings() both call this so the check can never drift
    from what's actually rendered."""
    root = from_box.root
    cache = None
    if root is not None and to_box.root is root:
        # Every check, the fit transform and the renderer ask for the same
        # links' plans against the same laid-out tree - compute each once.
        cache = _routing_index(root).setdefault("plans", {})
        key = (link.from_id, link.to_id, link.from_side, link.to_side, link.style, tuple(link.waypoints), link.lane, link.lanes)
        if key in cache:
            return cache[key]
        cache[key] = plan = _link_render_plan(from_box, to_box, link)
        return plan
    return _link_render_plan(from_box, to_box, link)


LOOP_CLEARANCE = 16  # how far a self-loop stands off its node
LANE_GAP = 18  # spacing between parallel links joining the same two elements: clears a one-line label


def _self_loop_path(box: Box, link: Link) -> tuple[int, int, list[tuple[float, float]]]:
    """A link from an element to itself (a Mermaid `B -->|retry| B`): out of
    one side and back into the adjacent one around their shared corner -
    right to top unless fromSide/toSide name two adjacent sides."""
    s_idx = _SIDE_TO_IDX.get(link.from_side or "right", 3)
    e_idx = _SIDE_TO_IDX.get(link.to_side or "top", 0)
    if _IDX_AXIS[s_idx] == _IDX_AXIS[e_idx]:  # same or opposite sides: no corner to go round
        s_idx, e_idx = 3, 0
    p1, p2 = connection_point(box, s_idx), connection_point(box, e_idx)

    def out(point, idx):
        dx, dy = {0: (0, -1), 1: (-1, 0), 2: (0, 1), 3: (1, 0)}[idx]
        return (point[0] + dx * LOOP_CLEARANCE, point[1] + dy * LOOP_CLEARANCE)

    o1, o2 = out(p1, s_idx), out(p2, e_idx)
    corner = (o1[0], o2[1]) if _IDX_AXIS[s_idx] == "horizontal" else (o2[0], o1[1])
    return s_idx, e_idx, [p1, o1, corner, o2, p2]


def _containment_path(inner: Box, outer: Box) -> tuple[int, list[tuple[float, float]]]:
    """A link between a container and something inside it: straight from the
    inner element's side nearest the container's frame to that frame, rather
    than a route to the container's far side through everything in it."""
    best = None
    for idx in range(4):
        cx, cy = connection_point(inner, idx)
        edge = {
            0: (cx, outer.abs_y),
            1: (outer.abs_x, cy),
            2: (cx, outer.abs_y + outer.height),
            3: (outer.abs_x + outer.width, cy),
        }[idx]
        distance = math.dist((cx, cy), edge)
        if best is None or distance < best[0]:
            best = (distance, idx, [(cx, cy), edge])
    return best[1], best[2]


def _is_inside(inner: Box, outer: Box) -> bool:
    root = inner.root
    if root is None or outer.root is not root or outer.element.kind != "container":
        return False
    parent_of = _routing_index(root)["parent_of"]
    cur = parent_of.get(inner.element.id)
    while cur is not None:
        if cur == outer.element.id:
            return True
        cur = parent_of.get(cur)
    return False


def _shift_lane(link: Link, s_idx: int, e_idx: int, p1, p2, from_box: Box, to_box: Box):
    """Move both ends of a parallel link sideways by its lane's offset (the
    same absolute direction whichever way the link runs), within each end's
    own icon."""
    offset = (link.lane - (link.lanes - 1) / 2) * LANE_GAP

    def shift(point, idx, box):
        if _IDX_AXIS[idx] == "vertical":  # leaves through top/bottom: slide along x
            limit = max(0.0, box.width / 2 - 4)
            return (point[0] + max(-limit, min(limit, offset)), point[1])
        limit = max(0.0, box.height / 2 - 4)
        return (point[0], point[1] + max(-limit, min(limit, offset)))

    return shift(p1, s_idx, from_box), shift(p2, e_idx, to_box)


def _link_render_plan(from_box: Box, to_box: Box, link: Link) -> tuple[int, int, str, list[tuple[float, float]]]:
    if not link.waypoints:
        if from_box is to_box:
            s_idx, e_idx, path = _self_loop_path(from_box, link)
            return s_idx, e_idx, "polyline", path
        if not (link.from_side or link.to_side):
            if _is_inside(from_box, to_box):
                idx, path = _containment_path(from_box, to_box)
                return idx, idx, "straight", path
            if _is_inside(to_box, from_box):
                idx, path = _containment_path(to_box, from_box)
                return idx, idx, "straight", path[::-1]
    s_idx, e_idx = choose_connection_indices(from_box, to_box, link)
    p1, p2 = connection_point(from_box, s_idx), connection_point(to_box, e_idx)
    if link.lanes > 1 and not link.waypoints:
        p1, p2 = _shift_lane(link, s_idx, e_idx, p1, p2, from_box, to_box)
    if link.waypoints:
        # Explicit polyline: straight segments through each via. Detection walks
        # path segments the same way it does for elbow, so no checker changes.
        path = [p1, *[(float(x), float(y)) for x, y in link.waypoints], p2]
        return s_idx, e_idx, "polyline", path
    if is_same_side(s_idx, e_idx):
        return s_idx, e_idx, "polyline", _same_side_path(p1, p2, s_idx)
    eff_style = effective_connector_style(link.style, p1, p2)
    path = connector_path(eff_style, p1, p2, s_idx, e_idx)
    return s_idx, e_idx, eff_style, path


class LinkCheckContext:
    """Everything the link checks need, computed once per laid-out tree:
    obstacles, container labels, and each link's rendered path and label
    box. Individual links can be re-planned in place (set_link), which is
    how doctor scores a candidate re-routing of one link without re-running
    every check over every link.

    Element obstacles: ancestors/descendants of either endpoint are
    excluded, since a link legitimately touches its own endpoint's
    containers on the way in. Container *label* obstacles use a lighter
    exclusion - only the exact endpoint ids - because crossing straight
    through an ancestor's visible label text still looks wrong.

    `margin` (canvas.overlapMargin, logical units) inflates every obstacle/
    label rect before testing, so a path or label that runs merely close to
    something - not literally through/over it - is flagged too.
    """

    def __init__(self, root_box: Box, links: list[Link], registry: MultiRegistry, margin: float = 0):
        self.links = list(links)
        self.margin = margin
        self.by_id, self.parent_of = _build_indices(root_box)
        self.obstacles = [
            (eid, _inflate_rect(_footprint_rect(b), margin)) for eid, b in self.by_id.items() if eid != "__root__"
        ]
        self.container_labels = [
            (eid, _inflate_rect(rect, margin))
            for eid, b in self.by_id.items()
            if eid != "__root__" and (rect := container_label_rect(b, registry)) is not None
        ]
        self._related: dict[str, set[str]] = {}
        self.paths: dict[int, list[tuple[float, float]] | None] = {}
        self.bboxes: dict[int, tuple[float, float, float, float]] = {}
        self.axis_ranges: dict[int, list] = {}
        self.label_rects: dict[int, tuple[float, float, float, float]] = {}
        self.own_rects: dict[int, list[tuple[float, float, float, float]]] = {}
        self.label_homes: dict[int, str] = {}  # link -> the container its label sticks out of
        for i, link in enumerate(self.links):
            self.set_link(i, link)

    def _related_to(self, element_id: str) -> set[str]:
        if element_id not in self._related:
            self._related[element_id] = _related_ids({"by_id": self.by_id, "parent_of": self.parent_of}, element_id)
        return self._related[element_id]

    def exclude(self, i: int) -> set[str]:
        link = self.links[i]
        return self._related_to(link.from_id) | self._related_to(link.to_id)

    def set_link(self, i: int, link: Link) -> None:
        """(Re)plan link `i` as `link` - its path, label box and the rects of
        its own endpoint nodes the path must not pass back through."""
        self.links[i] = link
        from_box, to_box = self.by_id.get(link.from_id), self.by_id.get(link.to_id)
        self.label_rects.pop(i, None)
        if from_box is None or to_box is None:
            self.paths[i] = None  # dangling refs are Fatal elsewhere; defensive only
            self.own_rects[i] = []
            return
        _, _, _, path = link_render_plan(from_box, to_box, link)
        self.paths[i] = path
        xs, ys = [p[0] for p in path], [p[1] for p in path]
        self.bboxes[i] = (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
        self.axis_ranges[i] = [_segment_axis_range(a, b) for a, b in zip(path, path[1:])]
        self.own_rects[i] = own_endpoint_rects(from_box, to_box)
        self.label_homes.pop(i, None)
        if link.label:
            bounds = _label_bounds(from_box, to_box)
            label = link_label_rect(path, link.label, link.label_font_size, self.own_rects[i], bounds)
            self.label_rects[i] = _inflate_rect(label, self.margin)
            if bounds is not None and not _contains_rect(bounds, label):
                self.label_homes[i] = _enclosing_container(from_box, to_box).element.id

    def crosses(self, i: int, rect: tuple[float, float, float, float]) -> bool:
        path = self.paths[i]
        if path is None:
            return False
        bx, by, bw, bh = self.bboxes[i]
        rx, ry, rw, rh = rect
        if bx > rx + rw or rx > bx + bw or by > ry + rh or ry > by + bh:
            return False
        return any(_segment_intersects_rect(p1, p2, rect) for p1, p2 in zip(path, path[1:]))

    def subject_messages(self, i: int) -> list[str]:
        """Every crossing warning about link `i` itself: its path through an
        element, a container label, another link's label or back through its
        own endpoint; its own label over an element or a container label."""
        path = self.paths[i]
        if path is None:
            return []
        link = self.links[i]
        name = f"link {link.from_id!r} -> {link.to_id!r}"
        exclude = self.exclude(i)
        endpoints_only = {link.from_id, link.to_id}
        messages = []
        for eid, rect in self.obstacles:
            if eid not in exclude and self.crosses(i, rect):
                messages.append(Finding(f"{name} passes through element {eid!r}", "link-crosses-element", [eid], [link]))
        for cid, rect in self.container_labels:
            if cid not in endpoints_only and self.crosses(i, rect):
                messages.append(Finding(
                    f"{name} passes through the label of container {cid!r}", "link-crosses-container-label", [cid], [link]
                ))
        for j, rect in self.label_rects.items():
            if j != i and self.crosses(i, rect):
                other = self.links[j]
                messages.append(Finding(
                    f"{name} passes through the label of link {other.from_id!r} -> {other.to_id!r}",
                    "link-crosses-link-label", [], [link, other],
                ))
        if any(self.crosses(i, rect) for rect in self.own_rects.get(i, [])):
            messages.append(Finding(
                f"{name} runs back through one of its own endpoints", "link-through-own-endpoint",
                [link.from_id, link.to_id], [link],
            ))
        own_label = self.label_rects.get(i)
        if i in self.label_homes:
            home = self.label_homes[i]
            messages.append(Finding(
                f"the label of {name} sticks out of container {home!r}, across its frame - shorten the label, "
                "give the container room, or move the link's ends",
                "link-label-outside-container", [home], [link],
            ))
        if own_label is not None and any(_rects_overlap(own_label, rect) for rect in self.own_rects.get(i, [])):
            # link_label_rect() found no spot clear of them (e.g. endpoints too close)
            messages.append(Finding(
                f"the label of {name} covers one of its own endpoints", "link-label-covers-endpoint",
                [link.from_id, link.to_id], [link],
            ))
        if own_label is not None:
            for eid, rect in self.obstacles:
                if eid not in exclude and _rects_overlap(own_label, rect):
                    messages.append(Finding(
                        f"the label of {name} overlaps element {eid!r}", "link-label-overlaps-element", [eid], [link]
                    ))
            for cid, rect in self.container_labels:
                if cid not in endpoints_only and _rects_overlap(own_label, rect):
                    messages.append(Finding(
                        f"the label of {name} overlaps the label of container {cid!r}",
                        "link-label-overlaps-container-label", [cid], [link],
                    ))
        return messages

    def label_pair_message(self, i: int, j: int) -> str | None:
        ri, rj = self.label_rects.get(i), self.label_rects.get(j)
        if ri is None or rj is None or not _rects_overlap(ri, rj):
            return None
        a, b = self.links[i], self.links[j]
        return Finding(
            f"the label of link {a.from_id!r} -> {a.to_id!r} overlaps the label of link {b.from_id!r} -> {b.to_id!r}",
            "link-labels-overlap", [], [a, b],
        )

    def crosses_label_of(self, i: int, j: int) -> bool:
        """Whether link i's path runs through link j's label (one of i's
        subject messages - kept separately for incremental rescoring)."""
        rect = self.label_rects.get(j)
        return i != j and rect is not None and self.crosses(i, rect)

    def aliasing_message(self, i: int, j: int) -> str | None:
        path_i, path_j = self.paths[i], self.paths[j]
        if path_i is None or path_j is None:
            return None
        a, b = self.links[i], self.links[j]

        def same_point(p: tuple[float, float], q: tuple[float, float]) -> bool:
            return abs(p[0] - q[0]) < 0.5 and abs(p[1] - q[1]) < 0.5

        # Two links leaving the same node from the same point (fan-out), or
        # arriving at the same point (fan-in), naturally share a trunk there -
        # that reads as a branch/merge, not as a false direct edge. Only a
        # trunk shared by one arriving and one departing link (or by
        # unrelated links) misleads.
        if (a.from_id == b.from_id and same_point(path_i[0], path_j[0])) or (
            a.to_id == b.to_id and same_point(path_i[-1], path_j[-1])
        ):
            return None
        (ax_, ay_, aw_, ah_), (bx_, by_, bw_, bh_) = self.bboxes[i], self.bboxes[j]
        if ax_ > bx_ + bw_ + 0.5 or bx_ > ax_ + aw_ + 0.5 or ay_ > by_ + bh_ + 0.5 or by_ > ay_ + ah_ + 0.5:
            return None
        overlap = next(
            (o for ra in self.axis_ranges[i] for rb in self.axis_ranges[j] if (o := _range_overlap(ra, rb))),
            None,
        )
        if overlap is None:
            return None
        (x0, y0), (x1, y1) = overlap
        return Finding(
            f"link {a.from_id!r} -> {a.to_id!r} and link {b.from_id!r} -> {b.to_id!r} share a collinear "
            f"segment near ({x0:.0f}, {y0:.0f})-({x1:.0f}, {y1:.0f}), which may appear as a direct connection",
            "link-aliasing", [], [a, b],
        )


def _range_overlap(a, b, epsilon: float = 0.5):
    """_collinear_overlap() on precomputed _segment_axis_range() values."""
    if a is None or b is None or a[0] != b[0]:
        return None
    axis, coord_a, (lo_a, hi_a) = a
    _, coord_b, (lo_b, hi_b) = b
    if abs(coord_a - coord_b) > epsilon:
        return None
    lo, hi = max(lo_a, lo_b), min(hi_a, hi_b)
    if lo > hi + epsilon:
        return None
    return ((lo, coord_a), (hi, coord_a)) if axis == "h" else ((coord_a, lo), (coord_a, hi))


def link_crossing_warnings(root_box: Box, links: list[Link], registry: MultiRegistry, margin: float = 0) -> list[str]:
    """Mechanically detect a link's rendered path - and its own label box -
    running through an unrelated element, a container's label text, another
    link's label, or back through one of its own endpoints, using the exact
    same connection-point/routing geometry python-pptx will render
    (link_render_plan() above). See LinkCheckContext for the exclusions.

    Path-crossing is exact for `style: straight` and `elbow`. `curved` is
    approximated as a straight chord between the endpoints, since its real
    bezier bow isn't modeled - documented in docs-site/limitations.md.
    """
    ctx = LinkCheckContext(root_box, links, registry, margin)
    messages: list[str] = []
    for i in range(len(links)):
        messages.extend(ctx.subject_messages(i))
    for i in range(len(links)):
        for j in range(i + 1, len(links)):
            if (message := ctx.label_pair_message(i, j)) is not None:
                messages.append(message)
    return messages


def _segment_axis_range(
    p1: tuple[float, float], p2: tuple[float, float], epsilon: float = 0.5
) -> tuple[str, float, tuple[float, float]] | None:
    """('h', y, (x_lo, x_hi)) or ('v', x, (y_lo, y_hi)) for an axis-aligned
    segment; None for a diagonal one (straight links that stayed diagonal,
    e.g. an explicit `style: straight` override, never alias this way)."""
    if abs(p1[1] - p2[1]) < epsilon:
        return ("h", (p1[1] + p2[1]) / 2, (min(p1[0], p2[0]), max(p1[0], p2[0])))
    if abs(p1[0] - p2[0]) < epsilon:
        return ("v", (p1[0] + p2[0]) / 2, (min(p1[1], p2[1]), max(p1[1], p2[1])))
    return None


def _collinear_overlap(
    seg_a: tuple[tuple[float, float], tuple[float, float]],
    seg_b: tuple[tuple[float, float], tuple[float, float]],
    epsilon: float = 0.5,
) -> tuple[tuple[float, float], tuple[float, float]] | None:
    """The shared sub-segment of two axis-aligned segments that sit on the
    same line, or None if they're on different lines or don't touch at all.
    A single shared point (ranges that only touch at an endpoint) counts -
    that's exactly the case where two Z-routes meet nose-to-tail and read
    as one continuous line."""
    a, b = _segment_axis_range(*seg_a, epsilon), _segment_axis_range(*seg_b, epsilon)
    if a is None or b is None or a[0] != b[0]:
        return None
    axis, coord_a, (lo_a, hi_a) = a
    _, coord_b, (lo_b, hi_b) = b
    if abs(coord_a - coord_b) > epsilon:
        return None
    lo, hi = max(lo_a, lo_b), min(hi_a, hi_b)
    if lo > hi + epsilon:
        return None
    return ((lo, coord_a), (hi, coord_a)) if axis == "h" else ((coord_a, lo), (coord_a, hi))


def link_aliasing_warnings(root_box: Box, links: list[Link]) -> list[str]:
    """Two distinct links can each independently pick a routing that, put
    together, reads as one uninterrupted straight line - typically when
    both attach to the exact same connection point of a node they share
    (one arrives there, the other departs from it) and `choose_connection_
    indices()` happens to pick the same edge for both, per the "Z-route
    false edge aliasing" bug report. Detected by checking every segment of
    one link's rendered path against every segment of another's for a
    collinear, touching-or-overlapping run - not a crossing (perpendicular
    hit), but the same-line continuation that makes two separate arrows
    look like a single direct edge. Warning only; routing is unchanged."""
    ctx = LinkCheckContext(root_box, links, MultiRegistry(), 0)
    messages: list[str] = []
    for i in range(len(links)):
        for j in range(i + 1, len(links)):
            if (message := ctx.aliasing_message(i, j)) is not None:
                messages.append(message)
    return messages


def icon_resolution_warnings(root_box: Box, registry: MultiRegistry) -> list[str]:
    """sec9: an unresolved `type`, or a resolved entry whose file is
    missing on disk, is a Warning (placeholder icon), not Fatal. Pure
    lookup/`Path.exists()` - safe to run without rendering, so `validate`
    catches the same issues `build` would (render.py no longer emits this
    warning itself, to avoid a duplicate when build calls both)."""
    messages: list[str] = []
    for box in iter_boxes(root_box):
        element = box.element
        if element.id == "__root__" or is_shape_node(element):
            continue
        if element.kind == "container":
            if registry.resolve_group(element.type, element.provider) is None:
                messages.append(Finding(
                    f"unknown container type {element.type!r} for container {element.id!r}; drawn as a plain frame"
                    + registry.suggest_type(element.type, element.provider, kind="container"),
                    "unknown-container-type", [element.id],
                ))
            continue
        icon_entry = registry.resolve_icon(element.type, element.provider)
        if icon_entry is None:
            messages.append(Finding(
                f"unknown type {element.type!r} for node {element.id!r} (provider {element.provider!r}); "
                "using placeholder icon" + registry.suggest_type(element.type, element.provider),
                "unknown-type", [element.id],
            ))
        elif not icon_entry.file.exists():
            messages.append(Finding(
                f"icon file missing for type {element.type!r} ({icon_entry.file}); using placeholder icon",
                "icon-file-missing", [element.id],
            ))
        elif (problem := icon_png(icon_entry.file)[1]) is not None:
            messages.append(Finding(
                f"icon file for type {element.type!r} ({icon_entry.file}) {problem}; using placeholder icon",
                "icon-file-unreadable", [element.id],
            ))
    return messages


FIT_WARNING_SCALE = 0.7  # below this, a shrink-to-fit is reported: text gets hard to read


@dataclass
class FitTransform:
    """Uniform scale + offset from layout (logical) coordinates to the slide.
    Identity unless canvas.fit shrinks a diagram that doesn't fit. Applied by
    the renderers only - layout, the checks, doctor and the YAML all stay in
    the author's logical coordinates."""

    scale: float = 1.0
    dx: float = 0.0
    dy: float = 0.0

    @property
    def is_identity(self) -> bool:
        return self.scale == 1.0 and self.dx == 0.0 and self.dy == 0.0

    def x(self, value: float) -> float:
        return value * self.scale + self.dx

    def y(self, value: float) -> float:
        return value * self.scale + self.dy

    def length(self, value: float) -> float:
        return value * self.scale


def _drawn_rects(root_box: Box, links: list[Link]):
    """(what, rect) for everything that gets drawn: element boxes (a node with
    its label), link paths (as their bounding boxes) and link labels."""
    by_id = {}
    for box in iter_boxes(root_box):
        if box.element.id == "__root__":
            continue
        by_id[box.element.id] = box
        rect = _footprint_rect(box) if box.element.kind == "node" else (box.abs_x, box.abs_y, box.width, box.height)
        yield f"element {box.element.id!r}", rect, ([box.element.id], [])
    for link in links:
        from_box, to_box = by_id.get(link.from_id), by_id.get(link.to_id)
        if from_box is None or to_box is None:
            continue
        _, _, _, path = link_render_plan(from_box, to_box, link)
        xs, ys = [p[0] for p in path], [p[1] for p in path]
        yield f"link {link.from_id!r} -> {link.to_id!r}", (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)), ([], [link])
        if link.label:
            yield (
                f"the label of link {link.from_id!r} -> {link.to_id!r}",
                link_label_rect_for(from_box, to_box, path, link),
                ([], [link]),
            )


def fit_transform(diagram: Diagram, root_box: Box) -> FitTransform:
    """canvas.fit: "shrink" (default) scales a diagram that spills off the
    slide down uniformly - text included - and centres it within the canvas
    padding; one that already fits is left exactly as laid out. A standard
    two-AZ, three-tier layout is taller than 720 at the default spacing, and
    the only alternative used to be hand-tuning every padding/gap."""
    if diagram.canvas.fit == "none":
        return FitTransform()
    canvas_w, canvas_h = diagram.canvas.size
    rects = [r for _, r, _ in _drawn_rects(root_box, diagram.links)]
    if not rects:
        return FitTransform()
    min_x = min(r[0] for r in rects)
    min_y = min(r[1] for r in rects)
    max_x = max(r[0] + r[2] for r in rects)
    max_y = max(r[1] + r[3] for r in rects)
    eps = 0.5
    if min_x >= -eps and min_y >= -eps and max_x <= canvas_w + eps and max_y <= canvas_h + eps:
        return FitTransform()
    padding = diagram.canvas.padding
    avail_w, avail_h = max(1.0, canvas_w - 2 * padding), max(1.0, canvas_h - 2 * padding)
    width, height = max(1.0, max_x - min_x), max(1.0, max_y - min_y)
    scale = min(1.0, avail_w / width, avail_h / height)
    dx = padding + (avail_w - width * scale) / 2 - min_x * scale
    dy = padding + (avail_h - height * scale) / 2 - min_y * scale
    return FitTransform(scale, dx, dy)


def canvas_warnings(diagram: Diagram, root_box: Box) -> list[str]:
    """What doesn't fit the slide: with canvas.fit "none", everything drawn
    outside it (an element, a node's label, a link's path or label); with the
    default "shrink", nothing is outside, but a shrink below
    FIT_WARNING_SCALE is reported, since the text shrinks with it."""
    transform = fit_transform(diagram, root_box)
    canvas_w, canvas_h = diagram.canvas.size
    if not transform.is_identity:
        if transform.scale < FIT_WARNING_SCALE:
            # One mistyped coordinate (x: 12000 for 1200) shrinks everything
            # else to a speck - name it rather than blame the element count.
            stray_boxes = [
                box for box in iter_boxes(root_box)
                if box.element.id != "__root__"
                and box.element.has_explicit_position
                and not _within(_footprint_rect(box), canvas_w, canvas_h)
            ]
            stray = [f"{box.element.id!r} (x={box.abs_x:.0f}, y={box.abs_y:.0f})" for box in stray_boxes]
            if stray:
                hint = (
                    f"explicitly positioned outside the canvas: {', '.join(stray)} - check "
                    f"{'that coordinate' if len(stray) == 1 else 'those coordinates'}"
                )
            else:
                wider = ", or aspectRatio 16:9" if diagram.canvas.aspect_ratio != "16:9" else ""
                hint = f"consider fewer elements per slide or a smaller layout gap/padding{wider}"
            return [Finding(
                f"the diagram was scaled to {transform.scale:.0%} to fit the slide, so its text is that much "
                f"smaller - {hint}",
                "canvas-shrunk", [box.element.id for box in stray_boxes],
            )]
        return []
    messages = []
    parent_of = _routing_index(root_box)["parent_of"]
    reported: set[str] = set()
    for what, (x, y, w, h), (elements, links) in _drawn_rects(root_box, diagram.links):
        if _within((x, y, w, h), canvas_w, canvas_h):
            continue
        if elements:
            # One report for a whole container that's off the slide, not one
            # per element inside it.
            ancestor = parent_of.get(elements[0])
            while ancestor is not None and ancestor not in reported:
                ancestor = parent_of.get(ancestor)
            if ancestor is not None:
                continue
            reported.add(elements[0])
        messages.append(Finding(
            f"{what} is positioned outside the canvas bounds (x={x:.0f}, y={y:.0f}, w={w:.0f}, h={h:.0f})",
            "off-canvas", elements, links,
        ))
    return messages


def _within(rect: tuple[float, float, float, float], canvas_w: float, canvas_h: float) -> bool:
    x, y, w, h = rect
    return x >= -0.5 and y >= -0.5 and x + w <= canvas_w + 0.5 and y + h <= canvas_h + 0.5


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


def containment_warnings(root_box: Box) -> list[str]:
    """A child drawn (partly) outside its own container: an explicit x/y
    beyond the container's explicit width/height, or a negative x/y. The
    overlap check compares siblings only, so this is the one place a child
    spilling across its parent's frame - and possibly over the next
    container - is caught."""
    messages: list[str] = []
    for box in iter_boxes(root_box):
        if box.element.kind != "container" or box.element.id == "__root__":
            continue
        left, top = box.abs_x - 0.5, box.abs_y - 0.5
        right, bottom = box.abs_x + box.width + 0.5, box.abs_y + box.height + 0.5
        for child in box.children:
            x, y, w, h = _footprint_rect(child)
            if x < left or y < top or x + w > right or y + h > bottom:
                messages.append(Finding(
                    f"element {child.element.id!r} extends outside its container {box.element.id!r}",
                    "outside-container", [child.element.id, box.element.id],
                ))
    return messages


def diagram_warnings(diagram: Diagram, root_box: Box, registry: MultiRegistry) -> list[str]:
    """Every Warning-class check `validate`/`build` run (yaml-spec sec9), in
    the order they're reported."""
    margin = diagram.canvas.overlap_margin
    return (
        icon_resolution_warnings(root_box, registry)
        + canvas_warnings(diagram, root_box)
        + overlap_warnings(root_box, registry, margin)
        + containment_warnings(root_box)
        + link_crossing_warnings(root_box, diagram.links, registry, margin)
        + link_aliasing_warnings(root_box, diagram.links)
    )
