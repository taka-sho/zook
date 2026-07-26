"""Export to / sync back from draw.io (.drawio, mxGraph XML).

Design rationale (docs/detailed-design-pptx.md sec8.14): unlike the pptx
renderer, container/node parent-child relationships map directly onto
mxGraph's own `parent` attribute, and mxCell child geometry is already
parent-relative - the exact same semantics as `layout.Box.local_x/local_y`.
So, unlike render.py's EMU conversion and group chOff/chExt bookkeeping,
export here needs no coordinate transform at all: logical units are used
as draw.io's coordinate units directly, and resizing a `container=1` shape
in draw.io does not rescale its children (verified against jgraph/drawio's
own AWS4 "Groups" palette, which always sets `container=1`).

`sync_from_drawio()` only ever adjusts existing elements' `x`/`y`/`width`/
`height`. Structural edits made in draw.io (added/removed shapes, color/
style changes) are out of scope by design - see the "Z-route" style
warning-only precedent (layout.link_aliasing_warnings) for the project's
established stance on detect-but-don't-auto-fix.
"""

from __future__ import annotations

import base64
import zlib
from typing import Optional
from urllib.parse import unquote
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

from ruamel.yaml import YAML

from .layout import Box, build_layout, is_shape_node, iter_boxes
from .model import Diagram, Element, parse_diagram
from .registry import MultiRegistry

_EPSILON = 0.5  # logical units; matches the tolerance used elsewhere in layout.py

_EDGE_STYLE = {"straight": "", "elbow": "edgeStyle=orthogonalEdgeStyle;", "curved": "edgeStyle=orthogonalEdgeStyle;curved=1;"}

_DEFAULT_NODE_STYLE = "sketch=0;outlineConnect=0;fontColor=#232F3E;verticalLabelPosition=bottom;verticalAlign=top;align=center;html=1;"
_DEFAULT_CONTAINER_STYLE = "container=1;collapsible=0;recursiveResize=0;verticalAlign=top;align=left;html=1;whiteSpace=wrap;"


_SHAPE_STYLE_BASE = {
    "rect": "rounded=0;whiteSpace=wrap;html=1;",
    "rounded": "rounded=1;whiteSpace=wrap;html=1;",
    "diamond": "rhombus;whiteSpace=wrap;html=1;",
    "circle": "ellipse;whiteSpace=wrap;html=1;",
}


def _shape_node_style(element: Element) -> str:
    # mxGraph natively centers `value=` text inside these shapes (unlike
    # _DEFAULT_NODE_STYLE's verticalLabelPosition=bottom, which places the
    # label below an icon) - no extra label plumbing needed here.
    fill = element.style.get("fillColor", "#FFFFFF").lstrip("#")
    stroke = element.style.get("borderColor", "#000000").lstrip("#")
    return _SHAPE_STYLE_BASE[element.style["shape"]] + f"fillColor=#{fill};strokeColor=#{stroke};"


def _node_style(element: Element, registry: MultiRegistry) -> str:
    if is_shape_node(element):
        return _shape_node_style(element)
    icon_entry = registry.resolve_icon(element.type, element.provider)
    if icon_entry and icon_entry.drawio_shape:
        # The registry's drawioShape is just the icon's own visual style
        # (fillColor/shape/resIcon); label placement is a separate,
        # shape-independent concern, so it isn't baked into that value -
        # apply it here for every node regardless of where its shape style
        # came from.
        return _DEFAULT_NODE_STYLE + icon_entry.drawio_shape
    icon_path = icon_entry.file if (icon_entry and icon_entry.file.exists()) else registry.placeholder_icon
    data = base64.b64encode(icon_path.read_bytes()).decode("ascii")
    return _DEFAULT_NODE_STYLE + f"shape=image;imageAspect=0;image=data:image/png;base64,{data};"


def _container_style(element: Element, registry: MultiRegistry) -> str:
    group_style = registry.resolve_group(element.type, element.provider)
    if group_style and group_style.drawio_shape:
        return group_style.drawio_shape
    border = (group_style.border_color if group_style else "#5A6B86").lstrip("#")
    fill = (group_style.fill_color if group_style else None)
    dashed = "1" if (group_style and group_style.dashed) else "0"
    fill_part = f"fillColor=#{fill.lstrip('#')};" if fill else "fillColor=none;"
    return _DEFAULT_CONTAINER_STYLE + f"strokeColor=#{border};{fill_part}dashed={dashed};"


def _label_for(element: Element, registry: MultiRegistry) -> str:
    if element.label is not None:
        return element.label
    if element.kind == "node":
        if is_shape_node(element):
            return element.type
        icon_entry = registry.resolve_icon(element.type, element.provider)
        return icon_entry.label if (icon_entry and icon_entry.label) else element.type
    group_style = registry.resolve_group(element.type, element.provider)
    return group_style.label if group_style else ""


def _emit_cell(lines: list[str], box: Box, parent_id: str, registry: MultiRegistry) -> None:
    element = box.element
    style = _container_style(element, registry) if element.is_container else _node_style(element, registry)
    label = escape(_label_for(element, registry))
    lines.append(
        f'<mxCell id="{escape(element.id)}" value="{label}" style="{escape(style)}" '
        f'vertex="1" parent="{escape(parent_id)}">'
        f'<mxGeometry x="{box.local_x:.2f}" y="{box.local_y:.2f}" width="{box.width:.2f}" '
        f'height="{box.height:.2f}" as="geometry"/></mxCell>'
    )
    for child in box.children:
        _emit_cell(lines, child, element.id, registry)


def _emit_edges(lines: list[str], diagram: Diagram) -> None:
    for i, link in enumerate(diagram.links):
        link_id = link.id or f"__link{i}"
        style = _EDGE_STYLE.get(link.style, "")
        if link.arrow == "none":
            style += "endArrow=none;"
        if link.arrow == "both":
            style += "startArrow=classic;"
        value = f' value="{escape(link.label)}"' if link.label else ""
        lines.append(
            f'<mxCell id="{escape(link_id)}"{value} style="{escape(style)}" edge="1" '
            f'source="{escape(link.from_id)}" target="{escape(link.to_id)}" parent="1">'
            f'<mxGeometry relative="1" as="geometry"/></mxCell>'
        )


def export_drawio(diagram: Diagram, root_box: Box, registry: MultiRegistry) -> str:
    """Render `diagram`/`root_box` (from layout.build_layout) as a .drawio
    (mxGraph XML) document, ready to open/edit in draw.io."""
    lines = ['<mxCell id="0"/>', '<mxCell id="1" parent="0"/>']
    for child_box in root_box.children:
        _emit_cell(lines, child_box, "1", registry)
    _emit_edges(lines, diagram)
    body = "".join(lines)
    return (
        '<mxfile host="archdiagram">'
        '<diagram id="archdiagram" name="Page-1">'
        f'<mxGraphModel dx="800" dy="600" grid="0" guides="1" tooltips="1" connect="1" arrows="1" '
        f'fold="1" page="1" pageScale="1" math="0" shadow="0"><root>{body}</root></mxGraphModel>'
        "</diagram></mxfile>"
    )


def _diagram_model_root(diagram_el: ET.Element) -> Optional[ET.Element]:
    """A `<diagram>` element holds its mxGraphModel one of two ways:

    - Uncompressed (what export_drawio() writes, and what draw.io itself
      offers via "Edit Diagram > uncompressed"): `<mxGraphModel>` is a real
      nested XML *element*, not text - an XML parser never sees it as
      `.text` at all, since unescaped `<...>` inside is markup.
    - draw.io's default when saved from the UI: opaque `.text` content,
      compressed via encodeURIComponent -> raw deflate -> base64.
    """
    nested = diagram_el.find("mxGraphModel")
    if nested is not None:
        return nested
    if not diagram_el.text or not diagram_el.text.strip():
        return None
    compressed = base64.b64decode(diagram_el.text.strip())
    inflated = zlib.decompressobj(-15).decompress(compressed)
    return ET.fromstring(unquote(inflated.decode("utf-8")))


def _parse_geometry(cell: ET.Element) -> Optional[tuple[float, float, float, float]]:
    geom = cell.find("mxGeometry")
    if geom is None:
        return None
    try:
        return (float(geom.get("x", 0)), float(geom.get("y", 0)), float(geom.get("width", 0)), float(geom.get("height", 0)))
    except (TypeError, ValueError):
        return None


def _find_element_node(raw_elements: list, element_id: str):
    """Recursively search a ruamel-loaded `elements`/`children` list for the
    mapping node with the given `id`, returning that mapping directly so
    callers can mutate it in place (preserving comments/ordering)."""
    for node in raw_elements:
        if node.get("id") == element_id:
            return node
        found = _find_element_node(node.get("children", []), element_id)
        if found is not None:
            return found
    return None


def sync_from_drawio(yaml_path: str, drawio_path: str, user_registry_path: str | None = None):
    """Diff an edited .drawio file against the diagram's own auto-layout
    baseline and write back only the elements whose position/size actually
    changed (as explicit x/y/width/height), leaving auto-placed elements
    that weren't touched exactly as they were.

    Returns (updated_yaml_data, warnings) - `updated_yaml_data` is a ruamel
    CommentedMap ready to be dumped with a round-trip YAML() instance so
    comments/ordering in the original file survive.
    """
    from .registry import load_registries
    from .validate import validate

    yaml_rt = YAML()
    yaml_rt.preserve_quotes = True
    with open(yaml_path, encoding="utf-8") as f:
        raw = yaml_rt.load(f)

    validate(raw)
    diagram = parse_diagram(raw)
    registry = load_registries(user_registry_path=user_registry_path)
    baseline_root = build_layout(diagram, registry)
    baseline_by_id = {b.element.id: b for b in iter_boxes(baseline_root) if b.element.id != "__root__"}

    with open(drawio_path, encoding="utf-8") as f:
        drawio_text = f.read()
    mxfile = ET.fromstring(drawio_text)
    diagram_el = mxfile.find(".//diagram")
    if diagram_el is None:
        return raw, [f"no <diagram> element found in {drawio_path!r}"]
    model_root = _diagram_model_root(diagram_el)
    if model_root is None:
        return raw, [f"<diagram> in {drawio_path!r} has no content"]

    warnings: list[str] = []
    seen_ids: set[str] = set()
    for cell in model_root.iter("mxCell"):
        cell_id = cell.get("id")
        if cell_id in (None, "0", "1") or cell.get("edge") == "1":
            continue
        if cell_id not in baseline_by_id:
            warnings.append(
                f"drawio cell {cell_id!r} does not match any known element id - ignored "
                "(node/container additions aren't synced; edit the YAML directly)"
            )
            continue
        seen_ids.add(cell_id)

        geometry = _parse_geometry(cell)
        if geometry is None:
            continue
        x, y, width, height = geometry
        box = baseline_by_id[cell_id]
        node = _find_element_node(raw["elements"], cell_id)
        if node is None:
            continue  # unreachable in practice: cell_id came from baseline_by_id, built from the same raw

        moved = abs(x - box.local_x) > _EPSILON or abs(y - box.local_y) > _EPSILON
        resized = abs(width - box.width) > _EPSILON or abs(height - box.height) > _EPSILON
        if moved:
            node["x"] = round(x, 2)
            node["y"] = round(y, 2)
        if resized:
            node["width"] = round(width, 2)
            node["height"] = round(height, 2)

    for element_id in baseline_by_id:
        if element_id not in seen_ids:
            warnings.append(
                f"element {element_id!r} not found in {drawio_path!r} - was it deleted in draw.io? "
                "structural changes aren't synced; edit the YAML directly if intentional"
            )

    return raw, warnings


def dump_yaml(data, path: str) -> None:
    yaml_rt = YAML()
    yaml_rt.preserve_quotes = True
    yaml_rt.indent(mapping=2, sequence=4, offset=2)
    with open(path, "w", encoding="utf-8") as f:
        yaml_rt.dump(data, f)
