import re

import pytest

from zook.errors import DiagramError
from zook.validate import validate


def _base(**overrides):
    doc = {
        "version": "1.0",
        "canvas": {"aspectRatio": "16:9"},
        "elements": [{"kind": "node", "id": "a", "type": "EC2"}],
    }
    doc.update(overrides)
    return doc


def test_valid_document_passes():
    validate(_base())


def test_missing_required_field_is_fatal():
    doc = _base()
    del doc["canvas"]
    with pytest.raises(DiagramError):
        validate(doc)


def test_x_without_y_is_fatal():
    doc = _base(elements=[{"kind": "node", "id": "a", "type": "EC2", "x": 10}])
    with pytest.raises(DiagramError):
        validate(doc)


def test_x_without_y_error_names_the_specific_dependency():
    # A bare "is not valid under any of the given schemas" (jsonschema's
    # generic oneOf message) gives no actionable hint for self-correction.
    # validate_schema() should surface the specific sub-error instead.
    doc = _base(elements=[{"kind": "node", "id": "a", "type": "EC2", "x": 10}])
    with pytest.raises(DiagramError, match="dependency"):
        validate(doc)


def test_unknown_top_level_field_is_fatal():
    doc = _base(bogus="nope")
    with pytest.raises(DiagramError):
        validate(doc)


def test_duplicate_id_is_fatal():
    doc = _base(
        elements=[
            {"kind": "node", "id": "a", "type": "EC2"},
            {"kind": "node", "id": "a", "type": "S3"},
        ]
    )
    with pytest.raises(DiagramError, match="Duplicate"):
        validate(doc)


def test_duplicate_id_across_nesting_is_fatal():
    doc = _base(
        elements=[
            {
                "kind": "container",
                "id": "a",
                "type": "vpc",
                "children": [{"kind": "node", "id": "a", "type": "EC2"}],
            }
        ]
    )
    with pytest.raises(DiagramError, match="Duplicate"):
        validate(doc)


def test_dangling_link_reference_is_fatal():
    doc = _base(links=[{"from": "a", "to": "missing"}])
    with pytest.raises(DiagramError, match="unknown element id"):
        validate(doc)


def test_valid_link_passes():
    doc = _base(
        elements=[
            {"kind": "node", "id": "a", "type": "EC2"},
            {"kind": "node", "id": "b", "type": "S3"},
        ],
        links=[{"from": "a", "to": "b"}],
    )
    validate(doc)


def test_node_label_gap_style_passes():
    doc = _base(
        elements=[{"kind": "node", "id": "a", "type": "EC2", "style": {"labelGap": 12}}],
    )
    validate(doc)


def test_negative_label_gap_is_fatal():
    doc = _base(
        elements=[{"kind": "node", "id": "a", "type": "EC2", "style": {"labelGap": -5}}],
    )
    with pytest.raises(DiagramError):
        validate(doc)


def test_link_side_same_axis_passes():
    doc = _base(
        elements=[
            {"kind": "node", "id": "a", "type": "EC2"},
            {"kind": "node", "id": "b", "type": "S3"},
        ],
        links=[{"from": "a", "to": "b", "fromSide": "right", "toSide": "left"}],
    )
    validate(doc)


def test_link_single_side_passes():
    doc = _base(
        elements=[
            {"kind": "node", "id": "a", "type": "EC2"},
            {"kind": "node", "id": "b", "type": "S3"},
        ],
        links=[{"from": "a", "to": "b", "fromSide": "bottom"}],
    )
    validate(doc)


def test_link_mismatched_axis_sides_is_fatal():
    doc = _base(
        elements=[
            {"kind": "node", "id": "a", "type": "EC2"},
            {"kind": "node", "id": "b", "type": "S3"},
        ],
        links=[{"from": "a", "to": "b", "fromSide": "bottom", "toSide": "left"}],
    )
    with pytest.raises(DiagramError, match="same axis"):
        validate(doc)


def test_canvas_overlap_margin_passes():
    doc = _base(canvas={"aspectRatio": "16:9", "overlapMargin": 20})
    validate(doc)


def test_negative_overlap_margin_is_fatal():
    doc = _base(canvas={"aspectRatio": "16:9", "overlapMargin": -1})
    with pytest.raises(DiagramError):
        validate(doc)


def _nested(child):
    return _base(
        elements=[
            {
                "kind": "container",
                "id": "vpc",
                "type": "vpc",
                "children": [{"kind": "container", "id": "sub", "type": "subnet", "children": [child]}],
            }
        ]
    )


def _schema_error(doc) -> str:
    with pytest.raises(DiagramError) as exc_info:
        validate(doc)
    return str(exc_info.value)


def test_nested_mistake_is_reported_at_its_own_path():
    # With `element` as oneOf[container, node], this was reported against the
    # whole top-level container as "('children', 'layout' were unexpected)" -
    # the *node* branch's complaint - pointing a self-correcting AI at the
    # wrong fix (deleting children).
    message = _schema_error(_nested({"kind": "node", "id": "a", "type": "EC2", "colour": "red"}))
    assert "$['elements'][0]['children'][0]['children'][0]: Additional properties are not allowed ('colour' was unexpected)" in message
    assert "children' was unexpected" not in message
    assert "children', 'layout' were unexpected" not in message


def test_node_enum_mistake_names_the_node_field_not_the_container_branch():
    message = _schema_error(_base(elements=[{"kind": "node", "id": "a", "type": "EC2", "style": {"labelPosition": "bottom"}}]))
    assert "$['elements'][0]['style']['labelPosition']: 'bottom' is not one of" in message
    assert "'container' was expected" not in message


def test_container_mistake_names_the_container_field():
    message = _schema_error(_base(elements=[{"kind": "container", "id": "g", "type": "group", "style": {"dashed": True}}]))
    assert "$['elements'][0]['style']: Additional properties are not allowed ('dashed' was unexpected)" in message


def test_unknown_kind_is_reported_once_on_kind():
    message = _schema_error(_base(elements=[{"kind": "nodee", "id": "a", "type": "EC2"}]))
    assert "$['elements'][0]['kind']: 'nodee' is not one of ['container', 'node']" in message
    assert message.count("\n") == 1  # one violation line, not the other branches' noise


def test_missing_kind_is_reported_on_the_element():
    message = _schema_error(_base(elements=[{"id": "a", "type": "EC2"}]))
    assert "$['elements'][0]: 'kind' is a required property" in message


def test_nested_x_without_y_still_names_the_dependency():
    message = _schema_error(_nested({"kind": "node", "id": "a", "type": "EC2", "x": 10}))
    assert "$['elements'][0]['children'][0]['children'][0]: 'y' is a dependency of 'x'" in message


def test_huge_instance_is_not_dumped_into_the_message():
    children = [{"kind": "node", "id": f"n{i}", "type": "EC2", "label": "x" * 40} for i in range(20)]
    message = _schema_error(_base(elements=[{"kind": "container", "id": "g", "type": "group", "children": "oops"},
                                             {"kind": "container", "id": "h", "type": "group", "children": children, "x": 1}]))
    assert len(message) < 600


@pytest.mark.parametrize(
    "overrides,expected",
    [
        ({"canvas": {"aspectRatio": 969}}, "969 is not one of"),
        ({"version": 1.0}, "1.0 is not of type 'string'"),
        ({"elements": [{"kind": "node", "id": "a", "type": "EC2", "label": False}]}, "False is not of type 'string'"),
    ],
)
def test_yaml_11_misreads_get_a_quoting_hint(overrides, expected):
    message = _schema_error(_base(**overrides))
    assert expected in message
    assert "wrap it in quotes" in message


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_numbers_are_fatal(value):
    doc = _base(elements=[{"kind": "node", "id": "a", "type": "EC2", "x": value, "y": 0}])
    with pytest.raises(DiagramError, match=r"NaN/Infinity and huge values are not valid\): \$\['elements'\]\[0\]\['x'\]"):
        validate(doc)


@pytest.mark.parametrize("item", ["web", None, ["kind", "node"]])
def test_non_object_element_is_reported_once(item):
    message = _schema_error(_base(elements=[item]))
    assert message.count("\n") == 1
    assert "$['elements'][0]:" in message and "is not of type 'object'" in message


def test_huge_integer_does_not_crash_the_error_report():
    # repr() of an int past Python's 4300-digit limit raises ValueError.
    message = _schema_error(_base(canvas={"aspectRatio": "16:9", "padding": int("F" * 4000, 16), "bogus": 1}))
    assert "'bogus' was unexpected" in message


@pytest.mark.parametrize(
    "links, message",
    [
        ([{"id": "l", "from": "a", "to": "b"}, {"id": "l", "from": "b", "to": "a"}], "duplicate link id(s): l"),
        ([{"id": "a", "from": "a", "to": "b"}], "link id(s) also used by an element: a"),
    ],
)
def test_link_ids_share_the_element_id_namespace(links, message):
    doc = {
        "version": "1.0",
        "canvas": {"aspectRatio": "16:9"},
        "elements": [{"kind": "node", "id": "a", "type": "EC2"}, {"kind": "node", "id": "b", "type": "EC2"}],
        "links": links,
    }
    with pytest.raises(DiagramError, match=re.escape(message)):
        validate(doc)
