#!/usr/bin/env python3
import os
import re
import subprocess
import sys
from importlib import metadata
from pathlib import Path
from pathlib import PurePosixPath

from packaging.requirements import Requirement


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = PROJECT_ROOT / "src" / "bambutton" / "gui.py"
MICRO_DIR = PROJECT_ROOT / "micro"
FIRMWARE_DIR = PROJECT_ROOT / "firmware"
PROJECT_LICENSE = PROJECT_ROOT / "LICENSE"
THIRD_PARTY_NOTICES = PROJECT_ROOT / "THIRD_PARTY_NOTICES.md"
PYINSTALLER_CONFIG_DIR = PROJECT_ROOT / ".pyinstaller-cache"
RUNTIME_DISTRIBUTIONS = ("esptool", "FreeSimpleGUI", "mpremote")
REPOSITORY_LICENSES = {
    "pyserial": PROJECT_ROOT / "THIRD_PARTY_LICENSES" / "pyserial-3.5-LICENSE.txt",
}
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
    """Bundle licence texts for active runtime dependencies and requirements."""
    pending = list(RUNTIME_DISTRIBUTIONS)
    seen = set()
    destinations = set()
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

        for requirement_text in distribution.requires or ():
            requirement = Requirement(requirement_text)
            if requirement.marker and not requirement.marker.evaluate():
                continue
            pending.append(requirement.name)

        found_license = False
        license_contents = []
        for file in distribution.files or ():
            relative = PurePosixPath(str(file))
            if not _is_license_document(relative.name):
                continue

            source = Path(distribution.locate_file(file))
            if not source.is_file():
                continue
            found_license = True
            try:
                license_contents.append(source.read_text(encoding="utf-8"))
            except (OSError, UnicodeError):
                pass
            destination_dir = _third_party_destination(normalized, relative.parent)
            _append_data_arg(license_args, destinations, source, destination_dir)

        metadata_license = getattr(distribution, "metadata", {}).get("License", "")
        metadata_license = metadata_license.strip()
        if len(metadata_license) >= 512 and not any(
            metadata_license in content for content in license_contents
        ):
            source = PYINSTALLER_CONFIG_DIR / "licenses" / normalized / "LICENSE-METADATA.txt"
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text(metadata_license + "\n", encoding="utf-8")
            destination_dir = _third_party_destination(
                normalized, PurePosixPath(".")
            )
            _append_data_arg(license_args, destinations, source, destination_dir)

        fallback = REPOSITORY_LICENSES.get(normalized)
        if fallback and fallback.is_file() and not found_license:
            _append_data_arg(
                license_args,
                destinations,
                fallback,
                _third_party_destination(normalized, PurePosixPath(".")),
            )

    return license_args


def _is_license_document(filename):
    lowered = filename.lower()
    if lowered.endswith((".py", ".pyc", ".pyo", ".json", ".toml", ".yaml", ".yml")):
        return False
    return lowered.startswith(("license", "licence", "copying", "notice", "copyright"))


def _third_party_destination(distribution, relative_parent):
    base = PurePosixPath("bambutton/third_party_licenses") / distribution
    if str(relative_parent) in ("", "."):
        return base.as_posix()
    return (base / relative_parent).as_posix()


def _append_data_arg(arguments, destinations, source, destination_dir):
    output = (destination_dir, source.name)
    if output in destinations:
        return
    destinations.add(output)
    arguments.extend(["--add-data", data_arg(source, destination_dir)])


def data_arg(source, destination):
    separator = ";" if sys.platform.startswith("win") else ":"
    return "{}{}{}".format(source, separator, destination)


if __name__ == "__main__":
    main()
