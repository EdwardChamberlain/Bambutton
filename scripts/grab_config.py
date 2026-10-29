#!/usr/bin/env python3
import argparse
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(
        description="Download config.json from the connected board with mpremote.",
    )
    parser.add_argument(
        "--device",
        help="Optional mpremote device/port, for example /dev/tty.usbmodemXXXX.",
    )
    args = parser.parse_args()

    output_dir = PROJECT_ROOT / "grabbed configs"
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        # Reserve a unique filename so repeated or concurrent grabs cannot
        # overwrite an earlier capture. Close it before mpremote for Windows.
        with tempfile.NamedTemporaryFile(
            prefix=datetime.now().strftime("config-%Y%m%d-%H%M%S-"),
            suffix=".json",
            dir=output_dir,
            delete=False,
        ) as config_file:
            destination = Path(config_file.name)
    except OSError as exc:
        parser.exit(1, "Could not prepare config download: {}\n".format(exc))

    command = ["mpremote"]
    if args.device:
        command.extend(["connect", args.device])
    command.extend(["cp", ":config.json", str(destination)])

    downloaded = False
    try:
        run(command)
        downloaded = True
    except (OSError, subprocess.CalledProcessError) as exc:
        parser.exit(1, "Could not grab config.json: {}\n".format(exc))
    finally:
        if not downloaded:
            destination.unlink(missing_ok=True)

    print("Saved configuration to {}".format(destination))


def run(command):
    print("+", " ".join(command))
    subprocess.run(command, check=True)


if __name__ == "__main__":
    main()
