"""Schema + semantic validation, per docs/yaml-spec.md sec9.

Structural breakage (schema violation, duplicate id, dangling link reference)
is Fatal: raises DiagramError so the CLI can stop with a non-zero exit code.
"""

from __future__ import annotations

import importlib.resources as resources
import json
import math
from typing import Any

import jsonschema
from jsonschema.exceptions import best_match

from .errors import DiagramError


def _load_schema(name: str = "zook.schema.json") -> dict:
    schema_text = resources.files("zook.schemas").joinpath(name).read_text(encoding="utf-8")
    return json.loads(schema_text)


_MAX_INSTANCE_REPR = 80


def _yaml_type_hint(err) -> str:
    """YAML 1.1 turns some unquoted scalars into something other than the
    string the author meant - `16:9` is the base-60 int 969, `no`/`yes`/`on`
    are booleans, `1.0` is a float. The schema error alone ("969 is not one
    of ['16:9', '4:3']") doesn't say why, so name the fix."""
    instance = err.instance
    if not isinstance(instance, (bool, int, float)):
        return ""
    wants_string = (
        (err.validator == "type" and "string" in ([err.validator_value] if isinstance(err.validator_value, str) else err.validator_value))
        or (err.validator == "enum" and all(isinstance(v, str) for v in err.validator_value))
        or (err.validator == "const" and isinstance(err.validator_value, str))
    )
    if not wants_string:
        return ""
    if isinstance(instance, bool):
        return " - YAML read this unquoted value as a boolean (yes/no/on/off/true/false); wrap it in quotes"
    return " - YAML read this unquoted value as a number (16:9 even becomes 969); wrap it in quotes, e.g. \"16:9\" or \"1.0\""


def _message(err) -> str:
    """jsonschema's message, with a huge instance repr (a whole container
    subtree) cut down to its start - the path already says where it is."""
    message = err.message
    if len(message) > _MAX_INSTANCE_REPR:
        try:
            instance_repr = repr(err.instance)
        except (ValueError, RecursionError):  # e.g. an int past Python's 4300-digit str limit
            instance_repr = ""
        if instance_repr and len(instance_repr) > _MAX_INSTANCE_REPR and message.startswith(instance_repr):
            message = instance_repr[: _MAX_INSTANCE_REPR - 3] + "..." + message[len(instance_repr):]
    if err.context:
        # Only reachable from a oneOf/anyOf; `element` itself selects its
        # branch by `kind` (if/then), so its errors already sit at the exact
        # nested path with the specific cause.
        message = f"{message} (closest match: {best_match(err.context).message})"
    return message + _yaml_type_hint(err)


def schema_errors(raw: Any, schema_name: str = "zook.schema.json") -> list[str]:
    """Every violation of `schema_name` in `raw`, one `$path: message` line
    each, ordered by path."""
    validator = jsonschema.Draft202012Validator(_load_schema(schema_name))
    errors = sorted(validator.iter_errors(raw), key=lambda e: [(0, p) if isinstance(p, int) else (1, p) for p in e.absolute_path])
    lines = []
    for err in errors:
        path = "$" + "".join(f"[{p!r}]" if isinstance(p, str) else f"[{p}]" for p in err.absolute_path)
        lines.append(f"  {path}: {_message(err)}")
    return lines


def validate_schema(raw: dict) -> None:
    """Raise DiagramError with all violations if `raw` does not match the JSON Schema.

    Each violation is reported at its own path (e.g.
    `$['elements'][0]['children'][1]`) with jsonschema's specific message.
    `element` picks the container or node schema by `kind` with if/then
    instead of oneOf; with oneOf, a mistake deep inside a container was
    reported against the whole top-level element with the *other* branch's
    complaint ("'children' was unexpected"), steering a self-correcting AI
    toward deleting children.
    """
    if not isinstance(raw, dict):
        # e.g. `zook sync d.drawio d.yaml` (arguments swapped): the XML reads as
        # one YAML string, and "'<mxfile ...' is not of type 'object'" says
        # nothing about what went wrong.
        kinds = {str: "a string", list: "a list", bool: "a boolean", int: "a number", float: "a number"}
        what = "empty" if raw is None else kinds.get(type(raw), f"a {type(raw).__name__}")
        hint = ""
        if isinstance(raw, str) and raw.lstrip().startswith("<"):
            hint = (
                " - it looks like XML (a .drawio file?); commands take the diagram YAML "
                "(for sync: `zook sync DIAGRAM.yaml DIAGRAM.drawio`)"
            )
        raise DiagramError(f"not a zook diagram: the document is {what}, not a mapping with version/canvas/elements{hint}")
    lines = schema_errors(raw)
    if lines:
        raise DiagramError("Schema validation failed:\n" + "\n".join(lines))


# Every number in a diagram is a coordinate, size, spacing or font size; none
# is meaningful beyond this, and a huge one (1e308) overflowed to infinity in
# layout arithmetic and leaked `Infinity` - not valid JSON - into reports.
_MAX_ABS_NUMBER = 1_000_000


def _non_finite_numbers(value, path: str = "$"):
    """Paths of every NaN/Infinity (YAML `.nan`/`.inf`) or absurdly large
    number in the document. JSON Schema's `number` accepts them, but no
    coordinate or size can be one - they crashed layout/rendering instead of
    failing validation."""
    if isinstance(value, bool):
        return
    if isinstance(value, float) and not math.isfinite(value):
        yield path
    elif isinstance(value, (int, float)) and abs(value) > _MAX_ABS_NUMBER:
        yield path
    elif isinstance(value, dict):
        for key, child in value.items():
            yield from _non_finite_numbers(child, f"{path}[{key!r}]")
    elif isinstance(value, list):
        for i, child in enumerate(value):
            yield from _non_finite_numbers(child, f"{path}[{i}]")


def _walk_elements(elements: list[dict]):
    for el in elements:
        yield el
        yield from _walk_elements(el.get("children", []))


_SIDE_AXIS = {"top": "vertical", "bottom": "vertical", "left": "horizontal", "right": "horizontal"}


def validate_semantics(raw: dict) -> None:
    """id uniqueness (elements and links share one namespace) and link
    from/to existence. Assumes schema-valid input."""
    non_finite = list(_non_finite_numbers(raw))
    if non_finite:
        raise DiagramError(
            f"numbers must be finite and within ±{_MAX_ABS_NUMBER:,} (NaN/Infinity and huge values are not valid): "
            + ", ".join(non_finite)
        )

    ids: dict[str, int] = {}
    for el in _walk_elements(raw["elements"]):
        ids[el["id"]] = ids.get(el["id"], 0) + 1
    duplicates = sorted(k for k, v in ids.items() if v > 1)
    if duplicates:
        raise DiagramError(f"Duplicate element id(s): {', '.join(duplicates)}")

    known_ids = set(ids)
    link_ids: dict[str, int] = {}
    for link in raw.get("links", []):
        if "id" in link:
            link_ids[link["id"]] = link_ids.get(link["id"], 0) + 1
    problems = []
    if duplicated := sorted(k for k, v in link_ids.items() if v > 1):
        problems.append(f"duplicate link id(s): {', '.join(duplicated)}")
    if clashing := sorted(set(link_ids) & known_ids):
        problems.append(f"link id(s) also used by an element: {', '.join(clashing)}")
    if problems:
        # export-drawio writes ids as mxCell ids, where a repeat makes draw.io
        # decode one cell over another (a node turning into an edge).
        raise DiagramError("ids must be unique across elements and links: " + "; ".join(problems))

    missing: list[str] = []
    for link in raw.get("links", []):
        if link["from"] not in known_ids:
            missing.append(f"link.from={link['from']!r}")
        if link["to"] not in known_ids:
            missing.append(f"link.to={link['to']!r}")
    if missing:
        raise DiagramError("Link references unknown element id(s): " + ", ".join(missing))

    mismatched: list[str] = []
    for link in raw.get("links", []):
        from_side, to_side = link.get("fromSide"), link.get("toSide")
        # The axis-match rule exists because a plain elbow (bentConnector3) must
        # enter/exit on one axis; a waypoint link is an explicit polyline, so any
        # side combination is fine there.
        if link.get("waypoints"):
            continue
        if from_side and to_side and _SIDE_AXIS[from_side] != _SIDE_AXIS[to_side]:
            mismatched.append(f"{link['from']!r} -> {link['to']!r} (fromSide={from_side!r}, toSide={to_side!r})")
    if mismatched:
        raise DiagramError(
            "link fromSide/toSide must be on the same axis (both top/bottom, or both left/right): "
            + ", ".join(mismatched)
        )


def validate(raw: dict) -> None:
    validate_schema(raw)
    validate_semantics(raw)
