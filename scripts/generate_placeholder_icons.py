"""Generate placeholder PNG icons for the Tier-1 aws/gcp/azure vocabularies.

These are NOT official cloud-provider icons (not sourced/licensed here) -
just distinct, readable stand-ins so the tool is runnable end-to-end.
Swapping in real vendor icons later is a drop-in file replacement: keep the
same `file` paths in each registry.<provider>.yaml, no code changes needed
(per docs/icon-registry-and-vocabulary.md sec8).

Rasterization follows the confirmed decision in
docs/detailed-design-pptx.md sec8.6: render at 4x the logical display size
(here, the registry's default icon size of 64 logical units -> 256px).

Usage: .venv/bin/python scripts/generate_placeholder_icons.py
"""

from __future__ import annotations

from pathlib import Path

import cairosvg
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
PROVIDERS = ["aws", "gcp", "azure"]
RASTER_SCALE = 4  # confirmed in detailed-design-pptx.md sec8.6

CATEGORY_COLORS = {
    "Compute": "#ED7100",
    "Storage": "#7AA116",
    "Database": "#527FFF",
    "Networking": "#8C4FFF",
    "Integration": "#E7157B",
    "Security": "#DD344C",
    "General": "#3B48CC",
}
DEFAULT_COLOR = "#5A6B86"


def _abbrev(key: str) -> str:
    return key[:4].upper()


def _icon_svg(label: str, color: str) -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <rect x="2" y="2" width="60" height="60" rx="8" fill="{color}" stroke="#232F3E" stroke-width="1.5"/>
  <text x="32" y="38" font-family="Helvetica,Arial,sans-serif" font-size="13" font-weight="bold"
        fill="#ffffff" text-anchor="middle">{label}</text>
</svg>"""


def _actor_svg(label: str, color: str) -> str:
    """Circle badge (vs. the rounded-square service icons) to visually mark
    non-service actors (people/roles) at a glance, per the request to make
    users/admins in a diagram distinguishable from AWS services. No in-badge
    text: the node's own `label` is already rendered under the icon by the
    renderer, and every actor type shares this one person glyph on purpose."""
    del label  # kept for call-site symmetry with _icon_svg; unused here
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <circle cx="32" cy="32" r="30" fill="{color}" stroke="#232F3E" stroke-width="1.5"/>
  <circle cx="32" cy="24" r="10" fill="#ffffff"/>
  <path d="M 14 52 C 14 38 50 38 50 52 Z" fill="#ffffff"/>
</svg>"""


def _cloud_badge_svg(color: str) -> str:
    """Small corner badge for a container's `groups.<type>.icon` (e.g. the
    AWS Cloud boundary), rendered next to the container label."""
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <path d="M 46 40 H 18 A 10 10 0 0 1 16 20.4 A 13 13 0 0 1 41.5 16.8
           A 10 10 0 0 1 46 40 Z" fill="{color}"/>
</svg>"""


def _placeholder_svg() -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <rect x="2" y="2" width="60" height="60" rx="8" fill="{DEFAULT_COLOR}" stroke="#232F3E"
        stroke-width="1.5" stroke-dasharray="4,3"/>
  <text x="32" y="42" font-family="Helvetica,Arial,sans-serif" font-size="26" font-weight="bold"
        fill="#ffffff" text-anchor="middle">?</text>
</svg>"""


def _rasterize(svg_text: str, out_path: Path, size_logical_units: float) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    px = int(round(size_logical_units * RASTER_SCALE))
    cairosvg.svg2png(bytestring=svg_text.encode("utf-8"), write_to=str(out_path), output_width=px, output_height=px)


def _generate_for_provider(provider: str) -> None:
    registry_path = REPO_ROOT / f"src/archdiagram/data/icons/{provider}/registry.{provider}.yaml"
    out_dir = registry_path.parent
    registry = yaml.safe_load(registry_path.read_text())
    default_size = registry.get("defaults", {}).get("size", 64)

    for key, spec in registry["icons"].items():
        category = spec.get("category")
        color = CATEGORY_COLORS.get(category, DEFAULT_COLOR)
        svg_text = _actor_svg(_abbrev(key), color) if category == "General" else _icon_svg(_abbrev(key), color)
        out_path = out_dir / spec["file"]
        size = spec.get("size", default_size)
        _rasterize(svg_text, out_path, size)
        print(f"wrote {out_path}")

    placeholder_path = out_dir / "_placeholder.png"
    _rasterize(_placeholder_svg(), placeholder_path, default_size)
    print(f"wrote {placeholder_path}")

    badge_size = 28  # corner badge, smaller than a regular service icon
    for spec in registry.get("groups", {}).values():
        if not spec.get("icon"):
            continue
        out_path = out_dir / spec["icon"]
        # Corner badge uses the group's own brand border color (e.g. AWS
        # squid ink, Google blue, Azure blue) instead of one fixed color.
        _rasterize(_cloud_badge_svg(spec.get("borderColor", DEFAULT_COLOR)), out_path, badge_size)
        print(f"wrote {out_path}")


def main() -> None:
    for provider in PROVIDERS:
        _generate_for_provider(provider)


if __name__ == "__main__":
    main()
