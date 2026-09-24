#!/usr/bin/env python3
import argparse
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MICRO_DIR = PROJECT_ROOT / "micro"
CONFIG_FILE = MICRO_DIR / "config.json"
BOOTSTRAP_DIR = ".bambutton/bootstrap"

BOOTSTRAP_PREPARE_CODE = """
import os


def remove(path):
    try:
        mode = os.stat(path)[0]
        is_dir = mode & 0x4000
    except OSError:
        return

    if is_dir:
        for name in os.listdir(path):
            remove(path + "/" + name)
        os.rmdir(path)
    else:
        os.remove(path)


def mkdir(path):
    try:
        os.mkdir(path)
    except OSError:
        pass


mkdir(".bambutton")
remove(".bambutton/bootstrap")
mkdir(".bambutton/bootstrap")
"""

BOOTSTRAP_COMMIT_CODE = """
import os


def exists(path):
    try:
        os.stat(path)
        return True
    except OSError:
        return False


def is_recoverable_install():
    try:
        with open(".bambutton/bootstrap-install.marker") as marker:
            return marker.read() == "bambutton-bootstrap-v1\\n"
    except OSError:
        return False


def write_install_marker():
    with open(".bambutton/bootstrap-install.marker", "w") as marker:
        marker.write("bambutton-bootstrap-v1\\n")


required = (
    ".bambutton/bootstrap/api.py",
    ".bambutton/bootstrap/app_main.py",
    ".bambutton/bootstrap/bambuddy_api.py",
    ".bambutton/bootstrap/config_loader.py",
    ".bambutton/bootstrap/gpio_button.py",
    ".bambutton/bootstrap/led_flasher.py",
    ".bambutton/bootstrap/periodic_timer.py",
    ".bambutton/bootstrap/ota_manager.py",
    ".bambutton/bootstrap/web_config.py",
    ".bambutton/bootstrap/wifi.py",
    ".bambutton/bootstrap/boot.py",
    ".bambutton/bootstrap/main.py",
)
for path in required:
    if not exists(path):
        raise RuntimeError("Incomplete staged MicroPython installation: " + path)

state_names = os.listdir(".bambutton")
has_ota_state = any(
    name == "active.json" or name.startswith("active.")
    for name in state_names
)
recoverable_install = is_recoverable_install()
if (exists("boot.py") or exists("ota_manager.py")) and not has_ota_state and not recoverable_install:
    raise RuntimeError(
        "Unknown existing boot files; use a clean USB installation for recovery"
    )

# Record the ownership of a new staged installation before touching root
# files. Preserve an existing valid marker so a power loss during a retry
# cannot destroy the recovery evidence.
if not recoverable_install:
    write_install_marker()

# If the previous attempt installed only the manager, it is not executable
# without boot.py. Replace that incomplete copy before retrying the handoff.
if exists("ota_manager.py") and not exists("boot.py") and not has_ota_state:
    os.remove("ota_manager.py")

# Install the new manager while preserving an existing flat-root main.py.
if not exists("ota_manager.py"):
    os.rename(".bambutton/bootstrap/ota_manager.py", "ota_manager.py")

if not exists("config.json") and exists(".bambutton/bootstrap/config.json"):
    os.rename(".bambutton/bootstrap/config.json", "config.json")

# Install the short boot recovery hook before changing main.py. If power fails
# during the handoff, boot.py completes it and then exits into main.py.
if not exists("boot.py"):
    os.rename(".bambutton/bootstrap/boot.py", "boot.py")

# Preserve the old flat-root entrypoint for migration rollback. Existing OTA
# installations already have the stable loader and must keep it.
if not has_ota_state:
    legacy_main = ".bambutton/legacy_main.py"
    if exists("main.py") and not exists(legacy_main):
        os.rename("main.py", legacy_main)
    if not exists("main.py"):
        os.rename(".bambutton/bootstrap/main.py", "main.py")
"""

CLEAN_BOARD_CODE = """
import os


def remove(path):
    try:
        mode = os.stat(path)[0]
        is_dir = mode & 0x4000
    except OSError:
        return

    if is_dir:
        for name in os.listdir(path):
            remove(path + "/" + name)
        os.rmdir(path)
    else:
        os.remove(path)


for name in os.listdir():
    remove(name)
"""


def main():
    parser = argparse.ArgumentParser(
        description="Push MicroPython application files to the connected board.",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Delete all files from the board filesystem before copying files.",
    )
    parser.add_argument(
        "--device",
        help="Optional mpremote device/port, for example /dev/tty.usbmodemXXXX.",
    )
    parser.add_argument(
        "--no-reset",
        action="store_true",
        help="Do not reset the board after copying files.",
    )
    parser.add_argument(
        "--no-main",
        "--nomain",
        dest="no_main",
        action="store_true",
        help="Do not copy main.py, preventing the application from auto-starting.",
    )
    args = parser.parse_args()

    files = sorted(MICRO_DIR.glob("*.py"))
    if args.no_main:
        files = [path for path in files if path.name not in ("main.py", "boot.py")]

    if not files and not CONFIG_FILE.exists():
        raise SystemExit("No files found to copy from {}".format(MICRO_DIR))

    mpremote_prefix = ["mpremote"]
    if args.device:
        mpremote_prefix.extend(["connect", args.device])

    if args.clean:
        run(mpremote_prefix + ["exec", CLEAN_BOARD_CODE])

    if args.no_main:
        for path in files:
            run(mpremote_prefix + ["cp", str(path), ":"])
        if CONFIG_FILE.exists():
            run(mpremote_prefix + ["cp", str(CONFIG_FILE), ":config.json"])
    else:
        run(mpremote_prefix + ["exec", BOOTSTRAP_PREPARE_CODE])
        for path in files:
            run(mpremote_prefix + [
                "cp",
                str(path),
                ":" + BOOTSTRAP_DIR + "/" + path.name,
            ])
        if CONFIG_FILE.exists():
            run(mpremote_prefix + [
                "cp",
                str(CONFIG_FILE),
                ":" + BOOTSTRAP_DIR + "/config.json",
            ])
        run(mpremote_prefix + ["exec", BOOTSTRAP_COMMIT_CODE])

    if not args.no_reset:
        run(mpremote_prefix + ["reset"])


def run(command):
    print("+", " ".join(command))
    subprocess.run(command, check=True)


if __name__ == "__main__":
    main()
