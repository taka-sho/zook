"""PPTX rendering.

Decisions carried over from docs/detailed-design-pptx.md (confirmed via the
prototype in prototype/build_prototype.py):

- 1 logical unit == 9525 EMU == 1px @ 96dpi, for both supported aspect ratios
  (sec8.5).
- Groups get absolute (slide-level) coordinates on every descendant; relying
  on python-pptx's automatic chOff/chExt = off/ext extent recalculation
  (sec8.4) instead of a hand-rolled helper.
- Connector connection-point indices: 0=top, 1=left, 2=bottom, 3=right
  (sec8.2), chosen from the relative position of the two endpoints.
- Connector labels cannot be injected as cxnSp/txBody (invalid per the OOXML
  schema); they are separate textboxes (sec8.3), placed where
  layout.link_label_rect() says.
- Container labels need an explicit TOP vertical anchor or python-pptx's
  default vertical-centering makes them collide with nested content.
- Everything goes through layout.fit_transform(): identity for a diagram that
  fits the slide, a uniform shrink (text included) for one that doesn't.
"""

from __future__ import annotations

import io
import os
import re
from datetime import datetime, timezone

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Pt

from . import __version__
from .layout import (
    DEFAULT_BACKDROP,
    SHAPE_TEXT_INSET,
    SHAPE_TEXT_INSET_Y,
    Box,
    FitTransform,
    backdrops,
    container_label_rect,
    fit_transform,
    is_shape_node,
    link_label_rect_for,
    link_render_plan,
    node_label_font_size,
    node_label_rect,
    readable_on,
    resolve_container_style,
)
from .model import Diagram, Link
from .registry import MultiRegistry, icon_png

LOGICAL_TO_EMU = 9525
LOGICAL_TO_PT = LOGICAL_TO_EMU / 12700  # 1pt = 12700 EMU
CORNER_BADGE_SIZE = 20  # logical units; corner icon for a container's group style (e.g. "AWS Cloud")
CORNER_BADGE_PADDING = 6
_ROT_90 = str(90 * 60000)  # OOXML angles are in 1/60000 degree


def E(value: float) -> Emu:
    return Emu(int(round(value * LOGICAL_TO_EMU)))


class _Slide:
    """Logical coordinates -> EMU on the slide, through the fit transform."""

    def __init__(self, transform: FitTransform, colors: dict | None = None, canvas_background: str | None = None):
        self.t = transform
        self.colors = colors or {}  # layout.backdrops(): the colour behind/inside each element
        self.canvas_background = canvas_background or DEFAULT_BACKDROP

    def rgb(self, color: str, element_id, inside: bool = False) -> RGBColor:
        """`color`, adjusted with readable_on() for what lies behind it."""
        backdrop = self.colors.get((element_id, "inside") if inside else element_id, self.canvas_background)
        return RGBColor.from_string(readable_on(color, backdrop).lstrip("#"))

    def x(self, value: float) -> Emu:
        return E(self.t.x(value))

    def y(self, value: float) -> Emu:
        return E(self.t.y(value))

    def length(self, value: float) -> Emu:
        return E(self.t.length(value))

    def pt(self, size: float) -> Pt:
        return Pt(size * self.t.scale)

    def font(self, size: float) -> Pt:
        # OOXML font sizes start at 1pt; a very heavy shrink-to-fit (reported
        # as a Warning) mustn't make the size invalid.
        return Pt(max(1.0, size * self.t.scale))


def _set_dashed(line) -> None:
    ln = line._get_or_add_ln()
    ln.append(ln.makeelement(qn("a:prstDash"), {"val": "dash"}))


def _no_shadow(shape) -> None:
    # The default theme's effect style gives shapes/connectors an outer shadow.
    # An empty effect list is enough for PowerPoint; LibreOffice still applies
    # the style's effectRef, so point that at "no effect" too.
    shape.shadow.inherit = False
    style = shape._element.find(qn("p:style"))
    effect_ref = style.find(qn("a:effectRef")) if style is not None else None
    if effect_ref is not None:
        effect_ref.set("idx", "0")


def _zero_margins(tf) -> None:
    # Layout measured the text against the full box width (layout.text), so
    # the text frame mustn't eat PowerPoint's default 0.1in side insets.
    tf.margin_left = tf.margin_right = 0
    tf.margin_top = tf.margin_bottom = 0


def _apply_label_position(text_frame, position: str) -> None:
    text_frame.vertical_anchor = MSO_ANCHOR.BOTTOM if "bottom" in position else MSO_ANCHOR.TOP
    align = PP_ALIGN.CENTER if "center" in position else PP_ALIGN.LEFT
    for p in text_frame.paragraphs:
        p.alignment = align


def _add_container_rect(shapes, box: Box, registry: MultiRegistry, s: _Slide):
    element = box.element
    style = resolve_container_style(element, registry)

    rect = shapes.add_shape(MSO_SHAPE.RECTANGLE, s.x(box.abs_x), s.y(box.abs_y), s.length(box.width), s.length(box.height))
    rect.name = element.id
    if style.fill_color:
        rect.fill.solid()
        rect.fill.fore_color.rgb = RGBColor.from_string(style.fill_color.lstrip("#"))
    else:
        rect.fill.background()
    if style.border_width > 0:
        rect.line.color.rgb = s.rgb(style.border_color, element.id)
        rect.line.width = Pt(style.border_width)
        if style.dashed:
            _set_dashed(rect.line)
    else:
        rect.line.fill.background()  # borderWidth 0: no border at all
    _no_shadow(rect)

    tf = rect.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_top = tf.margin_right = tf.margin_bottom = s.pt(4)
    tf.text = style.label_text
    _apply_label_position(tf, style.label_position)
    for p in tf.paragraphs:
        _style_text(p, s.font(style.label_font_size), s.rgb(style.border_color, element.id, inside=True))

    # Corner badge (e.g. the AWS Cloud logo) marks visually where a boundary
    # like "AWS Cloud" starts, per groups.<type>.icon in the icon registry -
    # also with `label: ""` (the band then falls within the padding).
    label_rect = container_label_rect(box, registry)
    badge_png = icon_png(style.corner_icon)[0] if style.corner_icon else None
    if badge_png is not None and "left" in style.label_position:
        if label_rect is not None:
            _, band_y, _, band_h = label_rect
        else:
            band_h = CORNER_BADGE_SIZE + 2 * CORNER_BADGE_PADDING
            band_y = box.abs_y if "top" in style.label_position else box.abs_y + box.height - band_h
        badge_x = box.abs_x + CORNER_BADGE_PADDING
        badge_y = (
            band_y + CORNER_BADGE_PADDING
            if "top" in style.label_position
            else band_y + band_h - CORNER_BADGE_PADDING - CORNER_BADGE_SIZE
        )
        shapes.add_picture(
            io.BytesIO(badge_png), s.x(badge_x), s.y(badge_y), s.length(CORNER_BADGE_SIZE), s.length(CORNER_BADGE_SIZE)
        )
        tf.margin_left = s.pt((CORNER_BADGE_SIZE + CORNER_BADGE_PADDING) * LOGICAL_TO_PT)

    return rect


def _add_node_label(shapes, box: Box, position: str, s: _Slide):
    rect = node_label_rect(box)
    if rect is None:
        return None
    x, y, w, h = rect
    tb = shapes.add_textbox(s.x(x), s.y(y), s.length(w), s.length(h))
    tb.name = f"{box.element.id} label"
    tf = tb.text_frame
    tf.word_wrap = True
    _zero_margins(tf)
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE if position == "right" else MSO_ANCHOR.TOP
    tf.paragraphs[0].text = box.label_text
    tf.paragraphs[0].alignment = PP_ALIGN.LEFT if position == "right" else PP_ALIGN.CENTER
    _style_text(tf.paragraphs[0], s.font(node_label_font_size(box.element)), s.rgb(NODE_TEXT_COLOR, box.element.id))
    return tb


_SHAPE_MSO = {
    "rect": MSO_SHAPE.RECTANGLE,
    "rounded": MSO_SHAPE.ROUNDED_RECTANGLE,
    "diamond": MSO_SHAPE.DIAMOND,
    "circle": MSO_SHAPE.OVAL,
}


def _add_shape_node(shapes, box: Box, s: _Slide):
    element = box.element
    shape = shapes.add_shape(
        _SHAPE_MSO[element.style["shape"]], s.x(box.abs_x), s.y(box.abs_y), s.length(box.width), s.length(box.height)
    )
    shape.name = element.id

    shape.fill.solid()
    shape.fill.fore_color.rgb = RGBColor.from_string(element.style.get("fillColor", "FFFFFF").lstrip("#").upper())
    shape.line.color.rgb = RGBColor.from_string(element.style.get("borderColor", "000000").lstrip("#").upper())
    _no_shadow(shape)

    tf = shape.text_frame
    tf.word_wrap = True
    # PowerPoint's default insets (layout.SHAPE_TEXT_INSET/_Y), written out so
    # they shrink with a shrink-to-fit like everything else.
    tf.margin_left = tf.margin_right = s.pt(SHAPE_TEXT_INSET * LOGICAL_TO_PT)
    tf.margin_top = tf.margin_bottom = s.pt(SHAPE_TEXT_INSET_Y * LOGICAL_TO_PT)
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    tf.paragraphs[0].text = box.label_text
    tf.paragraphs[0].alignment = PP_ALIGN.CENTER
    fill = element.style.get("fillColor", "#FFFFFF")
    _style_text(tf.paragraphs[0], s.font(node_label_font_size(element)), RGBColor.from_string(readable_on("#000000", fill).lstrip("#")))
    return shape


def _add_node(shapes, box: Box, registry: MultiRegistry, s: _Slide):
    # Unresolved type / missing icon file are reported by
    # layout.icon_resolution_warnings() (run once, before rendering, so
    # `validate` sees the same warnings `build` would) - fall back to the
    # placeholder silently here rather than reporting it a second time.
    element = box.element
    if is_shape_node(element):
        return _add_shape_node(shapes, box, s)

    label_position = element.style.get("labelPosition", "below")
    has_label = label_position != "none" and node_label_rect(box) is not None
    # An icon and its label move together in PowerPoint: one group per node.
    target = shapes
    if has_label:
        group = shapes.add_group_shape()
        group.name = element.id
        target = group.shapes
    png = registry.node_icon_png(element.type, element.provider)
    pic = target.add_picture(io.BytesIO(png), s.x(box.abs_x), s.y(box.abs_y), s.length(box.width), s.length(box.height))
    pic.name = f"{element.id} icon" if has_label else element.id
    # Alt text: what the icon stands for, not the icon file's name.
    pic._element.nvPicPr.cNvPr.set("descr", f"{box.label_text or element.id} ({element.type})")
    label = _add_node_label(target, box, label_position, s) if has_label else None
    return pic, label


def _render_element(shapes, box: Box, registry: MultiRegistry, shape_index: dict, s: _Slide) -> None:
    element = box.element
    if element.is_container:
        group = shapes.add_group_shape()
        group.name = f"{element.id} group"
        group_shapes = group.shapes
        rect = _add_container_rect(group_shapes, box, registry, s)
        shape_index[element.id] = (rect, box, None)
        for child in box.children:
            _render_element(group_shapes, child, registry, shape_index, s)
    elif is_shape_node(element):
        shape_index[element.id] = (_add_shape_node(shapes, box, s), box, None)
    else:
        pic, label = _add_node(shapes, box, registry, s)
        shape_index[element.id] = (pic, box, label)


def _add_link_label(shapes, rect: tuple[float, float, float, float], text: str, font_size: float, s: _Slide) -> None:
    """sec8.3: p:cxnSp cannot carry txBody; use a separate textbox.

    `rect` (logical units) is layout.link_label_rect() - exactly where
    link_crossing_warnings() predicts the label sits, so render and the
    overlap check never disagree."""
    x, y, w, h = rect
    tb = shapes.add_textbox(s.x(x), s.y(y), s.length(w), s.length(h))
    tb.fill.solid()
    tb.fill.fore_color.rgb = RGBColor.from_string("FFFFFF")
    tb.line.fill.background()
    tf = tb.text_frame
    tf.word_wrap = True
    _zero_margins(tf)
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    tf.paragraphs[0].text = text
    tf.paragraphs[0].alignment = PP_ALIGN.CENTER
    _style_text(tf.paragraphs[0], s.font(font_size))


_CONNECTOR_TYPES = {"straight": MSO_CONNECTOR.STRAIGHT, "elbow": MSO_CONNECTOR.ELBOW, "curved": MSO_CONNECTOR.CURVE}


_NON_RECT_SHAPES = {"diamond", "circle"}


_SITE_TOLERANCE = 0.5  # logical units


def _glue_target(box: Box, shape, label_shape, idx: int, point: tuple[float, float]):
    """The shape to glue a connector end to, or None to leave it free.

    A glued end is where PowerPoint (after a move) and LibreOffice (on open)
    redraw it: at the middle of side `idx` of the glued shape. So glue only
    to a shape whose side-middle *is* the planned point - the icon, or the
    label textbox for an end placed past the node's own label - and leave
    the end free otherwise (a parallel link's shifted lane, a link meeting a
    container's frame part-way along): glued there, it was pulled back onto
    the icon's edge, through the label, or onto its neighbour's lane."""
    candidates = []
    if not _is_non_rect_shape_node(box):
        candidates.append((shape, (box.abs_x, box.abs_y, box.width, box.height)))
    if label_shape is not None:
        candidates.append((label_shape, node_label_rect(box)))
    for target, (x, y, w, h) in candidates:
        site = {0: (x + w / 2, y), 1: (x, y + h / 2), 2: (x + w / 2, y + h), 3: (x + w, y + h / 2)}[idx]
        if abs(site[0] - point[0]) < _SITE_TOLERANCE and abs(site[1] - point[1]) < _SITE_TOLERANCE:
            return target
    return None


def _is_non_rect_shape_node(box: Box) -> bool:
    # diamond/circle prstGeom connection sites aren't laid out top/left/
    # bottom/right in bounding-box order the way rect/rounded/pictures/
    # containers are - PowerPoint/LibreOffice snap a glued (stCxn/endCxn)
    # connector to the shape's own site for that index, silently overriding
    # the literal begin_x/y we write below (python-pptx's begin_connect/
    # end_connect docstring warns of exactly this for non-rectangular
    # shapes). Skipping the glue for these keeps the literal, geometrically
    # correct point instead.
    return is_shape_node(box.element) and box.element.style.get("shape") in _NON_RECT_SHAPES


def _style_connector(conn, s: "_Slide") -> None:
    # Lines cross every fill on the slide; they're kept readable on the canvas itself.
    conn.line.color.rgb = RGBColor.from_string(readable_on(LINE_COLOR, s.canvas_background).lstrip("#"))
    conn.line.width = Pt(1.25)
    _no_shadow(conn)


NODE_TEXT_COLOR = "#000000"
LINE_COLOR = "#545B64"
_KANA = re.compile(r"[\u3040-\u30ff\u31f0-\u31ff\uff66-\uff9f]")
_HANGUL = re.compile(r"[\uac00-\ud7af\u1100-\u11ff]")


def _style_text(paragraph, size: Pt, color: RGBColor | None = None) -> None:
    """Size (and colour) a paragraph's text on every run, not only as the
    paragraph's default (a:pPr/a:defRPr, which PowerPoint doesn't apply to
    runs that already exist) - and mark Japanese (kana) or Korean (hangul)
    text with its language, so the viewer picks a font of that language for
    it (LibreOffice drew Japanese labels in a Chinese font). Kanji alone
    could be either, so it is left to the viewer."""
    targets = [paragraph.font, *(run.font for run in paragraph.runs)]
    for font in targets:
        font.size = size
        if color is not None:
            font.color.rgb = color
    for run in paragraph.runs:
        lang = "ja-JP" if _KANA.search(run.text) else "ko-KR" if _HANGUL.search(run.text) else None
        if lang:
            rpr = run._r.get_or_add_rPr()
            rpr.set("lang", lang)
            rpr.set("altLang", "en-US")


def _set_metadata(prs: Presentation) -> None:
    """Replace python-pptx's template leftovers - author "Steve Canny", a 2013
    date, a 4:3 slide-size type and "On-screen Show (4:3)" - with the truth.
    SOURCE_DATE_EPOCH, when set, fixes the timestamps (reproducible builds)."""
    props = prs.core_properties
    props.author = props.last_modified_by = "zook"
    props.title = ""
    props.description = props.comments = f"Generated by zook {__version__}"
    props.revision = 1
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    when = datetime.fromtimestamp(int(epoch), tz=timezone.utc) if epoch and epoch.isdigit() else datetime.now(timezone.utc)
    props.created = props.modified = when.replace(tzinfo=None, microsecond=0)
    size = prs.part._element.find(qn("p:sldSz"))
    if size is not None and "type" in size.attrib:
        del size.attrib["type"]  # screen4x3; the slide is whatever size canvas.aspectRatio set
    for part in prs.part.package.iter_parts():
        if str(part.partname) == "/docProps/app.xml":
            xml = part.blob.decode("utf-8")
            xml = re.sub(r"<PresentationFormat>[^<]*</PresentationFormat>", "<PresentationFormat>Custom</PresentationFormat>", xml)
            xml = re.sub(r"<Slides>\d+</Slides>", "<Slides>1</Slides>", xml)
            xml = re.sub(r"<Application>[^<]*</Application>", "<Application>zook</Application>", xml)
            part._blob = xml.encode("utf-8")


def _add_arrowhead(conn, tag: str) -> None:
    ln = conn.line._get_or_add_ln()
    ln.append(ln.makeelement(qn(tag), {"type": "triangle", "w": "med", "len": "med"}))


def _orient_vertical_connector(conn, p1: tuple[int, int], p2: tuple[int, int]) -> None:
    """bentConnector3/curvedConnector3 are defined leaving their start
    *horizontally*: (l,t) -> (mid,t) -> (mid,b) -> (r,b). Unrotated, a link
    that leaves its start shape through the top/bottom edge was therefore
    drawn H-V-H by any viewer that draws the stored geometry (PowerPoint,
    Quick Look), while layout, the crossing checks and the preview all
    modelled the V-H-V route actually intended. Rotating the connector 90
    degrees clockwise, with its extent swapped and flips chosen per
    direction, makes the stored geometry *be* that V-H-V route (all four
    quadrants are checked in tests/test_render_geometry.py)."""
    (x1, y1), (x2, y2) = p1, p2
    dx, dy = x2 - x1, y2 - y1
    width, height = abs(dy), abs(dx)  # the unrotated box runs along the path
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    xfrm = conn._element.spPr.get_or_add_xfrm()
    xfrm.set("rot", _ROT_90)
    for attr in ("flipH", "flipV"):
        if attr in xfrm.attrib:
            del xfrm.attrib[attr]
    if dy < 0:
        xfrm.set("flipH", "1")
    if dx > 0:
        xfrm.set("flipV", "1")
    off = xfrm.get_or_add_off()
    off.x, off.y = Emu(int(round(cx - width / 2))), Emu(int(round(cy - height / 2)))
    ext = xfrm.get_or_add_ext()
    ext.cx, ext.cy = Emu(int(width)), Emu(int(height))


def _render_polyline_link(shapes, link: Link, path, from_glue, to_glue, start_idx, end_idx, s: _Slide):
    """A waypoint link (or a same-side U route) renders as one straight
    connector per segment (spike finding: the lowest-risk way to draw an
    N-bend polyline - it reuses the exact begin/end-override primitive the
    single-segment case uses). The arrowhead goes on the last segment only
    (and the head, for `both`, on the first) so the chain reads as one
    arrow."""
    points = [(s.x(x), s.y(y)) for x, y in path]
    segments = []
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        conn = shapes.add_connector(MSO_CONNECTOR.STRAIGHT, x0, y0, x1, y1)
        conn.begin_x, conn.begin_y = x0, y0
        conn.end_x, conn.end_y = x1, y1
        _style_connector(conn, s)
        segments.append(conn)

    # Glue the two ends (_glue_target; interior joints stay at the explicit
    # via points); re-assert the exact endpoints, since begin/end_connect snap.
    if from_glue is not None:
        segments[0].begin_connect(from_glue, start_idx)
        segments[0].begin_x, segments[0].begin_y = points[0]
    if to_glue is not None:
        segments[-1].end_connect(to_glue, end_idx)
        segments[-1].end_x, segments[-1].end_y = points[-1]

    if link.arrow == "both":
        _add_arrowhead(segments[0], "a:headEnd")
    if link.arrow != "none":
        _add_arrowhead(segments[-1], "a:tailEnd")


def _render_link(shapes, link: Link, shape_index: dict, s: _Slide) -> None:
    from_shape, from_box, from_label = shape_index[link.from_id]
    to_shape, to_box, to_label = shape_index[link.to_id]
    start_idx, end_idx, eff_style, path = link_render_plan(from_box, to_box, link)
    from_glue = _glue_target(from_box, from_shape, from_label, start_idx, path[0])
    to_glue = _glue_target(to_box, to_shape, to_label, end_idx, path[-1])

    if eff_style == "polyline":  # explicit waypoints, a same-side U route, a self-loop
        _render_polyline_link(shapes, link, path, from_glue, to_glue, start_idx, end_idx, s)
    else:
        conn = shapes.add_connector(_CONNECTOR_TYPES[eff_style], E(0), E(0), E(1), E(1))
        if from_glue is not None:
            conn.begin_connect(from_glue, start_idx)
        if to_glue is not None:
            conn.end_connect(to_glue, end_idx)
        # begin_connect/end_connect snap to the connected shape's own edge; override
        # with our (possibly label-aware, sec "connection_point") points so a
        # bottom/top exit past a below/above label, and the auto-elbow bend for a
        # diagonal `straight` link, both actually render as planned.
        p1 = (s.x(path[0][0]), s.y(path[0][1]))
        p2 = (s.x(path[-1][0]), s.y(path[-1][1]))
        conn.begin_x, conn.begin_y = p1
        conn.end_x, conn.end_y = p2
        if eff_style in ("elbow", "curved") and start_idx in (0, 2) and p1[0] != p2[0]:
            _orient_vertical_connector(conn, p1, p2)
        _style_connector(conn, s)
        # a:ln wants headEnd before tailEnd (CT_LineProperties sequence)
        if link.arrow == "both":
            _add_arrowhead(conn, "a:headEnd")
        if link.arrow != "none":
            _add_arrowhead(conn, "a:tailEnd")

    if link.label:
        _add_link_label(shapes, link_label_rect_for(from_box, to_box, path, link), link.label, link.label_font_size, s)


def render(diagram: Diagram, root_box: Box, registry: MultiRegistry) -> Presentation:
    prs = Presentation()
    canvas_w, canvas_h = diagram.canvas.size
    prs.slide_width = E(canvas_w)
    prs.slide_height = E(canvas_h)
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    s = _Slide(fit_transform(diagram, root_box), backdrops(root_box, registry, diagram.canvas.background), diagram.canvas.background)
    _set_metadata(prs)

    if diagram.canvas.background:
        slide.background.fill.solid()
        slide.background.fill.fore_color.rgb = RGBColor.from_string(diagram.canvas.background.lstrip("#"))

    shape_index: dict[str, tuple] = {}
    for child_box in root_box.children:
        _render_element(slide.shapes, child_box, registry, shape_index, s)

    for link in diagram.links:
        _render_link(slide.shapes, link, shape_index, s)

    return prs
