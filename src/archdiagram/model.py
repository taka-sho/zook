"""In-memory representation of a parsed diagram, per docs/yaml-spec.md."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

ASPECT_RATIOS = {
    # aspectRatio -> (logical width, logical height)
    "16:9": (1280, 720),
    "4:3": (960, 720),
}


@dataclass
class Canvas:
    aspect_ratio: str
    padding: float = 40
    background: Optional[str] = None
    overlap_margin: float = 0

    @property
    def size(self) -> tuple[float, float]:
        return ASPECT_RATIOS[self.aspect_ratio]


@dataclass
class Layout:
    direction: str = "grid"
    columns: Optional[int] = None
    gap: float = 24
    padding: float = 32


@dataclass
class Element:
    kind: str  # "container" | "node"
    id: str
    type: str
    provider: str
    label: Optional[str] = None
    x: Optional[float] = None
    y: Optional[float] = None
    width: Optional[float] = None
    height: Optional[float] = None
    size: Optional[float] = None  # node-only shorthand for width+height; ignored on an axis width/height sets explicitly
    style: dict[str, Any] = field(default_factory=dict)
    layout: Optional[Layout] = None
    children: list["Element"] = field(default_factory=list)

    @property
    def is_container(self) -> bool:
        return self.kind == "container"

    @property
    def has_explicit_position(self) -> bool:
        return self.x is not None and self.y is not None


@dataclass
class Link:
    from_id: str
    to_id: str
    id: Optional[str] = None
    arrow: str = "end"
    style: str = "straight"
    label: Optional[str] = None
    label_font_size: float = 8
    from_side: Optional[str] = None  # "top"|"bottom"|"left"|"right"; None -> auto
    to_side: Optional[str] = None


@dataclass
class Diagram:
    canvas: Canvas
    elements: list[Element]
    links: list[Link] = field(default_factory=list)


def _parse_layout(raw: Optional[dict]) -> Optional[Layout]:
    if raw is None:
        return None
    return Layout(
        direction=raw.get("direction", "grid"),
        columns=raw.get("columns"),
        gap=raw.get("gap", 24),
        padding=raw.get("padding", 32),
    )


def _parse_element(raw: dict) -> Element:
    default_provider = "generic" if raw["kind"] == "container" else "aws"
    return Element(
        kind=raw["kind"],
        id=raw["id"],
        type=raw["type"],
        provider=raw.get("provider", default_provider),
        label=raw.get("label"),
        x=raw.get("x"),
        y=raw.get("y"),
        width=raw.get("width"),
        height=raw.get("height"),
        size=raw.get("size"),
        style=raw.get("style", {}),
        layout=_parse_layout(raw.get("layout")),
        children=[_parse_element(c) for c in raw.get("children", [])],
    )


def _parse_link(raw: dict) -> Link:
    return Link(
        from_id=raw["from"],
        to_id=raw["to"],
        id=raw.get("id"),
        arrow=raw.get("arrow", "end"),
        style=raw.get("style", "straight"),
        label=raw.get("label"),
        label_font_size=raw.get("labelFontSize", 8),
        from_side=raw.get("fromSide"),
        to_side=raw.get("toSide"),
    )


def parse_diagram(raw: dict) -> Diagram:
    """Build the in-memory model from a schema-valid dict.

    Caller must have already validated `raw` against arch-diagram.schema.json.
    """
    canvas_raw = raw["canvas"]
    canvas = Canvas(
        aspect_ratio=canvas_raw["aspectRatio"],
        padding=canvas_raw.get("padding", 40),
        background=canvas_raw.get("background"),
        overlap_margin=canvas_raw.get("overlapMargin", 0),
    )
    elements = [_parse_element(e) for e in raw["elements"]]
    links = [_parse_link(link) for link in raw.get("links", [])]
    return Diagram(canvas=canvas, elements=elements, links=links)
