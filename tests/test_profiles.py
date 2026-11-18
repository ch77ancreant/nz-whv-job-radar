from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
import yaml

from nz_job_radar.profiles import ProfileError, load_profiles


def valid_profile() -> dict:
    return {
        "id": "test-cafe",
        "name": "Test Cafe",
        "enabled": True,
        "country": "NZ",
        "locations": ["Auckland"],
        "keywords": ["front of house"],
        "exclude_title": ["barista"],
        "employers": [],
        "max_results": 2,
        "max_pages": 1,
        "notification_labels": ["needs_confirmation"],
    }


def write_profile(directory: Path, data: dict, name: str = "profile.yaml") -> None:
    (directory / name).write_text(yaml.safe_dump(data), encoding="utf-8")


def test_bundled_profiles_load() -> None:
    profiles = load_profiles(Path(__file__).resolve().parents[1] / "profiles")
    assert set(profiles) == {"auckland-cafe-service", "nz-ski-fields"}
    assert profiles["nz-ski-fields"].employers
    assert profiles["auckland-cafe-service"].country == "NZ"


def test_profile_is_immutable(tmp_path: Path) -> None:
    write_profile(tmp_path, valid_profile())
    profile = load_profiles(tmp_path)["test-cafe"]
    assert isinstance(profile.keywords, tuple)
    with pytest.raises(FrozenInstanceError):
        profile.enabled = False


@pytest.mark.parametrize(
    "field,value",
    [
        ("enabled", "true"),
        ("enabled", 1),
        ("id", "UpperCase"),
        ("id", ""),
        ("name", " "),
        ("name", 42),
        ("country", "AU"),
        ("country", "nz"),
        ("locations", []),
        ("locations", "Auckland"),
        ("locations", [True]),
        ("keywords", []),
        ("keywords", [" "]),
        ("keywords", ["foo\nbar"]),
        ("keywords", ["FOO", "foo"]),
        ("exclude_title", None),
        ("employers", {}),
        ("max_results", True),
        ("max_results", 0),
        ("max_results", 5001),
        ("max_results", 1.0),
        ("max_pages", 0),
        ("max_pages", 101),
        ("notification_labels", ["matched"]),
        ("notification_labels", "needs_confirmation"),
    ],
)
def test_rejects_invalid_fields(tmp_path: Path, field: str, value: object) -> None:
    data = valid_profile()
    data[field] = value
    write_profile(tmp_path, data)
    with pytest.raises(ProfileError):
        load_profiles(tmp_path)


def test_optional_notification_can_be_empty(tmp_path: Path) -> None:
    data = valid_profile()
    data["notification_labels"] = []
    write_profile(tmp_path, data)
    assert load_profiles(tmp_path)["test-cafe"].notification_labels == ()


def test_rejects_missing_and_unknown_fields(tmp_path: Path) -> None:
    data = valid_profile()
    del data["keywords"]
    write_profile(tmp_path, data)
    with pytest.raises(ProfileError, match="Missing required"):
        load_profiles(tmp_path)
    data = valid_profile()
    data["token"] = "SHOULD_NOT_BE_ECHOED"
    write_profile(tmp_path, data)
    with pytest.raises(ProfileError) as error:
        load_profiles(tmp_path)
    assert "SHOULD_NOT_BE_ECHOED" not in str(error.value)


def test_rejects_duplicate_yaml_keys_and_ids(tmp_path: Path) -> None:
    data = valid_profile()
    write_profile(tmp_path, data)
    with (tmp_path / "profile.yaml").open("a", encoding="utf-8") as output:
        output.write("country: NZ\n")
    with pytest.raises(ProfileError, match="Duplicate YAML"):
        load_profiles(tmp_path)
    write_profile(tmp_path, data)
    write_profile(tmp_path, data, "second.yml")
    with pytest.raises(ProfileError, match="Duplicate profile id"):
        load_profiles(tmp_path)


@pytest.mark.parametrize("content", ["[]", "!!python/object:thing {}", "foo: [", "true: false"])
def test_rejects_invalid_yaml_without_echoing_contents(tmp_path: Path, content: str) -> None:
    (tmp_path / "profile.yaml").write_text(content, encoding="utf-8")
    with pytest.raises(ProfileError):
        load_profiles(tmp_path)


def test_empty_or_missing_directory(tmp_path: Path) -> None:
    with pytest.raises(ProfileError, match="No YAML"):
        load_profiles(tmp_path)
    with pytest.raises(ProfileError, match="does not exist"):
        load_profiles(tmp_path / "absent")
