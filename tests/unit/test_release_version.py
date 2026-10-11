import runpy
from pathlib import Path

import pytest

release_version = runpy.run_path(
    Path(__file__).parents[2] / "scripts" / "check_release_version.py"
)
newest_version = release_version["newest_version"]
version_key = release_version["version_key"]


@pytest.mark.parametrize(
    ("older", "newer"),
    [
        ("0.1.0rc1", "0.1.0rc2"),
        ("0.1.0rc2", "0.1.0"),
        ("0.1.0", "0.1.1rc1"),
        ("0.1.9", "0.2.0rc1"),
        ("0.9.9", "1.0.0rc1"),
    ],
)
def test_release_versions_are_ordered(older: str, newer: str) -> None:
    assert version_key(older) < version_key(newer)


@pytest.mark.parametrize(
    "version",
    ["1.0", "v1.0.0", "1.0.0-rc1", "1.0.0rc0", "01.0.0", "1.0.0.dev1"],
)
def test_unsupported_release_version_is_rejected(version: str) -> None:
    with pytest.raises(ValueError, match="unsupported release version"):
        version_key(version)


def test_newest_version_uses_release_semantics() -> None:
    assert newest_version(["0.2.0rc2", "0.1.9", "0.2.0rc1"]) == "0.2.0rc2"
    assert newest_version(["0.2.0rc2", "0.2.0"]) == "0.2.0"


def test_newest_version_accepts_no_versions() -> None:
    assert newest_version([]) is None
