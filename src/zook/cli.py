"""CLI entry point. Requirements R-OP-02/R-OP-03: YAML -> PPTX, non-zero exit on Fatal.

Subcommands:
  build           YAML -> PPTX (the original single-command behavior).
  validate        Schema + semantic + overlap/crossing checks, no rendering.
  doctor          Auto-resolve sibling/label overlaps by nudging coordinates.
  diff            Semantic structural diff between two diagrams.
  icons list      Show every registered icon type/alias/group.
  preview         YAML -> lightweight PNG, no PowerPoint/LibreOffice needed.
  export-drawio   YAML -> .drawio, for manual editing in draw.io.
  sync            Edited .drawio -> updated YAML (position/size only; see
                  docs/detailed-design-pptx.md sec8.14).
  from-mermaid    Mermaid flowchart (.mmd) -> zook YAML.
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


def _check_raw(raw: dict, user_registry_path: str | None) -> tuple[Diagram, Box, MultiRegistry, Warnings]:
    """Shared by build/validate/from-mermaid: validate (raises DiagramError
    on Fatal), lay out, and collect every Warning-class check. Never renders."""
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


def _load_and_check(input_path: str, user_registry_path: str | None) -> tuple[Diagram, Box, MultiRegistry, Warnings]:
    with open(input_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return _check_raw(raw, user_registry_path)


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
    """zook: generate PowerPoint architecture diagrams from a YAML definition."""


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


def _emit_doctor(fmt: str, result, *, output_path: str | None) -> None:
    """Report what `doctor` changed and what it left for the author, in the
    same three formats the other commands use."""
    moves = [{"id": m.id, "x": m.x, "y": m.y} for m in result.moves]
    link_changes = [
        {
            "from": c.from_id,
            "to": c.to_id,
            "fromSide": c.from_side,
            "toSide": c.to_side,
            "waypoints": None if c.waypoints is None else [{"x": x, "y": y} for x, y in c.waypoints],
        }
        for c in result.link_changes
    ]
    changed = bool(result.moves or result.link_changes)

    def _routing(c: dict) -> str:
        parts = [f"{k}={c[k]}" for k in ("fromSide", "toSide") if c[k] is not None]
        if c["waypoints"]:
            vias = ", ".join(f"({w['x']:g},{w['y']:g})" for w in c["waypoints"])
            parts.append(f"waypoints [{vias}]")
        return ", ".join(parts) if parts else "auto"

    if fmt == "json":
        payload: dict = {
            "status": result.status,
            "moves": moves,
            "linkChanges": link_changes,
            "resolvedOverlaps": result.resolved_overlaps,
            "remaining": result.remaining,
        }
        if output_path is not None:
            payload["output"] = output_path
        print(json.dumps(payload))
        return

    if fmt == "github":
        for m in moves:
            print(f"::notice::moved {m['id']} to x={m['x']:g}, y={m['y']:g}")
        for c in link_changes:
            print(f"::notice::routed link {c['from']} -> {c['to']} via {_routing(c)}")
        for message in result.remaining:
            print(f"::warning::{message}")
        if output_path is not None:
            print(f"Wrote {output_path}")
        return

    # text (default)
    if not changed and result.status == "ok":
        print("No overlaps or link-routing collisions to resolve.")
    else:
        for m in moves:
            print(f"Moved {m['id']} -> x={m['x']:g}, y={m['y']:g}")
        for c in link_changes:
            print(f"Routed link {c['from']} -> {c['to']} via {_routing(c)}")
        if result.status == "partial":
            print("Some collisions could not be resolved automatically.", file=sys.stderr)
    for message in result.remaining:
        print(f"Remaining: {message}", file=sys.stderr)
    if output_path is not None:
        print(f"Wrote {output_path}")
    elif changed:
        print("(dry run - pass -o/--fix to apply these changes)")


@main.command(name="doctor")
@click.argument("input_path", type=click.Path(exists=True, dir_okay=False))
@click.option("-o", "--output", "output_path", default=None, type=click.Path(dir_okay=False),
              help="Write the fixed YAML here (default: dry run - only report proposed positions).")
@click.option("--fix", "fix_in_place", is_flag=True, default=False,
              help="Apply the fixes to INPUT_PATH in place (ignored if -o is given).")
@_registry_option
@_strict_option
@_format_option
def doctor_cmd(input_path: str, output_path: str | None, fix_in_place: bool,
               user_registry_path: str | None, strict: bool, fmt: str) -> None:
    """Auto-resolve overlaps and link-routing collisions in INPUT_PATH.

    Four stages: (1) separate the sibling-vs-sibling and element-vs-container-
    label overlaps `validate` detects, by writing explicit x/y; (2) clear link
    crossings and false-edge aliasing by assigning fromSide/toSide; (3) when no
    side re-routes around an obstacle, slide the (auto-placed) obstacle out of
    the path; (4) if the obstacle can't move (author-pinned), detour the link
    around it with waypoints. Every change is verified so the diagram never
    gets worse. A collision none of the stages can remove is reported under
    `remaining`, along with off-canvas and placeholder-icon warnings (which
    doctor never touches) - handle those via draw.io or by editing the YAML.

    Defaults to a dry run that only proposes the changes; pass -o PATH or --fix
    to write them. Comments and key ordering in the original file are kept.
    """
    from ruamel.yaml import YAML

    from .doctor import diagnose_and_fix
    from .drawio import dump_yaml

    yaml_rt = YAML()
    yaml_rt.preserve_quotes = True
    with open(input_path, encoding="utf-8") as f:
        raw = yaml_rt.load(f)

    try:
        validate(raw)
    except DiagramError as exc:
        _emit(fmt, status="error", warning_messages=[], error=str(exc))
        sys.exit(1)

    registry = load_registries(user_registry_path=user_registry_path)
    result = diagnose_and_fix(raw, registry)

    changed = bool(result.moves or result.link_changes)
    dest = output_path or (input_path if fix_in_place else None)
    if dest is not None and changed:
        dump_yaml(raw, dest)

    _emit_doctor(fmt, result, output_path=dest if changed else None)
    if strict and result.status == "partial":
        sys.exit(1)


def _fmt_value(value) -> str:
    if value is None:
        return "none"
    if isinstance(value, str):
        return f'"{value}"'
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return f"{value}"


def _fmt_changes(changes) -> str:
    return "; ".join(f"{c.field} {_fmt_value(c.old)} -> {_fmt_value(c.new)}" for c in changes)


def _emit_diff(fmt: str, result) -> None:
    if fmt == "json":
        payload = {
            "identical": result.identical,
            "canvas": [{"field": c.field, "old": c.old, "new": c.new} for c in result.canvas],
            "elements": {
                "added": [{"id": r.id, "kind": r.kind, "type": r.type, "parent": r.parent} for r in result.added_elements],
                "removed": [{"id": r.id, "kind": r.kind, "type": r.type, "parent": r.parent} for r in result.removed_elements],
                "reparented": [{"id": r.id, "from": r.old_parent, "to": r.new_parent} for r in result.reparented],
                "modified": [
                    {"id": m.id, "kind": m.kind, "type": m.type,
                     "changes": [{"field": c.field, "old": c.old, "new": c.new} for c in m.changes]}
                    for m in result.modified_elements
                ],
            },
            "links": {
                "added": [{"from": r.from_id, "to": r.to_id, "id": r.id} for r in result.added_links],
                "removed": [{"from": r.from_id, "to": r.to_id, "id": r.id} for r in result.removed_links],
                "modified": [
                    {"from": m.from_id, "to": m.to_id, "id": m.id,
                     "changes": [{"field": c.field, "old": c.old, "new": c.new} for c in m.changes]}
                    for m in result.modified_links
                ],
            },
        }
        print(json.dumps(payload))
        return

    lines: list[str] = []
    for c in result.canvas:
        lines.append(f"~ canvas.{c.field}: {_fmt_value(c.old)} -> {_fmt_value(c.new)}")
    for r in result.added_elements:
        where = f" in {r.parent}" if r.parent else ""
        lines.append(f"+ {r.id} ({r.kind} {r.type}){where}")
    for r in result.removed_elements:
        where = f" in {r.parent}" if r.parent else ""
        lines.append(f"- {r.id} ({r.kind} {r.type}){where}")
    for r in result.reparented:
        lines.append(f"> {r.id}: moved {r.old_parent or '(root)'} -> {r.new_parent or '(root)'}")
    for m in result.modified_elements:
        lines.append(f"~ {m.id} ({m.kind} {m.type}): {_fmt_changes(m.changes)}")
    for r in result.added_links:
        lines.append(f"+ link {r.from_id} -> {r.to_id}")
    for r in result.removed_links:
        lines.append(f"- link {r.from_id} -> {r.to_id}")
    for m in result.modified_links:
        lines.append(f"~ link {m.from_id} -> {m.to_id}: {_fmt_changes(m.changes)}")

    if fmt == "github":
        for line in lines:
            print(f"::notice::{line}")
        return

    # text (default)
    if result.identical:
        print("No structural differences.")
        return
    for line in lines:
        print(line)


@main.command(name="diff")
@click.argument("old_path", type=click.Path(exists=True, dir_okay=False))
@click.argument("new_path", type=click.Path(exists=True, dir_okay=False))
@click.option("--exit-code", "exit_code", is_flag=True, default=False,
              help="Exit non-zero (1) if the diagrams differ, like `git diff --exit-code`.")
@_format_option
def diff_cmd(old_path: str, new_path: str, exit_code: bool, fmt: str) -> None:
    """Show the structural difference between two diagrams (OLD_PATH -> NEW_PATH).

    Matches elements by `id` and links by id-or-endpoints and reports what
    actually changed - elements added, removed, moved between containers, or
    modified field-by-field; links added/removed/modified; canvas changes -
    rather than the line noise a text diff would show. Values left to their
    default on one side and written explicitly on the other are not reported.
    """
    from .diff import diff_diagrams

    try:
        with open(old_path, encoding="utf-8") as f:
            old_raw = yaml.safe_load(f)
        with open(new_path, encoding="utf-8") as f:
            new_raw = yaml.safe_load(f)
        validate(old_raw)
        validate(new_raw)
    except DiagramError as exc:
        _emit(fmt, status="error", warning_messages=[], error=str(exc))
        sys.exit(1)

    result = diff_diagrams(old_raw, new_raw)
    _emit_diff(fmt, result)
    if exit_code and not result.identical:
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
                    {"type": e.name, "aliases": e.aliases, "category": e.category}
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


@main.command(name="export-drawio")
@click.argument("input_path", type=click.Path(exists=True, dir_okay=False))
@click.option("-o", "--output", "output_path", required=True, type=click.Path(dir_okay=False), help="Output .drawio path.")
@_registry_option
@_format_option
def export_drawio_cmd(input_path: str, output_path: str, user_registry_path: str | None, fmt: str) -> None:
    """Export INPUT_PATH as a .drawio file for manual editing in draw.io."""
    from .drawio import export_drawio

    try:
        diagram, root_box, registry, warnings = _load_and_check(input_path, user_registry_path)
    except DiagramError as exc:
        _emit(fmt, status="error", warning_messages=[], error=str(exc))
        sys.exit(1)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(export_drawio(diagram, root_box, registry))

    status = "warning" if warnings.messages else "ok"
    _emit(fmt, status=status, warning_messages=warnings.messages, output_path=output_path)


@main.command(name="sync")
@click.argument("yaml_path", type=click.Path(exists=True, dir_okay=False))
@click.argument("drawio_path", type=click.Path(exists=True, dir_okay=False))
@click.option("-o", "--output", "output_path", type=click.Path(dir_okay=False), help="Where to write the updated YAML (default: overwrite YAML_PATH).")
@_registry_option
@_format_option
def sync_cmd(yaml_path: str, drawio_path: str, output_path: str | None, user_registry_path: str | None, fmt: str) -> None:
    """Sync position/size changes made in an edited DRAWIO_PATH back into YAML_PATH.

    Only elements whose position or size actually changed (vs. what the
    original YAML's auto-layout would have produced) are touched; added/
    removed shapes and style/color changes made in draw.io are not synced
    - see docs/detailed-design-pptx.md sec8.14.
    """
    from .drawio import dump_yaml, sync_from_drawio

    try:
        updated, warnings = sync_from_drawio(yaml_path, drawio_path, user_registry_path=user_registry_path)
    except DiagramError as exc:
        _emit(fmt, status="error", warning_messages=[], error=str(exc))
        sys.exit(1)

    dest = output_path or yaml_path
    dump_yaml(updated, dest)

    status = "warning" if warnings else "ok"
    _emit(fmt, status=status, warning_messages=warnings, output_path=dest)


@main.command(name="from-mermaid")
@click.argument("input_path", type=click.Path(exists=True, dir_okay=False))
@click.option("-o", "--output", "output_path", required=True, type=click.Path(dir_okay=False), help="Output YAML path.")
@_registry_option
@_strict_option
@_format_option
def from_mermaid_cmd(input_path: str, output_path: str, user_registry_path: str | None, strict: bool, fmt: str) -> None:
    """Convert a Mermaid flowchart (INPUT_PATH, e.g. *.mmd) to zook YAML.

    Only `flowchart`/`graph` syntax is supported (sequenceDiagram and other
    Mermaid diagram types are not) - see docs-site/mermaid-import.md for the
    exact supported subset. The generated YAML is validated the same way
    `build`/`validate` do before being written, so Fatal/Warning issues are
    reported here; the result feeds straight into the existing
    validate/build/export-drawio/sync pipeline.
    """
    from .mermaid_flowchart import parse_flowchart

    with open(input_path, encoding="utf-8") as f:
        text = f.read()

    try:
        raw = parse_flowchart(text)
        _diagram, _root_box, _registry, warnings = _check_raw(raw, user_registry_path)
    except DiagramError as exc:
        _emit(fmt, status="error", warning_messages=[], error=str(exc))
        sys.exit(1)

    # yaml.safe_dump (not drawio.dump_yaml's ruamel round-trip dumper): this
    # writes a fresh file with no existing comments/ordering to preserve, and
    # PyYAML's resolver-aware quoting is what protects "16:9"/"yes"/"no"/etc.
    # from being misread back as a sexagesimal int or bool - which is exactly
    # how they're read elsewhere in this codebase (yaml.safe_load).
    with open(output_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(raw, f, sort_keys=False, allow_unicode=True)

    status = "warning" if warnings.messages else "ok"
    _emit(fmt, status=status, warning_messages=warnings.messages, output_path=output_path)
    if strict and warnings.messages:
        sys.exit(1)


if __name__ == "__main__":
    main()
