"""Reading input files, with every failure turned into a DiagramError.

Every command reads its YAML through here, so they all agree on what a file
means (docs/yaml-spec.md sec9): the same YAML 1.1 interpretation, duplicate
mapping keys rejected instead of silently keeping the last one, and a syntax
error / non-UTF-8 file / unreadable path reported as a one-line Fatal with the
line and column, not a Python traceback - the `--format json` contract (one
`{"status": "error", ...}` object on stdout) has to hold for the mistakes an
AI makes most often, and a malformed file is the most common of them.

`doctor`/`sync` also need a round-trip (ruamel) tree so they can write the
file back with comments and key order intact. ruamel reads YAML 1.2, which
disagrees with YAML 1.1 on some unquoted scalars (`16:9` is the base-60 int
969 in 1.1 but a string in 1.2; `0600` is octal 384 vs decimal 600; `1e3` is
a string vs a float). So the round-trip tree is loaded *in addition to* the
strict one and then aligned to it: every scalar the two readings disagree on
is overwritten with the strict value. doctor/sync therefore validate, lay
out and edit exactly the diagram validate/build see.
"""

from __future__ import annotations

from typing import Any

import yaml

from .errors import DiagramError


class _StrictSafeLoader(yaml.SafeLoader):
    """yaml.SafeLoader that rejects a mapping key written twice.

    PyYAML's default keeps the last value, so a second `links:` block silently
    discards the first one - the diagram validates, builds, and is simply
    missing connectors. Merge keys (`<<: *anchor`) are exempt: overriding a
    merged key is what they're for.
    """

    def construct_mapping(self, node, deep=False):
        if isinstance(node, yaml.MappingNode):
            seen: dict[Any, yaml.Mark] = {}
            for key_node, _value_node in node.value:
                # `<<` merges and YAML 1.1's `=` value key get special
                # handling in flatten_mapping (run by the base class below).
                if key_node.tag in ("tag:yaml.org,2002:merge", "tag:yaml.org,2002:value"):
                    continue
                key = self.construct_object(key_node, deep=True)
                try:
                    first = seen.get(key)
                except TypeError:  # unhashable key - the base class reports it
                    continue
                if first is not None:
                    raise yaml.constructor.ConstructorError(
                        "while constructing a mapping",
                        node.start_mark,
                        f"found duplicate key {key!r} (first defined at line {first.line + 1})",
                        key_node.start_mark,
                    )
                seen[key] = key_node.start_mark
        return super().construct_mapping(node, deep=deep)


def yaml_error_message(exc: Exception, path: str) -> str:
    """One line naming the file, line and column, for PyYAML and ruamel alike
    (both expose `problem`/`problem_mark` on their marked errors)."""
    problem = getattr(exc, "problem", None)
    mark = getattr(exc, "problem_mark", None)
    if problem and mark is not None:
        return f"YAML error in {path} at line {mark.line + 1}, column {mark.column + 1}: {problem}"
    return f"YAML error in {path}: {exc}"


def read_text(path: str) -> str:
    """Read a UTF-8 text file (a leading BOM is accepted and dropped)."""
    try:
        with open(path, encoding="utf-8-sig") as f:
            return f.read()
    except UnicodeDecodeError as exc:
        raise DiagramError(
            f"{path} is not valid UTF-8 (byte {exc.start}): save the file as UTF-8"
        ) from exc
    except OSError as exc:
        raise DiagramError(f"cannot read {path}: {exc.strerror or exc}") from exc


def parse_yaml(text: str, path: str) -> Any:
    try:
        return yaml.load(text, Loader=_StrictSafeLoader)  # noqa: S506 - a SafeLoader subclass
    except yaml.YAMLError as exc:
        raise DiagramError(yaml_error_message(exc, path)) from exc


def load_yaml(path: str) -> Any:
    """Strictly load a YAML file: the interpretation every command validates."""
    return parse_yaml(read_text(path), path)


def _align_to_strict(roundtrip: Any, strict: Any) -> None:
    """Overwrite, in place, every scalar of the ruamel tree whose value
    differs from the strict (YAML 1.1) reading at the same path. Containers
    are walked, not replaced, so comments and key order survive; only the
    few ambiguous scalars change (and are written back in canonical form)."""
    if isinstance(roundtrip, dict) and isinstance(strict, dict):
        for key in list(roundtrip.keys()):
            if key in strict:
                _align_child(roundtrip, key, strict[key])
    elif isinstance(roundtrip, list) and isinstance(strict, list) and len(roundtrip) == len(strict):
        for i, value in enumerate(strict):
            _align_child(roundtrip, i, value)


def _align_child(parent: Any, key: Any, strict_value: Any) -> None:
    current = parent[key]
    if isinstance(current, (dict, list)) and isinstance(strict_value, (dict, list)):
        _align_to_strict(current, strict_value)
    elif type(current) is not type(strict_value) or current != strict_value:
        # e.g. ruamel's ScalarFloat vs float: compare as plain Python values
        plain = current
        for cast in (bool, int, float, str):
            if isinstance(current, cast):
                plain = cast(current)
                break
        if type(plain) is not type(strict_value) or plain != strict_value:
            parent[key] = strict_value


def load_yaml_roundtrip(path: str):
    """Load `path` twice: strictly (returned first) and as a ruamel
    round-trip tree aligned to it (returned second, to edit and write back).
    Both describe the same diagram - see the module docstring."""
    from ruamel.yaml import YAML
    from ruamel.yaml.error import YAMLError as RuamelYAMLError

    text = read_text(path)
    strict = parse_yaml(text, path)
    yaml_rt = YAML()
    yaml_rt.preserve_quotes = True
    try:
        roundtrip = yaml_rt.load(text)
    except RuamelYAMLError as exc:
        raise DiagramError(yaml_error_message(exc, path)) from exc
    _align_to_strict(roundtrip, strict)
    return strict, roundtrip


def yaml_number(value: float):
    """A coordinate as written back into YAML: an int when it is one (so
    `x: 150` doesn't come back as `x: 150.0`), else rounded to 2 decimals."""
    rounded = round(value, 2)
    return int(rounded) if rounded == int(rounded) else rounded


def write_text(path: str, text: str) -> None:
    write_bytes(path, text.encode("utf-8", errors="strict"))


def write_bytes(path: str, data: bytes) -> None:
    """Write `data` to `path` in one go. Encoding happens before the file is
    opened, so an encode failure can't leave a truncated, empty output."""
    try:
        with open(path, "wb") as f:
            f.write(data)
    except OSError as exc:
        raise DiagramError(f"cannot write {path}: {exc.strerror or exc}") from exc
