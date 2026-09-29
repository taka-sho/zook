"""The package must carry everything an AI needs when zook is installed
from a wheel rather than cloned: the guide texts (byte-identical copies of
repository docs), the schemas and registries (copies of docs/), and the
patterns - and the commands that serve them must work."""

import json
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from zook.cli import main
from zook.guide import BUNDLED_DOCS, STARTER, TOPICS, guide_text, pattern_names, pattern_text
from zook.validate import validate

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "src" / "zook"

COPIES = {
    **{f"data/guide/{bundled}": source for bundled, source in BUNDLED_DOCS.items()},
    "schemas/zook.schema.json": "docs/zook.schema.json",
    "schemas/icon-registry.schema.json": "docs/icon-registry.schema.json",
    **{f"data/icons/{p}/registry.{p}.yaml": f"docs/registry.{p}.yaml" for p in ("aws", "gcp", "azure")},
}


@pytest.mark.parametrize("bundled, source", COPIES.items())
def test_bundled_copy_is_current(bundled, source):
    assert (PACKAGE / bundled).read_bytes() == (ROOT / source).read_bytes(), (
        f"src/zook/{bundled} is stale - run `python scripts/sync_bundled_docs.py` (docs) "
        f"or copy {source} over it (schemas/registries)"
    )


@pytest.mark.parametrize("topic", TOPICS)
def test_every_guide_topic_prints(topic):
    text = guide_text(topic)
    assert len(text) > 500 and "md-button" not in text


def test_workflow_guide_is_the_agent_part_of_agents_md():
    text = guide_text("workflow")
    assert text.startswith("## From Architecture Proposal")
    assert "## Key References" not in text and "## When Making Changes" not in text


@pytest.mark.parametrize("name", pattern_names())
def test_every_pattern_is_served_and_valid(name):
    validate(yaml.safe_load(pattern_text(name)))


def test_starter_is_valid_and_warning_free(tmp_path):
    validate(yaml.safe_load(STARTER))
    out = tmp_path / "d.yaml"
    runner = CliRunner()
    assert runner.invoke(main, ["init", str(out)]).exit_code == 0
    result = runner.invoke(main, ["validate", str(out), "--format", "json"])
    assert json.loads(result.stdout) == {"status": "ok", "warnings": [], "details": []}


def test_init_refuses_to_overwrite_and_writes_a_pattern(tmp_path):
    out = tmp_path / "d.yaml"
    out.write_text("mine", encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(main, ["init", str(out), "--format", "json"])
    assert result.exit_code == 1 and "already exists" in json.loads(result.stdout)["error"]
    assert out.read_text(encoding="utf-8") == "mine"
    assert runner.invoke(main, ["init", str(out), "--pattern", "serverless-api", "--force"]).exit_code == 0
    assert out.read_text(encoding="utf-8") == pattern_text("serverless-api")


def test_patterns_list_json_and_schema_commands():
    runner = CliRunner()
    listed = json.loads(runner.invoke(main, ["patterns", "list", "--format", "json"]).stdout)
    assert [p["name"] for p in listed] == pattern_names()
    assert all(p["summary"] and p["providers"] for p in listed)
    assert json.loads(runner.invoke(main, ["schema"]).stdout)["title"]
    assert "registryVersion" in json.loads(runner.invoke(main, ["schema", "--icon-registry"]).stdout)["required"]
    bad = runner.invoke(main, ["patterns", "show", "nope", "--format", "json"])
    assert bad.exit_code == 1 and "unknown pattern" in json.loads(bad.stdout)["error"]
