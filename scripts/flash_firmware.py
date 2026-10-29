#!/usr/bin/env python3
"""Clean-flash an ESP32-C3 MicroPython firmware image over USB."""

import argparse
from pathlib import Path
import struct
import subprocess
import sys


def validate_firmware(filename):
    path = Path(filename).expanduser().resolve()
    if path.suffix.lower() != ".bin" or not path.is_file():
        raise ValueError("Choose an existing ESP32-C3 firmware .bin file.")

    from esptool.bin_image import LoadFirmwareImage
    from esptool.targets.esp32c3 import ESP32C3ROM
    from esptool.util import FatalError

    try:
        image = LoadFirmwareImage("esp32c3", str(path))
        if image.chip_id != ESP32C3ROM.IMAGE_CHIP_ID:
            raise ValueError("The firmware image is not for an ESP32-C3.")
        if image.checksum != image.calculate_checksum():
            raise ValueError("The firmware image checksum is invalid.")
        if image.append_digest and image.stored_digest != image.calc_digest:
            raise ValueError("The firmware image validation hash is invalid.")
    except (OSError, FatalError, EOFError, struct.error) as exc:
        raise ValueError("Could not read firmware image: {}".format(exc)) from exc
    return path


def select_device(device):
    if device is not None:
        if not device.strip():
            raise ValueError("--device must name a serial port, for example COM4.")
        return device

    from serial.tools.list_ports import comports

    ports = sorted(port.device for port in comports())
    if not ports:
        raise ValueError(
            "No serial ports found. Connect the board with a data-capable USB "
            "cable or select its port with --device."
        )
    if len(ports) > 1:
        raise ValueError(
            "Multiple serial ports found ({}). Select the board with --device."
            .format(", ".join(ports))
        )
    return ports[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "firmware", help="Path to a complete ESP32-C3 MicroPython firmware .bin image.",
    )
    parser.add_argument(
        "--device", help="Serial port, for example /dev/tty.usbmodemXXXX or COM4.",
    )
    parser.add_argument(
        "--clean", action="store_true",
        help="Confirm erasing all existing application files and settings.",
    )
    args = parser.parse_args()
    if not args.clean:
        parser.error(
            "re-flashing erases all application files and settings; back up "
            "config.json with scripts/grab_config.py, then pass --clean"
        )

    try:
        firmware = validate_firmware(args.firmware)
        device = select_device(args.device)
    except ImportError:
        parser.exit(1, "Install flashing dependencies: python -m pip install -r requirements.txt\n")
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    print("Clean re-flash of {} on {}; all settings will be erased.".format(firmware, device), flush=True)
    prefix = [sys.executable, "-m", "esptool", "--chip", "esp32c3", "--port", device]
    try:
        # One connection lets esptool check chip revision and image size before
        # erasing, then write and verify the image on the same board.
        run(prefix + ["write-flash", "--erase-all", "-z", "0x0", str(firmware)])
    except (OSError, subprocess.CalledProcessError) as exc:
        parser.exit(1, "Firmware re-flash failed: {}\n".format(exc))
    except KeyboardInterrupt:
        parser.exit(130, "Flashing interrupted; re-run the clean flash to recover.\n")

    print(
        "Firmware flashed successfully. Install the application with "
        "scripts/push_micro.py --clean --device {}".format(device)
    )


def run(command):
    print("+", " ".join(command), flush=True)
    subprocess.run(command, check=True)


if __name__ == "__main__":
    main()
