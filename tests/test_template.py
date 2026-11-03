"""Slide sizes beyond 16:9 and 4:3, and `zook build --template`."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.oxml.ns import qn
from pptx.util import Emu

from zook.cli import main
from zook.errors import DiagramError
from zook.layout import build_layout
from zook.model import parse_diagram
from zook.registry import load_registries
from zook.render import render
from zook.template import layout_background, open_template
from zook.validate import validate

EMU = 9525


def _diagram(canvas: dict | None = None) -> dict:
    return {
        "version": "1.0",
        "canvas": canvas or {"aspectRatio": "16:9"},
        "elements": [
            {"kind": "node", "id": "a", "type": "User", "label": "Client"},
            {"kind": "node", "id": "b", "type": "User", "label": "Server"},
        ],
        "links": [{"from": "a", "to": "b"}],
    }


def _write_diagram(path: Path, canvas: dict | None = None) -> str:
    path.write_text(yaml.safe_dump(_diagram(canvas)))
    return str(path)


def _render(raw: dict, template_path=None):
    diagram = parse_diagram(raw)
    registry = load_registries()
    return render(diagram, build_layout(diagram, registry), registry, template_path)


def _make_template(path: Path, size=(1280, 720), background=None, slides=1, logo=True) -> str:
    """A template the way a company has one: a logo on its blank layout, a
    sample slide, perhaps a dark background on the master."""
    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(size[0] * EMU), Emu(size[1] * EMU)
    title_only = prs.slide_layouts[5]
    for number in range(slides):
        slide = prs.slides.add_slide(title_only)
        slide.shapes.title.text = f"Secret sample slide {number}"
    if logo:
        scratch = prs.slides.add_slide(prs.slide_layouts[6])
        box = scratch.shapes.add_textbox(Emu(1100 * EMU), Emu(20 * EMU), Emu(120 * EMU), Emu(40 * EMU))
        box.text_frame.text = "ACME LOGO"
        box.name = "Logo"
        element = box._element
        element.getparent().remove(element)
        prs.slide_layouts[6].shapes._spTree.append(element)
        slide_ids = prs.slides._sldIdLst
        scratch_id = slide_ids[-1]
        prs.part.drop_rel(scratch_id.rId)
        slide_ids.remove(scratch_id)
    if background:
        fill = prs.slide_master.background.fill
        fill.solid()
        fill.fore_color.rgb = RGBColor.from_string(background.lstrip("#"))
    prs.save(path)
    return str(path)


def _as_potx(pptx_path: str, potx_path: Path) -> str:
    with zipfile.ZipFile(pptx_path) as source, zipfile.ZipFile(potx_path, "w", zipfile.ZIP_DEFLATED) as out:
        for item in source.infolist():
            data = source.read(item)
            if item.filename == "[Content_Types].xml":
                data = data.replace(b"presentationml.presentation.main+xml", b"presentationml.template.main+xml")
            out.writestr(item, data)
    return str(potx_path)


def _roundtrip(prs, tmp_path: Path, name: str = "out.pptx"):
    path = tmp_path / name
    prs.save(path)
    return Presentation(path), path


def _package_text(path: Path) -> bytes:
    with zipfile.ZipFile(path) as package:
        return b"".join(package.read(name) for name in package.namelist())


# --- slide sizes ---


@pytest.mark.parametrize("canvas, size", [
    ({"aspectRatio": "A4"}, (1040, 720)),
    ({"width": 1600, "height": 900}, (1600, 900)),
    ({"width": 720, "height": 1280}, (720, 1280)),
    ({"width": 96, "height": 5376}, (96, 5376)),
])
def test_canvas_sizes_reach_the_slide(canvas, size):
    raw = _diagram(canvas)
    validate(raw)
    prs = _render(raw)
    assert (prs.slide_width, prs.slide_height) == (size[0] * EMU, size[1] * EMU)
    assert len(prs.slides) == 1


def test_a4_is_named_as_powerpoints_a4_and_other_sizes_are_not():
    assert _render(_diagram({"aspectRatio": "A4"})).part._element.find(qn("p:sldSz")).get("type") == "A4"
    for canvas in ({"aspectRatio": "16:9"}, {"aspectRatio": "4:3"}, {"width": 1040, "height": 720}):
        assert "type" not in _render(_diagram(canvas)).part._element.find(qn("p:sldSz")).attrib


@pytest.mark.parametrize("canvas, expected", [
    ({"width": 1600}, "'height' is a required property"),
    ({"height": 900}, "'width' is a required property"),
    ({"aspectRatio": "16:9", "width": 1600, "height": 900}, "either aspectRatio or width/height, not both"),
    ({"padding": 10}, "'aspectRatio' is a required property"),
    ({"width": 95, "height": 900}, "less than the minimum"),
    ({"width": 5377, "height": 900}, "greater than the maximum"),
    ({"aspectRatio": "A3"}, "is not one of"),
])
def test_invalid_canvas_sizes_are_fatal(canvas, expected):
    with pytest.raises(DiagramError, match=expected):
        validate(_diagram(canvas))


def test_huge_integer_next_to_a_custom_size_does_not_crash_the_error_report():
    with pytest.raises(DiagramError, match="'bogus' was unexpected"):
        validate(_diagram({"width": 1600, "height": 900, "padding": int("F" * 4000, 16), "bogus": 1}))


def test_portrait_canvas_lays_out_within_the_slide():
    raw = _diagram({"width": 720, "height": 1280})
    raw["elements"] = [{"kind": "node", "id": f"n{i}", "type": "User", "label": f"Node {i}"} for i in range(12)]
    raw["links"] = []
    diagram = parse_diagram(raw)
    box = build_layout(diagram, load_registries())
    assert all(child.abs_x + child.width <= 720 and child.abs_y + child.height <= 1280 for child in box.children)


def test_shrink_hint_suggests_16_9_only_to_a_narrower_canvas(tmp_path):
    def warnings(canvas):
        raw = _diagram(canvas)
        raw["elements"] = [{"kind": "node", "id": f"n{i}", "type": "User", "label": f"Node {i}"} for i in range(150)]
        raw["links"] = []
        result = CliRunner().invoke(main, ["validate", _write_raw(tmp_path / "many.yaml", raw), "--format", "json"])
        return json.loads(result.output)["warnings"]

    assert any("aspectRatio 16:9" in w for w in warnings({"aspectRatio": "A4"}))
    assert not any("aspectRatio 16:9" in w for w in warnings({"width": 1600, "height": 900}))


def _write_raw(path: Path, raw: dict) -> str:
    path.write_text(yaml.safe_dump(raw))
    return str(path)


def test_diff_reports_a_size_change(tmp_path):
    old = _write_diagram(tmp_path / "old.yaml", {"aspectRatio": "16:9"})
    new = _write_diagram(tmp_path / "new.yaml", {"width": 1600, "height": 900})
    result = CliRunner().invoke(main, ["diff", old, new])
    assert "canvas.width" in result.output and "canvas.height" in result.output and "canvas.aspectRatio" in result.output


@pytest.mark.parametrize("command, suffix", [("preview", "png"), ("export-drawio", "drawio")])
def test_other_outputs_take_a_custom_size(tmp_path, command, suffix):
    source = _write_diagram(tmp_path / "d.yaml", {"width": 1600, "height": 900})
    out = tmp_path / f"out.{suffix}"
    result = CliRunner().invoke(main, [command, source, "-o", str(out)])
    assert result.exit_code == 0, result.output
    if suffix == "drawio":
        assert 'pageWidth="1600"' in out.read_text() and 'pageHeight="900"' in out.read_text()
    else:
        from PIL import Image
        assert Image.open(out).size == (2400, 1350)


# --- build without a template stays what it was ---


def test_no_template_output_has_no_thumbnail_or_stale_part_titles(tmp_path):
    _, path = _roundtrip(_render(_diagram()), tmp_path)
    with zipfile.ZipFile(path) as package:
        names = package.namelist()
        app = package.read("docProps/app.xml").decode()
    assert not any("thumbnail" in name for name in names)
    assert "TitlesOfParts" not in app and "HeadingPairs" not in app


def test_no_template_uses_the_blank_layout_on_white():
    prs = _render(_diagram())
    assert prs.slides[0].slide_layout.name == "Blank"
    assert layout_background(prs.slides[0].slide_layout) == "#FFFFFF"
    assert not list(prs.slides[0].placeholders)


# --- --template ---


def test_template_keeps_the_masters_and_drops_its_slides(tmp_path):
    template = _make_template(tmp_path / "corp.pptx", slides=3)
    prs, path = _roundtrip(_render(_diagram(), template), tmp_path)

    assert len(prs.slides) == 1
    layout = prs.slides[0].slide_layout
    assert layout._element.get("type") == "blank"
    assert any(shape.name == "Logo" for shape in layout.shapes)
    assert not list(prs.slides[0].placeholders)
    assert b"Secret sample slide" not in _package_text(path)
    with zipfile.ZipFile(path) as package:
        slides = [n for n in package.namelist() if n.startswith("ppt/slides/") and n.endswith(".xml")]
        assert slides == ["ppt/slides/slide1.xml"]


def test_potx_is_accepted(tmp_path):
    potx = _as_potx(_make_template(tmp_path / "corp.pptx"), tmp_path / "corp.potx")
    prs, path = _roundtrip(_render(_diagram(), potx), tmp_path)
    assert len(prs.slides) == 1
    with zipfile.ZipFile(path) as package:
        types = package.read("[Content_Types].xml")
    assert b"presentationml.presentation.main+xml" in types and b"template.main+xml" not in types


def test_template_is_left_untouched(tmp_path):
    template = Path(_make_template(tmp_path / "corp.pptx", slides=2))
    before = template.read_bytes()
    _render(_diagram(), str(template)).save(tmp_path / "out.pptx")
    assert template.read_bytes() == before
    assert len(Presentation(template).slides) == 2


def test_a_section_list_and_custom_show_dont_outlive_the_slides(tmp_path):
    template = tmp_path / "corp.pptx"
    prs = Presentation(_make_template(template, slides=2))
    root = prs.part._element
    p14 = "http://schemas.microsoft.com/office/powerpoint/2010/main"
    first_id = prs.slides._sldIdLst[0]
    from lxml import etree
    p_ns, r_ns = "http://schemas.openxmlformats.org/presentationml/2006/main", "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    root.append(etree.fromstring(
        f'<p:extLst xmlns:p="{p_ns}"><p:ext uri="{{521415D9-36F7-43E2-AB2F-B90AF26B5E84}}">'
        f'<p14:sectionLst xmlns:p14="{p14}"><p14:section name="Intro" id="{{00000000-0000-0000-0000-000000000000}}">'
        f'<p14:sldIdLst><p14:sldId id="{first_id.id}"/></p14:sldIdLst></p14:section></p14:sectionLst></p:ext></p:extLst>'
    ))
    show = etree.fromstring(
        f'<p:custShowLst xmlns:p="{p_ns}" xmlns:r="{r_ns}"><p:custShow name="Short" id="0">'
        f'<p:sldLst><p:sld r:id="{first_id.rId}"/></p:sldLst></p:custShow></p:custShowLst>'
    )
    prs.slides._sldIdLst.addnext(show)
    prs.save(template)

    out, path = _roundtrip(_render(_diagram(), str(template)), tmp_path)
    xml = out.part.blob.decode()
    assert "sectionLst" not in xml and "custShow" not in xml
    assert len(out.slides) == 1
    assert b"Secret sample slide" not in _package_text(path)


def test_a_button_jumping_to_a_sample_slide_doesnt_keep_it_in_the_file(tmp_path):
    """The link would keep the sample slide's text in every generated file,
    unseen, under a name that could also collide with the new slide's."""
    template = tmp_path / "corp.pptx"
    prs = Presentation(_make_template(template))
    layout = prs.slide_layouts[6]
    rId = layout.part.relate_to(prs.slides[0].part, "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide")
    logo = next(shape for shape in layout.shapes if shape.name == "Logo")
    properties = logo._element.find(f"{qn('p:nvSpPr')}/{qn('p:cNvPr')}")
    link = properties.makeelement(qn("a:hlinkClick"), {qn("r:id"): rId, "action": "ppaction://hlinksldjump"})
    properties.append(link)
    prs.save(template)

    out, path = _roundtrip(_render(_diagram(), str(template)), tmp_path)
    assert b"Secret sample slide" not in _package_text(path)
    with zipfile.ZipFile(path) as package:
        names = package.namelist()
    assert [n for n in names if n.startswith("ppt/slides/") and n.endswith(".xml")] == ["ppt/slides/slide1.xml"]
    assert len(names) == len(set(names))

    layout = out.slides[0].slide_layout
    assert any(shape.name == "Logo" for shape in layout.shapes)  # the button stays
    assert b"hlinkClick" not in layout.part.blob
    assert not [rel for rel in layout.part.rels.values() if rel.reltype.endswith("/slide")]


def test_view_state_listing_slides_is_dropped_with_them(tmp_path):
    """viewProps.xml can list slides in its own relationships (outline view)."""
    template = tmp_path / "corp.pptx"
    prs = Presentation(_make_template(template))
    view_props = next(rel.target_part for rel in prs.part.rels.values() if rel.reltype.endswith("/viewProps"))
    view_props.relate_to(prs.slides[0].part, "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide")
    prs.save(template)

    out, path = _roundtrip(_render(_diagram(), str(template)), tmp_path)
    assert b"Secret sample slide" not in _package_text(path)
    assert len(out.slides) == 1


def test_size_mismatch_names_the_fix(tmp_path):
    template = _make_template(tmp_path / "corp.pptx")
    with pytest.raises(DiagramError, match=r'1280x720 slides .* canvas is 960x720 - set canvas to \{aspectRatio: "16:9"\}') as err:
        _render(_diagram({"aspectRatio": "4:3"}), template)
    assert err.value.code == "template-size-mismatch"
    assert err.value.details[0]["template"] == {"width": 1280, "height": 720}


def test_size_mismatch_with_a_size_no_preset_has(tmp_path):
    template = _make_template(tmp_path / "corp.pptx", size=(960, 540))
    with pytest.raises(DiagramError, match=r"set canvas to \{width: 960, height: 540\}"):
        _render(_diagram(), template)
    assert len(_render(_diagram({"width": 960, "height": 540}), template).slides) == 1


def test_nearly_the_same_size_counts_as_the_same(tmp_path):
    template = tmp_path / "corp.pptx"
    prs = Presentation(_make_template(template))
    prs.slide_width = Emu(12191695)  # how PowerPoint has saved 16:9
    prs.save(template)
    out = _render(_diagram(), str(template))
    assert out.slide_width == 12191695  # the master was drawn for this; it isn't resized


def test_dark_template_background_makes_labels_readable(tmp_path):
    template = _make_template(tmp_path / "corp.pptx", background="#101820")

    def label_colors(prs):
        colors = []
        for shape in prs.slides[0].shapes:
            shapes = shape.shapes if shape.shape_type == 6 else [shape]
            for inner in shapes:
                if inner.has_text_frame and inner.text_frame.text in ("Client", "Server"):
                    colors.append(str(inner.text_frame.paragraphs[0].runs[0].font.color.rgb))
        return colors

    dark = label_colors(_render(_diagram(), template))
    assert dark and set(dark) == {"FFFFFF"}
    # canvas.background wins over the template's
    assert set(label_colors(_render(_diagram({"aspectRatio": "16:9", "background": "#FFFFFF"}), template))) != {"FFFFFF"}


def test_nothing_takes_its_text_colour_from_the_theme(tmp_path):
    """A dark theme maps the text colour to white. Link labels, unset, came out
    white on their own white box - invisible on half of Microsoft's dark themes."""
    template = tmp_path / "corp.pptx"
    prs = Presentation(_make_template(template, logo=False))
    color_map = prs.slide_master._element.find(qn("p:clrMap"))
    color_map.set("bg1", "dk1")
    color_map.set("tx1", "lt1")
    prs.save(template)

    raw = _diagram()
    raw["links"][0]["label"] = "HTTPS"
    raw["elements"].append({"kind": "container", "id": "c", "type": "Frame", "label": "Frame", "children": [
        {"kind": "node", "id": "d", "type": "User", "label": "Inside"},
    ]})
    tree = _render(raw, str(template)).slides[0].shapes._spTree
    runs = list(tree.iter(qn("a:r")))
    assert {run.find(qn("a:t")).text for run in runs} >= {"HTTPS", "Client", "Frame", "Inside"}
    for run in runs:
        assert run.find(qn("a:rPr")).find(qn("a:solidFill")) is not None, run.find(qn("a:t")).text


def test_background_colour_is_read_through_the_theme(tmp_path):
    """bg1 -> (colour map) -> dk1 -> the theme's colour, with a layout's own
    override of the map and PowerPoint's Lighter/Darker picks."""
    prs = open_template(_make_template(tmp_path / "corp.pptx", logo=False))
    layout = prs.slide_layouts[6]
    master = prs.slide_master
    assert layout_background(layout) == "#FFFFFF"

    master._element.find(qn("p:clrMap")).set("bg1", "dk1")
    assert layout_background(layout) == "#000000"
    master._element.find(qn("p:clrMap")).set("bg1", "lt1")

    from lxml import etree
    a = "http://schemas.openxmlformats.org/drawingml/2006/main"
    p = "http://schemas.openxmlformats.org/presentationml/2006/main"
    override = layout._element.find(qn("p:clrMapOvr"))
    for child in list(override):
        override.remove(child)
    mapping = dict(bg1="dk1", tx1="lt1", bg2="dk2", tx2="lt2", accent1="accent1", accent2="accent2", accent3="accent3",
                   accent4="accent4", accent5="accent5", accent6="accent6", hlink="hlink", folHlink="folHlink")
    override.append(etree.fromstring(f'<a:overrideClrMapping xmlns:a="{a}" ' + " ".join(f'{k}="{v}"' for k, v in mapping.items()) + "/>"))
    assert layout_background(layout) == "#000000"
    override.remove(override[0])
    override.append(etree.fromstring(f'<a:masterClrMapping xmlns:a="{a}"/>'))

    c_sld = layout._element.find(qn("p:cSld"))
    def set_background(xml):
        for old in c_sld.findall(qn("p:bg")):
            c_sld.remove(old)
        c_sld.insert(0, etree.fromstring(f'<p:bg xmlns:p="{p}" xmlns:a="{a}">{xml}</p:bg>'))

    set_background('<p:bgPr><a:solidFill><a:schemeClr val="bg1"><a:lumMod val="50000"/></a:schemeClr></a:solidFill><a:effectLst/></p:bgPr>')
    assert layout_background(layout) == "#808080"
    set_background('<p:bgPr><a:solidFill><a:srgbClr val="123456"/></a:solidFill><a:effectLst/></p:bgPr>')
    assert layout_background(layout) == "#123456"
    # A gradient counts as its first stop, a theme's fill (solid or not: idx 1003
    # is a gradient or picture in most real themes) as its base colour.
    set_background('<p:bgPr><a:gradFill><a:gsLst><a:gs pos="0"><a:srgbClr val="101010"/></a:gs></a:gsLst></a:gradFill><a:effectLst/></p:bgPr>')
    assert layout_background(layout) == "#101010"
    set_background('<p:bgRef idx="1003"><a:srgbClr val="202020"/></p:bgRef>')
    assert layout_background(layout) == "#202020"
    # A picture of the template's own can't be judged.
    set_background('<p:bgPr><a:blipFill><a:blip/></a:blipFill><a:effectLst/></p:bgPr>')
    assert layout_background(layout) is None


def test_a_template_without_a_blank_layout_uses_the_emptiest_and_clears_it(tmp_path):
    template = tmp_path / "corp.pptx"
    prs = Presentation(_make_template(template, logo=False))
    for layout in list(prs.slide_layouts):
        if layout.name not in ("Title Only", "Title and Content"):
            prs.slide_layouts.remove(layout)
    prs.save(template)

    out = _render(_diagram(), str(template))
    assert out.slides[0].slide_layout.name == "Title Only"
    assert not list(out.slides[0].placeholders)


def test_cli_build_with_template(tmp_path):
    source = _write_diagram(tmp_path / "d.yaml")
    template = _make_template(tmp_path / "corp.pptx")
    out = tmp_path / "out.pptx"
    result = CliRunner().invoke(main, ["build", source, "-o", str(out), "--template", template, "--format", "json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["status"] == "ok"
    assert len(Presentation(out).slides) == 1


def test_cli_refuses_to_overwrite_the_template(tmp_path):
    source = _write_diagram(tmp_path / "d.yaml")
    template = Path(_make_template(tmp_path / "corp.pptx"))
    before = template.read_bytes()
    result = CliRunner().invoke(main, ["build", source, "-o", str(template), "--template", str(template)])
    assert result.exit_code == 1
    assert template.read_bytes() == before


@pytest.mark.parametrize("make, code", [
    (lambda p: p.write_text("not a zip"), "template-unreadable"),
    (lambda p: zipfile.ZipFile(p, "w").close(), "template-unreadable"),
])
def test_cli_reports_an_unreadable_template(tmp_path, make, code):
    source = _write_diagram(tmp_path / "d.yaml")
    bad = tmp_path / "bad.potx"
    make(bad)
    out = tmp_path / "out.pptx"
    result = CliRunner().invoke(main, ["build", source, "-o", str(out), "--template", str(bad), "--format", "json"])
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["errorCode"] == code
    assert not out.exists()


def test_cli_reports_malformed_xml_in_a_template(tmp_path):
    source = _write_diagram(tmp_path / "d.yaml")
    bad = tmp_path / "broken.pptx"
    with zipfile.ZipFile(_make_template(tmp_path / "corp.pptx")) as src, zipfile.ZipFile(bad, "w") as out:
        for item in src.infolist():
            out.writestr(item, b"<not-closed" if item.filename == "ppt/presentation.xml" else src.read(item))
    result = CliRunner().invoke(main, ["build", source, "-o", str(tmp_path / "o.pptx"), "--template", str(bad), "--format", "json"])
    assert json.loads(result.output)["errorCode"] == "template-unreadable"


def test_cli_reports_a_word_file_as_not_a_template(tmp_path):
    source = _write_diagram(tmp_path / "d.yaml")
    bad = tmp_path / "doc.pptx"
    with zipfile.ZipFile(_make_template(tmp_path / "corp.pptx")) as src, zipfile.ZipFile(bad, "w") as out:
        for item in src.infolist():
            data = src.read(item)
            if item.filename == "[Content_Types].xml":
                data = data.replace(b"presentationml.presentation.main+xml", b"wordprocessingml.document.main+xml")
            out.writestr(item, data)
    result = CliRunner().invoke(main, ["build", source, "-o", str(tmp_path / "o.pptx"), "--template", str(bad), "--format", "json"])
    assert json.loads(result.output)["errorCode"] == "template-unreadable"


def test_cli_refuses_a_macro_enabled_template(tmp_path):
    source = _write_diagram(tmp_path / "d.yaml")
    bad = tmp_path / "corp.potm"
    with zipfile.ZipFile(_make_template(tmp_path / "corp.pptx")) as src, zipfile.ZipFile(bad, "w") as out:
        for item in src.infolist():
            data = src.read(item)
            if item.filename == "[Content_Types].xml":
                data = data.replace(
                    b"application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml",
                    b"application/vnd.ms-powerpoint.template.macroEnabled.main+xml",
                )
            out.writestr(item, data)
    result = CliRunner().invoke(main, ["build", source, "-o", str(tmp_path / "o.pptx"), "--template", str(bad), "--format", "json"])
    payload = json.loads(result.output)
    assert payload["errorCode"] == "template-unreadable" and "macro-enabled" in payload["error"]


def test_cli_reports_a_missing_template_as_an_io_error(tmp_path):
    source = _write_diagram(tmp_path / "d.yaml")
    result = CliRunner().invoke(main, ["build", source, "-o", str(tmp_path / "o.pptx"), "--template", str(tmp_path / "none.potx"), "--format", "json"])
    assert result.exit_code == 1
    assert json.loads(result.output)["errorCode"] == "io-error"


def test_cli_size_mismatch_writes_nothing(tmp_path):
    source = _write_diagram(tmp_path / "d.yaml", {"aspectRatio": "A4"})
    template = _make_template(tmp_path / "corp.pptx")
    out = tmp_path / "o.pptx"
    result = CliRunner().invoke(main, ["build", source, "-o", str(out), "--template", template, "--format", "json"])
    assert result.exit_code == 1
    assert json.loads(result.output)["errorCode"] == "template-size-mismatch"
    assert not out.exists()
