import base64
import zlib
from pathlib import Path
from urllib.parse import quote
from xml.etree import ElementTree as ET

import yaml

from zook.drawio import _diagram_model_root, _find_element_node, dump_yaml, export_drawio, sync_from_drawio
from zook.layout import build_layout
from zook.model import parse_diagram
from zook.registry import load_registries

FIXTURE = Path(__file__).parent / "fixtures" / "example.yaml"
REGISTRY = load_registries()


def _export(raw):
    diagram = parse_diagram(raw)
    root_box = build_layout(diagram, REGISTRY)
    return diagram, root_box, export_drawio(diagram, root_box, REGISTRY)


def _model_root(xml_str: str) -> ET.Element:
    mxfile = ET.fromstring(xml_str)
    return _diagram_model_root(mxfile.find(".//diagram"))


def test_export_produces_parseable_xml_with_expected_structure():
    raw = yaml.safe_load(FIXTURE.read_text())
    _, _, xml_str = _export(raw)
    model = _model_root(xml_str)

    cells = {c.get("id"): c for c in model.findall(".//mxCell") if c.get("id") not in ("0", "1")}
    assert "vpc-main" in cells
    assert "web-a" in cells
    # container/node parent-child relationships map directly onto mxCell parent=
    assert cells["az-a"].get("parent") == "vpc-main"
    assert cells["web-a"].get("parent") == "az-a"
    # top-level elements parent to the default layer
    assert cells["vpc-main"].get("parent") == "1"


def test_export_uses_official_drawio_shape_when_the_registry_has_one():
    raw = yaml.safe_load(FIXTURE.read_text())
    _, _, xml_str = _export(raw)
    model = _model_root(xml_str)
    ec2_cell = next(c for c in model.findall(".//mxCell") if c.get("id") == "web-a")
    assert "mxgraph.aws4.ec2" in ec2_cell.get("style")


def test_export_falls_back_to_embedded_png_without_a_registry_shape():
    raw = {
        "version": "1.0",
        "canvas": {"aspectRatio": "16:9"},
        "elements": [{"kind": "node", "id": "a", "type": "Admin", "x": 0, "y": 0}],
    }
    _, _, xml_str = _export(raw)
    model = _model_root(xml_str)
    cell = next(c for c in model.findall(".//mxCell") if c.get("id") == "a")
    style = cell.get("style")
    assert "shape=image" in style
    # draw.io parses a style by splitting on ";" (mxStylesheet.getCellStyle),
    # so the image value must survive that split intact: the semicolon-free
    # `data:image/png,<base64>` form draw.io itself writes.
    entries = dict(part.split("=", 1) for part in style.split(";") if "=" in part)
    image = entries["image"]
    assert image.startswith("data:image/png,")
    assert base64.b64decode(image.split(",", 1)[1]).startswith(b"\x89PNG")


def test_links_export_as_edges_with_source_and_target():
    raw = yaml.safe_load(FIXTURE.read_text())
    _, _, xml_str = _export(raw)
    model = _model_root(xml_str)
    edges = [c for c in model.findall(".//mxCell") if c.get("edge") == "1"]
    assert any(e.get("source") == "web-a" and e.get("target") == "db-a" for e in edges)


def test_sync_with_no_changes_is_a_no_op(tmp_path):
    drawio_path = tmp_path / "example.drawio"
    raw = yaml.safe_load(FIXTURE.read_text())
    _, _, xml_str = _export(raw)
    drawio_path.write_text(xml_str)

    updated, warnings = sync_from_drawio(str(FIXTURE), str(drawio_path))
    assert warnings == []
    out_path = tmp_path / "roundtrip.yaml"
    dump_yaml(updated, str(out_path))
    assert out_path.read_text() == FIXTURE.read_text()


def test_sync_freezes_only_the_moved_auto_placed_element(tmp_path):
    drawio_path = tmp_path / "example.drawio"
    raw = yaml.safe_load(FIXTURE.read_text())
    _, _, xml_str = _export(raw)
    # web-a is auto-placed (no explicit x/y in example.yaml); nudge it.
    edited = xml_str.replace(
        '<mxGeometry x="45.00" y="60.00" width="64.00" height="64.00" as="geometry"/></mxCell>'
        '<mxCell id="db-a"',
        '<mxGeometry x="80.00" y="60.00" width="64.00" height="64.00" as="geometry"/></mxCell>'
        '<mxCell id="db-a"',
    )
    assert edited != xml_str, "replacement did not match - fixture geometry changed?"
    drawio_path.write_text(edited)

    updated, warnings = sync_from_drawio(str(FIXTURE), str(drawio_path))
    assert warnings == []

    web_a = _find_element_node(updated["elements"], "web-a")
    assert web_a["x"] == 80.0
    assert web_a["y"] == 60.0
    # its untouched sibling stays auto-placed
    db_a = _find_element_node(updated["elements"], "db-a")
    assert "x" not in db_a


def test_sync_updates_an_already_explicit_element_in_place(tmp_path):
    drawio_path = tmp_path / "example.drawio"
    raw = yaml.safe_load(FIXTURE.read_text())
    _, _, xml_str = _export(raw)
    edited = xml_str.replace('x="1080.00" y="300.00" width="96.00" height="96.00"', 'x="900.00" y="250.00" width="96.00" height="96.00"')
    assert edited != xml_str
    drawio_path.write_text(edited)

    updated, warnings = sync_from_drawio(str(FIXTURE), str(drawio_path))
    assert warnings == []
    bucket = next(e for e in updated["elements"] if e["id"] == "bucket")
    assert bucket["x"] == 900.0
    assert bucket["y"] == 250.0
    assert bucket["width"] == 96  # untouched dimension keeps its original value


def test_sync_warns_on_an_unknown_cell_and_leaves_yaml_unchanged(tmp_path):
    drawio_path = tmp_path / "example.drawio"
    raw = yaml.safe_load(FIXTURE.read_text())
    _, _, xml_str = _export(raw)
    edited = xml_str.replace(
        "</root>",
        '<mxCell id="mystery" value="X" style="" vertex="1" parent="1">'
        '<mxGeometry x="0" y="0" width="10" height="10" as="geometry"/></mxCell></root>',
    )
    drawio_path.write_text(edited)

    _, warnings = sync_from_drawio(str(FIXTURE), str(drawio_path))
    assert any("mystery" in w and "ignored" in w for w in warnings)


def test_sync_warns_when_a_known_element_is_missing_from_the_drawio_file(tmp_path):
    import re

    drawio_path = tmp_path / "example.drawio"
    raw = yaml.safe_load(FIXTURE.read_text())
    _, _, xml_str = _export(raw)
    edited = re.sub(r'<mxCell id="fn-c"[^>]*>.*?</mxCell>', "", xml_str)
    assert 'id="fn-c"' not in edited
    drawio_path.write_text(edited)

    _, warnings = sync_from_drawio(str(FIXTURE), str(drawio_path))
    assert any("fn-c" in w and "deleted" in w for w in warnings)


def test_decode_diagram_handles_drawios_own_compressed_format():
    inner_xml = (
        '<mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/>'
        '<mxCell id="a" vertex="1" parent="1"><mxGeometry x="10" y="20" width="30" height="40" '
        'as="geometry"/></mxCell></root></mxGraphModel>'
    )
    encoded = quote(inner_xml, safe="")
    compressor = zlib.compressobj(level=9, wbits=-15)
    compressed = compressor.compress(encoded.encode("utf-8")) + compressor.flush()
    b64 = base64.b64encode(compressed).decode("ascii")

    drawio_text = f'<mxfile><diagram id="x" name="Page-1">{b64}</diagram></mxfile>'
    mxfile = ET.fromstring(drawio_text)
    model_root = _diagram_model_root(mxfile.find(".//diagram"))
    assert model_root is not None
    cell = model_root.find('.//mxCell[@id="a"]')
    assert cell is not None
    geom = cell.find("mxGeometry")
    assert (geom.get("x"), geom.get("y"), geom.get("width"), geom.get("height")) == ("10", "20", "30", "40")


def test_labels_with_xml_and_html_special_characters_export_to_valid_xml(tmp_path):
    # saxutils.escape() leaves `"` alone, so a label containing one closed the
    # value="..." attribute early: the file said "Wrote" but draw.io couldn't
    # open it and sync crashed on it.
    label = 'Say "hi" <b>& bye</b>\nline two'
    raw = {
        "version": "1.0",
        "canvas": {"aspectRatio": "16:9"},
        "elements": [
            {"kind": "container", "id": "g", "type": "group", "label": label,
             "children": [{"kind": "node", "id": "a", "type": "EC2", "label": label}]},
            {"kind": "node", "id": "b", "type": "EC2", "x": 600, "y": 300},
        ],
        "links": [{"from": "a", "to": "b", "label": label}],
    }
    _, _, xml_str = _export(raw)
    model = _model_root(xml_str)  # parses: the attribute survived intact
    cells = {c.get("id"): c for c in model.findall(".//mxCell")}

    # html=1 cells: HTML-escaped, newline as <br>, so draw.io shows the text literally
    assert "html=1" in cells["a"].get("style")
    assert cells["a"].get("value") == 'Say "hi" &lt;b&gt;&amp; bye&lt;/b&gt;<br>line two'
    assert cells["g"].get("value") == cells["a"].get("value")
    # the edge style has no html=1: plain text, newline preserved
    edge = next(c for c in model.findall(".//mxCell") if c.get("edge") == "1")
    assert edge.get("value") == label

    drawio_path = tmp_path / "d.drawio"
    drawio_path.write_text(xml_str, encoding="utf-8")
    yaml_path = tmp_path / "d.yaml"
    yaml_path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    _, warnings = sync_from_drawio(str(yaml_path), str(drawio_path))
    assert warnings == []


def test_undecodable_compressed_diagram_is_a_diagram_error(tmp_path):
    import pytest

    from zook.errors import DiagramError

    yaml_path = tmp_path / "d.yaml"
    yaml_path.write_text(FIXTURE.read_text())
    drawio_path = tmp_path / "d.drawio"
    drawio_path.write_text('<mxfile><diagram id="x">not base64 at all!</diagram></mxfile>')
    with pytest.raises(DiagramError, match="could not decode"):
        sync_from_drawio(str(yaml_path), str(drawio_path))


def test_compressed_diagram_that_inflates_too_far_is_refused(tmp_path, monkeypatch):
    import pytest

    import zook.drawio
    from zook.errors import DiagramError

    monkeypatch.setattr(zook.drawio, "_MAX_INFLATED_BYTES", 1024)
    payload = quote("<mxGraphModel><root>" + "<mxCell/>" * 2000 + "</root></mxGraphModel>")
    compressor = zlib.compressobj(9, zlib.DEFLATED, -15)
    data = base64.b64encode(compressor.compress(payload.encode()) + compressor.flush()).decode()
    yaml_path = tmp_path / "d.yaml"
    yaml_path.write_text(FIXTURE.read_text())
    drawio_path = tmp_path / "d.drawio"
    drawio_path.write_text(f'<mxfile><diagram id="x">{data}</diagram></mxfile>')
    with pytest.raises(DiagramError, match="inflates past"):
        sync_from_drawio(str(yaml_path), str(drawio_path))


def _compressed_drawio(xml_model: str, wrap: int | None = None) -> str:
    payload = quote(xml_model, safe="-_.!~*'()")
    compressor = zlib.compressobj(9, zlib.DEFLATED, -15)
    data = base64.b64encode(compressor.compress(payload.encode()) + compressor.flush()).decode()
    if wrap:
        data = "\n".join(data[i : i + wrap] for i in range(0, len(data), wrap))
    return f'<mxfile><diagram id="x">{data}</diagram></mxfile>'


def test_sync_accepts_base64_wrapped_with_newlines(tmp_path):
    # draw.io decodes with atob(), which ignores whitespace in the payload.
    raw = yaml.safe_load(FIXTURE.read_text())
    _, _, xml_str = _export(raw)
    model_xml = ET.tostring(_model_root(xml_str), encoding="unicode")
    yaml_path = tmp_path / "d.yaml"
    yaml_path.write_text(FIXTURE.read_text())
    drawio_path = tmp_path / "d.drawio"
    drawio_path.write_text(_compressed_drawio(model_xml, wrap=76))
    _, warnings = sync_from_drawio(str(yaml_path), str(drawio_path))
    assert warnings == []


def test_non_ascii_compressed_content_is_a_diagram_error(tmp_path):
    import pytest

    from zook.errors import DiagramError

    yaml_path = tmp_path / "d.yaml"
    yaml_path.write_text(FIXTURE.read_text())
    drawio_path = tmp_path / "d.drawio"
    drawio_path.write_text('<mxfile><diagram id="x">図のテキスト</diagram></mxfile>', encoding="utf-8")
    with pytest.raises(DiagramError, match="could not decode"):
        sync_from_drawio(str(yaml_path), str(drawio_path))


def test_xml_illegal_characters_are_dropped_from_labels():
    raw = {
        "version": "1.0",
        "canvas": {"aspectRatio": "16:9"},
        "elements": [{"kind": "node", "id": "a", "type": "EC2", "label": "bell\x07 ff\x0c ok\ud800"}],
    }
    _, _, xml_str = _export(raw)
    cell = next(c for c in _model_root(xml_str).findall(".//mxCell") if c.get("id") == "a")
    assert cell.get("value") == "bell ff ok"


def test_html_label_detection_follows_drawio(tmp_path):
    from zook.drawio import _cell_value

    assert _cell_value("a & <b>", "shape=x;whiteSpace=wrap;") == "a &amp; &lt;b&gt;"
    assert _cell_value("a & <b>", "html=1;shape=x;html=0;") == "a & <b>"
    assert _cell_value("a & <b>", "shape=x;") == "a & <b>"


def test_unchanged_sync_leaves_the_yaml_byte_identical(tmp_path):
    from click.testing import CliRunner

    from zook.cli import main

    yaml_path = tmp_path / "d.yaml"
    yaml_path.write_text("# a comment\n" + FIXTURE.read_text())
    original = yaml_path.read_bytes()
    drawio_path = tmp_path / "d.drawio"
    assert CliRunner().invoke(main, ["export-drawio", str(yaml_path), "-o", str(drawio_path)]).exit_code == 0

    result = CliRunner().invoke(main, ["sync", str(yaml_path), str(drawio_path), "--format", "json"])
    assert result.exit_code == 0
    assert yaml_path.read_bytes() == original


# --- sync: edits vs. the export, drift, structure ---

import re as _re

import pytest as _pytest

from zook.errors import DiagramError as _DiagramError

_VERTICAL = {
    "version": "1.0",
    "canvas": {"aspectRatio": "16:9"},
    "elements": [{
        "kind": "container", "id": "g", "type": "group", "layout": {"direction": "vertical"},
        "children": [
            {"kind": "node", "id": "a", "type": "EC2"},
            {"kind": "node", "id": "b", "type": "EC2"},
            {"kind": "node", "id": "c", "type": "EC2"},
        ],
    }, {"kind": "node", "id": "z", "type": "S3", "x": 600, "y": 100}],
    "links": [{"from": "a", "to": "z"}],
}


def _roundtrip_files(tmp_path, raw):
    yaml_path = tmp_path / "d.yaml"
    yaml_path.write_text(yaml.safe_dump(raw, sort_keys=False))
    _, _, xml_str = _export(raw)
    drawio_path = tmp_path / "d.drawio"
    return yaml_path, drawio_path, xml_str


def _move(xml_str, cell_id, x, y):
    pattern = _re.compile(rf'(<mxCell id="{cell_id}"[^>]*><mxGeometry )x="[^"]*" y="[^"]*"')
    edited, n = pattern.subn(rf'\g<1>x="{x}" y="{y}"', xml_str)
    assert n == 1
    return edited


def _layout_of(raw):
    root = build_layout(parse_diagram(raw), REGISTRY)
    from zook.layout import iter_boxes

    return {b.element.id: (round(b.local_x, 1), round(b.local_y, 1)) for b in iter_boxes(root) if b.element.id != "__root__"}


def test_moving_one_auto_element_keeps_its_siblings_where_drawio_showed_them(tmp_path):
    # Moving `a` takes it out of g's auto flow: b and c used to re-pack up
    # into its old spot (and could land on top of each other).
    yaml_path, drawio_path, xml_str = _roundtrip_files(tmp_path, _VERTICAL)
    before = _layout_of(_VERTICAL)
    drawio_path.write_text(_move(xml_str, "a", 200, 40))

    updated, warnings = sync_from_drawio(str(yaml_path), str(drawio_path))
    assert warnings == []
    after = _layout_of(updated)
    assert after["a"] == (200.0, 40.0)
    assert after["b"] == before["b"] and after["c"] == before["c"]


def test_a_drawio_exported_before_a_yaml_edit_does_not_revert_it(tmp_path):
    yaml_path, drawio_path, xml_str = _roundtrip_files(tmp_path, _VERTICAL)
    drawio_path.write_text(xml_str)
    changed = _copy_with_gap(_VERTICAL, 60)  # the YAML changes after the export
    yaml_path.write_text(yaml.safe_dump(changed, sort_keys=False))

    updated, warnings = sync_from_drawio(str(yaml_path), str(drawio_path))
    assert any("changed since this .drawio was exported" in w for w in warnings)
    assert all("x" not in c for c in updated["elements"][0]["children"])  # nothing pinned back
    assert _layout_of(updated) == _layout_of(changed)


def _copy_with_gap(raw, gap):
    import copy

    out = copy.deepcopy(raw)
    out["elements"][0]["layout"]["gap"] = gap
    return out


def test_reparenting_in_drawio_is_reported_not_misapplied(tmp_path):
    yaml_path, drawio_path, xml_str = _roundtrip_files(tmp_path, _VERTICAL)
    edited = xml_str.replace('<mxCell id="b" ', '<mxCell id="b" ').replace(
        _re.search(r'<mxCell id="b"[^>]*>', xml_str).group(0),
        _re.search(r'<mxCell id="b"[^>]*>', xml_str).group(0).replace('parent="g"', 'parent="1"'),
    )
    drawio_path.write_text(_move(edited, "b", 400, 300))

    updated, warnings = sync_from_drawio(str(yaml_path), str(drawio_path))
    assert any("'b' was moved into the top level" in w for w in warnings)
    b = next(c for c in updated["elements"][0]["children"] if c["id"] == "b")
    assert "x" not in b


def test_edited_bend_points_become_waypoints_and_label_edits_are_reported(tmp_path):
    raw = {**_VERTICAL, "links": [{"from": "a", "to": "z", "label": "HTTPS"}]}
    yaml_path, drawio_path, xml_str = _roundtrip_files(tmp_path, raw)
    edited = xml_str.replace(
        '<mxGeometry relative="1" as="geometry"/>',
        '<mxGeometry relative="1" as="geometry"><Array as="points"><mxPoint x="300" y="80"/></Array></mxGeometry>',
    ).replace('value="HTTPS"', 'value="HTTP/2"')
    drawio_path.write_text(edited)

    updated, warnings = sync_from_drawio(str(yaml_path), str(drawio_path))
    assert updated["links"][0]["waypoints"] == [{"x": 300, "y": 80}]
    assert any("label of link 'a' -> 'z' was changed" in w for w in warnings)


def test_a_file_without_a_diagram_is_an_error(tmp_path):
    yaml_path, drawio_path, _ = _roundtrip_files(tmp_path, _VERTICAL)
    drawio_path.write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")
    with _pytest.raises(_DiagramError, match="no <diagram>"):
        sync_from_drawio(str(yaml_path), str(drawio_path))


def test_a_shape_wrapped_in_a_user_object_is_still_synced(tmp_path):
    # draw.io wraps a cell in <UserObject> once it gets a link or a tooltip.
    yaml_path, drawio_path, xml_str = _roundtrip_files(tmp_path, _VERTICAL)
    cell = _re.search(r'<mxCell id="z"[^>]*>.*?</mxCell>', xml_str).group(0)
    wrapped = cell.replace('<mxCell id="z" value="S3" ', '<UserObject label="S3" link="https://example.com" id="z"><mxCell ')
    wrapped = wrapped.replace('x="600.00" y="100.00"', 'x="650" y="120"') + "</UserObject>"
    drawio_path.write_text(xml_str.replace(cell, wrapped))

    updated, warnings = sync_from_drawio(str(yaml_path), str(drawio_path))
    assert not any("'z'" in w and "deleted" in w for w in warnings)
    assert (updated["elements"][1]["x"], updated["elements"][1]["y"]) == (650, 120)


def test_the_zook_page_is_synced_when_there_are_several(tmp_path):
    yaml_path, drawio_path, xml_str = _roundtrip_files(tmp_path, _VERTICAL)
    other = '<diagram id="other" name="Notes"><mxGraphModel><root><mxCell id="0"/></root></mxGraphModel></diagram>'
    drawio_path.write_text(_move(xml_str, "z", 700, 100).replace('<mxfile host="zook">', '<mxfile host="zook">' + other))
    updated, warnings = sync_from_drawio(str(yaml_path), str(drawio_path))
    assert updated["elements"][1]["x"] == 700
    assert warnings == []


def test_export_carries_styles_sides_and_background():
    raw = {
        "version": "1.0",
        "canvas": {"aspectRatio": "16:9", "background": "#F0F0F0"},
        "elements": [
            {"kind": "container", "id": "g", "type": "vpc", "provider": "aws", "label": "VPC",
             "style": {"borderColor": "#FF0000", "labelPosition": "bottom-left", "labelFontSize": 15},
             "children": [{"kind": "node", "id": "a", "type": "EC2", "style": {"labelPosition": "right", "labelFontSize": 12}}]},
            {"kind": "node", "id": "b", "type": "EC2", "x": 700, "y": 400},
        ],
        "links": [{"from": "a", "to": "b", "fromSide": "bottom", "toSide": "top"}],
    }
    _, _, xml_str = _export(raw)
    model = _model_root(xml_str)
    assert ET.fromstring(xml_str).find(".//mxGraphModel").get("background") == "#F0F0F0"
    cells = {c.get("id"): c for c in model.findall(".//mxCell")}
    g_style = cells["g"].get("style")
    assert "strokeColor=#FF0000" in g_style and "verticalAlign=bottom" in g_style and "fontSize=20" in g_style
    assert "labelPosition=right" in cells["a"].get("style") and "fontSize=16" in cells["a"].get("style")
    edge = next(c for c in model.findall(".//mxCell") if c.get("edge") == "1")
    assert "exitX=0.5;exitY=1" in edge.get("style") and "entryX=0.5;entryY=0" in edge.get("style")
    assert cells["zook-meta"].get("visible") == "0"
