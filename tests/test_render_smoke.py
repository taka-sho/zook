from pathlib import Path

import yaml
from pptx import Presentation

from archdiagram.errors import Warnings
from archdiagram.layout import build_layout
from archdiagram.model import parse_diagram
from archdiagram.registry import load_registry
from archdiagram.render import render
from archdiagram.validate import validate

FIXTURE = Path(__file__).parent / "fixtures" / "example.yaml"
CLOUD_ACTORS_FIXTURE = Path(__file__).parent / "fixtures" / "example-cloud-actors.yaml"


def _build(raw):
    validate(raw)
    diagram = parse_diagram(raw)
    registry = load_registry("aws")
    root_box = build_layout(diagram, registry)
    warnings = Warnings()
    presentation = render(diagram, root_box, registry, warnings)
    return presentation, warnings


def test_example_yaml_renders_without_warnings():
    raw = yaml.safe_load(FIXTURE.read_text())
    presentation, warnings = _build(raw)
    assert warnings.messages == []
    slide = presentation.slides[0]
    # 2 top-level VPC/S3 elements + 3 links (each a connector + 1 label textbox for the labeled link)
    assert len(slide.shapes) >= 5


def test_example_yaml_output_reopens_cleanly(tmp_path):
    raw = yaml.safe_load(FIXTURE.read_text())
    presentation, _ = _build(raw)
    out = tmp_path / "out.pptx"
    presentation.save(out)

    reopened = Presentation(str(out))
    assert reopened.slide_width == presentation.slide_width
    assert len(reopened.slides) == 1


def test_unresolved_icon_produces_warning_not_error():
    raw = {
        "version": "1.0",
        "canvas": {"aspectRatio": "16:9"},
        "elements": [{"kind": "node", "id": "mystery", "type": "NotARealService"}],
    }
    _, warnings = _build(raw)
    assert any("NotARealService" in m for m in warnings.messages)


def test_cli_exits_nonzero_on_fatal_error(tmp_path):
    from click.testing import CliRunner

    from archdiagram.cli import main

    bad_yaml = tmp_path / "bad.yaml"
    bad_yaml.write_text(
        """
version: "1.0"
canvas:
  aspectRatio: "16:9"
elements:
  - kind: node
    id: a
    type: EC2
  - kind: node
    id: a
    type: S3
"""
    )
    runner = CliRunner()
    result = runner.invoke(main, [str(bad_yaml), "-o", str(tmp_path / "out.pptx")])
    assert result.exit_code == 1
    assert "Duplicate" in result.output


def test_cli_succeeds_on_example_yaml(tmp_path):
    from click.testing import CliRunner

    from archdiagram.cli import main

    out_path = tmp_path / "out.pptx"
    runner = CliRunner()
    result = runner.invoke(main, [str(FIXTURE), "-o", str(out_path)])
    assert result.exit_code == 0
    assert out_path.exists()


def test_example_cloud_actors_renders_without_warnings():
    raw = yaml.safe_load(CLOUD_ACTORS_FIXTURE.read_text())
    presentation, warnings = _build(raw)
    assert warnings.messages == []
    slide = presentation.slides[0]
    assert len(slide.shapes) > 0


def test_cli_succeeds_on_example_cloud_actors(tmp_path):
    from click.testing import CliRunner

    from archdiagram.cli import main

    out_path = tmp_path / "out.pptx"
    runner = CliRunner()
    result = runner.invoke(main, [str(CLOUD_ACTORS_FIXTURE), "-o", str(out_path)])
    assert result.exit_code == 0
    assert out_path.exists()


def test_cli_reports_overlapping_elements_as_warning_not_error(tmp_path):
    from click.testing import CliRunner

    from archdiagram.cli import main

    overlapping_yaml = tmp_path / "overlap.yaml"
    overlapping_yaml.write_text(
        """
version: "1.0"
canvas:
  aspectRatio: "16:9"
elements:
  - kind: node
    id: a
    type: EC2
    x: 100
    y: 100
  - kind: node
    id: b
    type: EC2
    x: 105
    y: 105
"""
    )
    runner = CliRunner()
    result = runner.invoke(main, [str(overlapping_yaml), "-o", str(tmp_path / "out.pptx")])
    assert result.exit_code == 0
    assert "overlaps" in (result.output + result.stderr)


def test_cli_reports_link_crossing_as_warning_not_error(tmp_path):
    from click.testing import CliRunner

    from archdiagram.cli import main

    crossing_yaml = tmp_path / "crossing.yaml"
    crossing_yaml.write_text(
        """
version: "1.0"
canvas:
  aspectRatio: "16:9"
elements:
  - kind: node
    id: a
    type: EC2
    x: 0
    y: 100
  - kind: node
    id: b
    type: EC2
    x: 150
    y: 100
  - kind: node
    id: c
    type: EC2
    x: 300
    y: 100
links:
  - from: a
    to: c
"""
    )
    runner = CliRunner()
    result = runner.invoke(main, [str(crossing_yaml), "-o", str(tmp_path / "out.pptx")])
    assert result.exit_code == 0
    assert "passes through element 'b'" in (result.output + result.stderr)
