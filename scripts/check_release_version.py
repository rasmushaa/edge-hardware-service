#!/usr/bin/env python3
"""Require a release version to be newer than the project and release tags."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Iterable

VERSION_PATTERN = re.compile(
    r"^(?P<major>0|[1-9][0-9]*)\."
    r"(?P<minor>0|[1-9][0-9]*)\."
    r"(?P<patch>0|[1-9][0-9]*)"
    r"(?:rc(?P<rc>[1-9][0-9]*))?$"
)
VersionKey = tuple[int, int, int, int, int]


def version_key(version: str) -> VersionKey:
    """Return a key where release candidates sort before their stable release."""
    match = VERSION_PATTERN.fullmatch(version)
    if match is None:
        raise ValueError(f"unsupported release version: {version}")

    rc = match.group("rc")
    return (
        int(match.group("major")),
        int(match.group("minor")),
        int(match.group("patch")),
        1 if rc is None else 0,
        0 if rc is None else int(rc),
    )


def newest_version(versions: Iterable[str]) -> str | None:
    """Return the newest supported version, or None when no versions are given."""
    parsed = [(version_key(version), version) for version in versions]
    return max(parsed, default=None)[1] if parsed else None


def release_tag_versions(candidate: str, *, allow_candidate_tag: bool) -> list[str]:
    """Read supported release versions from local Git tags."""
    tags = subprocess.run(
        ["git", "tag", "--list", "v*"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()

    versions: list[str] = []
    for tag in tags:
        version = tag.removeprefix("v")
        if VERSION_PATTERN.fullmatch(version) is None:
            continue
        if allow_candidate_tag and tag == f"v{candidate}":
            continue
        versions.append(version)
    return versions


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Require CANDIDATE to be newer than the baseline and all release tags."
        )
    )
    parser.add_argument("candidate")
    parser.add_argument("--baseline")
    parser.add_argument(
        "--allow-candidate-tag",
        action="store_true",
        help="ignore the exact candidate tag so a workflow can be safely rerun",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        candidate_key = version_key(args.candidate)
        existing = release_tag_versions(
            args.candidate,
            allow_candidate_tag=args.allow_candidate_tag,
        )
        if args.baseline:
            version_key(args.baseline)
            existing.append(args.baseline)
        newest = newest_version(existing)
    except (ValueError, subprocess.CalledProcessError) as error:
        print(f"Cannot validate release version: {error}", file=sys.stderr)
        return 1

    if newest is not None and candidate_key <= version_key(newest):
        print(
            f"Release version {args.candidate} must be greater than "
            f"the newest existing version {newest}.",
            file=sys.stderr,
        )
        return 1

    if newest is None:
        print(f"Release version {args.candidate} is the first release version.")
    else:
        print(f"Release version increases from {newest} to {args.candidate}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
