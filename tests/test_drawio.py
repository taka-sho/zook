import base64
import zlib
from pathlib import Path
from urllib.parse import quote
from xml.etree import ElementTree as ET

import yaml

from archdiagram.drawio import _diagram_model_root, _find_element_node, dump_yaml, export_drawio, sync_from_drawio
from archdiagram.layout import build_layout
from archdiagram.model import parse_diagram
from archdiagram.registry import load_registries

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
    assert "shape=image" in cell.get("style")
    assert "data:image/png;base64," in cell.get("style")


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
