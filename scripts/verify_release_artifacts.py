#!/usr/bin/env python3
"""Verify that downloaded release assets match the hardware-tested digests."""

import argparse
import hashlib
import json
from pathlib import Path


ARTIFACTS = {
    "windows_setup_tool_sha256": "Bambutton-windows.zip",
    "macos_setup_tool_sha256": "Bambutton-macos.zip",
    "ota_bundle_sha256": "bambutton-ota.json",
}


def release_artifact_errors(record, artifact_dir):
    expected_hashes = record.get("artifacts") if isinstance(record, dict) else None
    if not isinstance(expected_hashes, dict):
        return ["artifacts must be an object containing tested SHA-256 digests"]

    errors = []
    artifact_dir = Path(artifact_dir)
    for field, filename in ARTIFACTS.items():
        expected = expected_hashes.get(field)
        if not isinstance(expected, str) or len(expected) != 64:
            errors.append("artifact {} must record a SHA-256 digest".format(field))
            continue
        path = artifact_dir / filename
        try:
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            errors.append("release candidate artifact is missing: {}".format(filename))
            continue
        if actual.lower() != expected.lower():
            errors.append("release candidate artifact digest does not match: {}".format(filename))
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("record", type=Path)
    parser.add_argument("artifact_dir", type=Path)
    args = parser.parse_args()

    try:
        record = json.loads(args.record.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        parser.error("could not read release validation record: {}".format(exc))

    errors = release_artifact_errors(record, args.artifact_dir)
    if errors:
        for error in errors:
            print("Release artifact verification failed:", error)
        raise SystemExit(1)
    print("Release artifacts match the hardware-tested candidate digests.")


if __name__ == "__main__":
    main()
