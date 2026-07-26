"""Icon/group vocabulary resolution, per docs/icon-registry-and-vocabulary.md.

- `type` is never enum-constrained in the diagram schema; the registry is the
  single source of truth for the vocabulary.
- Lookup is alias-inclusive and case-insensitive (sec4).
- A user registry can be layered on top of the built-in one for its own
  declared `provider`; same key wins for the user side (sec5).
- Unknown `type` is not fatal: caller gets `None` back and falls back to a
  placeholder icon with a Warning (sec9 error policy, enforced by the render
  layer, not here).
- Multiple providers (aws/gcp/azure/custom) can be loaded at once; each
  element resolves against *its own* `provider` field via MultiRegistry,
  falling back to the aws registry's groups for container styling so every
  provider doesn't need to redefine generic concepts like "vpc"/"az".
"""

from __future__ import annotations

import importlib.resources as resources
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

DEFAULT_ICON_SIZE = 64
PLACEHOLDER_ICON_NAME = "_placeholder.png"
BUILTIN_PROVIDERS = ("aws", "gcp", "azure")


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
        return self.icons.get(type_.lower())

    def resolve_group(self, type_: str) -> Optional[GroupEntry]:
        return self.groups.get(type_.lower())


def _index_icons(raw_icons: dict, base_path: Path) -> dict[str, IconEntry]:
    index: dict[str, IconEntry] = {}
    for key, spec in raw_icons.items():
        entry = IconEntry(
            file=base_path / spec["file"],
            name=key,
            category=spec.get("category"),
            kind=spec.get("kind", "service"),
            label=spec.get("label"),
            size=spec.get("size"),
            aliases=list(spec.get("aliases", [])),
            drawio_shape=spec.get("drawioShape"),
        )
        index[key.lower()] = entry
        for alias in spec.get("aliases", []):
            index[alias.lower()] = entry
    return index


def _index_groups(raw_groups: dict, base_path: Path) -> dict[str, GroupEntry]:
    index: dict[str, GroupEntry] = {}
    for key, spec in raw_groups.items():
        entry = GroupEntry(
            name=key,
            label=spec.get("label", ""),
            border_color=spec.get("borderColor", "#5A6B86"),
            fill_color=spec.get("fillColor"),
            border_width=spec.get("borderWidth", 1),
            dashed=spec.get("dashed", False),
            label_position=spec.get("labelPosition", "top-left"),
            aliases=list(spec.get("aliases", [])),
            icon=(base_path / spec["icon"]) if spec.get("icon") else None,
            drawio_shape=spec.get("drawioShape"),
        )
        index[key.lower()] = entry
        for alias in spec.get("aliases", []):
            index[alias.lower()] = entry
    return index


def _load_builtin(provider: str) -> tuple[dict, Path]:
    try:
        data_dir = resources.files(f"archdiagram.data.icons.{provider}")
        registry_file = data_dir.joinpath(f"registry.{provider}.yaml")
        raw = yaml.safe_load(registry_file.read_text())
    except (ModuleNotFoundError, FileNotFoundError):
        return {"icons": {}, "groups": {}, "defaults": {}}, Path(".")
    base_path = Path(str(data_dir)) / raw.get("basePath", ".")
    return raw, base_path


def _placeholder_icon_path() -> Path:
    # A single shared "unknown icon" placeholder, regardless of provider.
    data_dir = resources.files("archdiagram.data.icons.aws")
    return Path(str(data_dir)) / PLACEHOLDER_ICON_NAME


def load_registry(provider: str, user_registry_path: Optional[str] = None) -> Registry:
    """Load one provider's built-in registry, optionally overlaying a user
    registry YAML that itself declares `provider: <provider>`."""
    raw, base_path = _load_builtin(provider)
    icons = _index_icons(raw.get("icons", {}), base_path)
    groups = _index_groups(raw.get("groups", {}), base_path)
    default_size = raw.get("defaults", {}).get("size", DEFAULT_ICON_SIZE)

    if user_registry_path:
        user_raw = yaml.safe_load(Path(user_registry_path).read_text())
        user_base = Path(user_registry_path).parent / user_raw.get("basePath", ".")
        icons.update(_index_icons(user_raw.get("icons", {}), user_base))
        groups.update(_index_groups(user_raw.get("groups", {}), user_base))
        default_size = user_raw.get("defaults", {}).get("size", default_size)

    return Registry(
        provider=provider,
        base_path=base_path,
        default_size=default_size,
        icons=icons,
        groups=groups,
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

    def _for(self, provider: str) -> Optional[Registry]:
        return self.registries.get(provider)

    def resolve_icon(self, type_: str, provider: str = "aws") -> Optional[IconEntry]:
        registry = self._for(provider)
        return registry.resolve_icon(type_) if registry else None

    def resolve_group(self, type_: str, provider: str = "generic") -> Optional[GroupEntry]:
        registry = self._for(provider)
        entry = registry.resolve_group(type_) if registry else None
        if entry is not None or provider == "aws":
            return entry
        aws = self._for("aws")
        return aws.resolve_group(type_) if aws else None

    def default_size(self, provider: str = "aws") -> float:
        registry = self._for(provider) or self._for("aws")
        return registry.default_size if registry else DEFAULT_ICON_SIZE

    @property
    def placeholder_icon(self) -> Path:
        return _placeholder_icon_path()


def load_registries(user_registry_path: Optional[str] = None) -> MultiRegistry:
    """Load every built-in provider registry (aws/gcp/azure), plus the
    provider a user registry declares (defaulting to "aws" if unset, or a
    brand-new key like "custom" if that's what it declares)."""
    user_provider = "aws"
    if user_registry_path:
        user_raw = yaml.safe_load(Path(user_registry_path).read_text())
        user_provider = user_raw.get("provider", "aws")

    providers = list(BUILTIN_PROVIDERS)
    if user_provider not in providers:
        providers.append(user_provider)

    registries = {
        provider: load_registry(
            provider=provider,
            user_registry_path=user_registry_path if provider == user_provider else None,
        )
        for provider in providers
    }
    return MultiRegistry(registries=registries)
