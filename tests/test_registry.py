from pathlib import Path

from zook.registry import load_registries, load_registry


def test_builtin_aws_resolves_primary_key():
    registry = load_registry("aws")
    entry = registry.resolve_icon("EC2")
    assert entry is not None
    assert entry.file.name == "EC2.png"


def test_alias_resolution_is_case_insensitive():
    registry = load_registry("aws")
    assert registry.resolve_icon("alb") is not None
    assert registry.resolve_icon("ALB") is not None
    assert registry.resolve_icon("ddb").file.name == "DynamoDB.png"
    assert registry.resolve_icon("AmazonEC2").file.name == "EC2.png"


def test_unknown_type_resolves_to_none():
    registry = load_registry("aws")
    assert registry.resolve_icon("NotAThing") is None


def test_group_style_resolution():
    registry = load_registry("aws")
    vpc = registry.resolve_group("vpc")
    assert vpc is not None
    assert vpc.label == "VPC"
    assert registry.resolve_group("nonexistent-container-type") is None


def test_actor_icons_resolve():
    registry = load_registry("aws")
    for type_, alias in [("User", "enduser"), ("Admin", "administrator"), ("Developer", "dev"), ("Client", "browser")]:
        assert registry.resolve_icon(type_) is not None
        assert registry.resolve_icon(type_).file.exists()
        assert registry.resolve_icon(alias) is registry.resolve_icon(type_)


def test_cloud_group_resolves_with_corner_icon():
    registry = load_registry("aws")
    cloud = registry.resolve_group("cloud")
    assert cloud is not None
    assert cloud.label == "AWS Cloud"
    assert cloud.icon is not None
    assert cloud.icon.exists()


def test_user_registry_overrides_builtin(tmp_path):
    override_file = tmp_path / "custom_icon.png"
    override_file.write_bytes(b"fake-png-bytes")
    user_registry = tmp_path / "user.yaml"
    user_registry.write_text(
        f"""
registryVersion: "1.0"
provider: aws
icons:
  EC2: {{ file: "{override_file.name}", category: Custom }}
"""
    )
    registry = load_registry("aws", user_registry_path=str(user_registry))
    entry = registry.resolve_icon("EC2")
    assert entry.file == override_file
    # Untouched builtin entries remain available.
    assert registry.resolve_icon("S3") is not None


# --- multi-cloud (MultiRegistry) --------------------------------------------


def test_gcp_and_azure_builtin_registries_resolve():
    multi = load_registries()
    gce = multi.resolve_icon("ComputeEngine", "gcp")
    assert gce is not None and gce.file.exists()
    vm = multi.resolve_icon("VirtualMachine", "azure")
    assert vm is not None and vm.file.exists()


def test_multi_registry_dispatches_by_element_provider():
    multi = load_registries()
    assert multi.resolve_icon("EC2", "aws") is not None
    assert multi.resolve_icon("EC2", "gcp") is None  # aws-only type, not defined for gcp
    assert multi.resolve_icon("ComputeEngine", "aws") is None  # gcp-only type, not defined for aws


def test_multi_registry_group_falls_back_to_aws_for_generic_concepts():
    multi = load_registries()
    # gcp.yaml doesn't define "az" itself; a generic concept should still
    # resolve via the aws registry's groups rather than coming back empty.
    az = multi.resolve_group("az", "gcp")
    assert az is not None


def test_multi_registry_group_prefers_providers_own_definition():
    multi = load_registries()
    gcp_cloud = multi.resolve_group("cloud", "gcp")
    aws_cloud = multi.resolve_group("cloud", "aws")
    assert gcp_cloud.label == "Google Cloud"
    assert aws_cloud.label == "AWS Cloud"
    assert gcp_cloud is not aws_cloud


def test_user_registry_declaring_custom_provider_is_isolated():
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        icon_file = tmp_path / "internal.png"
        icon_file.write_bytes(b"fake-png-bytes")
        user_registry = tmp_path / "custom.yaml"
        user_registry.write_text(
            f"""
registryVersion: "1.0"
provider: custom
icons:
  InternalService: {{ file: "{icon_file.name}", category: Custom }}
"""
        )
        multi = load_registries(user_registry_path=str(user_registry))
        assert multi.resolve_icon("InternalService", "custom") is not None
        # A node that forgets to set provider: custom doesn't accidentally pick it up.
        assert multi.resolve_icon("InternalService", "aws") is None


def _write_registry(tmp_path, name, body):
    import shutil

    shutil.copy(Path(__file__).parent.parent / "src/zook/data/icons/aws/Compute/EC2.png", tmp_path / "x.png")
    path = tmp_path / name
    path.write_text('registryVersion: "1.0"\n' + body, encoding="utf-8")
    return str(path)


def test_overriding_a_type_merges_and_keeps_its_aliases(tmp_path):
    reg = _write_registry(tmp_path, "r.yaml", 'provider: aws\nicons:\n  ELB: { file: "x.png" }\ngroups:\n  vpc: { borderColor: "#FF0000" }\n')
    multi = load_registries(user_registry_path=reg)
    elb, alb = multi.resolve_icon("ELB", "aws"), multi.resolve_icon("ALB", "aws")
    assert elb is alb and elb.file.name == "x.png"
    assert elb.category == "Networking"  # kept from the built-in entry
    assert elb.drawio_shape is None  # a new image: draw.io embeds it instead of the old official shape
    vpc = multi.resolve_group("vpc", "aws")
    assert vpc.border_color == "#FF0000" and vpc.label == "VPC" and vpc.drawio_shape


def test_a_user_alias_cannot_take_over_a_builtin_type(tmp_path):
    reg = _write_registry(tmp_path, "r.yaml", 'icons:\n  Mine: { file: "x.png", aliases: [S3, mymine] }\n')
    multi = load_registries(user_registry_path=reg)
    assert multi.resolve_icon("S3", "aws").name == "S3"
    assert multi.resolve_icon("mymine", "aws").name == "Mine"
    (warning,) = multi.warnings
    assert "alias 'S3'" in warning and "ignored" in warning


def test_several_registries_layer_in_order(tmp_path):
    aws = _write_registry(tmp_path, "a.yaml", 'icons:\n  Foo: { file: "x.png", category: A }\n')
    later = _write_registry(tmp_path, "b.yaml", 'icons:\n  Foo: { file: "x.png", category: B }\n')
    gcp = _write_registry(tmp_path, "g.yaml", 'provider: gcp\nicons:\n  Bar: { file: "x.png" }\n')
    multi = load_registries(user_registry_path=[aws, gcp, later])
    assert multi.resolve_icon("Foo", "aws").category == "B"
    assert multi.resolve_icon("Bar", "gcp") is not None


def test_a_registry_provider_must_be_one_a_diagram_can_name(tmp_path):
    import pytest

    from zook.errors import DiagramError

    reg = _write_registry(tmp_path, "r.yaml", 'provider: mycorp\nicons:\n  Foo: { file: "x.png" }\n')
    with pytest.raises(DiagramError, match="custom"):
        load_registries(user_registry_path=reg)
