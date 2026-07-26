"""CLI entry point. Requirements R-OP-02/R-OP-03: YAML -> PPTX, non-zero exit on Fatal.

Subcommands:
  build     YAML -> PPTX (the original single-command behavior).
  validate  Schema + semantic + overlap/crossing checks, no rendering.
  icons     list          Show every registered icon type/alias/group.
  preview   YAML -> lightweight PNG, no PowerPoint/LibreOffice needed.
"""

from __future__ import annotations

import json
import sys

import click
import yaml

from .errors import DiagramError, Warnings
from .layout import (
    Box,
    build_layout,
    icon_resolution_warnings,
    link_aliasing_warnings,
    link_crossing_warnings,
    out_of_canvas_warnings,
    overlap_warnings,
)
from .model import Diagram, parse_diagram
from .registry import MultiRegistry, load_registries
from .render import render
from .validate import validate

FORMAT_CHOICES = ["text", "json", "github"]


def _emit(fmt: str, *, status: str, warning_messages: list[str], error: str | None = None, output_path: str | None = None) -> None:
    if fmt == "json":
        payload: dict = {"status": status, "warnings": warning_messages}
        if error is not None:
            payload["error"] = error
        if output_path is not None:
            payload["output"] = output_path
        print(json.dumps(payload))
        return

    if fmt == "github":
        for message in warning_messages:
            print(f"::warning::{message}")
        if error is not None:
            print(f"::error::{error}")
        elif output_path is not None:
            print(f"Wrote {output_path}")
        return

    # text (default)
    for message in warning_messages:
        print(f"Warning: {message}", file=sys.stderr)
    if error is not None:
        print(f"Error: {error}", file=sys.stderr)
    elif output_path is not None:
        print(f"Wrote {output_path}")


def _load_and_check(input_path: str, user_registry_path: str | None) -> tuple[Diagram, Box, MultiRegistry, Warnings]:
    """Shared by build/validate: parse, validate (raises DiagramError on
    Fatal), lay out, and collect every Warning-class check. Never renders."""
    with open(input_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    validate(raw)
    diagram = parse_diagram(raw)
    registry = load_registries(user_registry_path=user_registry_path)
    root_box = build_layout(diagram, registry)

    warnings = Warnings()
    margin = diagram.canvas.overlap_margin
    for message in icon_resolution_warnings(root_box, registry):
        warnings.add(message)
    for message in out_of_canvas_warnings(root_box, *diagram.canvas.size):
        warnings.add(message)
    for message in overlap_warnings(root_box, registry, margin):
        warnings.add(message)
    for message in link_crossing_warnings(root_box, diagram.links, registry, margin):
        warnings.add(message)
    for message in link_aliasing_warnings(root_box, diagram.links):
        warnings.add(message)

    return diagram, root_box, registry, warnings


_registry_option = click.option(
    "--registry",
    "user_registry_path",
    type=click.Path(exists=True, dir_okay=False),
    default=None,
    help="Optional icon registry YAML layered on top of its declared provider's built-in registry.",
)
_strict_option = click.option(
    "--strict", is_flag=True, default=False, help="Exit non-zero if any Warning was raised, not just on Fatal errors."
)
_format_option = click.option(
    "--format",
    "fmt",
    type=click.Choice(FORMAT_CHOICES),
    default="text",
    help="Output format: text (default, human-readable), json (one machine-readable object), "
    "github (GitHub Actions ::warning::/::error:: annotations).",
)


@click.group()
def main() -> None:
    """archdiagram: generate PowerPoint architecture diagrams from a YAML definition."""


@main.command()
@click.argument("input_path", type=click.Path(exists=True, dir_okay=False))
@click.option("-o", "--output", "output_path", required=True, type=click.Path(dir_okay=False), help="Output .pptx path.")
@_registry_option
@_strict_option
@_format_option
def build(input_path: str, output_path: str, user_registry_path: str | None, strict: bool, fmt: str) -> None:
    """Generate a .pptx from INPUT_PATH."""
    try:
        diagram, root_box, registry, warnings = _load_and_check(input_path, user_registry_path)
        presentation = render(diagram, root_box, registry)
        presentation.save(output_path)
    except DiagramError as exc:
        _emit(fmt, status="error", warning_messages=[], error=str(exc))
        sys.exit(1)

    status = "warning" if warnings.messages else "ok"
    _emit(fmt, status=status, warning_messages=warnings.messages, output_path=output_path)
    if strict and warnings.messages:
        sys.exit(1)


@main.command(name="validate")
@click.argument("input_path", type=click.Path(exists=True, dir_okay=False))
@_registry_option
@_strict_option
@_format_option
def validate_cmd(input_path: str, user_registry_path: str | None, strict: bool, fmt: str) -> None:
    """Check INPUT_PATH for Fatal/Warning issues without rendering a .pptx."""
    try:
        _diagram, _root_box, _registry, warnings = _load_and_check(input_path, user_registry_path)
    except DiagramError as exc:
        _emit(fmt, status="error", warning_messages=[], error=str(exc))
        sys.exit(1)

    status = "warning" if warnings.messages else "ok"
    _emit(fmt, status=status, warning_messages=warnings.messages)
    if strict and warnings.messages:
        sys.exit(1)


@main.group()
def icons() -> None:
    """Inspect the icon/group registry."""


@icons.command("list")
@click.option(
    "--provider",
    type=click.Choice(["aws", "gcp", "azure"]),
    default=None,
    help="Limit output to a single provider's registry (default: all built-in providers).",
)
@_registry_option
@_format_option
def icons_list(provider: str | None, user_registry_path: str | None, fmt: str) -> None:
    """List every registered icon type/alias and container group."""
    multi = load_registries(user_registry_path=user_registry_path)
    providers = [provider] if provider else list(multi.registries.keys())

    def unique_entries(mapping):
        seen: dict[int, object] = {}
        for entry in mapping.values():
            seen.setdefault(id(entry), entry)
        return seen.values()

    if fmt == "json":
        payload = {}
        for p in providers:
            registry = multi.registries[p]
            payload[p] = {
                "icons": [
                    {"type": e.name, "aliases": e.aliases, "category": e.category, "file": str(e.file)}
                    for e in unique_entries(registry.icons)
                ],
                "groups": [
                    {"type": e.name, "aliases": e.aliases, "label": e.label} for e in unique_entries(registry.groups)
                ],
            }
        print(json.dumps(payload))
        return

    for p in providers:
        registry = multi.registries[p]
        if not registry.icons and not registry.groups:
            continue
        print(f"[{p}]")
        for entry in unique_entries(registry.icons):
            category = entry.category or "-"
            alias_suffix = f" (aliases: {', '.join(entry.aliases)})" if entry.aliases else ""
            print(f"  node   {entry.name:<20} [{category}]{alias_suffix}")
        for entry in unique_entries(registry.groups):
            alias_suffix = f" (aliases: {', '.join(entry.aliases)})" if entry.aliases else ""
            print(f"  group  {entry.name:<20}{alias_suffix}")


@main.command()
@click.argument("input_path", type=click.Path(exists=True, dir_okay=False))
@click.option("-o", "--output", "output_path", required=True, type=click.Path(dir_okay=False), help="Output .png path.")
@_registry_option
def preview(input_path: str, output_path: str, user_registry_path: str | None) -> None:
    """Render a quick PNG preview of INPUT_PATH (no PowerPoint/LibreOffice needed)."""
    from .preview import render_preview

    try:
        diagram, root_box, registry, warnings = _load_and_check(input_path, user_registry_path)
    except DiagramError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    warnings.emit()
    render_preview(diagram, root_box, registry).save(output_path)
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
