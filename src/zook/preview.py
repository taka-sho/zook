"""Lightweight PNG preview - no PowerPoint/LibreOffice needed.

Draws the same Box tree, label boxes (layout.node_label_rect /
link_label_rect, with the lines layout wrapped them into) and
link_render_plan() geometry render.py uses for the real .pptx, through the
same fit-to-slide transform, but with Pillow directly - so a diagram can be
sanity-checked in CI or a terminal (or by an AI reading the PNG) without
opening PowerPoint. Visual fidelity is approximate (rectangles/lines/text, no
shadows or true typography) - it's a fast structural preview, not a
substitute for the real output.

Text is drawn with a system font that has CJK glyphs when one can be found
(ZOOK_PREVIEW_FONT, then the usual macOS / Linux / Windows locations), so a
Japanese label shows as Japanese rather than as tofu boxes;
preview_font_warnings() reports when none was found, or when
ZOOK_PREVIEW_FONT had to be ignored. That font's Latin letters are usually
wider than the .pptx's Calibri, so a line that would overrun its label box is
drawn a little smaller instead of spilling out of it. Line widths and
arrowheads keep their .pptx size under a shrink-to-fit, as they do on the
slide.
"""

from __future__ import annotations

import io
import math
import os
import unicodedata
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .layout import (
    DEFAULT_BACKDROP,
    Box,
    FitTransform,
    container_label_rect,
    fit_transform,
    is_shape_node,
    backdrops,
    iter_boxes,
    link_label_box,
    link_label_rect_for,
    link_render_plan,
    node_label_font_size,
    node_label_rect,
    readable_on,
    resolve_container_style,
)
from .errors import Finding
from .model import Diagram
from .registry import MultiRegistry, icon_png
from .text import PT_TO_LOGICAL

SCALE = 1.5  # px per logical unit
BACKGROUND = (255, 255, 255, 255)
TEXT_COLOR = (30, 30, 30, 255)
LINE_COLOR = (84, 91, 100, 255)
LABEL_BG = (255, 255, 255, 230)
SHAPE_BORDER_PT = 0.75  # the default theme line of a shape node
CORNER_BADGE_SIZE = 20  # logical units; same as render.py
CORNER_BADGE_PADDING = 6

# Fonts with CJK coverage, most specific first. Any of them also has Latin.
_FONT_CANDIDATES = [
    "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/ipaexfont-gothic/ipaexg.ttf",
    "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
    "/usr/share/fonts/truetype/takao-gothic/TakaoPGothic.ttf",
    "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
    "C:/Windows/Fonts/YuGothM.ttc",
    "C:/Windows/Fonts/meiryo.ttc",
    "C:/Windows/Fonts/msgothic.ttc",
]


def _has_cjk_glyph(path: str) -> bool | None:
    """Whether the font file at `path` draws a real glyph for a kana (not
    its missing-glyph box); None if Pillow can't load it as a font at all."""
    try:
        font = ImageFont.truetype(path, 24)
    except (OSError, ValueError):
        return None

    def bitmap(ch: str) -> bytes:
        image = Image.new("L", (40, 40))
        ImageDraw.Draw(image).text((4, 4), ch, font=font, fill=255)
        return image.tobytes()

    # U+F0000 (supplementary private use) is drawn as the missing-glyph box
    return bitmap("あ") != bitmap("\U000F0000")


@lru_cache(maxsize=4)
def _font_choice(override: str | None) -> tuple[str | None, str | None]:
    """(font path, why ZOOK_PREVIEW_FONT was ignored). The override wins only
    if it is a loadable font with CJK glyphs; otherwise the first installed
    candidate is used, so a typo'd path doesn't turn Japanese into boxes
    while a working system font sits right there."""
    problem = None
    if override:
        usable = _has_cjk_glyph(override) if Path(override).is_file() else None
        if usable:
            return override, None
        if usable is None:
            problem = f"ZOOK_PREVIEW_FONT ({override}) is not a font file that could be loaded"
        else:
            problem = f"ZOOK_PREVIEW_FONT ({override}) has no Japanese/Chinese/Korean glyphs"
    found = next((c for c in _FONT_CANDIDATES if Path(c).is_file() and _has_cjk_glyph(c)), None)
    return found, problem


def _cjk_font_path() -> str | None:
    return _font_choice(os.environ.get("ZOOK_PREVIEW_FONT"))[0]


@lru_cache(maxsize=128)
def _font_file(path: str | None, size_px: int) -> ImageFont.ImageFont:
    size_px = max(1, size_px)
    if path:
        try:
            return ImageFont.truetype(path, size_px)
        except OSError:
            pass
    try:
        return ImageFont.load_default(size=size_px)
    except TypeError:  # Pillow < 10.1 doesn't accept a size kwarg here
        return ImageFont.load_default()


def _font(size_px: int) -> ImageFont.ImageFont:
    return _font_file(_cjk_font_path(), size_px)


def _has_wide_text(text: str) -> bool:
    return any(unicodedata.east_asian_width(ch) in ("W", "F") for ch in text)


def preview_font_warnings(diagram: Diagram, root_box: Box, registry: MultiRegistry) -> list[str]:
    """A Warning when ZOOK_PREVIEW_FONT had to be ignored, or when the
    diagram has CJK text but no CJK-capable font was found for the preview
    (the .pptx itself is unaffected either way)."""
    path, problem = _font_choice(os.environ.get("ZOOK_PREVIEW_FONT"))
    messages = []
    if problem is not None:
        using = f"using {path} instead" if path else "falling back to Pillow's built-in font"
        messages.append(Finding(
            f"{problem}, so it was ignored - {using} for the preview (the .pptx is unaffected)", "preview-font-ignored"
        ))
    if path is None:
        texts = [b.label_text for b in iter_boxes(root_box)] + [link.label or "" for link in diagram.links]
        if any(_has_wide_text(t) for t in texts):
            messages.append(Finding(
                "no font with Japanese/Chinese/Korean glyphs was found for the preview, so that text shows as "
                "boxes - set ZOOK_PREVIEW_FONT to a .ttf/.ttc that has them (the .pptx is unaffected)",
                "preview-no-cjk-font",
            ))
    return messages


def _hex_to_rgba(color: str, alpha: int = 255) -> tuple[int, int, int, int]:
    color = color.lstrip("#")
    return int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16), alpha


class _Canvas:
    """Logical coordinates -> image pixels, through the fit transform."""

    def __init__(self, transform: FitTransform, colors: dict | None = None, canvas_background: str | None = None):
        self.t = transform
        self.colors = colors or {}  # layout.backdrops(), as render.py uses it
        self.canvas_background = canvas_background or DEFAULT_BACKDROP

    def color(self, color: str, element_id, inside: bool = False) -> tuple[int, int, int, int]:
        backdrop = self.colors.get((element_id, "inside") if inside else element_id, self.canvas_background)
        return _hex_to_rgba(readable_on(color, backdrop))

    def x(self, value: float) -> float:
        return self.t.x(value) * SCALE

    def y(self, value: float) -> float:
        return self.t.y(value) * SCALE

    def length(self, value: float) -> float:
        return self.t.length(value) * SCALE

    def font(self, size_pt: float) -> ImageFont.ImageFont:
        # points -> logical units -> pixels, shrunk with the diagram
        return _font(round(size_pt * PT_TO_LOGICAL * self.length(1.0)))

    @staticmethod
    def stroke(width_pt: float) -> int:
        # a line width in points -> pixels, *not* shrunk: render.py writes
        # line widths and arrowheads unscaled, so the slide keeps them too
        return max(1, round(width_pt * PT_TO_LOGICAL * SCALE))

    def rect(self, rect) -> tuple[float, float, float, float]:
        x, y, w, h = rect
        return self.x(x), self.y(y), self.x(x + w), self.y(y + h)


def _text_size(draw: ImageDraw.ImageDraw, text: str, font) -> tuple[float, float]:
    left, top, right, bottom = draw.textbbox((0, 0), text or " ", font=font)
    return right - left, bottom - top


def _draw_lines(draw: ImageDraw.ImageDraw, lines: list[str], font, box: tuple[float, float, float, float],
                align: str, valign: str, fill) -> None:
    """Draw pre-wrapped `lines` inside pixel box (x0, y0, x1, y1)."""
    x0, y0, x1, y1 = box
    ascent, descent = font.getmetrics() if hasattr(font, "getmetrics") else (10, 2)
    line_h = (ascent + descent) * 1.1
    total = line_h * len(lines)
    if valign == "middle":
        y = (y0 + y1) / 2 - total / 2
    elif valign == "bottom":
        y = y1 - total
    else:
        y = y0
    for line in lines:
        line_font = font
        w, _ = _text_size(draw, line, font)
        if w > (x1 - x0) + 1 and getattr(font, "path", None):
            # The CJK font's Latin is wider than the Calibri layout measured
            # for: shrink this line into its box rather than draw a collision
            # the .pptx doesn't have.
            line_font = _font_file(font.path, max(1, int(font.size * (x1 - x0) / w)))
            w, _ = _text_size(draw, line, line_font)
        if align == "center":
            x = (x0 + x1) / 2 - w / 2
        elif align == "right":
            x = x1 - w
        else:
            x = x0
        draw.text((x, y), line, font=line_font, fill=fill)
        y += line_h


# PowerPoint's dash patterns, in multiples of the line width: "dash" 4 on / 3
# off, "sysDot" 1 on / 1 off.
_LINE_PATTERNS = {"dashed": (4, 3), "dotted": (1, 1)}


def _draw_patterned_line(draw: ImageDraw.ImageDraw, points, color, width: int, pattern: str) -> None:
    """A dashed/dotted polyline, the pattern running on across its corners."""
    on, off = (n * max(1, width) for n in _LINE_PATTERNS[pattern])
    position = 0.0  # where along the pattern the current segment starts
    for (ax, ay), (bx, by) in zip(points, points[1:]):
        length = math.hypot(bx - ax, by - ay)
        t = 0.0
        while t < length:
            phase = position % (on + off)
            step = min(length - t, (on - phase) if phase < on else (on + off - phase))
            if phase < on:
                t0, t1 = t / length, (t + step) / length
                draw.line([(ax + (bx - ax) * t0, ay + (by - ay) * t0), (ax + (bx - ax) * t1, ay + (by - ay) * t1)],
                          fill=color, width=width)
            t += step
            position += step


def _draw_dashed_rect(draw: ImageDraw.ImageDraw, x0, y0, x1, y1, color, width, dash=6, gap=4) -> None:
    def dashed_line(p0, p1):
        (ax, ay), (bx, by) = p0, p1
        length = math.hypot(bx - ax, by - ay)
        if length == 0:
            return
        step = dash + gap
        n = int(length // step) + 1
        for i in range(n):
            t0 = min(1.0, (i * step) / length)
            t1 = min(1.0, (i * step + dash) / length)
            draw.line(
                [(ax + (bx - ax) * t0, ay + (by - ay) * t0), (ax + (bx - ax) * t1, ay + (by - ay) * t1)],
                fill=color,
                width=width,
            )

    dashed_line((x0, y0), (x1, y0))
    dashed_line((x1, y0), (x1, y1))
    dashed_line((x1, y1), (x0, y1))
    dashed_line((x0, y1), (x0, y0))


def _paste_icon(image: Image.Image, png: bytes | None, x: float, y: float, w: float, h: float) -> bool:
    if png is None:
        return False
    try:
        icon = Image.open(io.BytesIO(png)).convert("RGBA").resize((max(1, round(w)), max(1, round(h))))
    except OSError:
        return False
    image.paste(icon, (round(x), round(y)), icon)
    return True


def _draw_container(image, draw: ImageDraw.ImageDraw, box: Box, registry: MultiRegistry, c: _Canvas) -> None:
    style = resolve_container_style(box.element, registry)
    x0, y0, x1, y1 = c.rect((box.abs_x, box.abs_y, box.width, box.height))

    if style.fill_color:
        draw.rectangle([x0, y0, x1, y1], fill=_hex_to_rgba(style.fill_color))

    border = c.color(style.border_color, box.element.id)
    width = c.stroke(style.border_width)  # borderWidth is in points, like the .pptx line
    if style.border_width <= 0:
        pass  # borderWidth 0: no frame, as in the .pptx
    elif style.dashed:
        _draw_dashed_rect(draw, x0, y0, x1, y1, border, width)
    else:
        draw.rectangle([x0, y0, x1, y1], outline=border, width=width)

    label_rect = container_label_rect(box, registry)
    if label_rect is None:
        return
    inset = 4 * PT_TO_LOGICAL  # render.py's 4pt text-frame margin
    lx, ly, lw, lh = label_rect
    badge_png = icon_png(style.corner_icon)[0] if style.corner_icon is not None else None
    badge = badge_png is not None and "left" in style.label_position
    if badge:
        badge_y = ly + CORNER_BADGE_PADDING if "top" in style.label_position else ly + lh - CORNER_BADGE_PADDING - CORNER_BADGE_SIZE
        _paste_icon(image, badge_png, c.x(lx + CORNER_BADGE_PADDING), c.y(badge_y),
                    c.length(CORNER_BADGE_SIZE), c.length(CORNER_BADGE_SIZE))
    left = lx + (CORNER_BADGE_SIZE + CORNER_BADGE_PADDING if badge else inset)
    text_box = c.rect((left, ly + inset, lw - (left - lx) - inset, lh - 2 * inset))
    align = "center" if "center" in style.label_position else "left"
    valign = "bottom" if "bottom" in style.label_position else "top"
    _draw_lines(draw, box.label_lines, c.font(style.label_font_size), text_box, align, valign,
                c.color(style.border_color, box.element.id, inside=True))


def _draw_shape_node(draw: ImageDraw.ImageDraw, box: Box, c: _Canvas) -> None:
    element = box.element
    x0, y0, x1, y1 = c.rect((box.abs_x, box.abs_y, box.width, box.height))
    fill = _hex_to_rgba(element.style.get("fillColor", "#FFFFFF"))
    outline = _hex_to_rgba(element.style.get("borderColor", "#000000"))

    shape = element.style["shape"]
    width = c.stroke(SHAPE_BORDER_PT)
    if shape == "diamond":
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        draw.polygon([(cx, y0), (x1, cy), (cx, y1), (x0, cy)], fill=fill, outline=outline, width=width)
    elif shape == "circle":
        draw.ellipse([x0, y0, x1, y1], fill=fill, outline=outline, width=width)
    elif shape == "rounded":
        # OOXML roundRect: corner radius 1/6 of the shorter side
        radius = min(x1 - x0, y1 - y0) / 6
        draw.rounded_rectangle([x0, y0, x1, y1], radius=radius, fill=fill, outline=outline, width=width)
    else:  # rect
        draw.rectangle([x0, y0, x1, y1], fill=fill, outline=outline, width=width)

    text = _hex_to_rgba(readable_on("#000000", element.style.get("fillColor", "#FFFFFF")))
    _draw_lines(draw, box.label_lines, c.font(node_label_font_size(element)), (x0, y0, x1, y1), "center", "middle", text)


def _draw_node(image: Image.Image, draw: ImageDraw.ImageDraw, box: Box, registry: MultiRegistry, c: _Canvas) -> None:
    element = box.element
    if is_shape_node(element):
        _draw_shape_node(draw, box, c)
        return

    x0, y0, x1, y1 = c.rect((box.abs_x, box.abs_y, box.width, box.height))
    if not _paste_icon(image, registry.node_icon_png(element.type, element.provider), x0, y0, x1 - x0, y1 - y0):
        draw.rectangle([x0, y0, x1, y1], outline=(150, 150, 150, 255))

    rect = node_label_rect(box)
    if rect is None:
        return
    right = element.style.get("labelPosition", "below") == "right"
    _draw_lines(draw, box.label_lines, c.font(node_label_font_size(element)), c.rect(rect),
                "left" if right else "center", "middle" if right else "top", c.color("#1E1E1E", element.id))


def _draw_element(image: Image.Image, draw: ImageDraw.ImageDraw, box: Box, registry: MultiRegistry, c: _Canvas) -> None:
    if box.element.is_container:
        _draw_container(image, draw, box, registry, c)
        for child in box.children:
            _draw_element(image, draw, child, registry, c)
    else:
        _draw_node(image, draw, box, registry, c)


def _draw_arrowhead(draw: ImageDraw.ImageDraw, tip, direction, color, size) -> None:
    dx, dy = direction
    length = math.hypot(dx, dy)
    if length == 0:
        return
    dx, dy = dx / length, dy / length
    perp = (-dy, dx)
    base = (tip[0] - dx * size, tip[1] - dy * size)
    left = (base[0] + perp[0] * size / 2, base[1] + perp[1] * size / 2)
    right = (base[0] - perp[0] * size / 2, base[1] - perp[1] * size / 2)
    draw.polygon([tip, left, right], fill=color)


def _draw_link(draw: ImageDraw.ImageDraw, from_box: Box, to_box: Box, link, c: _Canvas) -> None:
    _, _, _, path = link_render_plan(from_box, to_box, link)
    px_path = [(c.x(x), c.y(y)) for x, y in path]
    line_color = _hex_to_rgba(link.color or readable_on("#545B64", c.canvas_background))
    width = c.stroke(link.width)
    if link.line == "solid":
        draw.line(px_path, fill=line_color, width=width)
    else:
        _draw_patterned_line(draw, px_path, line_color, width, link.line)

    head = c.stroke(3 * link.width)  # a "med" arrowhead is 3x the line width
    if link.arrow in ("end", "both"):
        p0, p1 = px_path[-2], px_path[-1]
        _draw_arrowhead(draw, p1, (p1[0] - p0[0], p1[1] - p0[1]), line_color, head)
    if link.arrow == "both":
        p0, p1 = px_path[1], px_path[0]
        _draw_arrowhead(draw, p1, (p1[0] - p0[0], p1[1] - p0[1]), line_color, head)

    if link.label:
        x0, y0, x1, y1 = c.rect(link_label_rect_for(from_box, to_box, path, link))
        draw.rectangle([x0, y0, x1, y1], fill=LABEL_BG)
        _, _, lines = link_label_box(link.label, link.label_font_size)
        _draw_lines(draw, lines, c.font(link.label_font_size), (x0, y0, x1, y1), "center", "middle", TEXT_COLOR)


def render_preview(diagram: Diagram, root_box: Box, registry: MultiRegistry) -> Image.Image:
    canvas_w, canvas_h = diagram.canvas.size
    c = _Canvas(fit_transform(diagram, root_box), backdrops(root_box, registry, diagram.canvas.background),
                diagram.canvas.background)
    image = Image.new("RGBA", (round(canvas_w * SCALE), round(canvas_h * SCALE)), BACKGROUND)
    if diagram.canvas.background:
        image.paste(_hex_to_rgba(diagram.canvas.background), [0, 0, image.width, image.height])
    draw = ImageDraw.Draw(image)

    for child_box in root_box.children:
        _draw_element(image, draw, child_box, registry, c)

    by_id = {b.element.id: b for b in iter_boxes(root_box)}
    for link in diagram.links:
        from_box, to_box = by_id.get(link.from_id), by_id.get(link.to_id)
        if from_box is not None and to_box is not None:
            _draw_link(draw, from_box, to_box, link, c)

    return image.convert("RGB")
