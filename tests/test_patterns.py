"""Regression tests for docs/patterns/*.yaml - the reference architecture
patterns meant for an AI (or human) to pick from and adapt (AGENTS.md).
Each one must stay warning-free and render successfully, the same
invariant already enforced for docs/example.yaml/example-cloud-actors.yaml
in test_render_smoke.py.
"""

from pathlib import Path

import pytest
import yaml

from zook.errors import Warnings
from zook.layout import (
    build_layout,
    icon_resolution_warnings,
    link_aliasing_warnings,
    link_crossing_warnings,
    out_of_canvas_warnings,
    overlap_warnings,
)
from zook.model import parse_diagram
from zook.registry import load_registries
from zook.render import render
from zook.validate import validate

PATTERNS_DIR = Path(__file__).parent.parent / "docs" / "patterns"
PATTERN_FILES = sorted(PATTERNS_DIR.glob("*.yaml"))


def test_patterns_directory_is_not_empty():
    assert len(PATTERN_FILES) >= 7


@pytest.mark.parametrize("path", PATTERN_FILES, ids=lambda p: p.name)
def test_pattern_renders_without_warnings(path: Path):
    raw = yaml.safe_load(path.read_text())
    validate(raw)
    diagram = parse_diagram(raw)
    registry = load_registries()
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

    assert warnings.messages == [], f"{path.name} produced warnings: {warnings.messages}"

    presentation = render(diagram, root_box, registry)
    assert len(presentation.slides[0].shapes) > 0


@pytest.mark.parametrize("path", PATTERN_FILES, ids=lambda p: p.name)
def test_pattern_builds_via_cli(path: Path, tmp_path):
    from click.testing import CliRunner

    from zook.cli import main

    out_path = tmp_path / f"{path.stem}.pptx"
    runner = CliRunner()
    result = runner.invoke(main, ["build", str(path), "-o", str(out_path)])
    assert result.exit_code == 0, result.output
    assert out_path.exists()
