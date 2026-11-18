"""Strict, secret-free SEEK search profile configuration."""

import re
from dataclasses import dataclass, fields
from pathlib import Path

import yaml


class ProfileError(ValueError):
    """A profile file is invalid or ambiguous."""


@dataclass(frozen=True)
class Profile:
    id: str
    name: str
    enabled: bool
    country: str
    locations: tuple[str, ...]
    keywords: tuple[str, ...]
    exclude_title: tuple[str, ...]
    employers: tuple[str, ...]
    max_results: int
    max_pages: int
    notification_labels: tuple[str, ...]


class _UniqueKeyLoader(yaml.SafeLoader):
    """Reject duplicate keys instead of silently keeping the last value."""


def _unique_mapping(loader: _UniqueKeyLoader, node: yaml.MappingNode) -> dict[str, object]:
    loader.flatten_mapping(node)
    result: dict[str, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=True)
        if not isinstance(key, str):
            raise ProfileError("YAML mapping keys must be strings")
        if key in result:
            raise ProfileError("Duplicate YAML mapping key")
        result[key] = loader.construct_object(value_node, deep=True)
    return result


_UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping)
_LABELS = {"likely_suitable", "needs_confirmation", "likely_incompatible"}
_FIELDS = {field.name for field in fields(Profile)}


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProfileError(f"{field} must be a non-empty string")
    if any(ord(char) < 32 for char in value):
        raise ProfileError(f"{field} cannot contain control characters")
    return value.strip()


def _texts(value: object, field: str, *, required: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ProfileError(f"{field} must be a YAML list of strings")
    items = tuple(_text(item, field) for item in value)
    if required and not items:
        raise ProfileError(f"{field} must contain at least one entry")
    if len({item.casefold() for item in items}) != len(items):
        raise ProfileError(f"{field} contains duplicate entries")
    return items


def _bounded_int(value: object, field: str, maximum: int) -> int:
    if type(value) is not int or not 1 <= value <= maximum:
        raise ProfileError(f"{field} must be an integer from 1 to {maximum}")
    return value


def _parse_profile(data: object) -> Profile:
    if not isinstance(data, dict):
        raise ProfileError("Profile must be a YAML mapping")
    if set(data) - _FIELDS:
        raise ProfileError("Profile contains unknown fields")
    missing = _FIELDS - set(data)
    if missing:
        raise ProfileError("Missing required fields: " + ", ".join(sorted(missing)))
    profile_id = _text(data["id"], "id")
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", profile_id):
        raise ProfileError("id must be a lowercase hyphenated identifier")
    if type(data["enabled"]) is not bool:
        raise ProfileError("enabled must be a YAML boolean")
    if data["country"] != "NZ":
        raise ProfileError("country must be NZ")
    labels = _texts(data["notification_labels"], "notification_labels")
    if set(labels) - _LABELS:
        raise ProfileError("notification_labels contains an unsupported label")
    return Profile(
        id=profile_id,
        name=_text(data["name"], "name"),
        enabled=data["enabled"],
        country="NZ",
        locations=_texts(data["locations"], "locations", required=True),
        keywords=_texts(data["keywords"], "keywords", required=True),
        exclude_title=_texts(data["exclude_title"], "exclude_title"),
        employers=_texts(data["employers"], "employers"),
        max_results=_bounded_int(data["max_results"], "max_results", 5000),
        max_pages=_bounded_int(data["max_pages"], "max_pages", 100),
        notification_labels=labels,
    )


def load_profiles(directory: Path) -> dict[str, Profile]:
    """Load YAML files deterministically; never include YAML values in errors."""
    if not directory.is_dir():
        raise ProfileError("Profile directory does not exist")
    paths = sorted(
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in {".yaml", ".yml"}
    )
    if not paths:
        raise ProfileError("No YAML profiles found")
    profiles = {}
    for path in paths:
        try:
            data = yaml.load(path.read_text(encoding="utf-8-sig"), Loader=_UniqueKeyLoader)
            profile = _parse_profile(data)
        except (OSError, UnicodeError, yaml.YAMLError):
            raise ProfileError(f"Cannot read valid YAML from {path.name}") from None
        except ProfileError as exc:
            raise ProfileError(f"{path.name}: {exc}") from None
        if profile.id in profiles:
            raise ProfileError(f"{path.name}: Duplicate profile id")
        profiles[profile.id] = profile
    return profiles
