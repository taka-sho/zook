import pytest

from archdiagram.errors import DiagramError
from archdiagram.validate import validate


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
