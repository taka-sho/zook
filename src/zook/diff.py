"""Semantic structural diff between two zook diagrams, behind `zook diff`.

A plain text diff of two YAML files is noisy and misleading: reordering
children, reflowing a mapping, or auto-layout writing explicit coordinates all
show up as churn that hides the change that matters. This compares the two
diagrams by *meaning* instead - matching elements by their stable `id` and
links by id-or-endpoints - and reports what actually changed: elements added,
removed, re-parented (moved between containers), or modified field-by-field;
links added, removed, or modified; and canvas changes.

Comparison is done on the parsed model, not the raw YAML, so a field left to
its default on one side and written explicitly with that same default on the
other (e.g. `provider: aws` on a node, or `layout: {direction: grid}`) is not
reported as a difference - only genuine changes are.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from .model import Diagram, Element, Layout, Link, parse_diagram


@dataclass
class FieldChange:
    field: str
    old: Any
    new: Any


@dataclass
class ElementRef:
    id: str
    kind: str
    type: str
    parent: Optional[str]


@dataclass
class Reparent:
    id: str
    old_parent: Optional[str]
    new_parent: Optional[str]


@dataclass
class ElementMod:
    id: str
    kind: str
    type: str
    changes: list[FieldChange]


@dataclass
class LinkRef:
    from_id: str
    to_id: str
    id: Optional[str]


@dataclass
class LinkMod:
    from_id: str
    to_id: str
    id: Optional[str]
    changes: list[FieldChange]


@dataclass
class DiffResult:
    canvas: list[FieldChange] = field(default_factory=list)
    added_elements: list[ElementRef] = field(default_factory=list)
    removed_elements: list[ElementRef] = field(default_factory=list)
    reparented: list[Reparent] = field(default_factory=list)
    modified_elements: list[ElementMod] = field(default_factory=list)
    added_links: list[LinkRef] = field(default_factory=list)
    removed_links: list[LinkRef] = field(default_factory=list)
    modified_links: list[LinkMod] = field(default_factory=list)

    @property
    def identical(self) -> bool:
        return not (
            self.canvas
            or self.added_elements
            or self.removed_elements
            or self.reparented
            or self.modified_elements
            or self.added_links
            or self.removed_links
            or self.modified_links
        )


# --- element/link signatures (normalised, so defaults never read as changes) ---


def _norm_layout(layout: Optional[Layout]) -> tuple:
    """A container with no `layout` behaves exactly like the default grid, so
    normalise None to that default before comparing - an omitted layout and an
    explicit `{direction: grid}` are the same diagram."""
    resolved = layout or Layout()
    return (resolved.direction, resolved.columns, resolved.gap, resolved.padding)


def _element_signature(element: Element) -> dict[str, Any]:
    return {
        "kind": element.kind,
        "type": element.type,
        "provider": element.provider,
        "label": element.label,
        "x": element.x,
        "y": element.y,
        "width": element.width,
        "height": element.height,
        "size": element.size,
        "style": element.style,
        "layout": _norm_layout(element.layout),
    }


def _link_signature(link: Link) -> dict[str, Any]:
    return {
        "from": link.from_id,
        "to": link.to_id,
        "style": link.style,
        "label": link.label,
        "arrow": link.arrow,
        "fromSide": link.from_side,
        "toSide": link.to_side,
        "waypoints": link.waypoints,
        "labelFontSize": link.label_font_size,
    }


def _field_changes(old_sig: dict, new_sig: dict) -> list[FieldChange]:
    return [FieldChange(k, old_sig[k], new_sig[k]) for k in old_sig if old_sig[k] != new_sig[k]]


# --- indexing ---


def _index_elements(diagram: Diagram) -> dict[str, tuple[Element, Optional[str]]]:
    """id -> (element, parent_id). Parent is the containing element's id, or
    None for a top-level element."""
    index: dict[str, tuple[Element, Optional[str]]] = {}

    def walk(elements: list[Element], parent_id: Optional[str]) -> None:
        for element in elements:
            index[element.id] = (element, parent_id)
            walk(element.children, element.id)

    walk(diagram.elements, None)
    return index


def _index_links(diagram: Diagram) -> dict[str, Link]:
    """Match key for each link: its `id` if it has one, else its endpoints.
    Repeated endpoint pairs without ids get an occurrence suffix so two links
    between the same nodes still diff independently."""
    index: dict[str, Link] = {}
    counts: dict[str, int] = {}
    for link in diagram.links:
        base = link.id or f"{link.from_id}->{link.to_id}"
        counts[base] = counts.get(base, 0) + 1
        key = base if counts[base] == 1 else f"{base}#{counts[base]}"
        index[key] = link
    return index


# --- the diff ---

_CANVAS_FIELDS = [
    ("aspectRatio", "aspect_ratio"),
    ("padding", "padding"),
    ("background", "background"),
    ("overlapMargin", "overlap_margin"),
]


def diff_diagrams(old_raw: dict, new_raw: dict) -> DiffResult:
    """Structural diff of two Fatal-clean diagrams. Callers validate first."""
    old, new = parse_diagram(old_raw), parse_diagram(new_raw)
    result = DiffResult()

    for label, attr in _CANVAS_FIELDS:
        old_value, new_value = getattr(old.canvas, attr), getattr(new.canvas, attr)
        if old_value != new_value:
            result.canvas.append(FieldChange(label, old_value, new_value))

    old_elements, new_elements = _index_elements(old), _index_elements(new)
    for eid in new_elements.keys() - old_elements.keys():
        element, parent = new_elements[eid]
        result.added_elements.append(ElementRef(eid, element.kind, element.type, parent))
    for eid in old_elements.keys() - new_elements.keys():
        element, parent = old_elements[eid]
        result.removed_elements.append(ElementRef(eid, element.kind, element.type, parent))
    for eid in old_elements.keys() & new_elements.keys():
        old_element, old_parent = old_elements[eid]
        new_element, new_parent = new_elements[eid]
        if old_parent != new_parent:
            result.reparented.append(Reparent(eid, old_parent, new_parent))
        changes = _field_changes(_element_signature(old_element), _element_signature(new_element))
        if changes:
            result.modified_elements.append(ElementMod(eid, new_element.kind, new_element.type, changes))

    old_links, new_links = _index_links(old), _index_links(new)
    for key in new_links.keys() - old_links.keys():
        link = new_links[key]
        result.added_links.append(LinkRef(link.from_id, link.to_id, link.id))
    for key in old_links.keys() - new_links.keys():
        link = old_links[key]
        result.removed_links.append(LinkRef(link.from_id, link.to_id, link.id))
    for key in old_links.keys() & new_links.keys():
        old_link, new_link = old_links[key], new_links[key]
        changes = _field_changes(_link_signature(old_link), _link_signature(new_link))
        if changes:
            result.modified_links.append(LinkMod(new_link.from_id, new_link.to_id, new_link.id, changes))

    # Stable ordering so output (and tests) don't depend on set iteration order.
    result.added_elements.sort(key=lambda r: r.id)
    result.removed_elements.sort(key=lambda r: r.id)
    result.reparented.sort(key=lambda r: r.id)
    result.modified_elements.sort(key=lambda m: m.id)
    result.added_links.sort(key=lambda r: (r.from_id, r.to_id))
    result.removed_links.sort(key=lambda r: (r.from_id, r.to_id))
    result.modified_links.sort(key=lambda m: (m.from_id, m.to_id))
    return result
