#!/usr/bin/env python3
"""Fail a release when its tag does not match the plugin manifest version."""

from argparse import ArgumentParser
import json
from pathlib import Path
import sys


def validate_release_version(manifest_path: Path, tag: str, tag_prefix: str) -> str:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    version = manifest.get("version")
    if not isinstance(version, str) or not version:
        raise ValueError(f"plugin manifest has no valid version: {manifest_path}")

    expected_tag = f"{tag_prefix}{version}"
    if tag != expected_tag:
        raise ValueError(
            f"release tag {tag!r} does not match plugin manifest version "
            f"{version!r}; expected {expected_tag!r}"
        )
    return version


def main() -> int:
    parser = ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--tag-prefix", required=True)
    args = parser.parse_args()

    try:
        version = validate_release_version(
            args.manifest, args.tag, args.tag_prefix
        )
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1

    print(f"Release tag {args.tag} matches plugin manifest version {version}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
