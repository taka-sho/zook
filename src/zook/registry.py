"""Icon/group vocabulary resolution, per docs/icon-registry-and-vocabulary.md.

- `type` is never enum-constrained in the diagram schema; the registry is the
  single source of truth for the vocabulary.
- Lookup is alias-inclusive and ignores case, spaces, hyphens, underscores
  and dots (normalize_type: "API Gateway" = "api-gateway" = "APIGateway").
- A user registry can be layered on top of the built-in one for its own
  declared `provider`; same key wins for the user side (sec5).
- Unknown `type` is not fatal: caller gets `None` back and falls back to a
  placeholder icon with a Warning (sec9 error policy, enforced by the render
  layer, not here).
- Multiple providers (aws/gcp/azure/custom) can be loaded at once; each
  element resolves against *its own* `provider` field via MultiRegistry,
  falling back to the aws registry's groups for container styling so every
  provider doesn't need to redefine generic concepts like "vpc"/"az".
  Likewise the aws registry's `General` (actors such as User/Admin) and
  `Generic` (Server, Internet, OnPremises, SaaS, ...) icons serve every
  provider.
- For an unresolved type, suggest_type() offers close matches and the
  providers that do have it, so the Warning says how to fix it.
- Icon files are read through icon_png(): PNG/JPEG/... as-is (converted to
  PNG), SVG rasterized with cairosvg - one image format for the .pptx, the
  preview and the .drawio, and an unusable file is a Warning + placeholder
  instead of a crash deep inside rendering.
"""

from __future__ import annotations

import difflib
import importlib.resources as resources
import io
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Optional

import yaml

from .errors import DiagramError
from .loader import load_yaml

DEFAULT_ICON_SIZE = 64
PLACEHOLDER_ICON_NAME = "_placeholder.png"
BUILTIN_PROVIDERS = ("aws", "gcp", "azure")
SHARED_CATEGORIES = {"General", "Generic"}  # aws icons of these categories resolve for every provider


ICON_RASTER_PX = 256  # an SVG icon is rasterized at 4x the default 64-unit size (detailed-design sec8.6)


@lru_cache(maxsize=512)
def _icon_png(path: str, mtime: float) -> tuple[Optional[bytes], Optional[str]]:
    del mtime  # part of the cache key only: an edited file is read again
    try:
        data = Path(path).read_bytes()
    except OSError as exc:
        return None, f"can't be read ({exc.strerror or exc})"
    head = data[:512].lstrip().lower()
    if path.lower().endswith(".svg") or head.startswith(b"<svg") or (head.startswith(b"<?xml") and b"<svg" in head):
        try:
            import cairosvg
        except (ImportError, OSError):  # cairocffi raises OSError when the cairo library itself is missing
            return None, "is an SVG, and rasterizing SVG needs the cairo library - install it, or convert the icon to PNG"
        try:
            return cairosvg.svg2png(bytestring=data, output_width=ICON_RASTER_PX), None
        except Exception as exc:  # noqa: BLE001 - any parse failure means "not a usable SVG"
            return None, f"is an SVG that couldn't be rasterized ({type(exc).__name__}: {exc})"
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            if image.format == "PNG":
                return data, None
            out = io.BytesIO()
            image.save(out, "PNG")
            return out.getvalue(), None
    except (UnidentifiedImageError, OSError, ValueError):
        return None, "is not an image zook can read (use PNG, JPEG or SVG)"


def icon_png(path: Path) -> tuple[Optional[bytes], Optional[str]]:
    """(PNG bytes, None) for a usable icon file, or (None, why not)."""
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None, "does not exist"
    return _icon_png(str(path), mtime)


def normalize_type(name: str) -> str:
    """The lookup key for a `type`/alias: case, spaces, hyphens, underscores
    and dots don't matter, so "API Gateway", "api-gateway" and "Route 53"
    find APIGateway/Route53 as an AI (or a human) naturally writes them."""
    key = re.sub(r"[^0-9a-z]", "", name.lower())
    return key or name.lower()  # a name with no ASCII letters/digits keys as itself


@dataclass
class IconEntry:
    file: Path
    name: str = ""  # original-case primary key, e.g. "EC2" (lookup itself is case-insensitive)
    category: Optional[str] = None
    kind: str = "service"
    label: Optional[str] = None
    size: Optional[float] = None
    aliases: list = field(default_factory=list)
    drawio_shape: Optional[str] = None  # mxGraph style string; None -> export-drawio embeds `file` as a PNG data URI


@dataclass
class GroupEntry:
    name: str = ""  # original-case primary key, e.g. "vpc"
    label: str = ""
    border_color: str = "#5A6B86"
    fill_color: Optional[str] = None
    border_width: float = 1
    dashed: bool = False
    label_position: str = "top-left"
    icon: Optional[Path] = None
    aliases: list = field(default_factory=list)
    drawio_shape: Optional[str] = None  # mxGraph group-shape style string; None -> export-drawio draws a plain rect


@dataclass
class Registry:
    provider: str
    base_path: Path
    default_size: float
    icons: dict[str, IconEntry]
    groups: dict[str, GroupEntry]
    placeholder_icon: Path

    def resolve_icon(self, type_: str) -> Optional[IconEntry]:
        return self.icons.get(normalize_type(type_))

    def resolve_group(self, type_: str) -> Optional[GroupEntry]:
        return self.groups.get(normalize_type(type_))


def _icon_entry(key: str, spec: dict) -> IconEntry:
    return IconEntry(
        file=Path(spec["file"]),
        name=key,
        category=spec.get("category"),
        kind=spec.get("kind", "service"),
        label=spec.get("label"),
        size=spec.get("size"),
        aliases=list(spec.get("aliases", [])),
        drawio_shape=spec.get("drawioShape"),
    )


def _group_entry(key: str, spec: dict) -> GroupEntry:
    return GroupEntry(
        name=key,
        label=spec.get("label", ""),
        border_color=spec.get("borderColor", "#5A6B86"),
        fill_color=spec.get("fillColor"),
        border_width=spec.get("borderWidth", 1),
        dashed=spec.get("dashed", False),
        label_position=spec.get("labelPosition", "top-left"),
        aliases=list(spec.get("aliases", [])),
        icon=Path(spec["icon"]) if spec.get("icon") else None,
        drawio_shape=spec.get("drawioShape"),
    )


class _Layers:
    """One section (icons or groups) of a provider's registry, built from the
    built-in file and then each --registry file on top, in order.

    Redefining an existing type merges field by field - a user's
    `vpc: {borderColor: "#F00"}` keeps the built-in label and draw.io shape,
    and every alias of the old entry (ALB, LoadBalancer, ...) follows it to
    the new icon. A type's own name always wins over another entry's alias,
    so a user alias can't silently take over a built-in type (`aliases:
    [S3]` on some other entry); that alias is dropped with a Warning."""

    def __init__(self, path_field: str):
        self.path_field = path_field  # "file" (icons) / "icon" (groups): resolved against the defining file
        self.entries: dict[str, tuple[str, dict]] = {}  # normalized type -> (display name, merged spec)
        self.user_aliases: dict[tuple[str, str], str] = {}  # (entry key, alias) -> source file

    def add(self, section: dict, base: Path, source: Optional[str]) -> None:
        for key, spec in section.items():
            spec = dict(spec)
            if spec.get(self.path_field):
                spec[self.path_field] = str(base / spec[self.path_field])
            norm = normalize_type(key)
            if norm in self.entries:
                name, old = self.entries[norm]
                merged = {**old, **spec}
                merged["aliases"] = list(dict.fromkeys([*old.get("aliases", []), *spec.get("aliases", [])]))
                if self.path_field == "file" and "file" in spec and "drawioShape" not in spec:
                    # A new icon image: the built-in draw.io shape drew the old
                    # one, so export-drawio embeds the new file instead.
                    merged.pop("drawioShape", None)
                self.entries[norm] = (name, merged)
            else:
                self.entries[norm] = (key, spec)
            if source is not None:
                for alias in spec.get("aliases", []):
                    self.user_aliases[(norm, alias)] = source

    def index(self, make, warnings: list[str], what: str) -> dict:
        index = {}
        for norm, (name, spec) in self.entries.items():
            index[norm] = make(name, spec)
        for norm, (name, spec) in self.entries.items():
            entry = index[norm]
            for alias in spec.get("aliases", []):
                alias_key = normalize_type(alias)
                if alias_key in self.entries and alias_key != norm:
                    if (norm, alias) in self.user_aliases:
                        warnings.append(
                            f"alias {alias!r} of {what} {name!r} in {self.user_aliases[(norm, alias)]} is already the "
                            f"{what} {self.entries[alias_key][0]!r} - ignored (redefine {self.entries[alias_key][0]!r} "
                            "itself to change it)"
                        )
                    continue
                index[alias_key] = entry
        return index


def _load_builtin(provider: str) -> tuple[dict, Path]:
    try:
        data_dir = resources.files(f"zook.data.icons.{provider}")
        registry_file = data_dir.joinpath(f"registry.{provider}.yaml")
        # Explicit UTF-8: the registries contain non-ASCII text, and the
        # locale default (cp932 on Japanese Windows) can't decode it.
        raw = yaml.safe_load(registry_file.read_text(encoding="utf-8"))
    except (ModuleNotFoundError, FileNotFoundError):
        return {"icons": {}, "groups": {}, "defaults": {}}, Path(".")
    base_path = Path(str(data_dir)) / raw.get("basePath", ".")
    return raw, base_path


def _placeholder_icon_path() -> Path:
    # A single shared "unknown icon" placeholder, regardless of provider.
    data_dir = resources.files("zook.data.icons.aws")
    return Path(str(data_dir)) / PLACEHOLDER_ICON_NAME


def load_user_registry(path: str) -> dict:
    """Read a `--registry` file and check it against icon-registry.schema.json
    (the format docs-site/icons.md documents), so a malformed registry is a
    Fatal naming the file and field - not a KeyError deep inside layout."""
    from .validate import schema_errors

    raw = load_yaml(path)
    lines = schema_errors(raw, "icon-registry.schema.json")
    if lines:
        raise DiagramError(f"invalid icon registry {path}:\n" + "\n".join(lines))
    return raw


def load_registry(
    provider: str,
    user_registry_path: Optional[str] = None,
    user_raw: Optional[dict] = None,
    overlays: Optional[list[tuple[str, dict]]] = None,
    warnings: Optional[list[str]] = None,
) -> Registry:
    """Load one provider's built-in registry, with the user registries that
    declare `provider: <provider>` layered on top in order (`overlays`, or a
    single `user_registry_path`/`user_raw`). See _Layers for how an overlay
    combines with what is already there."""
    raw, base_path = _load_builtin(provider)
    if overlays is None:
        overlays = []
        if user_registry_path:
            overlays.append((user_registry_path, user_raw if user_raw is not None else load_user_registry(user_registry_path)))
    warnings = warnings if warnings is not None else []
    icons, groups = _Layers("file"), _Layers("icon")
    icons.add(raw.get("icons", {}), base_path, None)
    groups.add(raw.get("groups", {}), base_path, None)
    default_size = raw.get("defaults", {}).get("size", DEFAULT_ICON_SIZE)
    for path, overlay in overlays:
        overlay_base = Path(path).parent / overlay.get("basePath", ".")
        icons.add(overlay.get("icons", {}), overlay_base, path)
        groups.add(overlay.get("groups", {}), overlay_base, path)
        default_size = overlay.get("defaults", {}).get("size", default_size)

    return Registry(
        provider=provider,
        base_path=base_path,
        default_size=default_size,
        icons=icons.index(_icon_entry, warnings, "type"),
        groups=groups.index(_group_entry, warnings, "container type"),
        placeholder_icon=_placeholder_icon_path(),
    )


@dataclass
class MultiRegistry:
    """Dispatches icon/group resolution to the registry matching each
    element's own `provider` field, so a single diagram can mix aws/gcp/
    azure/custom nodes. Falls back to the aws registry for container
    *groups* not defined in the requested provider's own registry, since
    generic concepts (vpc/az/subnet/region/group) don't need to be
    redefined by every provider."""

    registries: dict[str, Registry] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)  # from layering the --registry files

    def _for(self, provider: str) -> Optional[Registry]:
        return self.registries.get(provider)

    def resolve_icon(self, type_: str, provider: str = "aws") -> Optional[IconEntry]:
        registry = self._for(provider)
        entry = registry.resolve_icon(type_) if registry else None
        if entry is None and provider != "aws" and (aws := self._for("aws")) is not None:
            shared = aws.resolve_icon(type_)
            if shared is not None and shared.category in SHARED_CATEGORIES:
                return shared  # an actor (User, ...) or other provider-neutral icon
        return entry

    def resolve_group(self, type_: str, provider: str = "generic") -> Optional[GroupEntry]:
        registry = self._for(provider)
        entry = registry.resolve_group(type_) if registry else None
        if entry is not None or provider == "aws":
            return entry
        aws = self._for("aws")
        return aws.resolve_group(type_) if aws else None

    def node_icon_png(self, type_: str, provider: str) -> bytes:
        """The image a node of `type_` is drawn with: its registry icon, or
        the placeholder when the type is unknown or its file unusable
        (icon_resolution_warnings reports both)."""
        entry = self.resolve_icon(type_, provider)
        if entry is not None:
            data, _ = icon_png(entry.file)
            if data is not None:
                return data
        data, problem = icon_png(self.placeholder_icon)
        if data is None:
            raise DiagramError(f"the bundled placeholder icon {self.placeholder_icon} {problem}")
        return data

    def suggest_type(self, type_: str, provider: str, kind: str = "node") -> str:
        """How to fix an unresolved `type`, as a Warning suffix: the close
        matches in its own provider's vocabulary, and the other providers
        that do define it."""
        key = normalize_type(type_)
        hints = []
        if kind == "node":
            elsewhere = [p for p, r in self.registries.items() if p != provider and r.resolve_icon(type_)]
            if elsewhere:
                hints.append(
                    f"it is a {' / '.join(elsewhere)} type - set `provider: {elsewhere[0]}` on the node"
                )
            candidates = {k: e.name for k, e in (self._for(provider).icons.items() if self._for(provider) else [])}
            if provider != "aws" and self._for("aws"):
                candidates.update(
                    {k: e.name for k, e in self._for("aws").icons.items() if e.category in SHARED_CATEGORIES}
                )
        else:
            candidates = {}
            for p in dict.fromkeys([provider, "aws"]):
                if self._for(p):
                    candidates.update({k: e.name for k, e in self._for(p).groups.items()})
        close = list(dict.fromkeys(candidates[k] for k in difflib.get_close_matches(key, candidates, n=3, cutoff=0.6)))
        if close and not hints:  # another provider's exact type beats a near miss here
            hints.append("did you mean " + " or ".join(repr(name) for name in close) + "?")
        if not hints:
            if kind == "node":
                hints.append(
                    "`zook icons list` shows the vocabulary; for something it lacks, use the closest service or "
                    "draw a plain shape (`style: {shape: rect}`) with the name as its label"
                )
            else:
                hints.append("`zook icons list` shows the container types; `type: group` is the plain frame")
        return " - " + "; ".join(hints)

    def default_size(self, provider: str = "aws") -> float:
        registry = self._for(provider) or self._for("aws")
        return registry.default_size if registry else DEFAULT_ICON_SIZE

    @property
    def placeholder_icon(self) -> Path:
        return _placeholder_icon_path()


def load_registries(user_registry_path=None) -> MultiRegistry:
    """Load every built-in provider registry (aws/gcp/azure), with each
    `--registry` file (one path, or a list of them, applied in order) layered
    onto the provider it declares - "aws" if unset, or a brand-new provider
    such as "custom". Problems found while layering (an alias that collides
    with a type) are kept in MultiRegistry.warnings."""
    if user_registry_path is None:
        paths: list[str] = []
    elif isinstance(user_registry_path, (str, Path)):
        paths = [str(user_registry_path)]
    else:
        paths = [str(p) for p in user_registry_path]
    overlays: dict[str, list[tuple[str, dict]]] = {}
    for path in paths:
        raw = load_user_registry(path)
        overlays.setdefault(raw.get("provider", "aws"), []).append((path, raw))

    warnings: list[str] = []
    providers = list(dict.fromkeys([*BUILTIN_PROVIDERS, *overlays]))
    registries = {
        provider: load_registry(provider, overlays=overlays.get(provider, []), warnings=warnings)
        for provider in providers
    }
    return MultiRegistry(registries=registries, warnings=warnings)
