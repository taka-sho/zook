"""Lightweight PNG preview - no PowerPoint/LibreOffice needed.

Draws the same Box tree and link_render_plan() geometry render.py uses for
the real .pptx, but with Pillow directly, so a diagram can be sanity-checked
in CI or a terminal without opening PowerPoint. Visual fidelity is
approximate (rectangles/lines/text, no shadows or true typography) - it's a
fast structural preview, not a substitute for the real output.
"""

from __future__ import annotations

import math

from PIL import Image, ImageDraw, ImageFont

from .layout import (
    Box,
    content_offset,
    iter_boxes,
    label_gap,
    link_label_size,
    link_render_plan,
    node_label_font_size,
    resolve_container_style,
)
from .model import Diagram
from .registry import MultiRegistry

SCALE = 1.5  # px per logical unit
BACKGROUND = (255, 255, 255, 255)
TEXT_COLOR = (30, 30, 30, 255)
LINE_COLOR = (84, 91, 100, 255)
LABEL_BG = (255, 255, 255, 230)


def _hex_to_rgba(color: str, alpha: int = 255) -> tuple[int, int, int, int]:
    color = color.lstrip("#")
    return int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16), alpha


def _px(value: float) -> float:
    return value * SCALE


def _font(size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1 doesn't accept a size kwarg here
        return ImageFont.load_default()


def _text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> tuple[float, float]:
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    return right - left, bottom - top


def _draw_centered_text(draw: ImageDraw.ImageDraw, cx: float, y: float, text: str, font, fill) -> None:
    w, _ = _text_size(draw, text, font)
    draw.text((cx - w / 2, y), text, font=font, fill=fill)


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


def _draw_container(draw: ImageDraw.ImageDraw, box: Box, registry: MultiRegistry) -> None:
    style = resolve_container_style(box.element, registry)
    x0, y0 = _px(box.abs_x), _px(box.abs_y)
    x1, y1 = _px(box.abs_x + box.width), _px(box.abs_y + box.height)

    if style.fill_color:
        draw.rectangle([x0, y0, x1, y1], fill=_hex_to_rgba(style.fill_color))

    border = _hex_to_rgba(style.border_color)
    width = max(1, round(style.border_width))
    if style.dashed:
        _draw_dashed_rect(draw, x0, y0, x1, y1, border, width)
    else:
        draw.rectangle([x0, y0, x1, y1], outline=border, width=width)

    if style.label_text:
        font = _font(round(style.label_font_size))
        label_y = y0 + 4 if "top" in style.label_position else y1 - 20
        label_x = (x0 + x1) / 2 if "center" in style.label_position else x0 + 6
        if "center" in style.label_position:
            _draw_centered_text(draw, label_x, label_y, style.label_text, font, border)
        else:
            draw.text((label_x, label_y), style.label_text, font=font, fill=border)


def _draw_node(image: Image.Image, draw: ImageDraw.ImageDraw, box: Box, registry: MultiRegistry) -> None:
    element = box.element
    icon_entry = registry.resolve_icon(element.type, element.provider)
    icon_path = icon_entry.file if (icon_entry and icon_entry.file.exists()) else registry.placeholder_icon

    try:
        icon = Image.open(icon_path).convert("RGBA")
        size = (max(1, round(_px(box.width))), max(1, round(_px(box.height))))
        icon = icon.resize(size)
        image.paste(icon, (round(_px(box.abs_x)), round(_px(box.abs_y))), icon)
    except OSError:
        draw.rectangle(
            [_px(box.abs_x), _px(box.abs_y), _px(box.abs_x + box.width), _px(box.abs_y + box.height)],
            outline=(150, 150, 150, 255),
        )

    label_position = element.style.get("labelPosition", "below")
    if label_position == "none":
        return
    label_text = element.label if element.label is not None else (
        icon_entry.label if icon_entry and icon_entry.label else element.type
    )
    font_size = node_label_font_size(element)
    font = _font(round(font_size))
    gap = label_gap(element)
    dx, dy = content_offset(box)
    footprint_x = _px(box.abs_x - dx)
    footprint_w = _px(box.footprint_w)
    if label_position == "below":
        _draw_centered_text(draw, footprint_x + footprint_w / 2, _px(box.abs_y + box.height + gap), label_text, font, TEXT_COLOR)
    elif label_position == "above":
        _draw_centered_text(draw, footprint_x + footprint_w / 2, _px(box.abs_y - dy), label_text, font, TEXT_COLOR)
    else:  # right
        draw.text((_px(box.abs_x + box.width + gap), _px(box.abs_y)), label_text, font=font, fill=TEXT_COLOR)


def _draw_element(image: Image.Image, draw: ImageDraw.ImageDraw, box: Box, registry: MultiRegistry) -> None:
    if box.element.is_container:
        _draw_container(draw, box, registry)
        for child in box.children:
            _draw_element(image, draw, child, registry)
    else:
        _draw_node(image, draw, box, registry)


def _draw_arrowhead(draw: ImageDraw.ImageDraw, tip, direction, color, size=8) -> None:
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


def _draw_link(draw: ImageDraw.ImageDraw, from_box: Box, to_box: Box, link, registry: MultiRegistry) -> None:
    _, _, _, path = link_render_plan(from_box, to_box, link.style)
    px_path = [(_px(x), _px(y)) for x, y in path]
    draw.line(px_path, fill=LINE_COLOR, width=2)

    if link.arrow in ("end", "both"):
        p0, p1 = px_path[-2], px_path[-1]
        _draw_arrowhead(draw, p1, (p1[0] - p0[0], p1[1] - p0[1]), LINE_COLOR)
    if link.arrow == "both":
        p0, p1 = px_path[1], px_path[0]
        _draw_arrowhead(draw, p1, (p1[0] - p0[0], p1[1] - p0[1]), LINE_COLOR)

    if link.label:
        font = _font(round(link.label_font_size))
        p1, p2 = path[0], path[-1]
        mx, my = _px((p1[0] + p2[0]) / 2), _px((p1[1] + p2[1]) / 2)
        label_w, label_h = link_label_size(link.label_font_size)
        w, h = _px(label_w), _px(label_h)
        draw.rectangle([mx - w / 2, my - h / 2, mx + w / 2, my + h / 2], fill=LABEL_BG)
        text_w, text_h = _text_size(draw, link.label, font)
        draw.text((mx - text_w / 2, my - text_h / 2), link.label, font=font, fill=TEXT_COLOR)


def render_preview(diagram: Diagram, root_box: Box, registry: MultiRegistry) -> Image.Image:
    canvas_w, canvas_h = diagram.canvas.size
    image = Image.new("RGBA", (round(_px(canvas_w)), round(_px(canvas_h))), BACKGROUND)
    if diagram.canvas.background:
        image.paste(_hex_to_rgba(diagram.canvas.background), [0, 0, image.width, image.height])
    draw = ImageDraw.Draw(image)

    for child_box in root_box.children:
        _draw_element(image, draw, child_box, registry)

    by_id = {b.element.id: b for b in iter_boxes(root_box)}
    for link in diagram.links:
        from_box, to_box = by_id.get(link.from_id), by_id.get(link.to_id)
        if from_box is not None and to_box is not None:
            _draw_link(draw, from_box, to_box, link, registry)

    return image.convert("RGB")
