"""Overlap-resolution engine behind `zook doctor`.

`validate`/`build` only *detect* sibling overlaps and container-label
collisions (docs-site/limitations.md): the author is told two elements
overlap and left to fix the pixels by hand. That hand-fixing is exactly what
zook's primary user - a generative AI - is worst at. `doctor` closes that
gap: it takes the same computed geometry the overlap checks run on and
actually separates the colliding elements, emitting the new coordinates (or
writing them straight back into the YAML with `--fix`/`-o`).

Four resolution stages, in order (each depends on the earlier ones being
settled - link routing follows from positions, displacing an obstacle follows
from the routing that's left, and a waypoint detour is the last resort):

  1. Element overlaps - the element-vs-element and element-vs-container-label
     collisions that `overlap_warnings()` reports - separated by nudging
     coordinates (details below).
  2. Link routing - the link-vs-element crossings and false-edge aliasing that
     `link_crossing_warnings()`/`link_aliasing_warnings()` report. A link has
     no coordinates of its own; its path is derived from its endpoints (now
     fixed) and its connection sides, so the only lever is which edge each end
     attaches to. A greedy search assigns `fromSide`/`toSide` to minimise the
     total link-warning count, verified against those same checkers and only
     ever accepting a strict improvement, so it can never make routing worse.
  3. Obstacle displacement - a link that runs straight through an unrelated
     element, when no connection side can route around it (e.g. an obstacle
     dead on the line between two vertically-aligned endpoints). The path can't
     move, so the *obstacle* does: it's slid perpendicular to the crossing
     segment until clear. Only auto-placed obstacles move (an authored position
     is never overridden), and each move is applied, re-checked through stages
     1-2, and kept only if the total residual strictly drops - otherwise rolled
     back exactly - so this stage, too, never makes a diagram worse.
  4. Waypoint detour - a crossing that survives stages 2 and 3 (the obstacle is
     author-pinned, so it can't move, and no side re-routes around it). The
     link's path *can* change: explicit `waypoints` are inserted to route it
     around the obstacle's bounding box. Only links the author didn't route
     themselves are candidates, and, like every other stage, a detour is kept
     only if the total residual strictly drops, else rolled back exactly.

The link stage minimises *every* link warning `link_crossing_warnings()`
reports, which includes a link's own midpoint label colliding with an element
or another label, so those are attempted too (re-siding a link moves its
midpoint). A collision none of the four stages can remove is reported under
`remaining`, never silently left half-fixed.

Still fully out of scope, reported under `remaining` but not auto-fixed:
off-canvas coordinates and placeholder-icon (unknown-`type`) warnings - a
coordinate nudge and a side swap don't address either; fix those by editing
the YAML or extending the registry.

How the element stage resolves, so the written YAML renders exactly what was
solved:

  1. Find every overlapping sibling pair / child-vs-label collision using the
     identical geometry `overlap_warnings()` uses, so clearing them here means
     the checker agrees they're gone.
  2. Pin every direct child of each *broken* parent at its current auto-layout
     position (explicit x/y). Once a broken container's children are all
     explicit there's no auto re-packing left to fight, so later nudges
     compose predictably. Containers with no overlap stay fully auto-placed.
  3. Iteratively separate one colliding pair per pass by pushing the movable
     element to the clear side of the other (positive direction - right/down -
     so a growing container never forces a negative coordinate), re-laying out
     between passes so cascades (a nudged child growing its parent) are picked
     up. Bounded; any residual overlap is reported, never hidden.

The movable element of a pair is chosen to preserve author intent: an
element the author positioned explicitly outranks an auto-placed one (the
auto one moves); between two of equal standing, the later-declared one moves,
for determinism.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field

from .drawio import _find_element_node
from .layout import (
    Box,
    build_layout,
    container_label_rect,
    icon_resolution_warnings,
    iter_boxes,
    link_aliasing_warnings,
    link_crossing_warnings,
    link_render_plan,
    out_of_canvas_warnings,
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

# Safety bound on the obstacle-displacement loop. Each accepted pass strictly
# lowers the residual count, so this only guards against a pathological input.
_MAX_OBSTACLE_PASSES = 40

Rect = tuple[float, float, float, float]

_SIDES = ("top", "bottom", "left", "right")
_SIDE_AXIS = {"top": "v", "bottom": "v", "left": "h", "right": "h"}


def _candidate_sides() -> list[tuple[str | None, str | None]]:
    """Every connection-side assignment `validate` accepts: both edges set on a
    matching axis (top/bottom together, or left/right together - the only
    combinations elbow routing supports, per docs-site/limitations.md), plus
    single-sided assignments that fix one edge and let the other auto-pick."""
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


# --- overlap discovery (structured; mirrors layout.overlap_warnings geometry) ---

# ("pair", parent_box, a_box, b_box) | ("label", parent_box, child_box, label_rect)
_Overlap = tuple


def _find_overlaps(root_box: Box, registry: MultiRegistry, margin: float) -> list[_Overlap]:
    """Every sibling-pair and child-vs-container-label overlap in the tree,
    detected with the exact predicate overlap_warnings() uses so that
    clearing them here is guaranteed to satisfy the checker."""
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
        for child in children:
            walk(child)

    walk(root_box)
    return found


# --- geometry helpers ---


def _separate_pair(m_rect: Rect, a_rect: Rect, sep: float) -> tuple[float, float]:
    """Translation that clears the movable rect `m_rect` off the anchor rect
    `a_rect` along the axis of shallower penetration, always in the positive
    direction (right or down) so a container that grows to fit never forces a
    negative coordinate. Returns (dx, 0) or (0, dy)."""
    mx, my, mw, mh = m_rect
    ax, ay, aw, ah = a_rect
    overlap_x = min(mx + mw, ax + aw) - max(mx, ax)
    overlap_y = min(my + mh, ay + ah) - max(my, ay)
    if overlap_x <= overlap_y:
        return (ax + aw) - mx + sep, 0.0
    return 0.0, (ay + ah) - my + sep


def _separate_from_label(c_rect: Rect, label_rect: Rect, sep: float) -> tuple[float, float]:
    """Push a child clear of its container's own label strip: down when the
    label sits above the child (the top-left default), up when it sits below."""
    cx, cy, cw, ch = c_rect
    lx, ly, lw, lh = label_rect
    if (ly + lh / 2) <= (cy + ch / 2):  # label above the child -> push child down
        return 0.0, (ly + lh) - cy + sep
    return 0.0, -((cy + ch) - ly + sep)  # label below -> push child up (may go off-canvas; reported)


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
            node["x"] = round(child.local_x, 2)
            node["y"] = round(child.local_y, 2)


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
    """Separate every sibling / child-vs-label overlap by nudging elements, in
    place. Pins the children of each broken parent first (so there's no auto
    re-packing to fight), then moves one colliding element per pass to the
    clear side. `author_explicit` (ids the author positioned in the original
    file) are preferred as anchors so an authored position is disturbed last.

    Idempotent on already-clean input, so it's safe to re-run after a stage-3
    obstacle move perturbs positions."""
    diagram = parse_diagram(raw)
    margin = diagram.canvas.overlap_margin
    sep = margin + _CLEARANCE
    root = build_layout(diagram, registry)
    order = _doc_order(raw)

    pinned_parents: set[str] = set()
    for _kind, parent, *_rest in _find_overlaps(root, registry, margin):
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

        kind = overlaps[0][0]
        if kind == "pair":
            _, _parent, a, b = overlaps[0]
            movable, anchor = _pick_movable(a, b, author_explicit, order)
            dx, dy = _separate_pair(_footprint_rect(movable), _footprint_rect(anchor), sep)
        else:  # "label"
            _, _parent, child, label_rect = overlaps[0]
            movable = child
            dx, dy = _separate_from_label(_footprint_rect(child), label_rect, sep)

        node = _find_element_node(raw["elements"], movable.element.id)
        node["x"] = round(movable.local_x + dx, 2)
        node["y"] = round(movable.local_y + dy, 2)


# --- stage 2: link routing - assign connection sides to clear crossings/aliasing ---


def _link_routing_warnings(root_box: Box, links, registry: MultiRegistry, margin: float) -> list[str]:
    """The link-routing problems doctor's side-search targets: a path (or its
    own label) running through an element/label, and two links reading as one
    (false-edge aliasing)."""
    return (
        link_crossing_warnings(root_box, links, registry, margin)
        + link_aliasing_warnings(root_box, links)
    )


def _resolve_link_routing(raw: dict, registry: MultiRegistry) -> list[LinkChange]:
    """Greedily assign fromSide/toSide to links to minimise the number of
    routing warnings. Positions are fixed by now, and connection sides don't
    affect layout, so this evaluates candidates against a single layout by
    mutating the in-memory Link objects - no re-layout per candidate.

    Only fully-auto links (neither side set by the author) are candidates, so
    an author's deliberate side choice is never overridden. Each pass applies
    the single best strictly-improving reassignment; a strictly-decreasing
    count guarantees termination.
    """
    diagram = parse_diagram(raw)
    links = diagram.links
    if not links:
        return []
    margin = diagram.canvas.overlap_margin
    root = build_layout(diagram, registry)

    auto = [i for i, link in enumerate(links) if link.from_side is None and link.to_side is None]
    if not auto:
        return []

    changes: dict[int, LinkChange] = {}
    for _ in range(len(links) * 4 + 8):  # safety bound; strict improvement already guarantees progress
        baseline = len(_link_routing_warnings(root, links, registry, margin))
        if baseline == 0:
            break
        best: tuple[int, int, str | None, str | None] | None = None  # (count, idx, from_side, to_side)
        for i in auto:
            original = (links[i].from_side, links[i].to_side)
            for from_side, to_side in _candidate_sides():
                links[i].from_side, links[i].to_side = from_side, to_side
                count = len(_link_routing_warnings(root, links, registry, margin))
                if best is None or count < best[0]:
                    best = (count, i, from_side, to_side)
            links[i].from_side, links[i].to_side = original
        if best is None or best[0] >= baseline:
            break  # no strictly-better assignment exists

        _count, i, from_side, to_side = best
        links[i].from_side, links[i].to_side = from_side, to_side  # persist for the next pass
        node = raw["links"][i]
        if from_side is not None:
            node["fromSide"] = from_side
        else:
            node.pop("fromSide", None)
        if to_side is not None:
            node["toSide"] = to_side
        else:
            node.pop("toSide", None)
        changes[i] = LinkChange(links[i].from_id, links[i].to_id, from_side, to_side)

    return list(changes.values())


# --- warnings doctor reports but never attempts to fix ---


def _unfixable_warnings(root_box: Box, diagram, registry: MultiRegistry) -> list[str]:
    return (
        icon_resolution_warnings(root_box, registry)
        + out_of_canvas_warnings(root_box, *diagram.canvas.size)
    )


# --- stage 3: displace an element that a link routes straight through ---


def _attempted_residual_count(raw: dict, registry: MultiRegistry) -> int:
    """Number of problems doctor's three stages target (element overlaps + link
    routing) in `raw`'s current state - the objective stage 3 must strictly
    lower for a move to be worth keeping."""
    diagram = parse_diagram(raw)
    margin = diagram.canvas.overlap_margin
    root = build_layout(diagram, registry)
    return len(overlap_warnings(root, registry, margin)) + len(
        _link_routing_warnings(root, diagram.links, registry, margin)
    )


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


def _link_element_crossings(root_box: Box, links, margin: float) -> list[tuple[Box, tuple, tuple]]:
    """Every (obstacle_box, seg_start, seg_end) where a link's rendered path
    runs through an unrelated element. Uses the exact routing geometry
    link_crossing_warnings() reports on (link_render_plan)."""
    by_id, parent_of = _build_indices(root_box)
    crossings: list[tuple[Box, tuple, tuple]] = []
    for link in links:
        from_box, to_box = by_id.get(link.from_id), by_id.get(link.to_id)
        if from_box is None or to_box is None:
            continue
        _s, _e, _style, path = link_render_plan(from_box, to_box, link)
        segments = list(zip(path, path[1:]))
        exclude = _endpoint_exclusion(by_id, parent_of, link)
        for eid, box in by_id.items():
            if eid == "__root__" or eid in exclude:
                continue
            rect = _inflate_rect(_footprint_rect(box), margin)
            for p1, p2 in segments:
                if _segment_intersects_rect(p1, p2, rect):
                    crossings.append((box, p1, p2))
                    break
    return crossings


def _obstacles_crossed_by_link(root_box: Box, links, margin: float) -> dict[int, list[Box]]:
    """Per-link map: link index -> the unrelated element boxes its path runs
    through. Same geometry/exclusion as _link_element_crossings, but grouped by
    link so stage 4 can detour a link around all the obstacles it hits at once."""
    by_id, parent_of = _build_indices(root_box)
    result: dict[int, list[Box]] = {}
    for i, link in enumerate(links):
        from_box, to_box = by_id.get(link.from_id), by_id.get(link.to_id)
        if from_box is None or to_box is None:
            continue
        _s, _e, _style, path = link_render_plan(from_box, to_box, link)
        segments = list(zip(path, path[1:]))
        exclude = _endpoint_exclusion(by_id, parent_of, link)
        obstacles = [
            box
            for eid, box in by_id.items()
            if eid != "__root__"
            and eid not in exclude
            and any(_segment_intersects_rect(p1, p2, _inflate_rect(_footprint_rect(box), margin)) for p1, p2 in segments)
        ]
        if obstacles:
            result[i] = obstacles
    return result


def _displacement_targets(obox: Box, p1: tuple, p2: tuple, sep: float) -> list[tuple[float, float, float]]:
    """Candidate (target_local_x, target_local_y, move_magnitude) that slide the
    obstacle perpendicular to an axis-aligned crossing segment until it clears -
    both directions, smaller move first. Empty for a diagonal segment (a rare
    explicit `style: straight` diagonal; not displaced)."""
    ox, oy, ow, oh = _footprint_rect(obox)
    lx, ly = obox.local_x, obox.local_y  # a pure translation shifts footprint and content alike
    out: list[tuple[float, float, float]] = []
    if abs(p1[1] - p2[1]) < 0.5:  # horizontal segment at y = Y: move the obstacle up/down
        y = (p1[1] + p2[1]) / 2
        for dy in ((y - oy) + sep, -((oy + oh) - y + sep)):
            out.append((round(lx, 2), round(ly + dy, 2), abs(dy)))
    elif abs(p1[0] - p2[0]) < 0.5:  # vertical segment at x = X: move left/right
        x = (p1[0] + p2[0]) / 2
        for dx in ((x - ox) + sep, -((ox + ow) - x + sep)):
            out.append((round(lx + dx, 2), round(ly, 2), abs(dx)))
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

    ranked: list[tuple[float, str, float, float]] = []
    seen: set[str] = set()
    for obox, p1, p2 in _link_element_crossings(root, diagram.links, margin):
        eid = obox.element.id
        if eid in author_explicit or eid in seen:
            continue
        targets = _displacement_targets(obox, p1, p2, sep)
        if not targets:
            continue
        seen.add(eid)
        for tx, ty, magnitude in targets:
            ranked.append((magnitude, eid, tx, ty))
    ranked.sort(key=lambda r: r[0])
    return [(eid, tx, ty) for _magnitude, eid, tx, ty in ranked]


def _resolve_obstacles(raw: dict, registry: MultiRegistry, author_explicit: set[str]) -> None:
    """Clear link-vs-element crossings that no connection side can fix, by
    moving the obstacle out of the path. Each candidate is applied, then stages
    1-2 are re-run and the total residual re-measured; the move is kept only if
    it strictly improves, otherwise `raw` is rolled back exactly. This never
    makes a diagram worse, and a strictly-decreasing residual terminates."""
    for _ in range(_MAX_OBSTACLE_PASSES):
        before = _attempted_residual_count(raw, registry)
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
            if _attempted_residual_count(raw, registry) < before:
                progressed = True
                break
            raw.clear()
            raw.update(backup)  # exact rollback, comments intact (ruamel deepcopy)
        if not progressed:
            return


# --- stage 4: detour a link (via waypoints) around an obstacle it crosses ---


def _union_rect(rects: list[Rect]) -> Rect:
    x0 = min(r[0] for r in rects)
    y0 = min(r[1] for r in rects)
    x1 = max(r[0] + r[2] for r in rects)
    y1 = max(r[1] + r[3] for r in rects)
    return (x0, y0, x1 - x0, y1 - y0)


def _detour_waypoints(p_start: tuple, p_end: tuple, rect: Rect, sep: float) -> list[tuple[list, float]]:
    """(waypoints, deviation) candidates that route a straight link from
    p_start to p_end *around* the obstacle bounding box `rect`, smaller
    deviation first. A near-vertical link detours sideways (left/right of the
    box); a near-horizontal one detours over/under it. Two vias take the path
    out to a clear column/row and back, so it clears the whole box in one go."""
    rx, ry, rw, rh = rect
    left, right = rx - sep, rx + rw + sep
    top, bottom = ry - sep, ry + rh + sep
    dx, dy = p_end[0] - p_start[0], p_end[1] - p_start[1]
    out: list[tuple[list, float]] = []
    if abs(dy) >= abs(dx):  # vertical-ish link -> detour horizontally
        y_near_start = top if p_start[1] <= p_end[1] else bottom
        y_near_end = bottom if p_start[1] <= p_end[1] else top
        mid_x = (p_start[0] + p_end[0]) / 2
        for x_detour in (right, left):
            out.append(([(x_detour, y_near_start), (x_detour, y_near_end)], abs(x_detour - mid_x)))
    else:  # horizontal-ish link -> detour vertically
        x_near_start = left if p_start[0] <= p_end[0] else right
        x_near_end = right if p_start[0] <= p_end[0] else left
        mid_y = (p_start[1] + p_end[1]) / 2
        for y_detour in (bottom, top):
            out.append(([(x_near_start, y_detour), (x_near_end, y_detour)], abs(y_detour - mid_y)))
    out.sort(key=lambda c: c[1])
    return out


def _detour_candidates(raw: dict, registry: MultiRegistry, author_routed: set[int]) -> list[tuple[int, list]]:
    """(link_index, waypoints) detours to try, least-deviating first. Skips
    links the author already routed with explicit waypoints - their routing is
    intentional and must not be overridden."""
    diagram = parse_diagram(raw)
    margin = diagram.canvas.overlap_margin
    sep = margin + _CLEARANCE
    root = build_layout(diagram, registry)
    by_id, _parent = _build_indices(root)

    ranked: list[tuple[float, int, list]] = []
    for i, obstacles in _obstacles_crossed_by_link(root, diagram.links, margin).items():
        if i in author_routed:
            continue
        link = diagram.links[i]
        _s, _e, _style, path = link_render_plan(by_id[link.from_id], by_id[link.to_id], link)
        union = _union_rect([_footprint_rect(b) for b in obstacles])
        for waypoints, deviation in _detour_waypoints(path[0], path[-1], union, sep):
            ranked.append((deviation, i, waypoints))
    ranked.sort(key=lambda r: r[0])
    return [(i, waypoints) for _dev, i, waypoints in ranked]


def _resolve_link_detours(raw: dict, registry: MultiRegistry, author_routed: set[int]) -> None:
    """Last resort for a link that still runs through an element no side change
    (stage 2) or obstacle move (stage 3) could clear - typically an author-
    pinned obstacle. Insert detour waypoints so the link routes around it. Each
    candidate is applied and the total residual re-measured; kept only if it
    strictly improves (adding waypoints changes only this link's routing, never
    element positions, so no earlier stage needs re-running), else rolled back
    exactly. Never makes a diagram worse; strict decrease terminates."""
    for _ in range(_MAX_OBSTACLE_PASSES):
        before = _attempted_residual_count(raw, registry)
        if before == 0:
            return
        candidates = _detour_candidates(raw, registry, author_routed)
        if not candidates:
            return
        progressed = False
        for link_idx, waypoints in candidates:
            backup = copy.deepcopy(raw)
            raw["links"][link_idx]["waypoints"] = [{"x": round(x, 2), "y": round(y, 2)} for x, y in waypoints]
            if _attempted_residual_count(raw, registry) < before:
                progressed = True
                break
            raw.clear()
            raw.update(backup)  # exact rollback, comments intact (ruamel deepcopy)
        if not progressed:
            return


# --- change reporting: diff the final tree against the original ---


def _collect_moves(original: dict, final: dict, registry: MultiRegistry) -> list[Move]:
    """Elements whose rendered position actually changed. Comparing laid-out
    coordinates (not raw x/y) means an element that only went from auto to an
    explicit pin at the *same* spot isn't reported as a move."""
    before = {b.element.id: (b.abs_x, b.abs_y) for b in iter_boxes(build_layout(parse_diagram(original), registry))}
    final_nodes = {n["id"]: n for n in _iter_raw_nodes(final.get("elements", []))}
    moves: list[Move] = []
    for box in iter_boxes(build_layout(parse_diagram(final), registry)):
        eid = box.element.id
        if eid == "__root__" or eid not in before:
            continue
        ox, oy = before[eid]
        if abs(box.abs_x - ox) > 0.5 or abs(box.abs_y - oy) > 0.5:
            node = final_nodes.get(eid, {})
            moves.append(Move(eid, node.get("x"), node.get("y")))
    return moves


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


def diagnose_and_fix(raw: dict, registry: MultiRegistry) -> DoctorResult:
    """Resolve overlaps and link-routing collisions in `raw` (a ruamel-loaded
    mapping), mutating it in place, and return what changed plus what remains.
    Caller decides whether to write `raw` back out.

    Four stages, in order (each later stage depends on the earlier ones being
    settled): (1) separate overlapping elements, (2) route links by connection
    side, (3) displace an (auto-placed) element a link still runs through,
    (4) detour a link with waypoints around an obstacle none of the above could
    clear (typically an author-pinned one). `raw` must already be Fatal-clean
    (schema + semantics validated) - parse/layout here assume that, exactly as
    build/validate/sync do.
    """
    diagram = parse_diagram(raw)
    margin = diagram.canvas.overlap_margin

    root = build_layout(diagram, registry)
    initial_overlaps = set(overlap_warnings(root, registry, margin))
    initial_link = _link_routing_warnings(root, diagram.links, registry, margin)
    if not initial_overlaps and not initial_link:
        return DoctorResult(status="ok", remaining=_unfixable_warnings(root, diagram, registry))

    original = copy.deepcopy(raw)
    author_explicit = _explicit_ids(raw)
    # A link whose routing the author touched at all - explicit waypoints or a
    # forced connection side - expresses routing intent, so stage 4 leaves it
    # be rather than detouring it a different way.
    author_routed = {
        i
        for i, link in enumerate(original.get("links", []) or [])
        if link.get("waypoints") or link.get("fromSide") or link.get("toSide")
    }

    _resolve_element_overlaps(raw, registry, author_explicit)  # stage 1
    _resolve_link_routing(raw, registry)  # stage 2
    _resolve_obstacles(raw, registry, author_explicit)  # stage 3
    _resolve_link_detours(raw, registry, author_routed)  # stage 4

    diagram = parse_diagram(raw)
    root = build_layout(diagram, registry)
    final_overlaps = set(overlap_warnings(root, registry, margin))
    final_link = _link_routing_warnings(root, diagram.links, registry, margin)

    # "partial" iff something doctor *attempts* (overlaps, link routing) still
    # remains; off-canvas/placeholder-icon warnings are reported, not counted.
    attempted_residual = sorted(final_overlaps) + final_link
    remaining = attempted_residual + _unfixable_warnings(root, diagram, registry)
    status = "fixed" if not attempted_residual else "partial"
    return DoctorResult(
        status=status,
        moves=_collect_moves(original, raw, registry),
        link_changes=_collect_link_changes(original, raw),
        resolved_overlaps=sorted(initial_overlaps - final_overlaps),
        remaining=remaining,
    )
