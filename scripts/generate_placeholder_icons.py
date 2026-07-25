"""Generate placeholder PNG icons for the Tier-1 AWS vocabulary.

These are NOT official AWS icons (not sourced/licensed here) - just distinct,
readable stand-ins so the tool is runnable end-to-end. Swapping in the real
AWS Architecture Icons later is a drop-in file replacement: keep the same
`file` paths in registry.aws.yaml, no code changes needed (per
docs/icon-registry-and-vocabulary.md sec8).

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
REGISTRY_PATH = REPO_ROOT / "src/archdiagram/data/icons/aws/registry.aws.yaml"
OUT_DIR = REGISTRY_PATH.parent
RASTER_SCALE = 4  # confirmed in detailed-design-pptx.md sec8.6

CATEGORY_COLORS = {
    "Compute": "#ED7100",
    "Storage": "#7AA116",
    "Database": "#527FFF",
    "Networking": "#8C4FFF",
    "Integration": "#E7157B",
    "Security": "#DD344C",
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


def main() -> None:
    registry = yaml.safe_load(REGISTRY_PATH.read_text())
    default_size = registry.get("defaults", {}).get("size", 64)

    for key, spec in registry["icons"].items():
        color = CATEGORY_COLORS.get(spec.get("category"), DEFAULT_COLOR)
        svg_text = _icon_svg(_abbrev(key), color)
        out_path = OUT_DIR / spec["file"]
        size = spec.get("size", default_size)
        _rasterize(svg_text, out_path, size)
        print(f"wrote {out_path}")

    placeholder_path = OUT_DIR / "_placeholder.png"
    _rasterize(_placeholder_svg(), placeholder_path, default_size)
    print(f"wrote {placeholder_path}")


if __name__ == "__main__":
    main()
