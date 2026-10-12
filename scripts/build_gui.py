#!/usr/bin/env python3
import os
import re
import subprocess
import sys
from importlib import metadata
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = PROJECT_ROOT / "src" / "bambutton" / "gui.py"
MICRO_DIR = PROJECT_ROOT / "micro"
FIRMWARE_DIR = PROJECT_ROOT / "firmware"
PROJECT_LICENSE = PROJECT_ROOT / "LICENSE"
THIRD_PARTY_NOTICES = PROJECT_ROOT / "THIRD_PARTY_NOTICES.md"
PYINSTALLER_CONFIG_DIR = PROJECT_ROOT / ".pyinstaller-cache"
RUNTIME_DISTRIBUTIONS = ("esptool", "FreeSimpleGUI", "mpremote")
MICRO_FILES = [
    "api.py",
    "app_main.py",
    "bambuddy_api.py",
    "boot.py",
    "config_loader.py",
    "gpio_button.py",
    "led_flasher.py",
    "main.py",
    "ota_manager.py",
    "periodic_timer.py",
    "wifi.py",
    "web_config.py",
    "config_example.json",
]


def main():
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--name",
        "Bambutton",
        "--windowed",
        "--clean",
        "--noconfirm",
        "--paths",
        str(PROJECT_ROOT / "src"),
        "--hidden-import",
        "esptool",
        "--hidden-import",
        "mpremote.main",
        "--collect-data",
        "esptool",
    ]

    if not sys.platform.startswith("darwin"):
        command.append("--onefile")

    for path in (PROJECT_LICENSE, THIRD_PARTY_NOTICES):
        command.extend(["--add-data", data_arg(path, "bambutton")])

    command.extend(third_party_license_data_args())

    for filename in MICRO_FILES:
        command.extend(
            [
                "--add-data",
                data_arg(MICRO_DIR / filename, "bambutton/micro"),
            ]
        )

    command.extend(
        [
            "--add-data",
            data_arg(FIRMWARE_DIR, "bambutton/firmware"),
        ]
    )
    command.append(str(ENTRYPOINT))

    env = os.environ.copy()
    env["PYINSTALLER_CONFIG_DIR"] = str(PYINSTALLER_CONFIG_DIR)

    print("+", " ".join(command))
    subprocess.run(command, check=True, env=env)


def third_party_license_data_args():
    """Bundle licence files for runtime dependencies and their requirements."""
    pending = list(RUNTIME_DISTRIBUTIONS)
    seen = set()
    license_args = []

    while pending:
        name = pending.pop(0)
        normalized = re.sub(r"[-_.]+", "-", name).lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        try:
            distribution = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            continue

        for requirement in distribution.requires or ():
            match = re.match(r"\s*([A-Za-z0-9_.-]+)", requirement)
            if match:
                pending.append(match.group(1))

        for file in distribution.files or ():
            relative = Path(str(file))
            lower_parts = [part.lower() for part in relative.parts]
            filename = relative.name.lower()
            is_license_file = (
                any(part in ("license", "licenses") for part in lower_parts[:-1])
                or filename.startswith(("license", "licence", "copying", "notice"))
            )
            if not is_license_file:
                continue

            source = Path(distribution.locate_file(file))
            if not source.is_file():
                continue
            destination = "bambutton/third_party_licenses/{}/{}".format(
                normalized, relative.name
            )
            license_args.extend(["--add-data", data_arg(source, destination)])

    return license_args


def data_arg(source, destination):
    separator = ";" if sys.platform.startswith("win") else ":"
    return "{}{}{}".format(source, separator, destination)


if __name__ == "__main__":
    main()
