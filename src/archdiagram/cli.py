"""CLI entry point. Requirements R-OP-02/R-OP-03: YAML -> PPTX, non-zero exit on Fatal."""

from __future__ import annotations

import sys

import click
import yaml

from .errors import DiagramError, Warnings
from .layout import build_layout, link_crossing_warnings, out_of_canvas_warnings, overlap_warnings
from .model import parse_diagram
from .registry import load_registry
from .render import render
from .validate import validate


@click.command()
@click.argument("input_path", type=click.Path(exists=True, dir_okay=False))
@click.option("-o", "--output", "output_path", required=True, type=click.Path(dir_okay=False), help="Output .pptx path.")
@click.option(
    "--registry",
    "user_registry_path",
    type=click.Path(exists=True, dir_okay=False),
    default=None,
    help="Optional icon registry YAML layered on top of the built-in AWS registry (same keys override).",
)
def main(input_path: str, output_path: str, user_registry_path: str | None) -> None:
    warnings = Warnings()
    try:
        with open(input_path, encoding="utf-8") as f:
            raw = yaml.safe_load(f)

        validate(raw)
        diagram = parse_diagram(raw)
        registry = load_registry(provider="aws", user_registry_path=user_registry_path)
        root_box = build_layout(diagram, registry)
        margin = diagram.canvas.overlap_margin
        for message in out_of_canvas_warnings(root_box, *diagram.canvas.size):
            warnings.add(message)
        for message in overlap_warnings(root_box, margin):
            warnings.add(message)
        for message in link_crossing_warnings(root_box, diagram.links, margin):
            warnings.add(message)

        presentation = render(diagram, root_box, registry, warnings)
        presentation.save(output_path)
    except DiagramError as exc:
        warnings.emit()
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    warnings.emit()
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
