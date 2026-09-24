#!/usr/bin/env python3
"""Require a completed hardware rehearsal record before publishing a tag."""

import argparse
import json
import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RECORD_PATH = PROJECT_ROOT / "docs" / "release-validation.json"
REQUIRED_CHECKS = (
    "fresh_usb_install",
    "usb_upgrade_from_previous_release",
    "settings_save_power_interruption_recovery",
    "plate_clear_api_outage_recovery",
    "web_ota_install",
    "larger_ota_install_and_rollback",
    "interrupted_ota_rollback",
    "windows_setup_tool_used",
    "macos_setup_tool_used",
)
REQUIRED_ARTIFACT_HASHES = (
    "windows_setup_tool_sha256",
    "macos_setup_tool_sha256",
    "ota_bundle_sha256",
)


def release_readiness_errors(record, tag, expected_commit):
    errors = []
    if not isinstance(record, dict):
        return ["release validation record must be a JSON object"]

    if record.get("release_tag") != tag:
        errors.append("release_tag must match {}".format(tag))
    candidate_version = record.get("candidate_version")
    if not isinstance(candidate_version, str) or tag != "v" + candidate_version:
        errors.append("candidate_version must match {}".format(tag))
    for field in ("tested_at_utc", "tested_commit", "board", "micropython_firmware"):
        if not isinstance(record.get(field), str) or not record[field].strip():
            errors.append("{} must be recorded".format(field))
    if record.get("tested_commit") != expected_commit:
        errors.append("tested_commit must match the release commit")
    if record.get("result") != "passed":
        errors.append("result must be passed")

    artifacts = record.get("artifacts")
    if not isinstance(artifacts, dict):
        errors.append("artifacts must be an object containing tested SHA-256 digests")
    else:
        for name in REQUIRED_ARTIFACT_HASHES:
            value = artifacts.get(name)
            if not isinstance(value, str) or re.fullmatch(r"[0-9a-fA-F]{64}", value) is None:
                errors.append("artifact {} must record a SHA-256 digest".format(name))

    checks = record.get("checks")
    if not isinstance(checks, dict):
        errors.append("checks must be an object")
    else:
        for name in REQUIRED_CHECKS:
            if checks.get(name) is not True:
                errors.append("check {} is incomplete".format(name))
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag")
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--record", type=Path, default=RECORD_PATH)
    args = parser.parse_args()

    try:
        record = json.loads(args.record.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        parser.error("could not read release validation record: {}".format(exc))

    errors = release_readiness_errors(record, args.tag, args.expected_commit)
    if errors:
        for error in errors:
            print("Release readiness failed:", error)
        raise SystemExit(1)
    print("Release validation record passed for {}".format(args.tag))


if __name__ == "__main__":
    main()
