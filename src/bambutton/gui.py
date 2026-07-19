#!/usr/bin/env python3
import contextlib
import io
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import serial.tools.list_ports

try:
    import FreeSimpleGUI as sg
except ImportError:
    print("FreeSimpleGUI is not installed. Run: python -m pip install -r requirements.txt")
    raise


PACKAGE_ROOT = Path(__file__).resolve().parent
SOURCE_ROOT = Path(__file__).resolve().parents[2]
if hasattr(sys, "_MEIPASS"):
    RESOURCE_ROOT = Path(sys._MEIPASS) / "bambutton"
else:
    RESOURCE_ROOT = SOURCE_ROOT if (SOURCE_ROOT / "micro").exists() else PACKAGE_ROOT

MICRO_DIR = RESOURCE_ROOT / "micro"
CONFIG_PATH = MICRO_DIR / "config.json"
DEFAULT_FIRMWARE_DIR = RESOURCE_ROOT / "firmware"

GPIO_MIN = 0
GPIO_MAX = 21

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
    window = build_window(load_existing_config())
    printers_by_label = {}

    while True:
        event, values = window.read(timeout=250)
        if event in (sg.WIN_CLOSED, "Exit"):
            break

        update_action_states(window, values)

        if event == "-REFRESH_BOARDS-":
            refresh_boards(window)

        elif event == "-GET_PRINTERS-":
            try:
                printers_by_label = fetch_printers(values)
                labels = sorted(printers_by_label.keys())
                window["-PRINTER-"].update(values=labels, value="", disabled=not labels)
                sg.popup("Printers loaded." if labels else "No printers returned by the API.")
            except Exception as exc:
                window["-PRINTER-"].update(values=[], value="", disabled=True)
                sg.popup_error("Could not load printers", str(exc))

        elif event == "-FLASH_SETTINGS-":
            try:
                config = build_config(values, printers_by_label)
                write_config(config)
                push_config(values["-BOARD-"])
                sg.popup("Settings pushed to board.")
            except Exception as exc:
                sg.popup_error("Could not flash settings", str(exc))

        elif event == "-FLASH_FIRMWARE-":
            try:
                config = build_config(values, printers_by_label)
                firmware_path = validate_firmware(values["-FIRMWARE-"])
                board = require_board(values["-BOARD-"])
                write_config(config)
                flash_firmware(board, firmware_path)
                time.sleep(2)
                push_micro_files(board, clean=True)
                sg.popup("Firmware and project files flashed.")
            except Exception as exc:
                sg.popup_error("Could not flash firmware", str(exc))

    window.close()


def build_window(config):
    sg.theme("SystemDefault")

    firmware_default = first_firmware_file()

    layout = [
        [
            sg.Frame(
                "Board Firmware",
                [
                    [
                        sg.Text("Firmware .bin", size=(16, 1)),
                        sg.Input(str(firmware_default), key="-FIRMWARE-", enable_events=True),
                        sg.FileBrowse(
                            file_types=(("Firmware binaries", "*.bin"), ("All files", "*.*")),
                            initial_folder=str(DEFAULT_FIRMWARE_DIR),
                        ),
                    ],
                ],
                expand_x=True,
            )
        ],
        [
            sg.Frame(
                "Bambuddy Config",
                [
                    [
                        sg.Text("IP and port", size=(16, 1)),
                        sg.Input(
                            ip_port_from_base_url(config["api"]["base_url"]),
                            key="-API_HOST-",
                            enable_events=True,
                            tooltip="Example: 192.168.1.200:8000",
                        ),
                    ],
                    [
                        sg.Text("API key", size=(16, 1)),
                        sg.Input(config["api"]["key"], key="-API_KEY-", enable_events=True),
                    ],
                    [
                        sg.Text("Printer", size=(16, 1)),
                        sg.Combo([], key="-PRINTER-", readonly=True, disabled=True, size=(36, 1), enable_events=True),
                        sg.Button("Get printers", key="-GET_PRINTERS-", disabled=True),
                    ],
                ],
                expand_x=True,
            )
        ],
        [
            sg.Frame(
                "Board Configuration",
                [
                    [
                        sg.Text("Board", size=(16, 1)),
                        sg.Combo([], key="-BOARD-", readonly=True, size=(36, 1), enable_events=True),
                        sg.Button("Refresh boards", key="-REFRESH_BOARDS-"),
                    ],
                    [
                        sg.Text("LED pin", size=(16, 1)),
                        sg.Input(str(config["led"]["pin"]), key="-LED_PIN-", size=(8, 1), enable_events=True),
                    ],
                    [
                        sg.Text("Button pin", size=(16, 1)),
                        sg.Input(str(config["button"]["pin"]), key="-BUTTON_PIN-", size=(8, 1), enable_events=True),
                    ],
                    [
                        sg.Text("Wi-Fi SSID", size=(16, 1)),
                        sg.Input(config["wifi"]["ssid"], key="-WIFI_SSID-", enable_events=True),
                    ],
                    [
                        sg.Text("Wi-Fi password", size=(16, 1)),
                        sg.Input(config["wifi"]["password"], key="-WIFI_PASSWORD-", enable_events=True),
                    ],
                ],
                expand_x=True,
            )
        ],
        [
            sg.Frame(
                "Flash",
                [
                    [
                        sg.Button("Flash firmware", key="-FLASH_FIRMWARE-", disabled=True),
                        sg.Button("Flash settings only", key="-FLASH_SETTINGS-", disabled=True),
                        sg.Button("Exit"),
                    ],
                    [sg.Text("", key="-VALIDATION-", text_color="firebrick", size=(72, 2))],
                ],
                expand_x=True,
            )
        ],
    ]

    window = sg.Window("Bambutton Setup", layout, finalize=True)
    update_action_states(window, window.read(timeout=0)[1])
    return window


def load_existing_config():
    default = {
        "wifi": {"ssid": "", "password": "", "timeout_seconds": 10},
        "api": {"base_url": "", "key": ""},
        "printer": {"id": 1, "poll_interval_seconds": 3},
        "led": {"pin": 3, "flash_interval_ms": 250},
        "button": {"pin": 4, "debounce_ms": 150, "pull": "down", "trigger": "rising"},
    }

    try:
        with CONFIG_PATH.open() as config_file:
            loaded = json.load(config_file)
    except OSError:
        return default

    deep_update(default, loaded)
    return default


def deep_update(target, source):
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            deep_update(target[key], value)
        else:
            target[key] = value


def update_action_states(window, values):
    if not values:
        return

    errors = collect_basic_errors(values, require_printer=False)
    can_get_printers = valid_host_port(values.get("-API_HOST-", "")) and not values.get("-API_KEY-", "").strip() == ""
    can_flash_settings = not collect_basic_errors(values, require_printer=True, require_firmware=False)
    can_flash_firmware = not collect_basic_errors(values, require_printer=True, require_firmware=True)

    window["-GET_PRINTERS-"].update(disabled=not can_get_printers)
    window["-FLASH_SETTINGS-"].update(disabled=not can_flash_settings)
    window["-FLASH_FIRMWARE-"].update(disabled=not can_flash_firmware)
    window["-VALIDATION-"].update(errors[0] if errors else "")


def collect_basic_errors(values, require_printer=True, require_firmware=True):
    errors = []

    if require_firmware:
        try:
            validate_firmware(values.get("-FIRMWARE-", ""))
        except ValueError as exc:
            errors.append(str(exc))

    if not valid_host_port(values.get("-API_HOST-", "")):
        errors.append("Enter Bambuddy IP and port as host:port.")

    if not values.get("-API_KEY-", "").strip():
        errors.append("Enter an API key.")

    if require_printer and not values.get("-PRINTER-"):
        errors.append("Load printers and select one.")

    if not values.get("-BOARD-"):
        errors.append("Refresh boards and select one.")

    try:
        led_pin = parse_pin(values.get("-LED_PIN-", ""), "LED pin")
        button_pin = parse_pin(values.get("-BUTTON_PIN-", ""), "Button pin")
        if led_pin == button_pin:
            errors.append("LED pin and button pin must be different.")
    except ValueError as exc:
        errors.append(str(exc))

    if not values.get("-WIFI_SSID-", "").strip():
        errors.append("Enter a Wi-Fi SSID.")

    return errors


def fetch_printers(values):
    api_base_url = api_base_url_from_host(values["-API_HOST-"])
    request = urllib.request.Request(
        route_url(api_base_url, "printers/"),
        headers={"X-API-Key": values["-API_KEY-"].strip()},
    )

    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise RuntimeError("API rejected the request with status {}".format(exc.code))
    except urllib.error.URLError as exc:
        raise RuntimeError("Could not connect to API: {}".format(exc.reason))

    printers = json.loads(body)
    if isinstance(printers, dict):
        for key in ("printers", "results", "items"):
            if key in printers and isinstance(printers[key], list):
                printers = printers[key]
                break

    if not isinstance(printers, list):
        raise RuntimeError("Printers route did not return a list.")

    printers_by_label = {}
    for printer in printers:
        if not isinstance(printer, dict) or "id" not in printer:
            continue

        printer_id = printer["id"]
        name = printer.get("friendly_name") or printer.get("name") or printer.get("display_name")
        if not name:
            name = "Printer {}".format(printer_id)

        printers_by_label["{} ({})".format(name, printer_id)] = printer_id

    return printers_by_label


def build_config(values, printers_by_label):
    selected_printer = values.get("-PRINTER-")
    if selected_printer not in printers_by_label:
        raise ValueError("Load printers and select one from the dropdown.")

    return {
        "wifi": {
            "ssid": values["-WIFI_SSID-"].strip(),
            "password": values["-WIFI_PASSWORD-"],
            "timeout_seconds": 10,
        },
        "api": {
            "base_url": api_base_url_from_host(values["-API_HOST-"]),
            "key": values["-API_KEY-"].strip(),
            "request_timeout_seconds": 3,
        },
        "printer": {
            "id": printers_by_label[selected_printer],
            "poll_interval_seconds": 3,
        },
        "led": {
            "pin": parse_pin(values["-LED_PIN-"], "LED pin"),
            "flash_interval_ms": 250,
        },
        "button": {
            "pin": parse_pin(values["-BUTTON_PIN-"], "Button pin"),
            "debounce_ms": 150,
            "pull": "down",
            "trigger": "rising",
        },
    }


def write_config(config):
    with CONFIG_PATH.open("w") as config_file:
        json.dump(config, config_file, indent=2)
        config_file.write("\n")


def refresh_boards(window, show_errors=True):
    try:
        boards = list_boards()
        window["-BOARD-"].update(values=boards, value=boards[0] if len(boards) == 1 else "")
    except Exception as exc:
        window["-BOARD-"].update(values=[], value="")
        if show_errors:
            sg.popup_error("Could not list boards", str(exc))


def list_boards():
    boards = []

    for port in sorted(serial.tools.list_ports.comports()):
        if not port.device:
            continue

        boards.append(port.device)

    return boards


def flash_firmware(board, firmware_path):
    run_esptool(["--chip", "esp32c3", "--port", board, "erase_flash"])
    run_esptool(
        [
            "--chip",
            "esp32c3",
            "--port",
            board,
            "write_flash",
            "-z",
            "0x0",
            str(firmware_path),
        ]
    )


def push_config(board):
    run_mpremote(mpremote_args(board, "cp", str(CONFIG_PATH), ":"))
    run_mpremote(mpremote_args(board, "reset"))


def push_micro_files(board, clean=False):
    if clean:
        run_mpremote(mpremote_args(board, "exec", CLEAN_BOARD_CODE))

    files = sorted(MICRO_DIR.glob("*.py")) + [CONFIG_PATH]
    for path in files:
        run_mpremote(mpremote_args(board, "cp", str(path), ":"))

    run_mpremote(mpremote_args(board, "reset"))


def mpremote_args(board, *args):
    return ["connect", board] + list(args)


def run_mpremote(args, capture=False):
    import mpremote.main

    return run_python_entrypoint("mpremote", mpremote.main.main, args, capture)


def run_esptool(args, capture=False):
    import esptool

    return run_python_entrypoint("esptool", esptool._main, args, capture)


def run_python_entrypoint(name, entrypoint, args, capture=False):
    old_argv = sys.argv
    stdout = CapturedText()
    stderr = CapturedText()
    sys.argv = [name] + list(args)

    try:
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            exit_code = call_entrypoint(entrypoint)
    finally:
        sys.argv = old_argv

    if exit_code:
        message = stderr.getvalue() or stdout.getvalue() or "{} failed".format(name)
        raise RuntimeError(message.strip())

    return ToolResult(stdout.getvalue(), stderr.getvalue())


def call_entrypoint(entrypoint):
    try:
        result = entrypoint()
    except SystemExit as exc:
        if exc.code is None:
            return 0
        if isinstance(exc.code, int):
            return exc.code
        return 1

    return result or 0


class ToolResult:
    def __init__(self, stdout="", stderr=""):
        self.stdout = stdout
        self.stderr = stderr


class CapturedText(io.StringIO):
    encoding = "utf-8"


def validate_firmware(path):
    firmware_path = Path(path).expanduser()
    if not firmware_path.exists():
        raise ValueError("Choose a firmware .bin file.")
    if firmware_path.suffix.lower() != ".bin":
        raise ValueError("Firmware file must end in .bin.")
    return firmware_path


def require_board(board):
    if not board:
        raise ValueError("Refresh boards and select a board.")
    return board


def valid_host_port(value):
    if not value:
        return False

    return re.match(r"^[A-Za-z0-9_.-]+:[0-9]{1,5}$", value.strip()) is not None


def api_base_url_from_host(host):
    host = host.strip()
    if not valid_host_port(host):
        raise ValueError("Enter Bambuddy IP and port as host:port.")

    return "http://" + host + "/api/v1"


def route_url(api_base_url, route):
    return api_base_url.rstrip("/") + "/" + route.lstrip("/")


def ip_port_from_base_url(base_url):
    if not base_url:
        return ""

    base_url = base_url.replace("http://", "").replace("https://", "")
    return base_url.replace("/api/v1", "").rstrip("/")


def parse_pin(value, label):
    try:
        pin = int(str(value).strip())
    except ValueError:
        raise ValueError("{} must be a number.".format(label))

    if pin < GPIO_MIN or pin > GPIO_MAX:
        raise ValueError("{} must be between {} and {}.".format(label, GPIO_MIN, GPIO_MAX))

    return pin


def first_firmware_file():
    firmware_files = sorted(DEFAULT_FIRMWARE_DIR.glob("*.bin"))
    if firmware_files:
        return firmware_files[0]

    return ""


if __name__ == "__main__":
    main()
