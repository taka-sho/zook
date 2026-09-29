"""Overlap-resolution engine behind `zook doctor`.

`validate`/`build` only *detect* overlaps and link collisions
(docs-site/limitations.md): the author is told two elements overlap and left
to fix the pixels by hand. That hand-fixing is exactly what zook's primary
user - a generative AI - is worst at. `doctor` closes that gap: it takes the
same computed geometry the checks run on and actually resolves what it can,
emitting the changes (or writing them straight back into the YAML with
`--fix`/`-o`).

Everything is judged by one objective: the *weighted* sum of the Warnings
`validate` would report that doctor can influence (`_WEIGHTS`) - an element
overlap or a link running back through its own endpoint weighs more than a
link merely crossing a container's frame, so trading one serious problem for
several cosmetic ones (or the reverse) is decided on how bad they look, not
on their count. Off-canvas / shrink-to-fit Warnings are part of the objective
too, so a fix that pushes things off the slide is a worse diagram, not a
better one. Every change is applied, re-measured, and kept only if the
objective strictly drops - otherwise rolled back exactly - so doctor never
makes a diagram worse.

Four stages, in order (each depends on the earlier ones being settled - link
routing follows from positions, displacing an obstacle follows from the
routing that's left, and a waypoint detour is the last resort); the whole
sequence repeats while a round still improves, so running doctor again on its
own output finds nothing more to do:

  1. Element overlaps - sibling-vs-sibling and element-vs-container-label
     collisions, and a child spilling outside its container - separated by
     moving elements (details below).
  2. Link routing - a link's path (or label) running through an element or a
     label, back through its own endpoint, or reading as one line with
     another link (false-edge aliasing). A link has no coordinates of its
     own; its path is derived from its endpoints (now fixed) and its
     connection sides, so the lever is which edge each end attaches to
     (including same-side U routes). A greedy search assigns `fromSide`/
     `toSide`; candidates are scored incrementally (only the warnings that
     involve the re-routed link are recomputed) and the best one is verified
     against the full checks before it's kept.
  3. Obstacle displacement - a link that runs straight through an unrelated
     auto-placed element that no connection side routes around: the element
     is slid perpendicular to the crossing segment until clear, staying
     inside its container. Each move is re-checked through stages 1-2.
  4. Waypoint detour - a crossing that survives stages 2 and 3 (typically an
     author-pinned obstacle): orthogonal `waypoints` route the link around
     the obstacle's bounding box. Only links the author didn't route
     themselves are candidates.

Still out of scope, reported under `remaining` but not auto-fixed:
placeholder-icon (unknown-`type`) warnings, and whatever no stage could clear.

How the element stage resolves, so the written YAML renders exactly what was
solved:

  1. Find every overlapping sibling pair / child-vs-label collision / child
     outside its container, using the identical geometry the checks use.
  2. Pin every direct child of each *broken* parent at its current auto-layout
     position (explicit x/y). Once a broken container's children are all
     explicit there's no auto re-packing left to fight, so later nudges
     compose predictably. Containers with no overlap stay fully auto-placed.
  3. Separate one colliding pair per pass by moving the movable element the
     shortest distance - right, down, left or up - that clears it while
     keeping it inside its container (and on the slide, at the top level),
     re-laying out between passes so cascades are picked up.

The movable element of a pair is chosen to preserve author intent: an
element the author positioned explicitly outranks an auto-placed one (the
auto one moves); between two author-positioned elements, the later-declared
one moves (it is still the author's diagram that overlaps - but only if that
makes the objective strictly better).
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field, replace

from .drawio import _find_element_node
from .loader import yaml_number
from .layout import (
    Box,
    LinkCheckContext,
    build_layout,
    canvas_warnings,
    containment_warnings,
    container_label_rect,
    icon_resolution_warnings,
    iter_boxes,
    link_render_plan,
    overlap_warnings,
    _build_indices,
    _footprint_rect,
    _inflate_rect,
    _rects_overlap,
    _segment_intersects_rect,
)
from .model import parse_diagram
from .registry import MultiRegistry

# Extra clearance, beyond canvas.overlapMargin, that a separated pair is left
# with. The overlap check flags a pair whose gap is below `margin`, so a final
# gap of exactly `margin + _CLEARANCE` clears it with room to spare.
_CLEARANCE = 8.0

# Safety bound on the separation loop. Diagrams are one-slide-sized (AGENTS.md:
# "1 YAML = 1 slide"), so real inputs converge in far fewer passes; this only
# stops a pathological cascade from spinning forever.
_MAX_PASSES = 200

# Safety bound on the obstacle/detour loops. Each accepted pass strictly
# lowers the objective, so this only guards against a pathological input.
_MAX_OBSTACLE_PASSES = 40

# How many of the least-disruptive stage-3/4 candidates are tried per pass:
# each costs a full re-layout (and, for stage 3, re-running stages 1-2).
_MAX_CANDIDATES = 8

# Whole-pipeline rounds; each must strictly improve on the last.
_MAX_ROUNDS = 4

Rect = tuple[float, float, float, float]

_SIDES = ("top", "bottom", "left", "right")
_SIDE_AXIS = {"top": "v", "bottom": "v", "left": "h", "right": "h"}


def _candidate_sides() -> list[tuple[str | None, str | None]]:
    """Every connection-side assignment `validate` accepts: both edges set on a
    matching axis (top/bottom together, or left/right together - including the
    same side twice, a U route), plus single-sided assignments that fix one
    edge and let the other auto-pick."""
    combos: list[tuple[str | None, str | None]] = [
        (fs, ts) for fs in _SIDES for ts in _SIDES if _SIDE_AXIS[fs] == _SIDE_AXIS[ts]
    ]
    for side in _SIDES:
        combos.append((side, None))
        combos.append((None, side))
    return combos


@dataclass
class Move:
    """One element repositioned to resolve an overlap."""

    id: str
    x: float
    y: float


@dataclass
class LinkChange:
    """One link re-routed to resolve a crossing/aliasing: connection sides
    reassigned (stage 2) and/or detour waypoints inserted (stage 4)."""

    from_id: str
    to_id: str
    from_side: str | None
    to_side: str | None
    waypoints: list[tuple[float, float]] | None = None


@dataclass
class DoctorResult:
    status: str  # "ok" (nothing to fix) | "fixed" | "partial" (residual remains)
    moves: list[Move] = field(default_factory=list)
    link_changes: list[LinkChange] = field(default_factory=list)
    resolved_overlaps: list[str] = field(default_factory=list)
    remaining: list[str] = field(default_factory=list)
    # Auto-placed elements that got an explicit x/y at the spot they already
    # occupied (so their container stops re-packing around a moved sibling):
    # the file changes for them even though nothing visibly moves.
    pinned: list[Move] = field(default_factory=list)


# --- the objective ---

# Weight of each kind of Warning doctor can influence. Anything not listed
# weighs 1. Crossing a *node* is worse than crossing a container's frame (a
# link routinely enters containers); running back through its own endpoint
# or two elements overlapping are the worst.
_WEIGHTS = [
    (re.compile(r"^element '.*' overlaps element "), 4),
    (re.compile(r"^element '.*' extends outside its container "), 4),
    (re.compile(r"^element '.*' overlaps the label of container "), 3),
    (re.compile(r" runs back through one of its own endpoints$"), 5),
    (re.compile(r"^the label of link .* covers one of its own endpoints$"), 3),
    (re.compile(r"^link .* passes through element '(?P<id>.*)'$"), None),  # 3 for a node, 1 for a container
    (re.compile(r"^the label of link .* overlaps element '(?P<id>.*)'$"), None),
    (re.compile(r"passes through the label of (container|link) "), 2),
    (re.compile(r"overlaps the label of (container|link) "), 2),
    (re.compile(r"share a collinear segment"), 2),
    (re.compile(r"is positioned outside the canvas bounds"), 3),
    (re.compile(r"^the diagram was scaled to "), 3),
]


def _weight(message: str, containers: set[str]) -> int:
    for pattern, weight in _WEIGHTS:
        m = pattern.search(message)
        if m is None:
            continue
        if weight is None:
            return 1 if m.group("id") in containers else 3
        return weight
    return 1


def _containers(root: Box) -> set[str]:
    return {b.element.id for b in iter_boxes(root) if b.element.kind == "container"}


@dataclass
class _Assessment:
    attempted: list[str]  # what doctor tries to fix
    canvas: list[str]  # off-canvas / shrink: part of the objective, reported, not "attempted"
    score: float


def _assess(raw: dict, registry: MultiRegistry) -> _Assessment:
    diagram = parse_diagram(raw)
    margin = diagram.canvas.overlap_margin
    root = build_layout(diagram, registry)
    ctx = LinkCheckContext(root, diagram.links, registry, margin)
    attempted = (
        overlap_warnings(root, registry, margin)
        + containment_warnings(root)
        + _all_link_messages(ctx)
    )
    canvas = canvas_warnings(diagram, root)
    containers = _containers(root)
    score = sum(_weight(m, containers) for m in attempted + canvas)
    return _Assessment(attempted, canvas, score)


def _score(raw: dict, registry: MultiRegistry) -> float:
    return _assess(raw, registry).score


def _all_link_messages(ctx: LinkCheckContext) -> list[str]:
    n = len(ctx.links)
    messages = [m for i in range(n) for m in ctx.subject_messages(i)]
    for i in range(n):
        for j in range(i + 1, n):
            for message in (ctx.label_pair_message(i, j), ctx.aliasing_message(i, j)):
                if message is not None:
                    messages.append(message)
    return messages


def _restore(raw: dict, snapshot: dict) -> None:
    raw.clear()
    raw.update(snapshot)  # exact rollback, comments intact (ruamel deepcopy)


_num = yaml_number

# --- overlap discovery (structured; mirrors layout's overlap/containment geometry) ---

# ("pair", parent_box, a_box, b_box) | ("label", parent_box, child_box, label_rect)
# | ("outside", parent_box, child_box, None)
_Overlap = tuple


def _find_overlaps(root_box: Box, registry: MultiRegistry, margin: float) -> list[_Overlap]:
    """Every sibling-pair and child-vs-container-label overlap, and every
    child outside its container, detected with the exact predicates the
    checks use so that clearing them here is guaranteed to satisfy them."""
    found: list[_Overlap] = []

    def walk(box: Box) -> None:
        children = box.children
        for i in range(len(children)):
            for j in range(i + 1, len(children)):
                a, b = children[i], children[j]
                if _rects_overlap(_inflate_rect(_footprint_rect(a), margin), _footprint_rect(b)):
                    found.append(("pair", box, a, b))
        label_rect = container_label_rect(box, registry)
        if label_rect is not None:
            for child in children:
                if _rects_overlap(_inflate_rect(label_rect, margin), _footprint_rect(child)):
                    found.append(("label", box, child, label_rect))
        if box.element.kind == "container" and box.element.id != "__root__":
            for child in children:
                if not _inside(_footprint_rect(child), (box.abs_x, box.abs_y, box.width, box.height)):
                    found.append(("outside", box, child, None))
        for child in children:
            walk(child)

    walk(root_box)
    return found


def _inside(rect: Rect, bounds: Rect, tolerance: float = 0.5) -> bool:
    x, y, w, h = rect
    bx, by, bw, bh = bounds
    return x >= bx - tolerance and y >= by - tolerance and x + w <= bx + bw + tolerance and y + h <= by + bh + tolerance


# --- geometry helpers ---


def _allowed_bounds(parent: Box, canvas: tuple[float, float]) -> Rect | None:
    """Where a child of `parent` may sit (absolute): inside the parent - the
    whole of it if its size is explicit; if it's auto-sized, anywhere right
    of / below its origin (it grows to fit) - or on the slide at top level."""
    if parent.element.id == "__root__":
        return (0.0, 0.0, canvas[0], canvas[1])
    if parent.element.width is not None and parent.element.height is not None:
        return (parent.abs_x, parent.abs_y, parent.width, parent.height)
    return (parent.abs_x, parent.abs_y, float("inf"), float("inf"))


def _shift_options(m_rect: Rect, a_rect: Rect, sep: float) -> list[tuple[float, float]]:
    """The four translations (right, down, left, up) that clear `m_rect` off
    `a_rect`, shortest first; ties keep that order."""
    mx, my, mw, mh = m_rect
    ax, ay, aw, ah = a_rect
    options = [
        ((ax + aw) - mx + sep, 0.0),
        (0.0, (ay + ah) - my + sep),
        (ax - (mx + mw) - sep, 0.0),
        (0.0, ay - (my + mh) - sep),
    ]
    return sorted(options, key=lambda d: abs(d[0]) + abs(d[1]))


def _best_shift(options: list[tuple[float, float]], rect: Rect, bounds: Rect | None) -> tuple[float, float]:
    """The shortest option that keeps `rect` inside `bounds`; failing that,
    the shortest one (the objective then decides whether it's kept)."""
    if bounds is not None:
        for dx, dy in options:
            x, y, w, h = rect
            if _inside((x + dx, y + dy, w, h), bounds):
                return dx, dy
    return options[0]


def _separate_from_label(c_rect: Rect, label_rect: Rect, sep: float) -> tuple[float, float]:
    """Push a child clear of its container's own label strip: down when the
    label sits above the child (the top-left default), up when it sits below."""
    cx, cy, cw, ch = c_rect
    lx, ly, lw, lh = label_rect
    if (ly + lh / 2) <= (cy + ch / 2):  # label above the child -> push child down
        return 0.0, (ly + lh) - cy + sep
    return 0.0, -((cy + ch) - ly + sep)


def _pull_inside(rect: Rect, bounds: Rect) -> tuple[float, float]:
    """Translation that brings `rect` back inside `bounds` (as far as it fits)."""
    x, y, w, h = rect
    bx, by, bw, bh = bounds
    dx = max(bx - x, 0.0) if x < bx else min((bx + bw) - (x + w), 0.0)
    dy = max(by - y, 0.0) if y < by else min((by + bh) - (y + h), 0.0)
    return dx, dy


# --- raw (ruamel) tree helpers ---


def _iter_raw_nodes(elements: list):
    for node in elements:
        yield node
        yield from _iter_raw_nodes(node.get("children", []))


def _explicit_ids(raw: dict) -> set[str]:
    return {
        n["id"]
        for n in _iter_raw_nodes(raw.get("elements", []))
        if n.get("x") is not None and n.get("y") is not None
    }


def _doc_order(raw: dict) -> dict[str, int]:
    return {n["id"]: i for i, n in enumerate(_iter_raw_nodes(raw.get("elements", [])))}


def _pin_children(raw: dict, parent_box: Box) -> None:
    """Give every direct child of `parent_box` an explicit x/y equal to its
    current auto-layout position, so the container stops auto-repacking and
    later nudges compose predictably. Already-explicit children are left as-is."""
    for child in parent_box.children:
        node = _find_element_node(raw["elements"], child.element.id)
        if node is None:
            continue
        if node.get("x") is None or node.get("y") is None:
            node["x"] = _num(child.local_x)
            node["y"] = _num(child.local_y)


def _pick_movable(a: Box, b: Box, explicit: set[str], order: dict[str, int]) -> tuple[Box, Box]:
    """(movable, anchor). An author-positioned element outranks an auto-placed
    one; between equals, the later-declared element moves."""
    a_exp, b_exp = a.element.id in explicit, b.element.id in explicit
    if a_exp != b_exp:
        return (b, a) if a_exp else (a, b)
    if order.get(a.element.id, 0) >= order.get(b.element.id, 0):
        return a, b
    return b, a


# --- stage 1: separate overlapping elements ---


def _resolve_element_overlaps(raw: dict, registry: MultiRegistry, author_explicit: set[str]) -> None:
    """Separate every sibling / child-vs-label overlap and bring every child
    that spills outside its container back in, by moving elements, in place.
    Pins the children of each broken parent first (so there's no auto
    re-packing to fight), then moves one element per pass. Kept only if the
    objective strictly improves; otherwise `raw` is restored exactly.

    Idempotent on already-clean input, so it's safe to re-run after a stage-3
    obstacle move perturbs positions."""
    before = _score(raw, registry)
    snapshot = copy.deepcopy(raw)

    diagram = parse_diagram(raw)
    margin = diagram.canvas.overlap_margin
    canvas = diagram.canvas.size
    sep = margin + _CLEARANCE
    root = build_layout(diagram, registry)
    order = _doc_order(raw)

    overlaps = _find_overlaps(root, registry, margin)
    if not overlaps:
        return
    pinned_parents: set[str] = set()
    for _kind, parent, *_rest in overlaps:
        if parent.element.id not in pinned_parents:
            _pin_children(raw, parent)
            pinned_parents.add(parent.element.id)

    for _ in range(_MAX_PASSES):
        diagram = parse_diagram(raw)
        root = build_layout(diagram, registry)
        overlaps = _find_overlaps(root, registry, margin)
        if not overlaps:
            break

        # A nudge can grow a container until it collides at a higher level,
        # breaking a parent we hadn't pinned yet. Pin those first, then re-lay
        # out before moving anything, so we never nudge against a still-auto
        # container.
        unpinned = [ov for ov in overlaps if ov[1].element.id not in pinned_parents]
        if unpinned:
            for _k, parent, *_r in unpinned:
                if parent.element.id not in pinned_parents:
                    _pin_children(raw, parent)
                    pinned_parents.add(parent.element.id)
            continue

        kind, parent = overlaps[0][0], overlaps[0][1]
        bounds = _allowed_bounds(parent, canvas)
        if kind == "pair":
            _, _parent, a, b = overlaps[0]
            movable, anchor = _pick_movable(a, b, author_explicit, order)
            rect = _footprint_rect(movable)
            dx, dy = _best_shift(_shift_options(rect, _footprint_rect(anchor), sep), rect, bounds)
        elif kind == "label":
            _, _parent, movable, label_rect = overlaps[0]
            dx, dy = _separate_from_label(_footprint_rect(movable), label_rect, sep)
        else:  # "outside"
            _, _parent, movable, _ = overlaps[0]
            dx, dy = _pull_inside(_footprint_rect(movable), (parent.abs_x, parent.abs_y, parent.width, parent.height))
            if dx == 0 and dy == 0:
                break  # doesn't fit inside at all - leave it to the author

        node = _find_element_node(raw["elements"], movable.element.id)
        node["x"] = _num(movable.local_x + dx)
        node["y"] = _num(movable.local_y + dy)

    if _score(raw, registry) >= before:
        _restore(raw, snapshot)


# --- stage 2: link routing - assign connection sides to clear crossings/aliasing ---


def _link_contribution(ctx: LinkCheckContext, i: int, containers: set[str]) -> float:
    """Weighted sum of every link Warning that involves link `i`: its own
    (path/label) messages, other links running through its label, and the
    label-overlap / aliasing pairs it's part of. Re-routing link i changes
    exactly these, so the difference between two routings of i is the
    difference of this sum."""
    total = sum(_weight(m, containers) for m in ctx.subject_messages(i))
    for j in range(len(ctx.links)):
        if j == i:
            continue
        if ctx.crosses_label_of(j, i):
            total += _weight("passes through the label of link ", containers)
        a, b = (i, j) if i < j else (j, i)
        for message in (ctx.label_pair_message(a, b), ctx.aliasing_message(a, b)):
            if message is not None:
                total += _weight(message, containers)
    return total


def _resolve_link_routing(raw: dict, registry: MultiRegistry) -> list[LinkChange]:
    """Greedily assign fromSide/toSide to links to lower the weighted link
    Warnings. Positions are fixed by now and connection sides don't affect
    layout, so candidates are scored against a single layout, incrementally
    (_link_contribution); the chosen change is then verified against the full
    objective and kept only if it strictly improves.

    Only fully-auto links (no side and no waypoints set by the author) are
    candidates, so an author's deliberate routing is never overridden."""
    diagram = parse_diagram(raw)
    links = diagram.links
    if not links:
        return []
    margin = diagram.canvas.overlap_margin
    root = build_layout(diagram, registry)
    containers = _containers(root)
    ctx = LinkCheckContext(root, links, registry, margin)

    auto = [i for i, link in enumerate(links) if link.from_side is None and link.to_side is None and not link.waypoints]
    if not auto:
        return []

    changes: dict[int, LinkChange] = {}
    for _ in range(len(links) * 4 + 8):  # safety bound; strict improvement already guarantees progress
        best: tuple[float, int, str | None, str | None] | None = None  # (delta, idx, from_side, to_side)
        for i in auto:
            current = ctx.links[i]
            base = _link_contribution(ctx, i, containers)
            if base == 0:
                continue
            for from_side, to_side in _candidate_sides():
                if (from_side, to_side) == (current.from_side, current.to_side):
                    continue
                ctx.set_link(i, replace(current, from_side=from_side, to_side=to_side))
                delta = _link_contribution(ctx, i, containers) - base
                if best is None or delta < best[0]:
                    best = (delta, i, from_side, to_side)
            ctx.set_link(i, current)
        if best is None or best[0] >= 0:
            break  # no strictly-better assignment exists

        _delta, i, from_side, to_side = best
        before = _score(raw, registry)
        node = raw["links"][i]
        saved = (node.get("fromSide"), node.get("toSide"))
        _write_sides(node, from_side, to_side)
        if _score(raw, registry) >= before:  # the full checks disagree - don't trust it
            _write_sides(node, *saved)
            break
        ctx.set_link(i, replace(ctx.links[i], from_side=from_side, to_side=to_side))
        changes[i] = LinkChange(links[i].from_id, links[i].to_id, from_side, to_side)

    return list(changes.values())


def _write_sides(node: dict, from_side: str | None, to_side: str | None) -> None:
    for key, value in (("fromSide", from_side), ("toSide", to_side)):
        if value is not None:
            node[key] = value
        else:
            node.pop(key, None)


# --- warnings doctor reports but never attempts to fix ---


def _unfixable_warnings(root_box: Box, diagram, registry: MultiRegistry) -> list[str]:
    return icon_resolution_warnings(root_box, registry)


# --- stage 3: displace an element that a link routes straight through ---


def _endpoint_exclusion(by_id: dict, parent_of: dict, link) -> set[str]:
    """Element ids a link is allowed to touch: its own two endpoints plus their
    ancestors (it legitimately passes through its containers) and descendants.
    A crossing of anything else is a real 'passes through element' warning."""

    def ancestors(eid: str) -> set[str]:
        result: set[str] = set()
        cur = parent_of.get(eid)
        while cur is not None:
            result.add(cur)
            cur = parent_of.get(cur)
        return result

    def descendants(eid: str) -> set[str]:
        box = by_id.get(eid)
        return {b.element.id for b in iter_boxes(box)} if box else set()

    return (
        {link.from_id, link.to_id}
        | ancestors(link.from_id)
        | ancestors(link.to_id)
        | descendants(link.from_id)
        | descendants(link.to_id)
    )


def _obstacles_crossed_by_link(root_box: Box, links, margin: float) -> dict[int, list[tuple[Box, tuple, tuple]]]:
    """Per-link map: link index -> [(obstacle box, seg start, seg end)] for
    every unrelated element its rendered path runs through (the first segment
    that hits it). Same geometry/exclusion as link_crossing_warnings."""
    by_id, parent_of = _build_indices(root_box)
    result: dict[int, list[tuple[Box, tuple, tuple]]] = {}
    for i, link in enumerate(links):
        from_box, to_box = by_id.get(link.from_id), by_id.get(link.to_id)
        if from_box is None or to_box is None:
            continue
        _s, _e, _style, path = link_render_plan(from_box, to_box, link)
        segments = list(zip(path, path[1:]))
        exclude = _endpoint_exclusion(by_id, parent_of, link)
        hits = []
        for eid, box in by_id.items():
            if eid == "__root__" or eid in exclude:
                continue
            rect = _inflate_rect(_footprint_rect(box), margin)
            for p1, p2 in segments:
                if _segment_intersects_rect(p1, p2, rect):
                    hits.append((box, p1, p2))
                    break
        if hits:
            result[i] = hits
    return result


def _displacement_targets(obox: Box, p1: tuple, p2: tuple, sep: float, bounds: Rect | None) -> list[tuple[float, float, float]]:
    """Candidate (target_local_x, target_local_y, move_magnitude) that slide the
    obstacle perpendicular to an axis-aligned crossing segment until it clears -
    both directions, smaller move first, dropping those that would leave the
    obstacle's container (or the slide). Empty for a diagonal segment."""
    ox, oy, ow, oh = _footprint_rect(obox)
    lx, ly = obox.local_x, obox.local_y  # a pure translation shifts footprint and content alike
    out: list[tuple[float, float, float]] = []
    if abs(p1[1] - p2[1]) < 0.5:  # horizontal segment at y = Y: move the obstacle up/down
        y = (p1[1] + p2[1]) / 2
        for dy in ((y - oy) + sep, -((oy + oh) - y + sep)):
            if bounds is None or _inside((ox, oy + dy, ow, oh), bounds):
                out.append((_num(lx), _num(ly + dy), abs(dy)))
    elif abs(p1[0] - p2[0]) < 0.5:  # vertical segment at x = X: move left/right
        x = (p1[0] + p2[0]) / 2
        for dx in ((x - ox) + sep, -((ox + ow) - x + sep)):
            if bounds is None or _inside((ox + dx, oy, ow, oh), bounds):
                out.append((_num(lx + dx), _num(ly), abs(dx)))
    out.sort(key=lambda t: t[2])
    return out


def _obstacle_move_options(
    raw: dict, registry: MultiRegistry, author_explicit: set[str]
) -> list[tuple[str, float, float]]:
    """(element_id, target_x, target_y) displacements to try, least-disruptive
    first. Only elements the author did not position explicitly are movable, so
    an authored coordinate is never overridden to clear someone else's link."""
    diagram = parse_diagram(raw)
    margin = diagram.canvas.overlap_margin
    sep = margin + _CLEARANCE
    root = build_layout(diagram, registry)
    by_id, parent_of = _build_indices(root)

    ranked: list[tuple[float, str, float, float]] = []
    seen: set[str] = set()
    for hits in _obstacles_crossed_by_link(root, diagram.links, margin).values():
        for obox, p1, p2 in hits:
            eid = obox.element.id
            if eid in author_explicit or eid in seen:
                continue
            seen.add(eid)
            parent = by_id[parent_of[eid]]
            for tx, ty, magnitude in _displacement_targets(obox, p1, p2, sep, _allowed_bounds(parent, diagram.canvas.size)):
                ranked.append((magnitude, eid, tx, ty))
    ranked.sort(key=lambda r: r[0])
    return [(eid, tx, ty) for _magnitude, eid, tx, ty in ranked[:_MAX_CANDIDATES]]


def _resolve_obstacles(raw: dict, registry: MultiRegistry, author_explicit: set[str]) -> None:
    """Clear link-vs-element crossings that no connection side can fix, by
    moving the obstacle out of the path. Each candidate is applied, then stages
    1-2 are re-run and the objective re-measured; the move is kept only if it
    strictly improves, otherwise `raw` is rolled back exactly."""
    for _ in range(_MAX_OBSTACLE_PASSES):
        before = _score(raw, registry)
        if before == 0:
            return
        options = _obstacle_move_options(raw, registry, author_explicit)
        if not options:
            return
        progressed = False
        for eid, tx, ty in options:
            backup = copy.deepcopy(raw)
            node = _find_element_node(raw["elements"], eid)
            node["x"], node["y"] = tx, ty
            _resolve_element_overlaps(raw, registry, author_explicit)
            _resolve_link_routing(raw, registry)
            if _score(raw, registry) < before:
                progressed = True
                break
            _restore(raw, backup)
        if not progressed:
            return


# --- stage 4: detour a link (via waypoints) around an obstacle it crosses ---


def _union_rect(rects: list[Rect]) -> Rect:
    x0 = min(r[0] for r in rects)
    y0 = min(r[1] for r in rects)
    x1 = max(r[0] + r[2] for r in rects)
    y1 = max(r[1] + r[3] for r in rects)
    return (x0, y0, x1 - x0, y1 - y0)


def _center(box: Box) -> tuple[float, float]:
    return box.abs_x + box.width / 2, box.abs_y + box.height / 2


def _detour_waypoints(from_box: Box, to_box: Box, rect: Rect, sep: float) -> list[tuple[list, float]]:
    """(waypoints, deviation) candidates that route a link *around* the
    obstacle bounding box `rect` with right angles only, smaller deviation
    first. A mostly-vertical link leaves its start straight down (or up) to
    just short of the obstacle, steps sideways past it, runs alongside, and
    steps back in line with its end; a mostly-horizontal one does the same
    turned 90 degrees. Each endpoint attaches on the side facing its first/
    last via, so the whole route stays orthogonal."""
    rx, ry, rw, rh = rect
    (fx, fy), (tx, ty) = _center(from_box), _center(to_box)
    out: list[tuple[list, float]] = []
    if abs(ty - fy) >= abs(tx - fx):  # vertical-ish
        before_y, after_y = (ry - sep, ry + rh + sep) if fy <= ty else (ry + rh + sep, ry - sep)
        mid_x = (fx + tx) / 2
        for x_detour in (rx + rw + sep, rx - sep):
            vias = [(fx, before_y), (x_detour, before_y), (x_detour, after_y), (tx, after_y)]
            out.append((vias, abs(x_detour - mid_x)))
    else:  # horizontal-ish
        before_x, after_x = (rx - sep, rx + rw + sep) if fx <= tx else (rx + rw + sep, rx - sep)
        mid_y = (fy + ty) / 2
        for y_detour in (ry + rh + sep, ry - sep):
            vias = [(before_x, fy), (before_x, y_detour), (after_x, y_detour), (after_x, ty)]
            out.append((vias, abs(y_detour - mid_y)))
    out.sort(key=lambda c: c[1])
    return out


def _detour_candidates(raw: dict, registry: MultiRegistry, author_routed: set[int]) -> list[tuple[int, list]]:
    """(link_index, waypoints) detours to try, least-deviating first. Skips
    links the author already routed (waypoints or sides) - their routing is
    intentional and must not be overridden."""
    diagram = parse_diagram(raw)
    margin = diagram.canvas.overlap_margin
    sep = margin + _CLEARANCE
    root = build_layout(diagram, registry)
    by_id, _parent = _build_indices(root)

    # Detour around what the link crosses now, and around what its plain
    # (side-less) route crosses: stage 2 may have settled for a same-side
    # route that crosses less, where a detour of the direct line clears all.
    unsided = [replace(link, from_side=None, to_side=None) for link in diagram.links]
    crossed = _obstacles_crossed_by_link(root, diagram.links, margin)
    crossed_unsided = _obstacles_crossed_by_link(root, unsided, margin)

    ranked: list[tuple[float, int, list]] = []
    seen: set[tuple] = set()
    for hits_by_link in (crossed, crossed_unsided):
        for i, hits in hits_by_link.items():
            if i in author_routed or i not in crossed:
                continue
            link = diagram.links[i]
            union = _union_rect([_footprint_rect(box) for box, _p1, _p2 in hits])
            for waypoints, deviation in _detour_waypoints(by_id[link.from_id], by_id[link.to_id], union, sep):
                key = (i, tuple(waypoints))
                if key not in seen:
                    seen.add(key)
                    ranked.append((deviation, i, waypoints))
    ranked.sort(key=lambda r: r[0])
    return [(i, waypoints) for _dev, i, waypoints in ranked[:_MAX_CANDIDATES]]


def _resolve_link_detours(raw: dict, registry: MultiRegistry, author_routed: set[int]) -> None:
    """Last resort for a link that still runs through an element no side change
    (stage 2) or obstacle move (stage 3) could clear - typically an author-
    pinned obstacle. Insert detour waypoints so the link routes around it. Each
    candidate is applied and the objective re-measured; kept only if it
    strictly improves, else rolled back exactly."""
    for _ in range(_MAX_OBSTACLE_PASSES):
        before = _score(raw, registry)
        if before == 0:
            return
        candidates = _detour_candidates(raw, registry, author_routed)
        if not candidates:
            return
        progressed = False
        for link_idx, waypoints in candidates:
            backup = copy.deepcopy(raw)
            link = raw["links"][link_idx]
            link["waypoints"] = [{"x": _num(x), "y": _num(y)} for x, y in waypoints]
            link.pop("fromSide", None)  # a detour attaches each end facing its first/last via
            link.pop("toSide", None)
            if _score(raw, registry) < before:
                progressed = True
                break
            _restore(raw, backup)
        if not progressed:
            return


# --- change reporting: diff the final tree against the original ---


def _collect_moves(original: dict, final: dict, registry: MultiRegistry) -> tuple[list[Move], list[Move]]:
    """(moves, pins). A move is an element doctor wrote a new x/y that
    actually changed where it renders; a pin is an auto-placed element that
    got an explicit x/y at the spot it already occupied (see stage 1).

    A descendant that shifted only because its container moved isn't a move
    doctor made: an auto-placed one has no x/y of its own (listing it as
    `{"x": null}` crashed the text/github report, after --fix had already
    written the file), and an author-positioned one keeps its x/y untouched
    (listing it claimed doctor had moved a pinned element)."""
    before = {b.element.id: (b.abs_x, b.abs_y) for b in iter_boxes(build_layout(parse_diagram(original), registry))}
    original_nodes = {n["id"]: n for n in _iter_raw_nodes(original.get("elements", []))}
    final_nodes = {n["id"]: n for n in _iter_raw_nodes(final.get("elements", []))}
    moves: list[Move] = []
    pins: list[Move] = []
    for box in iter_boxes(build_layout(parse_diagram(final), registry)):
        eid = box.element.id
        if eid == "__root__" or eid not in before:
            continue
        node = final_nodes.get(eid, {})
        if node.get("x") is None or node.get("y") is None:
            continue
        prior = original_nodes.get(eid, {})
        if (prior.get("x"), prior.get("y")) == (node["x"], node["y"]):
            continue
        ox, oy = before[eid]
        if abs(box.abs_x - ox) > 0.5 or abs(box.abs_y - oy) > 0.5:
            moves.append(Move(eid, node["x"], node["y"]))
        else:
            pins.append(Move(eid, node["x"], node["y"]))
    return moves, pins


def _waypoints_repr(waypoints) -> list[tuple[float, float]]:
    return [(wp["x"], wp["y"]) for wp in (waypoints or [])]


def _collect_link_changes(original: dict, final: dict) -> list[LinkChange]:
    original_links = original.get("links", []) or []
    changes: list[LinkChange] = []
    for i, link in enumerate(final.get("links", []) or []):
        prior = original_links[i] if i < len(original_links) else {}
        sides_changed = link.get("fromSide") != prior.get("fromSide") or link.get("toSide") != prior.get("toSide")
        final_wps = _waypoints_repr(link.get("waypoints"))
        waypoints_changed = final_wps != _waypoints_repr(prior.get("waypoints"))
        if sides_changed or waypoints_changed:
            changes.append(
                LinkChange(
                    link["from"],
                    link["to"],
                    link.get("fromSide"),
                    link.get("toSide"),
                    final_wps if waypoints_changed else None,
                )
            )
    return changes


def _run_stages(raw: dict, registry: MultiRegistry, author_explicit: set[str], author_routed: set[int]) -> None:
    _resolve_element_overlaps(raw, registry, author_explicit)  # stage 1
    _resolve_link_routing(raw, registry)  # stage 2
    _resolve_obstacles(raw, registry, author_explicit)  # stage 3
    _resolve_link_detours(raw, registry, author_routed)  # stage 4


def diagnose_and_fix(raw: dict, registry: MultiRegistry) -> DoctorResult:
    """Resolve overlaps and link-routing collisions in `raw` (a ruamel-loaded
    mapping), mutating it in place, and return what changed plus what remains.
    Caller decides whether to write `raw` back out.

    Runs the four stages (see the module docstring) in rounds, each kept only
    if it strictly lowers the weighted objective; stops at the first round
    that doesn't. `raw` must already be Fatal-clean (schema + semantics
    validated) - parse/layout here assume that, exactly as build/validate/
    sync do.
    """
    initial = _assess(raw, registry)
    if not initial.attempted and not initial.canvas:
        diagram = parse_diagram(raw)
        root = build_layout(diagram, registry)
        return DoctorResult(status="ok", remaining=_unfixable_warnings(root, diagram, registry))

    original = copy.deepcopy(raw)
    author_explicit = _explicit_ids(raw)
    # A link whose routing the author touched at all - explicit waypoints or a
    # forced connection side - expresses routing intent, so stages 2 and 4
    # leave it be rather than re-routing it a different way.
    author_routed = {
        i
        for i, link in enumerate(original.get("links", []) or [])
        if link.get("waypoints") or link.get("fromSide") or link.get("toSide")
    }

    score = initial.score
    for _ in range(_MAX_ROUNDS):
        snapshot = copy.deepcopy(raw)
        _run_stages(raw, registry, author_explicit, author_routed)
        new_score = _score(raw, registry)
        if new_score >= score:
            _restore(raw, snapshot)  # nothing gained this round: no churn either
            break
        score = new_score

    final = _assess(raw, registry)
    diagram = parse_diagram(raw)
    root = build_layout(diagram, registry)
    remaining = final.attempted + final.canvas + _unfixable_warnings(root, diagram, registry)
    # "partial" iff something doctor *attempts* (overlaps, containment, link
    # routing) still remains; canvas/placeholder-icon warnings are reported,
    # not counted.
    moves, pins = _collect_moves(original, raw, registry)
    link_changes = _collect_link_changes(original, raw)
    if final.attempted:
        status = "partial"
    else:
        status = "fixed" if (moves or pins or link_changes) else "ok"
    initial_overlaps = {m for m in initial.attempted if m.startswith("element ")}
    return DoctorResult(
        status=status,
        moves=moves,
        link_changes=link_changes,
        resolved_overlaps=sorted(initial_overlaps - set(final.attempted)),
        remaining=remaining,
        pinned=pins,
    )
