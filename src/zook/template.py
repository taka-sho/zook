"""Starting a .pptx from someone's template: its masters, layouts and theme,
none of its slides.

A slide gets what it inherits by itself: the background, the shapes drawn on
the master and layout (a logo, a footer bar) and the theme's fonts. It does
not get footer or slide number placeholders, which show only on a slide with
its own copy of them (PowerPoint's Insert > Header & Footer adds those), and
the diagram keeps its own colours rather than the theme's.
"""

from __future__ import annotations

import colorsys
import io
import zipfile
from typing import Optional

from pptx import Presentation
from pptx.exc import PackageNotFoundError
from pptx.opc.constants import CONTENT_TYPE as CT
from pptx.opc.constants import RELATIONSHIP_TYPE as RT
from pptx.opc.package import XmlPart
from pptx.oxml import parse_xml
from pptx.oxml.ns import qn

from .errors import DiagramError
from .model import ASPECT_RATIOS, LOGICAL_TO_EMU, Canvas

_TEMPLATE_MAIN = b"application/vnd.openxmlformats-officedocument.presentationml.template.main+xml"
_MACRO_MAIN = b"macroEnabled.main+xml"
_SECTION_LIST = "{http://schemas.microsoft.com/office/powerpoint/2010/main}sectionLst"
# Slide sizes this close are the same size: PowerPoint has saved 16:9 as
# 12191695 EMU wide (1279.97 logical) as well as 12192000.
_SIZE_TOLERANCE = 0.5


def open_template(path: str) -> Presentation:
    """The .pptx or .potx at `path`. python-pptx refuses a .potx for its main
    part's content type alone, so it reads a copy with that type swapped; a
    macro-enabled file is refused, since the macros can't survive being saved
    as a .pptx."""
    buffer = io.BytesIO()
    try:
        with zipfile.ZipFile(path) as source, zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as copy:
            for item in source.infolist():
                data = source.read(item)
                if item.filename == "[Content_Types].xml":
                    if _MACRO_MAIN in data:
                        raise DiagramError(
                            f"template {path} is macro-enabled - save it as a .potx or .pptx first",
                            "template-unreadable", [{"file": path}],
                        )
                    data = data.replace(_TEMPLATE_MAIN, CT.PML_PRESENTATION_MAIN.encode())
                copy.writestr(item, data)
        return Presentation(buffer)
    except (zipfile.BadZipFile, KeyError, ValueError, SyntaxError, PackageNotFoundError) as exc:  # SyntaxError: malformed XML
        raise DiagramError(
            f"template {path} is not a .pptx or .potx file (a password-protected one can't be read)",
            "template-unreadable", [{"file": path}],
        ) from exc


def check_slide_size(prs: Presentation, canvas: Canvas, path: str) -> None:
    """A diagram is laid out for its canvas, before any template is opened,
    and a template's master isn't drawn for any other size: the two must agree."""
    width, height = round(prs.slide_width / LOGICAL_TO_EMU, 2), round(prs.slide_height / LOGICAL_TO_EMU, 2)
    canvas_w, canvas_h = canvas.size

    def same(w: float, h: float) -> bool:
        return abs(width - w) <= _SIZE_TOLERANCE and abs(height - h) <= _SIZE_TOLERANCE

    if same(canvas_w, canvas_h):
        return
    preset = next((name for name, size in ASPECT_RATIOS.items() if same(*size)), None)
    fix = f'aspectRatio: "{preset}"' if preset else f"width: {width:g}, height: {height:g}"
    raise DiagramError(
        f"template {path} has {width:g}x{height:g} slides but the diagram's canvas is {canvas_w:g}x{canvas_h:g} "
        f"- set canvas to {{{fix}}}",
        "template-size-mismatch",
        [{"file": path, "template": {"width": width, "height": height}, "canvas": {"width": canvas_w, "height": canvas_h}}],
    )


def remove_slides(prs: Presentation) -> None:
    """Empty the deck, along with what refers to its slides: a section or a
    custom show naming a missing slide makes PowerPoint offer to repair the
    file."""
    part, presentation = prs.part, prs.part._element
    for section_list in list(presentation.iter(_SECTION_LIST)):
        extension = section_list.getparent()
        extension.getparent().remove(extension)
    custom_shows = presentation.find(qn("p:custShowLst"))
    if custom_shows is not None:
        presentation.remove(custom_shows)

    slide_ids = prs.slides._sldIdLst
    for slide_id in list(slide_ids):
        rId = slide_id.rId
        slide_ids.remove(slide_id)
        part.drop_rel(rId)

    # Saved view state can list slides too (outline view); it's disposable.
    for rId, rel in list(part.rels.items()):
        if rel.reltype == RT.VIEW_PROPS and len(rel.target_part.rels):
            part.rels.pop(rId)
    # A link to a slide (a button on a layout jumping to it) would keep that
    # slide's content in the file, so the link goes; the button stays.
    for holder in list(part.package.iter_parts()):
        for rId, rel in list(holder.rels.items()):
            if rel.is_external or rel.reltype != RT.SLIDE:
                continue
            if isinstance(holder, XmlPart):
                for reference in holder._element.xpath(f'//*[@r:id="{rId}"]'):
                    reference.getparent().remove(reference)
            holder.rels.pop(rId)


def blank_layout(prs: Presentation):
    """The first blank layout, known by its type (its name is translated or
    made up), else the one that leaves the fewest placeholders to clear."""
    layouts = [layout for master in prs.slide_masters for layout in master.slide_layouts]
    for layout in layouts:
        if layout._element.get("type") == "blank":
            return layout
    return min(layouts, key=lambda layout: sum(1 for _ in layout.iter_cloneable_placeholders()))


def layout_background(layout) -> Optional[str]:
    """The colour (#RRGGBB) behind everything on a slide using `layout`, what
    a diagram's default colours have to stay readable on. A gradient or a
    theme's picture counts as its base colour, close enough to tell light from
    dark; None for a picture of the template's own, which zook can't judge."""
    master = layout.slide_master
    background = layout._element.find(f"{qn('p:cSld')}/{qn('p:bg')}")
    if background is None:
        background = master._element.find(f"{qn('p:cSld')}/{qn('p:bg')}")
    if background is None:
        return None

    color = None
    properties = background.find(qn("p:bgPr"))
    if properties is not None:
        stops = properties.find(f"{qn('a:gradFill')}/{qn('a:gsLst')}")
        fill = stops[0] if stops is not None and len(stops) else properties.find(qn("a:solidFill"))
        color = fill[0] if fill is not None and len(fill) else None
    else:
        # The theme's fills, solid or not, are all drawn in this one colour.
        reference = background.find(qn("p:bgRef"))
        color = reference[0] if reference is not None and len(reference) else None
    if color is None:
        return None

    override = layout._element.find(f"{qn('p:clrMapOvr')}/{qn('a:overrideClrMapping')}")
    mapping = override if override is not None else master._element.find(qn("p:clrMap"))
    return _resolve_color(color, mapping, parse_xml(master.part.part_related_by(RT.THEME).blob))


def _resolve_color(color, mapping, theme) -> Optional[str]:
    base = color
    if color.tag == qn("a:schemeClr"):
        # bg1 means whichever theme slot the master's colour map says, usually lt1.
        name = color.get("val")
        slot = theme.find(f".//{qn('a:clrScheme')}/{qn('a:' + (mapping.get(name, name) if mapping is not None else name))}")
        if slot is None or not len(slot):
            return None
        base = slot[0]
    value = base.get("val") if base.tag == qn("a:srgbClr") else base.get("lastClr") if base.tag == qn("a:sysClr") else None
    if value is None:
        return None
    return _apply_luminance(value, color)


def _apply_luminance(value: str, color) -> str:
    """PowerPoint's "Darker 50%" and "Lighter 25%" picks (a:lumMod/a:lumOff)."""
    modulate = color.find(qn("a:lumMod"))
    offset = color.find(qn("a:lumOff"))
    if modulate is None and offset is None:
        return f"#{value.upper()}"
    red, green, blue = (int(value[i:i + 2], 16) / 255 for i in (0, 2, 4))
    hue, lightness, saturation = colorsys.rgb_to_hls(red, green, blue)
    if modulate is not None:
        lightness *= int(modulate.get("val")) / 100000
    if offset is not None:
        lightness += int(offset.get("val")) / 100000
    channels = colorsys.hls_to_rgb(hue, min(lightness, 1.0), saturation)
    return "#" + "".join(f"{round(channel * 255):02X}" for channel in channels)
