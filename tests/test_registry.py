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
