"""Overlap-resolution engine behind `zook doctor`.

`validate`/`build` only *detect* sibling overlaps and container-label
collisions (docs-site/limitations.md): the author is told two elements
overlap and left to fix the pixels by hand. That hand-fixing is exactly what
zook's primary user - a generative AI - is worst at. `doctor` closes that
gap: it takes the same computed geometry the overlap checks run on and
actually separates the colliding elements, emitting the new coordinates (or
writing them straight back into the YAML with `--fix`/`-o`).

Two resolution stages, in order (positions first, since link routing is
derived from them):

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

The link stage minimises *every* link warning `link_crossing_warnings()`
reports, which includes a link's own midpoint label colliding with an element
or another label, so those are attempted too (re-siding a link moves its
midpoint). What it can't help - a collision no side assignment removes (e.g.
an obstacle dead on the line between two vertically-aligned endpoints) - is
reported, never silently left half-fixed.

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

from dataclasses import dataclass, field

from .drawio import _find_element_node
from .layout import (
    Box,
    build_layout,
    container_label_rect,
    icon_resolution_warnings,
    link_aliasing_warnings,
    link_crossing_warnings,
    out_of_canvas_warnings,
    overlap_warnings,
    _footprint_rect,
    _inflate_rect,
    _rects_overlap,
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
    """One link's connection sides assigned to resolve a crossing/aliasing."""

    from_id: str
    to_id: str
    from_side: str | None
    to_side: str | None


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


# --- link routing: assign connection sides to clear crossings/aliasing ---


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


def diagnose_and_fix(raw: dict, registry: MultiRegistry) -> DoctorResult:
    """Resolve overlaps and link-routing collisions in `raw` (a ruamel-loaded
    mapping), mutating it in place, and return what changed plus what remains.
    Caller decides whether to write `raw` back out.

    `raw` must already be Fatal-clean (schema + semantics validated) - parse/
    layout here assume that, exactly as build/validate/sync do.
    """
    diagram = parse_diagram(raw)
    margin = diagram.canvas.overlap_margin
    sep = margin + _CLEARANCE

    root = build_layout(diagram, registry)
    initial_overlaps = set(overlap_warnings(root, registry, margin))
    initial_link = _link_routing_warnings(root, diagram.links, registry, margin)
    if not initial_overlaps and not initial_link:
        return DoctorResult(status="ok", remaining=_unfixable_warnings(root, diagram, registry))

    explicit = _explicit_ids(raw)
    order = _doc_order(raw)

    # Pin the children of every already-broken parent up front so there's no
    # auto re-packing to fight during separation.
    pinned_parents: set[str] = set()
    for kind, parent, *_rest in _find_overlaps(root, registry, margin):
        if parent.element.id not in pinned_parents:
            _pin_children(raw, parent)
            pinned_parents.add(parent.element.id)

    moves: dict[str, Move] = {}
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
            for _kind, parent, *_rest in unpinned:
                if parent.element.id not in pinned_parents:
                    _pin_children(raw, parent)
                    pinned_parents.add(parent.element.id)
            continue

        kind = overlaps[0][0]
        if kind == "pair":
            _, _parent, a, b = overlaps[0]
            movable, anchor = _pick_movable(a, b, explicit, order)
            dx, dy = _separate_pair(_footprint_rect(movable), _footprint_rect(anchor), sep)
        else:  # "label"
            _, _parent, child, label_rect = overlaps[0]
            movable = child
            dx, dy = _separate_from_label(_footprint_rect(child), label_rect, sep)

        node = _find_element_node(raw["elements"], movable.element.id)
        node["x"] = round(movable.local_x + dx, 2)
        node["y"] = round(movable.local_y + dy, 2)
        moves[movable.element.id] = Move(movable.element.id, node["x"], node["y"])

    # Stage 2: link routing. Positions are settled, so connection sides can be
    # chosen against the final geometry.
    link_changes = _resolve_link_routing(raw, registry)

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
        moves=list(moves.values()),
        link_changes=link_changes,
        resolved_overlaps=sorted(initial_overlaps - final_overlaps),
        remaining=remaining,
    )
