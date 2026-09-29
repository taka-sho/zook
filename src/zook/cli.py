"""CLI entry point. Requirements R-OP-02/R-OP-03: YAML -> PPTX, non-zero exit on Fatal.

Subcommands:
  build           YAML -> PPTX (the original single-command behavior).
  validate        Schema + semantic + overlap/crossing checks, no rendering.
  doctor          Auto-resolve overlaps and link-routing collisions (four
                  verified stages: nudge, re-side, displace, detour).
  diff            Semantic structural diff between two diagrams.
  icons list      Show every registered icon type/alias/group.
  preview         YAML -> lightweight PNG, no PowerPoint/LibreOffice needed.
  export-drawio   YAML -> .drawio, for manual editing in draw.io.
  sync            Edited .drawio -> updated YAML (position/size only; see
                  docs/detailed-design-pptx.md sec8.14).
  from-mermaid    Mermaid flowchart (.mmd) -> zook YAML.
  guide           Print the bundled workflow / YAML spec / other docs.
  schema          Print the diagram (or icon-registry) JSON Schema.
  patterns        List / print the bundled reference architectures.
  init            Write a starter diagram YAML (or a pattern) to edit.
"""

from __future__ import annotations

import functools
import json
import os
import shutil
import sys
import traceback
from pathlib import Path

import click
import yaml

from . import __version__
from .errors import DiagramError, Warnings, finding_detail
from .layout import Box, build_layout, diagram_warnings
from .loader import load_yaml, load_yaml_roundtrip, read_text, write_text
from .model import Diagram, parse_diagram
from .registry import SHARED_CATEGORIES, MultiRegistry, load_registries
from .render import render
from .validate import validate

FORMAT_CHOICES = ["text", "json", "github"]


def _gh_escape(message: str) -> str:
    """GitHub workflow commands end at the first newline, so a multi-line
    message (a schema error lists one violation per line) must be encoded."""
    return message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _emit(fmt: str, *, status: str, warning_messages: list[str], error: str | None = None,
          output_path: str | None = None, error_code: str | None = None, error_details: list | None = None) -> None:
    if fmt == "json":
        # `warnings`/`error` stay plain text for people and older scripts;
        # `details`/`errorCode`/`errorDetails` carry the same, structured
        # (a code per problem and the ids it concerns) for tools and AIs.
        payload: dict = {
            "status": status,
            "warnings": [str(m) for m in warning_messages],
            "details": [finding_detail(m) for m in warning_messages],
        }
        if error is not None:
            payload["error"] = error
            payload["errorCode"] = error_code or "error"
            payload["errorDetails"] = error_details or []
        if output_path is not None:
            payload["output"] = output_path
        print(json.dumps(payload))
        return

    if fmt == "github":
        for message in warning_messages:
            print(f"::warning::{_gh_escape(message)}")
        if error is not None:
            print(f"::error::{_gh_escape(error)}")
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


def _check_raw(raw: dict, user_registry_path: tuple[str, ...]) -> tuple[Diagram, Box, MultiRegistry, Warnings]:
    """Shared by build/validate/from-mermaid: validate (raises DiagramError
    on Fatal), lay out, and collect every Warning-class check. Never renders."""
    validate(raw)
    diagram = parse_diagram(raw)
    registry = load_registries(user_registry_path=user_registry_path)
    root_box = build_layout(diagram, registry)

    warnings = Warnings()
    for message in registry.warnings + diagram_warnings(diagram, root_box, registry):
        warnings.add(message)
    return diagram, root_box, registry, warnings


def _load_and_check(input_path: str, user_registry_path: tuple[str, ...]) -> tuple[Diagram, Box, MultiRegistry, Warnings]:
    return _check_raw(load_yaml(input_path), user_registry_path)


def _guard(error_exit: int = 1):
    """Turn every failure inside a command into the command's own error
    report - `{"status": "error", "error": ...}` under --format json, an
    `::error::` annotation under github, one `Error:` line otherwise - and a
    non-zero exit, instead of a Python traceback on stderr and nothing on
    stdout. DiagramError is the expected Fatal path; OSError is a path the
    user gave us; anything else is a zook bug, still reported in the same
    shape (with the traceback available via ZOOK_DEBUG=1)."""

    def decorate(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            fmt = kwargs.get("fmt", "text")

            def fail(message: str, code: str, details: list | None = None):
                _emit(fmt, status="error", warning_messages=[], error=message, error_code=code, error_details=details)
                sys.exit(error_exit)

            try:
                return func(*args, **kwargs)
            except DiagramError as exc:
                fail(str(exc), exc.code or "fatal", exc.details)
            except OSError as exc:
                where = f": {exc.filename}" if exc.filename else ""
                fail(f"{exc.strerror or exc}{where}", "io-error", [{"file": exc.filename}] if exc.filename else [])
            except RecursionError:
                fail("input is nested too deeply, or a YAML alias refers to itself", "too-deep")
            except Exception as exc:  # noqa: BLE001 - last line of defence, see docstring
                if os.environ.get("ZOOK_DEBUG"):
                    traceback.print_exc()
                fail(
                    f"internal error: {type(exc).__name__}: {exc} "
                    "(this is a zook bug - please report it; set ZOOK_DEBUG=1 for a traceback)",
                    "internal-error",
                )

        return wrapper

    return decorate


def _same_file(a: str, b: str) -> bool:
    """True if two paths name one file - including a case variant on a
    case-insensitive filesystem (macOS, Windows) or a hard link, which a
    plain resolved-path comparison misses."""
    try:
        if os.path.exists(a) and os.path.exists(b):
            return os.path.samefile(a, b)
    except OSError:
        pass
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def _refuse_same_path(input_path: str, output_path: str) -> None:
    """build/preview/export-drawio/from-mermaid (and sync, for its .drawio)
    write a different kind of file than they read, so an output path equal to
    the input would destroy the source (e.g. `zook build d.yaml -o d.yaml`
    overwrote the YAML with a .pptx)."""
    if _same_file(input_path, output_path):
        raise DiagramError(f"output path {output_path} is the input file {input_path} itself - choose a different -o path")


# Paths are deliberately not checked by click (`exists=True`, the default
# `readable=True`, `dir_okay=False`): click would reject a missing, unreadable
# or directory path with its own usage error - plain text, exit 2 - before
# `--format json` could apply. Opening the file reports it instead, in the
# command's own error format.
_INPUT_PATH = click.Path(readable=False)
_OUTPUT_PATH = click.Path()

_registry_option = click.option(
    "--registry",
    "user_registry_path",
    type=_INPUT_PATH,
    multiple=True,
    help="Icon registry YAML layered on top of the built-in registry of the provider it declares. "
    "Repeatable: each file is applied in order.",
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


@click.group(epilog="New to zook, or an AI agent writing a diagram? Start with `zook guide`.")
@click.version_option(__version__, prog_name="zook")
def main() -> None:
    """zook: generate PowerPoint architecture diagrams from a YAML definition."""
    # A console or pipe whose encoding can't represent a Japanese label (e.g.
    # cp1252 on a Windows CI runner) must not turn a report into a
    # UnicodeEncodeError traceback: escape what can't be encoded instead.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(errors="backslashreplace")
            except (ValueError, OSError):
                pass


@main.command()
@click.argument("input_path", type=_INPUT_PATH)
@click.option("-o", "--output", "output_path", required=True, type=_OUTPUT_PATH, help="Output .pptx path.")
@_registry_option
@_strict_option
@_format_option
@_guard()
def build(input_path: str, output_path: str, user_registry_path: tuple[str, ...], strict: bool, fmt: str) -> None:
    """Generate a .pptx from INPUT_PATH."""
    _refuse_same_path(input_path, output_path)
    diagram, root_box, registry, warnings = _load_and_check(input_path, user_registry_path)
    presentation = render(diagram, root_box, registry)
    presentation.save(output_path)

    status = "warning" if warnings.messages else "ok"
    _emit(fmt, status=status, warning_messages=warnings.messages, output_path=output_path)
    if strict and warnings.messages:
        sys.exit(1)


@main.command(name="validate")
@click.argument("input_path", type=_INPUT_PATH)
@_registry_option
@_strict_option
@_format_option
@_guard()
def validate_cmd(input_path: str, user_registry_path: tuple[str, ...], strict: bool, fmt: str) -> None:
    """Check INPUT_PATH for Fatal/Warning issues without rendering a .pptx."""
    _diagram, _root_box, _registry, warnings = _load_and_check(input_path, user_registry_path)

    status = "warning" if warnings.messages else "ok"
    _emit(fmt, status=status, warning_messages=warnings.messages)
    if strict and warnings.messages:
        sys.exit(1)


def _emit_doctor(fmt: str, result, *, output_path: str | None) -> None:
    """Report what `doctor` changed and what it left for the author, in the
    same three formats the other commands use."""
    moves = [{"id": m.id, "x": m.x, "y": m.y} for m in result.moves]
    pinned = [{"id": m.id, "x": m.x, "y": m.y} for m in result.pinned]
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
    layout_changes = [
        {"id": c.id, "order": c.order, **({"direction": c.direction} if c.direction else {})}
        for c in result.layout_changes
    ]
    changed = bool(result.moves or result.link_changes or result.pinned or result.layout_changes)

    def _arranged(c: dict) -> str:
        where = "the top level" if c["id"] == "canvas" else c["id"]
        how = f" ({c['direction']})" if "direction" in c else ""
        return f"arranged {where} along its links{how} - layout.order: flow"

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
            "pinned": pinned,
            "layoutChanges": layout_changes,
            "linkChanges": link_changes,
            "resolvedOverlaps": result.resolved_overlaps,
            "remaining": [str(m) for m in result.remaining],
            "remainingDetails": [finding_detail(m) for m in result.remaining],
        }
        if output_path is not None:
            payload["output"] = output_path
        print(json.dumps(payload))
        return

    if fmt == "github":
        for c in layout_changes:
            print(f"::notice::{_arranged(c)}")
        for m in moves:
            print(f"::notice::moved {m['id']} to x={m['x']:g}, y={m['y']:g}")
        if pinned:
            print(f"::notice::pinned {', '.join(m['id'] for m in pinned)} at their current positions")
        for c in link_changes:
            print(f"::notice::routed link {c['from']} -> {c['to']} via {_routing(c)}")
        for message in result.remaining:
            print(f"::warning::{_gh_escape(message)}")
        if output_path is not None:
            print(f"Wrote {output_path}")
        return

    # text (default)
    if not changed and result.status == "ok":
        print("No overlaps or link-routing collisions to resolve.")
    else:
        for c in layout_changes:
            text = _arranged(c)
            print(text[0].upper() + text[1:])
        for m in moves:
            print(f"Moved {m['id']} -> x={m['x']:g}, y={m['y']:g}")
        if pinned:
            print(f"Pinned {', '.join(m['id'] for m in pinned)} at their current positions (explicit x/y written)")
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
@click.argument("input_path", type=_INPUT_PATH)
@click.option("-o", "--output", "output_path", default=None, type=_OUTPUT_PATH,
              help="Write the fixed YAML here (default: dry run - only report proposed positions).")
@click.option("--fix", "fix_in_place", is_flag=True, default=False,
              help="Apply the fixes to INPUT_PATH in place (ignored if -o is given).")
@_registry_option
@_strict_option
@_format_option
@_guard()
def doctor_cmd(input_path: str, output_path: str | None, fix_in_place: bool,
               user_registry_path: tuple[str, ...], strict: bool, fmt: str) -> None:
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
    to write them. -o always writes PATH (an unchanged copy if there was
    nothing to fix, so a following `build PATH` never reads a stale file);
    --fix rewrites INPUT_PATH only when something changed. Comments and key
    ordering in the original file are kept.
    """
    from .doctor import diagnose_and_fix
    from .drawio import dump_yaml

    # `raw` (the round-trip tree doctor edits and writes back) is aligned to
    # the strict reading validate/build use, so both describe one diagram.
    strict_raw, raw = load_yaml_roundtrip(input_path)
    validate(strict_raw)

    registry = load_registries(user_registry_path=user_registry_path)
    result = diagnose_and_fix(raw, registry)

    changed = bool(result.moves or result.link_changes or result.pinned or result.layout_changes)
    if output_path is not None:
        dest = output_path
    elif fix_in_place and changed:
        dest = input_path
    else:
        dest = None
    if dest is not None:
        if changed:
            dump_yaml(raw, dest, source_text=read_text(input_path))
        elif not _same_file(input_path, dest):
            # Nothing to fix: a byte-for-byte copy, not a re-serialisation
            # (which would re-indent and normalise line endings).
            shutil.copyfile(input_path, dest)

    _emit_doctor(fmt, result, output_path=dest)
    if strict and result.remaining:
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
            "status": "ok",
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
                "reordered": [{"parent": r.parent, "old": r.old_order, "new": r.new_order} for r in result.reordered],
            },
            "links": {
                "added": [{"from": r.from_id, "to": r.to_id, "id": r.id, "label": r.label} for r in result.added_links],
                "removed": [{"from": r.from_id, "to": r.to_id, "id": r.id, "label": r.label} for r in result.removed_links],
                "modified": [
                    {"from": m.from_id, "to": m.to_id, "id": m.id, "label": m.label,
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
    for r in result.reordered:
        lines.append(f"~ order in {r.parent or '(root)'}: {', '.join(r.old_order)} -> {', '.join(r.new_order)}")

    def link_name(ref) -> str:
        extra = [f"id {ref.id}"] if ref.id else []
        extra += [f'"{ref.label}"'] if ref.label else []
        return f"link {ref.from_id} -> {ref.to_id}" + (f" ({', '.join(extra)})" if extra else "")

    for r in result.added_links:
        lines.append(f"+ {link_name(r)}")
    for r in result.removed_links:
        lines.append(f"- {link_name(r)}")
    for m in result.modified_links:
        lines.append(f"~ {link_name(m)}: {_fmt_changes(m.changes)}")

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
@click.argument("old_path", type=_INPUT_PATH)
@click.argument("new_path", type=_INPUT_PATH)
@click.option("--exit-code", "exit_code", is_flag=True, default=False,
              help="Exit 1 if the diagrams differ, like `git diff --exit-code` (an invalid input exits 2).")
@_format_option
@_guard(error_exit=2)
def diff_cmd(old_path: str, new_path: str, exit_code: bool, fmt: str) -> None:
    """Show the structural difference between two diagrams (OLD_PATH -> NEW_PATH).

    Matches elements by `id` and links by id-or-endpoints and reports what
    actually changed - elements added, removed, moved between containers, or
    modified field-by-field; links added/removed/modified; canvas changes -
    rather than the line noise a text diff would show. Values left to their
    default on one side and written explicitly on the other are not reported.
    """
    from .diff import diff_diagrams

    def load_valid(path: str, role: str) -> dict:
        try:
            raw = load_yaml(path)
            validate(raw)
        except DiagramError as exc:
            raise DiagramError(f"{role} diagram {path}: {exc}") from exc
        return raw

    old_raw = load_valid(old_path, "old")
    new_raw = load_valid(new_path, "new")

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
    type=click.Choice(["aws", "gcp", "azure", "custom"]),
    default=None,
    help="Limit output to a single provider's registry (default: all loaded providers).",
)
@_registry_option
@_format_option
@_guard()
def icons_list(provider: str | None, user_registry_path: tuple[str, ...], fmt: str) -> None:
    """List every registered icon type/alias and container group. Lookup
    ignores case, spaces and hyphens; `General`/`Generic` icons (actors,
    Server, Internet, ...) work with any provider."""
    multi = load_registries(user_registry_path=user_registry_path)
    if provider and provider not in multi.registries:
        raise DiagramError(f"no {provider!r} registry is loaded - pass a --registry file that declares provider: {provider}")
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
                    {"type": e.name, "aliases": e.aliases, "category": e.category,
                     "anyProvider": p == "aws" and e.category in SHARED_CATEGORIES}
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
            if p == "aws" and entry.category in SHARED_CATEGORIES:
                category += ", any provider"
            alias_suffix = f" (aliases: {', '.join(entry.aliases)})" if entry.aliases else ""
            print(f"  node   {entry.name:<20} [{category}]{alias_suffix}")
        for entry in unique_entries(registry.groups):
            alias_suffix = f" (aliases: {', '.join(entry.aliases)})" if entry.aliases else ""
            print(f"  group  {entry.name:<20}{alias_suffix}")


@main.command()
@click.argument("input_path", type=_INPUT_PATH)
@click.option("-o", "--output", "output_path", required=True, type=_OUTPUT_PATH, help="Output .png path.")
@_registry_option
@_strict_option
@_format_option
@_guard()
def preview(input_path: str, output_path: str, user_registry_path: tuple[str, ...], strict: bool, fmt: str) -> None:
    """Render a quick PNG preview of INPUT_PATH (no PowerPoint/LibreOffice needed)."""
    from .preview import preview_font_warnings, render_preview

    if Path(output_path).suffix.lower() != ".png":
        raise DiagramError(f"preview writes PNG only - give -o a .png path (got {output_path})")
    _refuse_same_path(input_path, output_path)
    diagram, root_box, registry, warnings = _load_and_check(input_path, user_registry_path)
    for message in preview_font_warnings(diagram, root_box, registry):
        warnings.add(message)
    render_preview(diagram, root_box, registry).save(output_path)

    status = "warning" if warnings.messages else "ok"
    _emit(fmt, status=status, warning_messages=warnings.messages, output_path=output_path)
    if strict and warnings.messages:
        sys.exit(1)


@main.command(name="export-drawio")
@click.argument("input_path", type=_INPUT_PATH)
@click.option("-o", "--output", "output_path", required=True, type=_OUTPUT_PATH, help="Output .drawio path.")
@_registry_option
@_format_option
@_guard()
def export_drawio_cmd(input_path: str, output_path: str, user_registry_path: tuple[str, ...], fmt: str) -> None:
    """Export INPUT_PATH as a .drawio file for manual editing in draw.io."""
    from .drawio import export_drawio

    _refuse_same_path(input_path, output_path)
    diagram, root_box, registry, warnings = _load_and_check(input_path, user_registry_path)
    write_text(output_path, export_drawio(diagram, root_box, registry))

    status = "warning" if warnings.messages else "ok"
    _emit(fmt, status=status, warning_messages=warnings.messages, output_path=output_path)


@main.command(name="sync")
@click.argument("yaml_path", type=_INPUT_PATH)
@click.argument("drawio_path", type=_INPUT_PATH)
@click.option("-o", "--output", "output_path", type=_OUTPUT_PATH, help="Where to write the updated YAML (default: overwrite YAML_PATH).")
@_registry_option
@_format_option
@_guard()
def sync_cmd(yaml_path: str, drawio_path: str, output_path: str | None, user_registry_path: tuple[str, ...], fmt: str) -> None:
    """Sync position/size changes made in an edited DRAWIO_PATH back into YAML_PATH.

    Only elements whose position or size actually changed (vs. what the
    original YAML's auto-layout would have produced) are touched; added/
    removed shapes and style/color changes made in draw.io are not synced
    - see docs/detailed-design-pptx.md sec8.14.
    """
    from .drawio import dump_yaml, sync_from_drawio

    dest = output_path or yaml_path
    _refuse_same_path(drawio_path, dest)  # writing YAML over the edited .drawio would lose the edits
    updated, warnings = sync_from_drawio(yaml_path, drawio_path, user_registry_path=user_registry_path)

    if updated == load_yaml(yaml_path):
        # Nothing moved in draw.io: don't rewrite (and reformat) the YAML - an
        # unchanged sync used to produce a whole-file diff, and an empty PR
        # from the drawio-sync workflow.
        if not _same_file(yaml_path, dest):
            shutil.copyfile(yaml_path, dest)
    else:
        dump_yaml(updated, dest, source_text=read_text(yaml_path))

    status = "warning" if warnings else "ok"
    _emit(fmt, status=status, warning_messages=warnings, output_path=dest)


@main.command(name="from-mermaid")
@click.argument("input_path", type=_INPUT_PATH)
@click.option("-o", "--output", "output_path", required=True, type=_OUTPUT_PATH, help="Output YAML path.")
@_registry_option
@_strict_option
@_format_option
@_guard()
def from_mermaid_cmd(input_path: str, output_path: str, user_registry_path: tuple[str, ...], strict: bool, fmt: str) -> None:
    """Convert a Mermaid flowchart (INPUT_PATH, e.g. *.mmd) to zook YAML.

    Only `flowchart`/`graph` syntax is supported (sequenceDiagram and other
    Mermaid diagram types are not) - see docs-site/mermaid-import.md for the
    exact supported subset. The generated YAML is validated the same way
    `build`/`validate` do before being written, so Fatal/Warning issues are
    reported here; the result feeds straight into the existing
    validate/build/export-drawio/sync pipeline.
    """
    from .mermaid_flowchart import parse_flowchart

    _refuse_same_path(input_path, output_path)
    raw = parse_flowchart(read_text(input_path))
    _diagram, _root_box, _registry, warnings = _check_raw(raw, user_registry_path)

    # yaml.safe_dump (not drawio.dump_yaml's ruamel round-trip dumper): this
    # writes a fresh file with no existing comments/ordering to preserve, and
    # PyYAML's resolver-aware quoting is what protects "16:9"/"yes"/"no"/etc.
    # from being misread back as a sexagesimal int or bool - which is exactly
    # how they're read elsewhere in this codebase (loader.load_yaml).
    write_text(output_path, yaml.safe_dump(raw, sort_keys=False, allow_unicode=True))

    status = "warning" if warnings.messages else "ok"
    _emit(fmt, status=status, warning_messages=warnings.messages, output_path=output_path)
    if strict and warnings.messages:
        sys.exit(1)


@main.command()
@click.argument("topic", required=False, default="workflow")
def guide(topic: str) -> None:
    """Print a bundled guide. TOPIC: workflow (default - start here), yaml,
    patterns, usage, limitations, mermaid, drawio."""
    from .guide import TOPICS, guide_text

    try:
        click.echo(guide_text(topic))
    except DiagramError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)
    if topic == "workflow":
        others = ", ".join(f"{name} ({description})" for name, (_, _, description) in TOPICS.items() if name != "workflow")
        click.echo(f"Other topics: {others}")


@main.command()
@click.option("--icon-registry", "registry_schema", is_flag=True, default=False,
              help="Print the schema of a --registry file instead of a diagram's.")
def schema(registry_schema: bool) -> None:
    """Print the JSON Schema a diagram YAML is validated against (the
    formal counterpart of `zook guide yaml`)."""
    import importlib.resources as resources

    name = "icon-registry.schema.json" if registry_schema else "zook.schema.json"
    click.echo(resources.files("zook.schemas").joinpath(name).read_text(encoding="utf-8"), nl=False)


@main.group()
def patterns() -> None:
    """The bundled reference architectures - start from the closest one."""


@patterns.command("list")
@_format_option
@_guard()
def patterns_list(fmt: str) -> None:
    """List every pattern with what it is for (`zook guide patterns` explains how to choose)."""
    from .guide import pattern_summaries

    summaries = pattern_summaries()
    if fmt == "json":
        print(json.dumps(summaries, ensure_ascii=False))
        return
    for entry in summaries:
        print(f"{entry['name']:<26} [{', '.join(entry['providers'])}] {entry['summary']}")


@patterns.command("show")
@click.argument("name")
@_format_option
@_guard()
def patterns_show(name: str, fmt: str) -> None:
    """Print pattern NAME's YAML (`zook init --pattern NAME` writes it to a file)."""
    from .guide import pattern_text

    click.echo(pattern_text(name), nl=False)


@main.command()
@click.argument("output_path", required=False, default="diagram.yaml", type=_OUTPUT_PATH)
@click.option("--pattern", "pattern_name", default=None, help="Start from this bundled pattern (see `zook patterns list`).")
@click.option("--force", is_flag=True, default=False, help="Overwrite OUTPUT_PATH if it exists.")
@_format_option
@_guard()
def init(output_path: str, pattern_name: str | None, force: bool, fmt: str) -> None:
    """Write a starter diagram to OUTPUT_PATH (default diagram.yaml): a small
    example, or --pattern NAME's reference architecture, ready to edit and
    `zook validate`."""
    from .guide import STARTER, pattern_text

    if Path(output_path).exists() and not force:
        raise DiagramError(f"{output_path} already exists - pass --force to overwrite it, or give another path")
    write_text(output_path, pattern_text(pattern_name) if pattern_name else STARTER)
    _emit(fmt, status="ok", warning_messages=[], output_path=output_path)


if __name__ == "__main__":
    main()
