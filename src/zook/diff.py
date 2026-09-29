"""Semantic structural diff between two zook diagrams, behind `zook diff`.

A plain text diff of two YAML files is noisy and misleading: reflowing a
mapping, or reordering elements that sit at explicit coordinates, shows up as
churn that hides the change that matters. This compares the two diagrams by
*meaning* instead - matching elements by their stable `id` and links by id,
then by endpoints and attributes - and reports what actually changed:
elements added, removed, re-parented (moved between containers), reordered
(auto-placed siblings, whose order *is* their placement), or modified
field-by-field; links added, removed, or modified; and canvas changes.

Comparison is done on the parsed model, not the raw YAML, so a field left to
its default on one side and written explicitly with that same default on the
other (`provider: aws` on a node, `layout: {direction: grid}`, a style value
equal to its default, `size: 64` on an icon) is not reported as a difference
- only genuine changes are.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Optional

from .layout import (
    CONTAINER_LABEL_FONT_SIZE_DEFAULT,
    LABEL_GAP_DEFAULT,
    LINK_LABEL_FONT_SIZE_DEFAULT,
    NODE_LABEL_FONT_SIZE_DEFAULT,
    SHAPE_DEFAULT_SIZE,
    resolve_container_style,
)
from .model import Diagram, Element, Layout, Link, parse_diagram
from .registry import MultiRegistry, load_registries


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
class Reorder:
    parent: Optional[str]  # None: the top level
    old_order: list[str]
    new_order: list[str]


@dataclass
class LinkRef:
    from_id: str
    to_id: str
    id: Optional[str]
    label: Optional[str] = None


@dataclass
class LinkMod:
    from_id: str
    to_id: str
    id: Optional[str]
    changes: list[FieldChange]
    label: Optional[str] = None


@dataclass
class DiffResult:
    canvas: list[FieldChange] = field(default_factory=list)
    added_elements: list[ElementRef] = field(default_factory=list)
    removed_elements: list[ElementRef] = field(default_factory=list)
    reparented: list[Reparent] = field(default_factory=list)
    modified_elements: list[ElementMod] = field(default_factory=list)
    reordered: list[Reorder] = field(default_factory=list)
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
            or self.reordered
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


_NODE_STYLE_DEFAULTS = {"labelPosition": "below", "labelGap": LABEL_GAP_DEFAULT, "labelFontSize": NODE_LABEL_FONT_SIZE_DEFAULT}
_SHAPE_STYLE_DEFAULTS = {"fillColor": "#FFFFFF", "borderColor": "#000000", "labelFontSize": NODE_LABEL_FONT_SIZE_DEFAULT}


def _norm_style(element: Element, registry: MultiRegistry) -> dict:
    """The element's style with every value equal to its default dropped:
    `labelPosition: below` on a node, or a container's `borderColor` equal to
    its registry frame colour, changes nothing that is drawn."""
    if element.kind == "container":
        resolved = resolve_container_style(replace(element, style={}), registry)
        defaults = {
            "borderColor": resolved.border_color, "fillColor": resolved.fill_color,
            "borderWidth": resolved.border_width, "dashed": resolved.dashed,
            "labelPosition": resolved.label_position, "labelFontSize": CONTAINER_LABEL_FONT_SIZE_DEFAULT,
        }
    elif element.style.get("shape"):
        defaults = _SHAPE_STYLE_DEFAULTS
    else:
        defaults = _NODE_STYLE_DEFAULTS
    return {k: v for k, v in element.style.items() if not (k in defaults and _same(defaults[k], v))}


def _same(a, b) -> bool:
    if isinstance(a, str) and isinstance(b, str):
        return a.lower() == b.lower()  # colours: #fff000 == #FFF000
    return a == b


def _declared_size(element: Element, registry: MultiRegistry) -> tuple:
    """(width, height) a node asks for, `size` resolved and defaults filled
    in, so `size: 64` on an icon (its default) or `size: 80` vs
    `width: 80, height: 80` compare equal. Containers: as written (None =
    auto-size)."""
    if element.kind != "node":
        return (element.width, element.height)
    if element.style.get("shape"):
        default_w, default_h = SHAPE_DEFAULT_SIZE[element.style["shape"]]
    else:
        entry = registry.resolve_icon(element.type, element.provider)
        registry_for = registry.registries.get(element.provider)
        default = (entry.size if entry and entry.size else None) or (registry_for.default_size if registry_for else 64)
        default_w = default_h = default
    return (element.width or element.size or default_w, element.height or element.size or default_h)


def _element_signature(element: Element, registry: MultiRegistry) -> dict[str, Any]:
    return {
        "kind": element.kind,
        "type": element.type,
        "provider": element.provider,
        "label": element.label,
        "x": element.x,
        "y": element.y,
        "size": _declared_size(element, registry),
        "style": _norm_style(element, registry),
        "layout": _norm_layout(element.layout),
    }


def _link_signature(link: Link) -> dict[str, Any]:
    return {
        "id": link.id,
        "from": link.from_id,
        "to": link.to_id,
        "style": link.style,
        "label": link.label,
        "arrow": link.arrow,
        "fromSide": link.from_side,
        "toSide": link.to_side,
        "waypoints": [list(p) for p in link.waypoints],
        "labelFontSize": link.label_font_size,
        "color": None if (link.color or "").upper() in ("", "#545B64") else link.color.upper(),
        "line": link.line,
        "width": link.width,
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


def _match_links(old: list[Link], new: list[Link]) -> tuple[list[tuple[Link, Link]], list[Link], list[Link]]:
    """Pair old and new links: by `id` where both sides have it; then, per
    endpoint pair, identical links first (so deleting the first of two
    parallel links is one removal, not "the first changed, the second went
    away") and the rest in order of appearance; what's left is added or
    removed. A link that only gained or lost an id pairs up as a
    modification of its `id`."""
    pairs: list[tuple[Link, Link]] = []
    new_by_id = {link.id: link for link in new if link.id}
    old_ids = {link.id for link in old if link.id}
    rest_old = []
    for link in old:
        if link.id and link.id in new_by_id:
            pairs.append((link, new_by_id[link.id]))
        else:
            rest_old.append(link)
    rest_new = [link for link in new if not (link.id and link.id in old_ids)]

    def body(link: Link) -> dict:
        signature = _link_signature(link)
        signature.pop("id")
        return signature

    for exact in (True, False):
        still_old = []
        for link in rest_old:
            candidates = [n for n in rest_new if (n.from_id, n.to_id) == (link.from_id, link.to_id)]
            if exact:
                candidates = [n for n in candidates if body(n) == body(link)]
            if candidates:
                pairs.append((link, candidates[0]))
                rest_new.remove(candidates[0])
            else:
                still_old.append(link)
        rest_old = still_old
    return pairs, rest_new, rest_old


def _auto_order(elements: list[Element]) -> list[str]:
    """The ids of auto-placed siblings, in order - the order they are laid
    out in (explicitly positioned ones are where they say, whatever their
    order)."""
    return [e.id for e in elements if e.x is None or e.y is None]


def _reorders(old: Diagram, new: Diagram) -> list[Reorder]:
    old_children = {None: old.elements}
    new_children = {None: new.elements}
    for index, diagram in ((old_children, old), (new_children, new)):
        stack = list(diagram.elements)
        while stack:
            element = stack.pop()
            index[element.id] = element.children
            stack.extend(element.children)
    reorders = []
    for parent in old_children.keys() & new_children.keys():
        before, after = _auto_order(old_children[parent]), _auto_order(new_children[parent])
        common = set(before) & set(after)
        before, after = [i for i in before if i in common], [i for i in after if i in common]
        if before != after:
            reorders.append(Reorder(parent, before, after))
    return reorders


# --- the diff ---

_CANVAS_FIELDS = [
    ("aspectRatio", "aspect_ratio"),
    ("padding", "padding"),
    ("background", "background"),
    ("overlapMargin", "overlap_margin"),
]


def diff_diagrams(old_raw: dict, new_raw: dict, registry: Optional[MultiRegistry] = None) -> DiffResult:
    """Structural diff of two Fatal-clean diagrams. Callers validate first.
    `registry` (default: the built-in ones) supplies the defaults a style or
    size is compared against."""
    old, new = parse_diagram(old_raw), parse_diagram(new_raw)
    registry = registry or load_registries()
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
        changes = _field_changes(_element_signature(old_element, registry), _element_signature(new_element, registry))
        if changes:
            result.modified_elements.append(ElementMod(eid, new_element.kind, new_element.type, changes))

    result.reordered = _reorders(old, new)

    pairs, added, removed = _match_links(old.links, new.links)
    new_position = {id(link): i for i, link in enumerate(new.links)}
    for link in added:
        result.added_links.append(LinkRef(link.from_id, link.to_id, link.id, link.label))
    for link in removed:
        result.removed_links.append(LinkRef(link.from_id, link.to_id, link.id, link.label))
    for old_link, new_link in sorted(pairs, key=lambda pair: new_position[id(pair[1])]):
        changes = _field_changes(_link_signature(old_link), _link_signature(new_link))
        if changes:
            result.modified_links.append(LinkMod(new_link.from_id, new_link.to_id, new_link.id, changes, new_link.label))

    # Deterministic ordering, whatever the set iteration order.
    result.added_elements.sort(key=lambda r: r.id)
    result.removed_elements.sort(key=lambda r: r.id)
    result.reparented.sort(key=lambda r: r.id)
    result.modified_elements.sort(key=lambda m: m.id)
    result.reordered.sort(key=lambda r: r.parent or "")
    result.added_links.sort(key=lambda r: (r.from_id, r.to_id, r.id or "", r.label or ""))
    result.removed_links.sort(key=lambda r: (r.from_id, r.to_id, r.id or "", r.label or ""))
    result.modified_links.sort(key=lambda m: (m.from_id, m.to_id, m.id or "", m.label or ""))
    return result
