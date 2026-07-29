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
