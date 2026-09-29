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
import html
import io
import json
import re
import zlib
from typing import Optional
from urllib.parse import unquote
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

from ruamel.yaml import YAML

from .errors import DiagramError
from .layout import (
    Box,
    build_layout,
    container_label_text,
    is_shape_node,
    iter_boxes,
    link_render_plan,
    node_label_font_size,
    node_label_text,
    resolve_container_style,
)
from .model import Diagram, Element, parse_diagram
from .registry import MultiRegistry

_EPSILON = 0.5  # logical units; matches the tolerance used elsewhere in layout.py

# A compressed <diagram> inflates ~1000x at worst; no real diagram gets near
# this, so hitting it means a hostile or corrupt file, not a big drawing.
_MAX_INFLATED_BYTES = 50 * 1024 * 1024


# Characters XML 1.0 can't carry at all (C0 controls other than tab/LF/CR,
# lone surrogates, U+FFFE/U+FFFF). draw.io strips them too (Graph.zapGremlins).
_XML_ILLEGAL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]")


def _attr(value: str) -> str:
    """Escape for a double-quoted XML attribute. saxutils.escape() alone
    leaves `"` alone (a label containing one closed the attribute early and
    produced a file draw.io can't open) and a raw newline, which XML
    attribute-value normalisation turns into a space."""
    value = _XML_ILLEGAL.sub("", value)
    return escape(value, {'"': "&quot;", "\n": "&#10;", "\r": "&#13;", "\t": "&#9;"})


def _is_html_label(style: str) -> bool:
    """draw.io's own rule (Graph.isHtmlLabel): html=1 or whiteSpace=wrap,
    with the style parsed as mxStylesheet does - `;`-separated, and a key
    given twice takes its last value."""
    entries: dict[str, str] = {}
    for part in style.split(";"):
        if "=" in part:
            key, value = part.split("=", 1)
            entries[key] = value
    return entries.get("html") == "1" or entries.get("whiteSpace") == "wrap"


def _cell_value(label: str, style: str) -> str:
    """The `value=` text for a cell. For an HTML label draw.io renders the
    value as HTML, so a literal `<b>` in a label would turn bold and a
    newline would vanish - escape it as HTML and use <br> for line breaks
    first; the XML-attribute escape then applies on top."""
    if _is_html_label(style):
        return html.escape(label, quote=False).replace("\r\n", "\n").replace("\n", "<br>")
    return label

_EDGE_STYLE = {"straight": "", "elbow": "edgeStyle=orthogonalEdgeStyle;", "curved": "edgeStyle=orthogonalEdgeStyle;curved=1;"}

_DEFAULT_NODE_STYLE = "sketch=0;outlineConnect=0;fontColor=#232F3E;verticalLabelPosition=bottom;verticalAlign=top;align=center;html=1;"
_DEFAULT_CONTAINER_STYLE = "container=1;collapsible=0;recursiveResize=0;verticalAlign=top;align=left;html=1;whiteSpace=wrap;"


_SHAPE_STYLE_BASE = {
    "rect": "rounded=0;whiteSpace=wrap;html=1;",
    "rounded": "rounded=1;whiteSpace=wrap;html=1;",
    "diamond": "rhombus;whiteSpace=wrap;html=1;",
    "circle": "ellipse;whiteSpace=wrap;html=1;",
}


_META_ID = "zook-meta"  # hidden cell recording what was exported (see sync_from_drawio)
_PT_TO_PX = 4 / 3  # draw.io sizes fonts and strokes in px; zook's are in pt
_EXIT = {0: (0.5, 0.0), 1: (0.0, 0.5), 2: (0.5, 1.0), 3: (1.0, 0.5)}  # connection index -> exitX/exitY


def _px(points: float) -> str:
    return f"{points * _PT_TO_PX:g}"


def _shape_node_style(element: Element) -> str:
    # mxGraph natively centers `value=` text inside these shapes (unlike
    # _DEFAULT_NODE_STYLE's verticalLabelPosition=bottom, which places the
    # label below an icon) - no extra label plumbing needed here.
    fill = element.style.get("fillColor", "#FFFFFF").lstrip("#")
    stroke = element.style.get("borderColor", "#000000").lstrip("#")
    return (
        _SHAPE_STYLE_BASE[element.style["shape"]]
        + f"fillColor=#{fill};strokeColor=#{stroke};fontSize={_px(node_label_font_size(element))};"
    )


_LABEL_POSITION_STYLE = {
    "below": "",  # _DEFAULT_NODE_STYLE already puts the label under the icon
    "above": "verticalLabelPosition=top;verticalAlign=bottom;",
    "right": "labelPosition=right;verticalLabelPosition=middle;align=left;verticalAlign=middle;",
    "none": "noLabel=1;",
}


def _node_style(element: Element, registry: MultiRegistry) -> str:
    if is_shape_node(element):
        return _shape_node_style(element)
    icon_entry = registry.resolve_icon(element.type, element.provider)
    label_style = (
        _LABEL_POSITION_STYLE[element.style.get("labelPosition", "below")]
        + f"fontSize={_px(node_label_font_size(element))};"
    )
    if icon_entry and icon_entry.drawio_shape:
        # The registry's drawioShape is just the icon's own visual style
        # (fillColor/shape/resIcon); label placement is a separate,
        # shape-independent concern, so it isn't baked into that value -
        # apply it here for every node regardless of where its shape style
        # came from.
        return _DEFAULT_NODE_STYLE + icon_entry.drawio_shape + label_style
    data = base64.b64encode(registry.node_icon_png(element.type, element.provider)).decode("ascii")
    # draw.io splits a style string on ";", so the usual `data:image/png;base64,`
    # prefix would cut the value at "data:image/png". draw.io's own convention
    # (EditorUi.convertDataUri / mxGraph.postProcessCellStyle) is the
    # semicolon-free `data:image/png,<base64>` form, which it expands back
    # to `;base64,` when it draws the image.
    return _DEFAULT_NODE_STYLE + f"shape=image;imageAspect=0;image=data:image/png,{data};" + label_style


_CONTAINER_LABEL_STYLE = {
    "top-left": "verticalAlign=top;align=left;",
    "top-center": "verticalAlign=top;align=center;",
    "bottom-left": "verticalAlign=bottom;align=left;",
}


def _container_style(element: Element, registry: MultiRegistry) -> str:
    """The registry's official draw.io group shape when there is one, with the
    element's resolved frame style (layout.resolve_container_style - the same
    precedence the .pptx uses: element style > registry group > defaults)
    applied on top, so the two outputs draw the same frame."""
    group_style = registry.resolve_group(element.type, element.provider)
    resolved = resolve_container_style(element, registry)
    base = group_style.drawio_shape if (group_style and group_style.drawio_shape) else _DEFAULT_CONTAINER_STYLE
    fill = f"fillColor={resolved.fill_color};" if resolved.fill_color else "fillColor=none;"
    stroke = (
        f"strokeColor={resolved.border_color};strokeWidth={_px(resolved.border_width)};"
        if resolved.border_width > 0
        else "strokeColor=none;"
    )
    return (
        base
        + ("" if base.endswith(";") else ";")
        + fill
        + stroke
        + f"dashed={1 if resolved.dashed else 0};fontColor={resolved.border_color};"
        + f"fontSize={_px(resolved.label_font_size)};"
        + _CONTAINER_LABEL_STYLE.get(resolved.label_position, "")
    )


def _label_for(element: Element, registry: MultiRegistry) -> str:
    if element.kind == "node":
        return node_label_text(element, registry)
    return container_label_text(element, registry)


def _dedupe_style(style: str) -> str:
    """One entry per key - the last value wins, as when draw.io reads it -
    kept where the key first appeared: the official shape styles repeat
    keys, and zook's overrides are appended after them."""
    entries: dict[str, str] = {}
    for item in style.split(";"):
        if item:
            entries[item.partition("=")[0]] = item  # an existing key keeps its position
    return "".join(f"{item};" for item in entries.values())


def _emit_cell(lines: list[str], box: Box, parent_id: str, registry: MultiRegistry, meta: dict) -> None:
    element = box.element
    style = _dedupe_style(_container_style(element, registry) if element.is_container else _node_style(element, registry))
    value = _cell_value(_label_for(element, registry), style)
    meta["labels"][element.id] = value
    meta["geometry"][element.id] = [round(v, 2) for v in (box.local_x, box.local_y, box.width, box.height)]
    lines.append(
        f'<mxCell id="{_attr(element.id)}" value="{_attr(value)}" style="{_attr(style)}" '
        f'vertex="1" parent="{_attr(parent_id)}">'
        f'<mxGeometry x="{box.local_x:.2f}" y="{box.local_y:.2f}" width="{box.width:.2f}" '
        f'height="{box.height:.2f}" as="geometry"/></mxCell>'
    )
    for child in box.children:
        _emit_cell(lines, child, element.id, registry, meta)


def _anchor(box: Box, idx: int, point: tuple[float, float]) -> tuple[tuple[float, float], bool]:
    """exitX/exitY (or entryX/entryY) for an edge end at `point`: the planned
    point as a fraction of the cell's bounds, so draw.io starts the line
    where the .pptx does - past a node's own label, on a parallel link's
    lane, part-way along a container's frame - rather than at the middle of
    the side (the second value says whether it is that middle; if not,
    exitPerimeter=0 keeps draw.io from projecting it onto the outline)."""
    middle = _EXIT[idx]
    if not box.width or not box.height:
        return middle, True
    fraction = ((point[0] - box.abs_x) / box.width, (point[1] - box.abs_y) / box.height)
    if abs(fraction[0] - middle[0]) < 1e-3 and abs(fraction[1] - middle[1]) < 1e-3:
        return middle, True
    return fraction, False


def _edge_id(link, i: int) -> str:
    return link.id or f"__link{i}"


def _emit_edges(lines: list[str], diagram: Diagram, root_box: Box, meta: dict) -> None:
    by_id = {b.element.id: b for b in iter_boxes(root_box)}
    for i, link in enumerate(diagram.links):
        link_id = _edge_id(link, i)
        from_box, to_box = by_id.get(link.from_id), by_id.get(link.to_id)
        s_idx, e_idx, eff_style, path = link_render_plan(from_box, to_box, link)
        # zook's own route, reproduced: the same connection sides, and for a
        # waypoint link or a same-side U route its intermediate points (drawn
        # as straight segments); an elbow (incl. a diagonal `straight` link,
        # which zook draws as an elbow) is draw.io's orthogonal routing.
        points = [(x, y) for x, y in path[1:-1]] if eff_style == "polyline" else []
        style = "" if points else _EDGE_STYLE.get(eff_style, "")
        (ex, ey), exit_exact = _anchor(from_box, s_idx, path[0])
        (nx, ny), entry_exact = _anchor(to_box, e_idx, path[-1])
        style += f"exitX={ex:.4g};exitY={ey:.4g};exitDx=0;exitDy=0;entryX={nx:.4g};entryY={ny:.4g};entryDx=0;entryDy=0;"
        if not exit_exact:
            style += "exitPerimeter=0;"
        if not entry_exact:
            style += "entryPerimeter=0;"
        if link.arrow == "none":
            style += "endArrow=none;"
        if link.arrow == "both":
            style += "startArrow=classic;"
        if link.label:
            style += f"fontSize={_px(link.label_font_size)};"
        value = _cell_value(link.label, style) if link.label else ""
        meta["labels"][link_id] = value
        meta["points"][link_id] = [[round(x, 2), round(y, 2)] for x, y in points]
        value_attr = f' value="{_attr(value)}"' if link.label else ""
        if points:
            xml_points = "".join(f'<mxPoint x="{x:.2f}" y="{y:.2f}"/>' for x, y in points)
            geometry = f'<mxGeometry relative="1" as="geometry"><Array as="points">{xml_points}</Array></mxGeometry>'
        else:
            geometry = '<mxGeometry relative="1" as="geometry"/>'
        lines.append(
            f'<mxCell id="{_attr(link_id)}"{value_attr} style="{_attr(style)}" edge="1" '
            f'source="{_attr(link.from_id)}" target="{_attr(link.to_id)}" parent="1">'
            f'{geometry}</mxCell>'
        )


def export_drawio(diagram: Diagram, root_box: Box, registry: MultiRegistry) -> str:
    """Render `diagram`/`root_box` (from layout.build_layout) as a .drawio
    (mxGraph XML) document, ready to open/edit in draw.io.

    A hidden cell (`zook-meta`) records the geometry, link points and labels
    as exported, so `sync` can tell what was edited in draw.io from what
    merely differs because the YAML changed since the export."""
    meta: dict = {"geometry": {}, "points": {}, "labels": {}}
    lines = ['<mxCell id="0"/>', '<mxCell id="1" parent="0"/>']
    for child_box in root_box.children:
        _emit_cell(lines, child_box, "1", registry, meta)
    _emit_edges(lines, diagram, root_box, meta)
    lines.append(
        f'<mxCell id="{_META_ID}" value="{_attr(json.dumps(meta, separators=(",", ":")))}" '
        'style="text;zookMeta=1;" vertex="1" visible="0" parent="1">'
        '<mxGeometry x="0" y="0" width="1" height="1" as="geometry"/></mxCell>'
    )
    body = "".join(lines)
    background = f' background="{diagram.canvas.background}"' if diagram.canvas.background else ""
    canvas_w, canvas_h = diagram.canvas.size
    return (
        '<mxfile host="zook">'
        '<diagram id="zook" name="Page-1">'
        f'<mxGraphModel dx="800" dy="600" grid="0" guides="1" tooltips="1" connect="1" arrows="1" '
        f'fold="1" page="1" pageScale="1" pageWidth="{canvas_w}" pageHeight="{canvas_h}" math="0" shadow="0"{background}>'
        f"<root>{body}</root></mxGraphModel>"
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
    try:
        # draw.io decodes with atob(), which ignores whitespace anywhere in
        # the payload (e.g. base64 wrapped at 76 columns) - so do we.
        compressed = base64.b64decode("".join(diagram_el.text.split()), validate=True)
        inflater = zlib.decompressobj(-15)
        inflated = inflater.decompress(compressed, _MAX_INFLATED_BYTES)
        # unconsumed_tail: input left over once the cap was reached. A full
        # buffer short of end-of-stream means the same, even if zlib happened
        # to have swallowed all of the input already.
        if inflater.unconsumed_tail or (len(inflated) >= _MAX_INFLATED_BYTES and not inflater.eof):
            raise DiagramError(
                f"compressed <diagram> content inflates past {_MAX_INFLATED_BYTES // (1024 * 1024)} MB - refusing to sync it"
            )
        return ET.fromstring(unquote(inflated.decode("utf-8")))
    except (ValueError, zlib.error, ET.ParseError) as exc:  # ValueError covers binascii.Error, UnicodeDecodeError, non-ASCII input
        raise DiagramError(f"could not decode the compressed <diagram> content: {exc}") from exc


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


def _cells(model_root: ET.Element) -> list[tuple[str, ET.Element]]:
    """(id, mxCell) for every cell - including one draw.io wrapped in an
    <object>/<UserObject> (it does that when a shape gets a link, tooltip or
    custom property), where the id lives on the wrapper."""
    root = model_root.find("root")
    if root is None:
        root = model_root
    cells = []
    for el in root:
        if el.tag == "mxCell" and el.get("id") is not None:
            cells.append((el.get("id"), el))
        elif el.tag in ("object", "UserObject") and el.get("id") is not None:
            inner = el.find("mxCell")
            if inner is not None:
                cells.append((el.get("id"), inner))
    return cells


def _points(cell: ET.Element) -> list[tuple[float, float]]:
    geom = cell.find("mxGeometry")
    array = geom.find("Array") if geom is not None else None
    if array is None:
        return []
    try:
        return [(float(p.get("x", 0)), float(p.get("y", 0))) for p in array.findall("mxPoint")]
    except ValueError:
        return []


def _differs(a, b) -> bool:
    return any(abs(x - y) > _EPSILON for x, y in zip(a, b)) or len(a) != len(b)


def _pick_diagram(mxfile: ET.Element, drawio_path: str, warnings: list[str]) -> ET.Element:
    diagrams = mxfile.findall(".//diagram")
    if not diagrams:
        raise DiagramError(
            f"no <diagram> in {drawio_path} - sync reads a .drawio file saved by draw.io "
            "(not .drawio.svg/.png, or a bare mxGraphModel)"
        )
    chosen = next((d for d in diagrams if d.get("id") == "zook"), diagrams[0])
    if len(diagrams) > 1 and chosen.get("id") != "zook":
        warnings.append(
            f"{drawio_path} has {len(diagrams)} pages; syncing the first one ({chosen.get('name', '?')!r})"
        )
    return chosen


def sync_from_drawio(yaml_path: str, drawio_path: str, user_registry_path: str | None = None):
    """Write position/size edits made in draw.io back into the YAML, as
    explicit x/y/width/height - so that the YAML then lays out exactly as the
    .drawio showed. Also writes edited link bend points back as `waypoints`.

    What counts as an edit: a difference from what was *exported* (recorded
    in the hidden `zook-meta` cell), not from the YAML's current layout - so
    a .drawio exported before the YAML changed doesn't silently pin every
    element back to its old position. Without that cell (a file exported by
    an older zook), the YAML's current layout is the baseline.

    Moving one auto-placed element takes it out of its container's auto
    flow, which would re-pack its siblings; so after applying the edits the
    layout is rebuilt and every element that no longer lands where draw.io
    showed it is pinned too, until the two agree.

    Returns (updated_yaml_data, warnings) - `updated_yaml_data` is a ruamel
    CommentedMap ready to be dumped with a round-trip YAML() instance so
    comments/ordering in the original file survive.
    """
    from .loader import load_yaml_roundtrip, read_text, yaml_number
    from .registry import load_registries
    from .validate import validate

    strict_raw, raw = load_yaml_roundtrip(yaml_path)
    validate(strict_raw)  # same reading validate/build use; `raw` is aligned to it (see loader.py)
    diagram = parse_diagram(strict_raw)
    registry = load_registries(user_registry_path=user_registry_path)
    baseline_root = build_layout(diagram, registry)
    boxes = {b.element.id: b for b in iter_boxes(baseline_root) if b.element.id != "__root__"}
    current = {eid: (b.local_x, b.local_y, b.width, b.height) for eid, b in boxes.items()}
    parent_of = {child.element.id: (box.element.id if box.element.id != "__root__" else None)
                 for box in iter_boxes(baseline_root) for child in box.children}

    drawio_text = read_text(drawio_path)
    try:
        mxfile = ET.fromstring(drawio_text)
    except ET.ParseError as exc:
        raise DiagramError(
            f"{drawio_path} is not a valid .drawio XML file ({exc}) - "
            "export it from draw.io as an uncompressed or compressed .drawio, not .svg/.png"
        ) from exc
    warnings: list[str] = []
    model_root = _diagram_model_root(_pick_diagram(mxfile, drawio_path, warnings))
    if model_root is None:
        raise DiagramError(f"the diagram in {drawio_path} has no content")

    cells = _cells(model_root)
    by_id = dict(cells)
    layers = {cid for cid, cell in cells if cell.get("parent") == "0"}
    meta = None
    if _META_ID in by_id:
        try:
            meta = json.loads(by_id[_META_ID].get("value", ""))
        except ValueError:
            warnings.append(f"the {_META_ID!r} cell in {drawio_path} is unreadable - comparing against the YAML's layout")
    exported = {k: tuple(v) for k, v in (meta or {}).get("geometry", {}).items()}
    if meta and any(_differs(exported[k], current[k]) for k in exported.keys() & current.keys()):
        warnings.append(
            "the YAML's layout has changed since this .drawio was exported - only what was edited in draw.io "
            "is written back; re-export to see the current layout"
        )

    # 1. what was edited in draw.io
    targets: dict[str, tuple[float, float, float, float]] = {}
    edited: dict[str, tuple[bool, bool]] = {}  # id -> (moved, resized)
    for eid in boxes:
        cell = by_id.get(eid)
        if cell is None:
            warnings.append(
                f"element {eid!r} not found in {drawio_path!r} - was it deleted in draw.io? "
                "structural changes aren't synced; edit the YAML directly if intentional"
            )
            continue
        drawio_parent = cell.get("parent")
        drawio_parent = None if drawio_parent in layers else drawio_parent
        if drawio_parent != parent_of.get(eid):
            where = repr(drawio_parent) if drawio_parent else "the top level"
            warnings.append(
                f"element {eid!r} was moved into {where} in draw.io - moving elements between containers "
                "isn't synced; its position was left as is (edit the YAML's nesting directly)"
            )
            continue
        geometry = _parse_geometry(cell)
        if geometry is None:
            continue
        base = exported.get(eid, current[eid])
        moved = _differs(geometry[:2], base[:2])
        resized = _differs(geometry[2:], base[2:])
        targets[eid] = geometry if (moved or resized) else current[eid]
        if moved or resized:
            edited[eid] = (moved, resized)

    for cid, cell in cells:
        if cid in ("0", _META_ID) or cid in layers or cid in boxes or cell.get("edge") == "1":
            continue
        warnings.append(
            f"drawio cell {cid!r} does not match any known element id - ignored "
            "(node/container additions aren't synced; edit the YAML directly)"
        )

    for eid, (moved, resized) in edited.items():
        node = _find_element_node(raw["elements"], eid)
        x, y, w, h = targets[eid]
        if moved:
            node["x"], node["y"] = yaml_number(x), yaml_number(y)
        if resized:
            node["width"], node["height"] = yaml_number(w), yaml_number(h)

    # 2. pin whatever the edits made drift, until the layout matches draw.io
    if edited:
        for _ in range(8):
            layout = {b.element.id: (b.local_x, b.local_y, b.width, b.height)
                      for b in iter_boxes(build_layout(parse_diagram(raw), registry))}
            drift = [eid for eid, target in targets.items() if _differs(layout[eid], target)]
            if not drift:
                break
            for eid in drift:
                node = _find_element_node(raw["elements"], eid)
                x, y, w, h = targets[eid]
                if _differs(layout[eid][:2], (x, y)):
                    node["x"], node["y"] = yaml_number(x), yaml_number(y)
                if _differs(layout[eid][2:], (w, h)):
                    node["width"], node["height"] = yaml_number(w), yaml_number(h)
        else:
            warnings.append("could not reproduce the draw.io layout exactly for: " + ", ".join(sorted(drift)))

    # 3. links: bend points and labels
    exported_points = (meta or {}).get("points", {})
    exported_labels = (meta or {}).get("labels", {})
    link_ids = set()
    for i, link in enumerate(diagram.links):
        edge_id = _edge_id(link, i)
        link_ids.add(edge_id)
        cell = by_id.get(edge_id)
        if cell is None:
            warnings.append(f"link {link.from_id!r} -> {link.to_id!r} not found in {drawio_path!r} - was it deleted?")
            continue
        if (cell.get("source"), cell.get("target")) != (link.from_id, link.to_id):
            warnings.append(
                f"link {link.from_id!r} -> {link.to_id!r} was reconnected in draw.io - connection changes aren't synced"
            )
        points = _points(cell)
        before = [tuple(p) for p in exported_points.get(edge_id, [])] if meta else list(link.waypoints)
        if _differs([c for p in points for c in p], [c for p in before for c in p]):
            raw_link = raw["links"][i]
            if points:
                raw_link["waypoints"] = [{"x": yaml_number(x), "y": yaml_number(y)} for x, y in points]
            else:
                raw_link.pop("waypoints", None)
        if meta and edge_id in exported_labels and cell.get("value", "") != exported_labels[edge_id]:
            warnings.append(f"the label of link {link.from_id!r} -> {link.to_id!r} was changed in draw.io - labels aren't synced; edit the YAML")
    for eid in boxes:
        cell = by_id.get(eid)
        if meta and cell is not None and eid in exported_labels and cell.get("value", "") != exported_labels[eid]:
            warnings.append(f"the label of {eid!r} was changed in draw.io - labels aren't synced; edit the YAML")
    for cid, cell in cells:
        if cell.get("edge") == "1" and cid not in link_ids:
            warnings.append(f"link {cid!r} added in draw.io isn't synced - add it to the YAML's links")

    return raw, warnings


def dump_yaml(data, path: str, source_text: str | None = None) -> None:
    """Write a round-trip tree back out. With the file's original text, its
    indentation style is detected and kept (4-space mappings, `- ` flush with
    or indented under its key), so an edit changes the edited lines, not the
    whole file."""
    from ruamel.yaml.util import load_yaml_guess_indent

    from .loader import write_text

    yaml_rt = YAML()
    yaml_rt.preserve_quotes = True
    mapping, sequence, offset = 2, 4, 2
    if source_text:
        try:
            _data, indent, block_seq_indent = load_yaml_guess_indent(source_text)
        except Exception:  # noqa: BLE001 - a guess; the default style is fine
            indent = None
        if indent:
            offset = block_seq_indent or 0
            mapping, sequence = (indent - offset) or 2, indent
    yaml_rt.indent(mapping=mapping, sequence=sequence, offset=offset)
    buffer = io.StringIO()
    yaml_rt.dump(data, buffer)  # serialise fully before touching the file
    write_text(path, buffer.getvalue())
