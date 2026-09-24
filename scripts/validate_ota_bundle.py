#!/usr/bin/env python3
"""Validate a built OTA asset using the device's limits and allowlist."""

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from micro.ota_manager import (  # noqa: E402
    MAX_BUNDLE_BODY_BYTES,
    OTAError,
    validate_bundle,
)


def validate_ota_artifact(path):
    artifact = Path(path).read_bytes()
    if len(artifact) > MAX_BUNDLE_BODY_BYTES:
        raise OTAError(
            "OTA artifact exceeds the {} byte payload limit".format(
                MAX_BUNDLE_BODY_BYTES
            )
        )
    try:
        bundle = json.loads(artifact.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise OTAError("OTA artifact is not valid JSON: {}".format(exc))
    return validate_bundle(bundle)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    args = parser.parse_args()

    try:
        validate_ota_artifact(args.artifact)
    except (OSError, OTAError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
