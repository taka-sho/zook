"""Schema + semantic validation, per docs/yaml-spec.md sec9.

Structural breakage (schema violation, duplicate id, dangling link reference)
is Fatal: raises DiagramError so the CLI can stop with a non-zero exit code.
"""

from __future__ import annotations

import importlib.resources as resources
import json
from typing import Any

import jsonschema
from jsonschema.exceptions import best_match

from .errors import DiagramError


def _load_schema() -> dict:
    schema_text = (
        resources.files("zook.schemas").joinpath("zook.schema.json").read_text()
    )
    return json.loads(schema_text)


def validate_schema(raw: dict) -> None:
    """Raise DiagramError with all violations if `raw` does not match the JSON Schema.

    `element` is a `oneOf: [container, node]`, so a violation's top-level
    message is jsonschema's generic "is not valid under any of the given
    schemas" - useless for self-correction (by a human or an AI) since it
    doesn't say which of the two branches was closer or why. `err.context`
    holds the per-branch sub-errors in that case; `best_match()` picks the
    most relevant one (e.g. "'y' is a dependency of 'x'") and we append it.
    """
    schema = _load_schema()
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(raw), key=lambda e: list(e.absolute_path))
    if not errors:
        return
    lines = []
    for err in errors:
        path = "$" + "".join(
            f"[{p!r}]" if isinstance(p, str) else f"[{p}]" for p in err.absolute_path
        )
        message = err.message
        if err.context:
            detail = best_match(err.context)
            message = f"{message} (closest match: {detail.message})"
        lines.append(f"  {path}: {message}")
    raise DiagramError("Schema validation failed:\n" + "\n".join(lines))


def _walk_elements(elements: list[dict]):
    for el in elements:
        yield el
        yield from _walk_elements(el.get("children", []))


_SIDE_AXIS = {"top": "vertical", "bottom": "vertical", "left": "horizontal", "right": "horizontal"}


def validate_semantics(raw: dict) -> None:
    """id uniqueness and link from/to existence. Assumes schema-valid input."""
    ids: dict[str, int] = {}
    for el in _walk_elements(raw["elements"]):
        ids[el["id"]] = ids.get(el["id"], 0) + 1
    duplicates = sorted(k for k, v in ids.items() if v > 1)
    if duplicates:
        raise DiagramError(f"Duplicate element id(s): {', '.join(duplicates)}")

    known_ids = set(ids)
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
