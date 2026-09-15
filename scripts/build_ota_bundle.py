#!/usr/bin/env python3
"""Build the JSON application bundle consumed by micro/ota_manager.py."""

import argparse
import base64
import hashlib
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MICRO_DIR = PROJECT_ROOT / "micro"
APP_FILES = (
    "api.py",
    "app_main.py",
    "bambuddy_api.py",
    "config_loader.py",
    "gpio_button.py",
    "led_flasher.py",
    "periodic_timer.py",
    "web_config.py",
    "wifi.py",
)


def build_bundle(version, release_notes=""):
    files = {}
    for filename in APP_FILES:
        path = MICRO_DIR / filename
        content = path.read_bytes()
        files[filename] = {
            "size": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
            "content": base64.b64encode(content).decode("ascii"),
        }

    return {
        "format": 1,
        "version": version,
        "release_notes": release_notes,
        "minimum_bootloader": 1,
        "files": files,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--release-notes", default="")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(build_bundle(args.version, args.release_notes), indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
