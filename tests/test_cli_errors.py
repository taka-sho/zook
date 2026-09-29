"""The CLI's error contract: whatever goes wrong with an input, a command
reports it the same way it reports a Fatal - one `{"status": "error", ...}`
object on stdout under `--format json`, one `::error::` line under github -
and exits non-zero, never with a Python traceback and an empty stdout.

AGENTS.md's self-correction loop depends on this: an AI runs
`zook validate --format json`, reads `error`, fixes the file, and repeats.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

from zook.cli import main

FIXTURE = Path(__file__).parent / "fixtures" / "example.yaml"

_SYNTAX_ERROR = 'version: "1.0"\ncanvas:\n  aspectRatio: "16:9"\nelements:\n  - kind: node\n    id: a\n     type: EC2\n'

_DUPLICATE_LINKS = """\
version: "1.0"
canvas: {aspectRatio: "16:9"}
elements:
  - {kind: node, id: a, type: EC2}
  - {kind: node, id: b, type: EC2}
links:
  - {from: a, to: b}
links:
  - {from: b, to: a}
"""


def _write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def _json_error(result) -> str:
    payload = json.loads(result.stdout)
    assert payload["status"] == "error"
    return payload["error"]


def _commands(path, tmp_path):
    return {
        "validate": ["validate", path],
        "build": ["build", path, "-o", str(tmp_path / "out.pptx")],
        "doctor": ["doctor", path],
        "preview": ["preview", path, "-o", str(tmp_path / "out.png")],
        "export-drawio": ["export-drawio", path, "-o", str(tmp_path / "out.drawio")],
        "diff": ["diff", str(FIXTURE), path],
    }


@pytest.mark.parametrize("command", ["validate", "build", "doctor", "preview", "export-drawio", "diff"])
def test_yaml_syntax_error_is_a_json_error_with_line_and_column(tmp_path, command):
    path = _write(tmp_path, "bad.yaml", _SYNTAX_ERROR)
    result = CliRunner().invoke(main, [*_commands(path, tmp_path)[command], "--format", "json"])

    assert result.exit_code == (2 if command == "diff" else 1)
    error = _json_error(result)
    assert "line 7, column 10" in error
    assert "bad.yaml" in error


@pytest.mark.parametrize("command", ["validate", "build", "doctor", "diff"])
def test_duplicate_key_is_rejected_the_same_way_by_every_command(tmp_path, command):
    # PyYAML keeps the last `links:` silently (a connector vanished from the
    # built slide); doctor's ruamel loader crashed on the same file.
    path = _write(tmp_path, "dup.yaml", _DUPLICATE_LINKS)
    result = CliRunner().invoke(main, [*_commands(path, tmp_path)[command], "--format", "json"])

    assert result.exit_code != 0
    assert "found duplicate key 'links' (first defined at line 6)" in _json_error(result)


def test_merge_key_override_is_not_a_duplicate(tmp_path):
    path = _write(
        tmp_path,
        "merge.yaml",
        'version: "1.0"\ncanvas: {aspectRatio: "16:9"}\nelements:\n'
        "  - &base {kind: node, id: a, type: EC2}\n"
        "  - {<<: *base, id: b}\n",
    )
    result = CliRunner().invoke(main, ["validate", path, "--format", "json"])
    assert json.loads(result.stdout)["status"] == "ok"


def test_unquoted_aspect_ratio_gets_a_quoting_hint_in_validate_and_doctor(tmp_path):
    # YAML 1.1 reads `16:9` as the base-60 int 969. doctor used to read the
    # file as YAML 1.2 (a string) and report "ok" on a file validate rejects.
    path = _write(tmp_path, "sexa.yaml", 'version: "1.0"\ncanvas: {aspectRatio: 16:9}\nelements: []\n')
    for command in (["validate", path], ["doctor", path]):
        result = CliRunner().invoke(main, [*command, "--format", "json"])
        assert result.exit_code == 1
        error = _json_error(result)
        assert "969 is not one of" in error
        assert "wrap it in quotes" in error


def test_non_utf8_input_is_a_json_error(tmp_path):
    path = tmp_path / "sjis.yaml"
    path.write_bytes('version: "1.0"\n# 日本語\n'.encode("cp932"))
    result = CliRunner().invoke(main, ["validate", str(path), "--format", "json"])

    assert result.exit_code == 1
    assert "not valid UTF-8" in _json_error(result)


def test_utf8_bom_is_accepted(tmp_path):
    path = tmp_path / "bom.yaml"
    path.write_bytes(b"\xef\xbb\xbf" + FIXTURE.read_bytes())
    result = CliRunner().invoke(main, ["validate", str(path), "--format", "json"])
    assert json.loads(result.stdout)["status"] == "ok"


def test_missing_output_directory_is_a_json_error(tmp_path):
    result = CliRunner().invoke(
        main, ["build", str(FIXTURE), "-o", str(tmp_path / "nodir" / "out.pptx"), "--format", "json"]
    )
    assert result.exit_code == 1
    assert "nodir" in _json_error(result)


@pytest.mark.parametrize("command", ["build", "export-drawio", "preview"])
def test_output_path_equal_to_input_is_refused(tmp_path, command):
    path = _write(tmp_path, "d.png" if command == "preview" else "d.yaml", FIXTURE.read_text(encoding="utf-8"))
    original = Path(path).read_bytes()
    result = CliRunner().invoke(main, [command, path, "-o", path, "--format", "json"])

    assert result.exit_code == 1
    assert Path(path).read_bytes() == original  # the source survived


def test_from_mermaid_refuses_to_overwrite_its_input(tmp_path):
    path = _write(tmp_path, "d.mmd", "flowchart TD\n  A --> B\n")
    result = CliRunner().invoke(main, ["from-mermaid", path, "-o", path, "--format", "json"])
    assert result.exit_code == 1
    assert Path(path).read_text(encoding="utf-8") == "flowchart TD\n  A --> B\n"


def test_preview_rejects_a_non_png_output(tmp_path):
    result = CliRunner().invoke(main, ["preview", str(FIXTURE), "-o", str(tmp_path / "x.svg"), "--format", "json"])
    assert result.exit_code == 1
    assert "PNG" in _json_error(result)


def test_preview_reports_in_the_requested_format(tmp_path):
    out = tmp_path / "x.png"
    result = CliRunner().invoke(main, ["preview", str(FIXTURE), "-o", str(out), "--format", "json"])
    assert result.exit_code == 0
    assert json.loads(result.stdout) == {"status": "ok", "warnings": [], "details": [], "output": str(out)}
    assert out.read_bytes().startswith(b"\x89PNG")


def test_nan_coordinate_is_fatal_not_a_crash(tmp_path):
    path = _write(
        tmp_path, "nan.yaml", 'version: "1.0"\ncanvas: {aspectRatio: "16:9"}\nelements:\n'
        "  - {kind: node, id: a, type: EC2, x: .nan, y: 0}\n"
    )
    result = CliRunner().invoke(main, ["build", path, "-o", str(tmp_path / "o.pptx"), "--format", "json"])
    assert result.exit_code == 1
    assert "NaN/Infinity" in _json_error(result)


def test_github_format_keeps_a_multiline_error_on_one_annotation(tmp_path):
    path = _write(
        tmp_path, "two.yaml", 'version: "1.0"\ncanvas: {aspectRatio: "16:9"}\nelements:\n'
        "  - {kind: node, id: a, type: EC2, colour: red}\n  - {kind: node, id: b, type: EC2, size: -1}\n"
    )
    result = CliRunner().invoke(main, ["validate", path, "--format", "github"])

    lines = result.stdout.splitlines()
    assert len(lines) == 1
    assert lines[0].startswith("::error::Schema validation failed:%0A")
    assert "colour" in lines[0] and "size" in lines[0]


def test_unexpected_exception_still_honours_the_json_contract(tmp_path, monkeypatch):
    import zook.cli

    def boom(*_args, **_kwargs):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(zook.cli, "render", boom)
    result = CliRunner().invoke(main, ["build", str(FIXTURE), "-o", str(tmp_path / "o.pptx"), "--format", "json"])

    assert result.exit_code == 1
    error = _json_error(result)
    assert error.startswith("internal error: RuntimeError: kaboom")


def test_sync_with_malformed_drawio_is_a_json_error(tmp_path):
    yaml_path = _write(tmp_path, "d.yaml", FIXTURE.read_text(encoding="utf-8"))
    drawio_path = _write(tmp_path, "d.drawio", "<mxfile><diagram>")
    result = CliRunner().invoke(main, ["sync", yaml_path, drawio_path, "--format", "json"])

    assert result.exit_code == 1
    assert "not a valid .drawio XML file" in _json_error(result)
    assert Path(yaml_path).read_text(encoding="utf-8") == FIXTURE.read_text(encoding="utf-8")


def test_version_option():
    from zook import __version__

    result = CliRunner().invoke(main, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_every_text_read_is_locale_independent(tmp_path):
    # With a non-UTF-8 locale (Japanese Windows is cp932) an `open()`/
    # `read_text()` without an explicit encoding can't decode the bundled
    # registries. EncodingWarning (PEP 597) flags exactly those calls on any
    # OS, so turning it into an error for zook's own modules catches a
    # regression without needing a cp932 machine.
    env = {**os.environ, "PYTHONWARNDEFAULTENCODING": "1"}
    code = (
        "import warnings, sys\n"
        "warnings.filterwarnings('error', category=EncodingWarning, module=r'zook(\\.|$)')\n"
        "from zook.cli import main\n"
        "sys.argv = ['zook', 'validate', sys.argv[1], '--format', 'json']\n"
        "main()\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code, str(FIXTURE)], capture_output=True, encoding="utf-8", env=env, check=False
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "ok"


@pytest.mark.parametrize("command", ["validate", "build", "doctor", "preview", "export-drawio", "diff"])
def test_missing_input_file_is_a_json_error(tmp_path, command):
    # click's own `exists=True` check answered with a plain-text usage error
    # (exit 2) before --format json could apply.
    missing = str(tmp_path / "nope.yaml")
    result = CliRunner().invoke(main, [*_commands(missing, tmp_path)[command], "--format", "json"])

    assert result.exit_code == (2 if command == "diff" else 1)
    assert "nope.yaml" in _json_error(result)


def test_directory_as_input_is_a_json_error(tmp_path):
    result = CliRunner().invoke(main, ["validate", str(tmp_path), "--format", "json"])
    assert result.exit_code == 1
    assert str(tmp_path) in _json_error(result)


def test_missing_registry_file_is_a_json_error(tmp_path):
    result = CliRunner().invoke(
        main, ["validate", str(FIXTURE), "--registry", str(tmp_path / "reg.yaml"), "--format", "json"]
    )
    assert result.exit_code == 1
    assert "reg.yaml" in _json_error(result)


@pytest.mark.skipif(os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0), reason="chmod 000 isn't enforced")
def test_unreadable_input_is_a_json_error(tmp_path):
    path = Path(_write(tmp_path, "noperm.yaml", FIXTURE.read_text(encoding="utf-8")))
    path.chmod(0)
    try:
        result = CliRunner().invoke(main, ["validate", str(path), "--format", "json"])
    finally:
        path.chmod(0o644)
    assert result.exit_code == 1
    assert "Permission denied" in _json_error(result)


def test_directory_as_output_is_a_json_error(tmp_path):
    outdir = tmp_path / "out.pptx"
    outdir.mkdir()
    result = CliRunner().invoke(main, ["build", str(FIXTURE), "-o", str(outdir), "--format", "json"])
    assert result.exit_code == 1
    assert "out.pptx" in _json_error(result)


def test_case_variant_or_hard_link_of_the_input_is_refused(tmp_path):
    src = Path(_write(tmp_path, "victim.yaml", FIXTURE.read_text(encoding="utf-8")))
    link = tmp_path / "hard.yaml"
    os.link(src, link)
    result = CliRunner().invoke(main, ["build", str(src), "-o", str(link), "--format", "json"])
    assert result.exit_code == 1
    assert src.read_text(encoding="utf-8") == FIXTURE.read_text(encoding="utf-8")

    upper = tmp_path / "VICTIM.yaml"
    if upper.exists():  # case-insensitive filesystem (macOS/Windows default)
        result = CliRunner().invoke(main, ["build", str(src), "-o", str(upper), "--format", "json"])
        assert result.exit_code == 1
        assert src.read_text(encoding="utf-8") == FIXTURE.read_text(encoding="utf-8")


def test_sync_refuses_to_write_over_its_drawio_input(tmp_path):
    yaml_path = _write(tmp_path, "d.yaml", FIXTURE.read_text(encoding="utf-8"))
    drawio_path = str(tmp_path / "d.drawio")
    assert CliRunner().invoke(main, ["export-drawio", yaml_path, "-o", drawio_path]).exit_code == 0
    original = Path(drawio_path).read_text(encoding="utf-8")

    result = CliRunner().invoke(main, ["sync", yaml_path, drawio_path, "-o", drawio_path, "--format", "json"])
    assert result.exit_code == 1
    assert Path(drawio_path).read_text(encoding="utf-8") == original


def test_non_utf8_console_cannot_crash_a_report(tmp_path):
    # A cp1252 console (Windows CI runners) can't encode a Japanese id; the
    # report must escape it, not die with UnicodeEncodeError.
    path = _write(tmp_path, "ja.yaml", 'version: "1.0"\ncanvas: {aspectRatio: "16:9"}\nelements:\n  - {kind: node, id: "ウェブ", type: EC2}\n')
    env = {**os.environ, "PYTHONIOENCODING": "cp1252"}
    result = subprocess.run(
        [sys.executable, "-m", "zook", "validate", path, "--format", "github"],
        capture_output=True, text=True, encoding="cp1252", env=env, check=False,
    )
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert result.stdout.startswith("::error::Schema validation failed")


def test_diff_prefixes_every_error_with_the_failing_side(tmp_path):
    bad = _write(tmp_path, "bad.yaml", _SYNTAX_ERROR)
    result = CliRunner().invoke(main, ["diff", str(FIXTURE), bad, "--format", "json"])
    assert result.exit_code == 2
    assert _json_error(result).startswith(f"new diagram {bad}: YAML error")


@pytest.mark.parametrize(
    "registry,expected",
    [
        ("- a\n- b\n", "$: ['a', 'b'] is not of type 'object'"),
        ('registryVersion: "1.0"\nprovider: aws\nicons:\n  Foo: {aliases: [foo]}\n', "$['icons']['Foo']: 'file' is a required property"),
        ("", "None is not of type 'object'"),
    ],
)
def test_malformed_user_registry_is_a_fatal_naming_the_field(tmp_path, registry, expected):
    reg = _write(tmp_path, "reg.yaml", registry)
    for command in (["validate", str(FIXTURE)], ["icons", "list"]):
        result = CliRunner().invoke(main, [*command, "--registry", reg, "--format", "json"])
        assert result.exit_code == 1
        error = _json_error(result)
        assert error.startswith(f"invalid icon registry {reg}:")
        assert expected in error


def test_huge_number_is_fatal_not_infinity_in_json(tmp_path):
    path = _write(
        tmp_path, "big.yaml", 'version: "1.0"\ncanvas: {aspectRatio: "16:9"}\nelements:\n'
        "  - {kind: container, id: c, type: group, x: 1.7e+308, y: 1.7e+308, width: 1.7e+308, height: 1.7e+308,\n"
        "     children: [{kind: node, id: a, type: EC2}, {kind: node, id: b, type: EC2}]}\n"
    )
    result = CliRunner().invoke(main, ["doctor", path, "--format", "json"])
    assert result.exit_code == 1
    assert "within ±1,000,000" in _json_error(result)


def test_swapped_sync_arguments_say_what_went_wrong(tmp_path):
    diagram = tmp_path / "d.yaml"
    example = Path(__file__).resolve().parent.parent / "docs" / "example.yaml"
    diagram.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
    drawio = tmp_path / "d.drawio"
    assert CliRunner().invoke(main, ["export-drawio", str(diagram), "-o", str(drawio)]).exit_code == 0
    result = CliRunner().invoke(main, ["sync", str(drawio), str(diagram), "--format", "json"])
    assert result.exit_code == 1
    error = json.loads(result.stdout)["error"]
    assert "looks like XML" in error and "zook sync DIAGRAM.yaml DIAGRAM.drawio" in error


def _write_diagram(tmp_path, text):
    path = tmp_path / "d.yaml"
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_warnings_carry_a_code_and_the_ids_they_concern(tmp_path):
    path = _write_diagram(tmp_path, """version: "1.0"
canvas: {aspectRatio: "16:9"}
elements:
  - {kind: node, id: a, type: Lamda, x: 100, y: 100}
  - {kind: node, id: b, type: EC2, x: 120, y: 110}
""")
    result = CliRunner().invoke(main, ["validate", path, "--format", "json"])
    payload = json.loads(result.stdout)
    assert payload["warnings"] == [d["message"] for d in payload["details"]]
    by_code = {d["code"]: d for d in payload["details"]}
    assert by_code["unknown-type"]["elements"] == ["a"]
    assert sorted(by_code["element-overlap"]["elements"]) == ["a", "b"]


def test_link_warnings_name_the_link(tmp_path):
    path = _write_diagram(tmp_path, """version: "1.0"
canvas: {aspectRatio: "16:9"}
elements:
  - {kind: node, id: a, type: EC2, x: 100, y: 100}
  - {kind: node, id: wall, type: EC2, x: 300, y: 100}
  - {kind: node, id: b, type: EC2, x: 500, y: 100}
links:
  - {id: ab, from: a, to: b}
""")
    payload = json.loads(CliRunner().invoke(main, ["validate", path, "--format", "json"]).stdout)
    (detail,) = [d for d in payload["details"] if d["code"] == "link-crosses-element"]
    assert detail["elements"] == ["wall"] and detail["links"] == [{"from": "a", "to": "b", "id": "ab"}]


def test_schema_errors_are_structured(tmp_path):
    path = _write_diagram(tmp_path, """version: "1.0"
canvas: {aspectRatio: "16:9"}
elements:
  - {kind: node, id: a, type: EC2, style: {labelPosition: bottom}}
""")
    payload = json.loads(CliRunner().invoke(main, ["validate", path, "--format", "json"]).stdout)
    assert payload["errorCode"] == "schema"
    (violation,) = payload["errorDetails"]
    assert violation["pointer"] == ["elements", 0, "style", "labelPosition"]


def test_an_unknown_link_endpoint_suggests_the_id_meant(tmp_path):
    path = _write_diagram(tmp_path, """version: "1.0"
canvas: {aspectRatio: "16:9"}
elements:
  - {kind: node, id: database, type: RDS}
  - {kind: node, id: web, type: EC2}
links:
  - {from: web, to: databse}
""")
    payload = json.loads(CliRunner().invoke(main, ["validate", path, "--format", "json"]).stdout)
    assert payload["errorCode"] == "unknown-link-endpoint"
    assert "did you mean 'database'?" in payload["error"]
    assert payload["errorDetails"] == [{"path": "$['links'][0]['to']", "id": "databse", "didYouMean": ["database"]}]


def test_a_yaml_syntax_error_gives_line_and_column(tmp_path):
    path = _write_diagram(tmp_path, 'version: "1.0"\ncanvas: {aspectRatio: "16:9"\nelements: []\n')
    payload = json.loads(CliRunner().invoke(main, ["validate", path, "--format", "json"]).stdout)
    assert payload["errorCode"] == "yaml-syntax"
    assert set(payload["errorDetails"][0]) == {"file", "line", "column"}


def test_one_warning_for_a_whole_container_off_the_slide(tmp_path):
    path = _write_diagram(tmp_path, """version: "1.0"
canvas: {aspectRatio: "16:9", fit: none}
elements:
  - kind: container
    id: g
    type: group
    x: 100
    y: 1000
    children:
      - {kind: node, id: a, type: EC2}
      - {kind: node, id: b, type: EC2}
""")
    payload = json.loads(CliRunner().invoke(main, ["validate", path, "--format", "json"]).stdout)
    assert [d["elements"] for d in payload["details"] if d["code"] == "off-canvas"] == [["g"]]
