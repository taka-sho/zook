"""Tests for `zook diff` - the semantic structural diff.

The point of the feature is that it reports *meaning*, not text: matched by id,
normalised against defaults, so reordering children or writing a default value
explicitly is silent, while a real change (added/removed/moved/retyped element,
link change, canvas change) is reported exactly once.
"""

import json

from click.testing import CliRunner

from zook.diff import diff_diagrams

BASE = {
    "version": "1.0",
    "canvas": {"aspectRatio": "16:9"},
    "elements": [
        {
            "kind": "container",
            "id": "vpc",
            "type": "vpc",
            "provider": "aws",
            "children": [
                {"kind": "node", "id": "web", "type": "EC2", "label": "Web"},
                {"kind": "node", "id": "db", "type": "RDS", "label": "Primary DB"},
            ],
        }
    ],
    "links": [{"from": "web", "to": "db", "label": "3306"}],
}


def _clone(**overrides):
    import copy

    doc = copy.deepcopy(BASE)
    doc.update(overrides)
    return doc


def test_identical_diagrams_report_no_differences():
    assert diff_diagrams(_clone(), _clone()).identical


def test_reordering_children_is_not_a_difference():
    reordered = _clone()
    reordered["elements"][0]["children"].reverse()
    assert diff_diagrams(_clone(), reordered).identical


def test_explicit_default_value_is_not_a_difference():
    # `db` gains an explicit provider equal to the node default, and the
    # container an explicit default grid layout - neither changes meaning.
    new = _clone()
    new["elements"][0]["children"][1]["provider"] = "aws"
    new["elements"][0]["layout"] = {"direction": "grid"}
    assert diff_diagrams(_clone(), new).identical


def test_added_and_removed_elements():
    new = _clone()
    new["elements"][0]["children"].append({"kind": "node", "id": "cache", "type": "ElastiCache"})
    del new["elements"][0]["children"][0]  # remove web

    result = diff_diagrams(_clone(), new)
    assert [r.id for r in result.added_elements] == ["cache"]
    assert [r.id for r in result.removed_elements] == ["web"]


def test_reparented_element_is_reported_as_a_move_not_add_remove():
    new = _clone()
    web = new["elements"][0]["children"].pop(0)
    new["elements"].append({"kind": "container", "id": "edge", "type": "subnet", "children": [web]})

    result = diff_diagrams(_clone(), new)
    # web itself is neither added nor removed - only moved; the new `edge`
    # container that now holds it is the sole addition.
    assert "web" not in {r.id for r in result.added_elements} | {r.id for r in result.removed_elements}
    assert [r.id for r in result.added_elements] == ["edge"]
    assert [(r.id, r.old_parent, r.new_parent) for r in result.reparented] == [("web", "vpc", "edge")]


def test_modified_element_lists_field_changes():
    new = _clone()
    db = new["elements"][0]["children"][1]
    db["type"], db["label"] = "Aurora", "Main DB"

    result = diff_diagrams(_clone(), new)
    assert len(result.modified_elements) == 1
    mod = result.modified_elements[0]
    assert mod.id == "db"
    assert {c.field: (c.old, c.new) for c in mod.changes} == {
        "type": ("RDS", "Aurora"),
        "label": ("Primary DB", "Main DB"),
    }


def test_link_added_removed_and_modified():
    new = _clone()
    new["links"] = [
        {"from": "web", "to": "db", "label": "3306", "style": "elbow"},  # style changed
        {"from": "db", "to": "web"},  # added
    ]
    result = diff_diagrams(_clone(), new)
    assert [(r.from_id, r.to_id) for r in result.added_links] == [("db", "web")]
    assert len(result.modified_links) == 1
    assert result.modified_links[0].changes[0].field == "style"


def test_canvas_change_is_reported():
    new = _clone(canvas={"aspectRatio": "4:3"})
    result = diff_diagrams(_clone(), new)
    assert [(c.field, c.old, c.new) for c in result.canvas] == [("aspectRatio", "16:9", "4:3")]


# --- CLI ---


def _write(tmp_path, name, doc):
    import yaml

    path = tmp_path / name
    path.write_text(yaml.safe_dump(doc))
    return str(path)


def test_cli_text_output_marks_each_change(tmp_path):
    from zook.cli import main

    new = _clone(canvas={"aspectRatio": "4:3"})
    old_path = _write(tmp_path, "old.yaml", _clone())
    new_path = _write(tmp_path, "new.yaml", new)

    result = CliRunner().invoke(main, ["diff", old_path, new_path])
    assert result.exit_code == 0
    assert "~ canvas.aspectRatio" in result.stdout


def test_cli_exit_code_flag(tmp_path):
    from zook.cli import main

    old_path = _write(tmp_path, "old.yaml", _clone())
    same = CliRunner().invoke(main, ["diff", old_path, old_path, "--exit-code"])
    assert same.exit_code == 0
    assert "No structural differences." in same.stdout

    new_path = _write(tmp_path, "new.yaml", _clone(canvas={"aspectRatio": "4:3"}))
    differ = CliRunner().invoke(main, ["diff", old_path, new_path, "--exit-code"])
    assert differ.exit_code == 1


def test_cli_json_output(tmp_path):
    from zook.cli import main

    new = _clone()
    new["elements"][0]["children"][1]["type"] = "Aurora"
    old_path = _write(tmp_path, "old.yaml", _clone())
    new_path = _write(tmp_path, "new.yaml", new)

    result = CliRunner().invoke(main, ["diff", old_path, new_path, "--format", "json"])
    payload = json.loads(result.stdout)
    assert payload["identical"] is False
    assert payload["elements"]["modified"][0]["id"] == "db"


def test_cli_fatal_on_invalid_input(tmp_path):
    from zook.cli import main

    good = _write(tmp_path, "good.yaml", _clone())
    bad = tmp_path / "bad.yaml"
    bad.write_text("version: '1.0'\ncanvas: {aspectRatio: '16:9'}\nelements:\n  - {kind: node, id: a, type: EC2}\n"
                   "links:\n  - {from: a, to: ghost}\n")
    result = CliRunner().invoke(main, ["diff", good, str(bad), "--format", "json"])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["status"] == "error"
