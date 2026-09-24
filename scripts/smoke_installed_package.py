#!/usr/bin/env python3
"""Smoke-test runtime resources in an installed wheel or source distribution."""

from pathlib import Path


def check_installed_package():
    import bambutton

    package_root = Path(bambutton.__file__).resolve().parent
    required_files = (
        "micro/app_main.py",
        "micro/boot.py",
        "micro/config_example.json",
        "micro/ota_manager.py",
        "micro/web_config.py",
        "firmware/ESP32_GENERIC_C3-20260406-v1.28.0.bin",
    )
    missing = [name for name in required_files if not (package_root / name).is_file()]
    if missing:
        raise RuntimeError(
            "Installed package is missing: {}".format(", ".join(missing))
        )
    return package_root


def main():
    package_root = check_installed_package()
    print("Installed Bambutton package is ready:", package_root)


if __name__ == "__main__":
    main()
