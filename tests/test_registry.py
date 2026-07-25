from archdiagram.registry import load_registry


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
