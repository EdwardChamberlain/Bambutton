#!/usr/bin/env python3
import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = PROJECT_ROOT / "src" / "bambutton" / "gui.py"
MICRO_DIR = PROJECT_ROOT / "micro"
FIRMWARE_DIR = PROJECT_ROOT / "firmware"
PYINSTALLER_CONFIG_DIR = PROJECT_ROOT / ".pyinstaller-cache"
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


def data_arg(source, destination):
    separator = ";" if sys.platform.startswith("win") else ":"
    return "{}{}{}".format(source, separator, destination)


if __name__ == "__main__":
    main()
