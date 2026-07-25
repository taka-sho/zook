"""Icon/group vocabulary resolution, per docs/icon-registry-and-vocabulary.md.

- `type` is never enum-constrained in the diagram schema; the registry is the
  single source of truth for the vocabulary.
- Lookup is alias-inclusive and case-insensitive (sec4).
- A user registry can be layered on top of the built-in one; same key wins
  for the user side (sec5).
- Unknown `type` is not fatal: caller gets `None` back and falls back to a
  placeholder icon with a Warning (sec9 error policy, enforced by the render
  layer, not here).
"""

from __future__ import annotations

import importlib.resources as resources
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

DEFAULT_ICON_SIZE = 64
PLACEHOLDER_ICON_NAME = "_placeholder.png"


@dataclass
class IconEntry:
    file: Path
    category: Optional[str] = None
    kind: str = "service"
    label: Optional[str] = None
    size: Optional[float] = None


@dataclass
class GroupEntry:
    label: str = ""
    border_color: str = "#5A6B86"
    fill_color: Optional[str] = None
    border_width: float = 1
    dashed: bool = False
    label_position: str = "top-left"
    icon: Optional[Path] = None


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
            category=spec.get("category"),
            kind=spec.get("kind", "service"),
            label=spec.get("label"),
            size=spec.get("size"),
        )
        index[key.lower()] = entry
        for alias in spec.get("aliases", []):
            index[alias.lower()] = entry
    return index


def _index_groups(raw_groups: dict, base_path: Path) -> dict[str, GroupEntry]:
    index: dict[str, GroupEntry] = {}
    for key, spec in raw_groups.items():
        entry = GroupEntry(
            label=spec.get("label", ""),
            border_color=spec.get("borderColor", "#5A6B86"),
            fill_color=spec.get("fillColor"),
            border_width=spec.get("borderWidth", 1),
            dashed=spec.get("dashed", False),
            label_position=spec.get("labelPosition", "top-left"),
            icon=(base_path / spec["icon"]) if spec.get("icon") else None,
        )
        index[key.lower()] = entry
        for alias in spec.get("aliases", []):
            index[alias.lower()] = entry
    return index


def _load_builtin_aws() -> tuple[dict, Path]:
    data_dir = resources.files("archdiagram.data.icons.aws")
    raw = yaml.safe_load(data_dir.joinpath("registry.aws.yaml").read_text())
    base_path = Path(str(data_dir)) / raw.get("basePath", ".")
    return raw, base_path


def load_registry(provider: str = "aws", user_registry_path: Optional[str] = None) -> Registry:
    if provider == "aws":
        raw, base_path = _load_builtin_aws()
    else:
        raw, base_path = {"icons": {}, "groups": {}, "defaults": {}}, Path(".")

    icons = _index_icons(raw.get("icons", {}), base_path)
    groups = _index_groups(raw.get("groups", {}), base_path)
    default_size = raw.get("defaults", {}).get("size", DEFAULT_ICON_SIZE)
    placeholder_dir = resources.files("archdiagram.data.icons.aws")
    placeholder_icon = Path(str(placeholder_dir)) / PLACEHOLDER_ICON_NAME

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
        placeholder_icon=placeholder_icon,
    )
