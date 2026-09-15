#!/usr/bin/env python3
import contextlib
import io
import json
import secrets
import sys
import tempfile
import time
from pathlib import Path

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
CONFIG_EXAMPLE_PATH = MICRO_DIR / "config_example.json"
DEFAULT_FIRMWARE_DIR = RESOURCE_ROOT / "firmware"
FIRMWARE_RESTART_DELAY_SECONDS = 2
BOOTSTRAP_DIR = ".bambutton/bootstrap"
HOSTNAME_SUFFIX_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
HOSTNAME_SUFFIX_LENGTH = 4
MAX_HOSTNAME_LENGTH = 63

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
    ".bambutton/bootstrap/app_main.py",
    ".bambutton/bootstrap/ota_manager.py",
    ".bambutton/bootstrap/web_config.py",
    ".bambutton/bootstrap/boot.py",
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

# Record the ownership of this staged installation before touching root files.
# If power fails after this point, a retry can distinguish our incomplete
# installation from an unrelated boot file.
write_install_marker()

# If the previous attempt installed only the manager, it is not executable
# without boot.py. Replace that incomplete copy before retrying the handoff.
if exists("ota_manager.py") and not exists("boot.py") and not has_ota_state:
    os.remove("ota_manager.py")

# An existing main.py is the legacy application. Leave it untouched and let
# boot.py run the migrated slot before MicroPython reaches main.py.
if not exists("ota_manager.py"):
    os.rename(".bambutton/bootstrap/ota_manager.py", "ota_manager.py")

if not exists("main.py"):
    os.rename(".bambutton/bootstrap/main.py", "main.py")

if not exists("config.json") and exists(".bambutton/bootstrap/config.json"):
    os.rename(".bambutton/bootstrap/config.json", "config.json")

# boot.py is normally absent on a legacy installation. If it is already
# present, it is retained so an interrupted retry cannot overwrite it.
if not exists("boot.py"):
    os.rename(".bambutton/bootstrap/boot.py", "boot.py")
"""


def main():
    window = build_window()

    try:
        while True:
            event, values = window.read(timeout=250)
            if event == sg.WIN_CLOSED:
                break

            if event in ("-WEB-", "-CONFIG-", "-CONFIG_PATH-", "-CONFIG_BROWSE-"):
                update_action_states(window, values)

            if event == "-SAVE_EXAMPLE-":
                handle_save_example_config(window)

            if event == "-FLASH-":
                handle_flash(window, values)
    finally:
        window.close()


def build_window():
    background_color = "#181C23"
    text_color = "#F3F4F6"
    secondary_text_color = "#AAB4C3"
    input_background_color = "#252B34"
    divider_color = "#343B47"
    primary_button_color = "#2563EB"
    secondary_button_color = "#2B313B"
    disabled_button_color = "#151A21"
    disabled_button_text_color = "#667085"

    sg.theme("DarkGrey13")
    sg.theme_background_color(background_color)
    sg.theme_element_background_color(background_color)
    sg.theme_text_element_background_color(background_color)
    sg.theme_text_color(text_color)
    sg.theme_input_background_color(input_background_color)
    sg.theme_input_text_color(text_color)
    sg.theme_button_color(("#FFFFFF", primary_button_color))
    sg.set_options(
        font=("Helvetica", 10),
        element_padding=(5, 4),
        margins=(18, 16),
        use_ttk_buttons=True,
        ttk_theme="clam",
    )

    layout = [
        [
            sg.Text(
                "Bambutton setup",
                font=("Helvetica", 14, "bold"),
                text_color=text_color,
                pad=(0, (0, 2)),
            )
        ],
        [
            sg.Text(
                "Choose how to provision your board.",
                text_color=secondary_text_color,
                pad=(0, (0, 12)),
            )
        ],
        [
            sg.Text(
                "SETUP MODE",
                font=("Helvetica", 9, "bold"),
                text_color=secondary_text_color,
                pad=(0, (0, 4)),
            )
        ],
        [
            sg.Radio(
                "Web GUI setup",
                "SETUP_MODE",
                default=True,
                key="-WEB-",
                enable_events=True,
                size=(24, 1),
                text_color=text_color,
            ),
            sg.Text(
                "Flash firmware, then configure in the web GUI.",
                text_color=secondary_text_color,
                expand_x=True,
            ),
        ],
        [
            sg.Radio(
                "Config based setup",
                "SETUP_MODE",
                key="-CONFIG-",
                enable_events=True,
                size=(24, 1),
                text_color=text_color,
            ),
            sg.Text(
                "Flash firmware with an existing config.json file.",
                text_color=secondary_text_color,
                expand_x=True,
            ),
        ],
        [sg.HorizontalSeparator(color=divider_color, pad=(0, (12, 10)))],
        [
            sg.Text(
                "CONFIGURATION FILE",
                font=("Helvetica", 9, "bold"),
                text_color=secondary_text_color,
                pad=(0, (0, 4)),
            )
        ],
        [
            sg.Text("config.json", size=(16, 1), text_color=text_color),
            sg.Input(
                key="-CONFIG_PATH-",
                enable_events=True,
                size=(32, 1),
                expand_x=True,
                background_color=input_background_color,
                text_color=text_color,
                font=("Helvetica", 10),
                border_width=1,
                pad=(4, 0),
            ),
            sg.Button(
                "Browse",
                key="-CONFIG_BROWSE-",
                target="-CONFIG_PATH-",
                button_type=sg.BUTTON_TYPE_BROWSE_FILE,
                file_types=(("JSON configuration", "*.json"), ("All files", "*.*")),
                button_color=(text_color, secondary_button_color),
                disabled_button_color=(disabled_button_text_color, disabled_button_color),
                mouseover_colors=(text_color, secondary_button_color),
                size=(8, 1),
                font=("Helvetica", 10),
                pad=(4, 0),
            ),
            sg.Button(
                "⇩",
                key="-SAVE_EXAMPLE-",
                size=(3, 1),
                tooltip="Save example configuration",
                button_color=(text_color, secondary_button_color),
                disabled_button_color=(disabled_button_text_color, disabled_button_color),
                mouseover_colors=(text_color, secondary_button_color),
                font=("Helvetica", 10, "bold"),
                pad=(4, 0),
            ),
        ],
        [
            sg.Checkbox(
                "Randomise hostname for each board",
                key="-RANDOMIZE_HOSTNAME-",
                text_color=text_color,
                disabled=True,
                tooltip="Append a fresh four-character suffix to the configured hostname.",
            )
        ],
        [sg.HorizontalSeparator(color=divider_color, pad=(0, (12, 10)))],
        [
            sg.Text(
                "FLASH",
                font=("Helvetica", 9, "bold"),
                text_color=secondary_text_color,
                pad=(0, (0, 4)),
            )
        ],
        [
            sg.Text(
                "Ready",
                key="-STATUS-",
                text_color=secondary_text_color,
                expand_x=True,
                justification="center",
                pad=(0, (0, 8)),
            )
        ],
        [
            sg.Button(
                "Flash",
                key="-FLASH-",
                disabled=True,
                size=(12, 1),
                expand_x=True,
                pad=(0, (0, 6)),
                button_color=("#FFFFFF", primary_button_color),
                disabled_button_color=(disabled_button_text_color, disabled_button_color),
                mouseover_colors=("#FFFFFF", primary_button_color),
                font=("Helvetica", 10, "bold"),
            )
        ],
    ]

    window = sg.Window("Bambutton Setup", layout, finalize=True)
    match_config_input_height(window)
    update_action_states(window, window.read(timeout=0)[1])
    return window


def match_config_input_height(window):
    """Make the single-line path input as tall as the adjacent buttons."""
    window.TKroot.update_idletasks()

    input_widget = window["-CONFIG_PATH-"].Widget
    button_heights = [
        window[key].Widget.winfo_height()
        for key in ("-CONFIG_BROWSE-", "-SAVE_EXAMPLE-")
    ]
    extra_height = max(button_heights) - input_widget.winfo_height()
    if extra_height > 0:
        input_widget.pack_configure(ipady=(extra_height + 1) // 2)
        window.TKroot.update_idletasks()


def select_example_config_path(window):
    from tkinter import filedialog

    return filedialog.asksaveasfilename(
        parent=window.TKroot,
        title="Save example configuration",
        initialfile="config.json",
        defaultextension=".json",
        filetypes=(("JSON configuration", "*.json"), ("All files", "*.*")),
    )


def handle_save_example_config(window):
    target = select_example_config_path(window)
    if not target:
        return

    try:
        target_path = save_example_config(target)
    except (OSError, ValueError) as exc:
        window["-STATUS-"].update(value="Could not save the example config.")
        sg.popup_error("Could not save example configuration", str(exc))
        return

    window["-CONFIG_PATH-"].update(value=str(target_path))
    window["-STATUS-"].update(value="Example config saved; edit it before flashing.")
    update_action_states(
        window,
        {"-CONFIG-": True, "-CONFIG_PATH-": str(target_path)},
        update_status=False,
    )


def handle_flash(window, values):
    window["-FLASH-"].update(disabled=True)
    window["-STATUS-"].update(value="Flashing...")
    window.refresh()

    try:
        firmware_path = validate_firmware(first_firmware_file())
        config_path = config_path_for_mode(values)
        flash_board(
            firmware_path,
            config_path,
            randomize_hostname=(
                values.get("-CONFIG-", False)
                and values.get("-RANDOMIZE_HOSTNAME-", False)
            ),
        )
    except Exception as exc:
        window["-STATUS-"].update(value="Flash failed; see the error dialog.")
        sg.popup_error("Could not flash firmware", str(exc))
    else:
        window["-STATUS-"].update(value="Flash complete.")
        sg.popup("Firmware and project files flashed.")
    finally:
        update_action_states(window, values, update_status=False)


def update_action_states(window, values, update_status=True):
    values = values or {}
    config_mode = values.get("-CONFIG-", False)

    window["-CONFIG_PATH-"].update(disabled=not config_mode)
    window["-CONFIG_BROWSE-"].update(disabled=not config_mode)
    window["-SAVE_EXAMPLE-"].update(disabled=not config_mode)
    window["-RANDOMIZE_HOSTNAME-"].update(disabled=not config_mode)

    errors = collect_basic_errors(values)
    window["-FLASH-"].update(disabled=bool(errors))

    if update_status:
        status = "Select a config.json file to continue." if errors else "Ready"
        window["-STATUS-"].update(value=status)


def collect_basic_errors(values):
    errors = []

    if values.get("-CONFIG-"):
        try:
            validate_config_file(values.get("-CONFIG_PATH-", ""))
        except ValueError as exc:
            errors.append(str(exc))

    return errors


def save_example_config(path):
    target_path = Path(path).expanduser()
    if target_path.suffix.lower() != ".json":
        raise ValueError("Example configuration must end in .json.")

    target_path.write_bytes(CONFIG_EXAMPLE_PATH.read_bytes())
    return target_path


def config_path_for_mode(values):
    if values.get("-CONFIG-"):
        return validate_config_file(values.get("-CONFIG_PATH-", ""))

    return None


def validate_config_file(path):
    config_path = Path(path).expanduser()
    if not config_path.is_file():
        raise ValueError("Choose a config.json file.")
    if config_path.suffix.lower() != ".json":
        raise ValueError("Configuration file must end in .json.")

    try:
        with config_path.open() as config_file:
            config = json.load(config_file)
    except (OSError, ValueError):
        raise ValueError("Configuration file must contain valid JSON.")

    if not isinstance(config, dict):
        raise ValueError("Configuration file must contain a JSON object.")

    return config_path


def flash_board(firmware_path, config_path, randomize_hostname=False):
    firmware_path = validate_firmware(firmware_path)
    if config_path is not None:
        config_path = validate_config_file(config_path)
    if randomize_hostname and config_path is None:
        raise ValueError("Hostname randomization requires a config.json file.")

    temporary_config_path = None
    if randomize_hostname:
        temporary_config_path = create_randomized_config(config_path)
        config_path = temporary_config_path

    try:
        flash_firmware(firmware_path)
        time.sleep(FIRMWARE_RESTART_DELAY_SECONDS)
        push_micro_files(config_path, clean=True)
    finally:
        if temporary_config_path is not None:
            temporary_config_path.unlink(missing_ok=True)


def create_randomized_config(config_path):
    config_path = validate_config_file(config_path)
    try:
        with config_path.open() as config_file:
            config = json.load(config_file)
    except (OSError, ValueError):
        raise ValueError("Configuration file must contain valid JSON.")

    wifi_config = config.get("wifi")
    hostname = wifi_config.get("hostname") if isinstance(wifi_config, dict) else None
    if not isinstance(hostname, str) or not hostname:
        raise ValueError("Configuration file must contain a Wi-Fi hostname to randomize.")

    wifi_config["hostname"] = randomized_hostname(hostname)

    temporary_file = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".json",
        prefix="bambutton-",
        delete=False,
    )
    temporary_path = Path(temporary_file.name)
    try:
        json.dump(config, temporary_file, indent=2)
        temporary_file.write("\n")
    except Exception:
        temporary_file.close()
        temporary_path.unlink(missing_ok=True)
        raise
    temporary_file.close()
    return temporary_path


def randomized_hostname(hostname):
    result = "{}-{}".format(hostname, random_hostname_suffix())
    if len(result) > MAX_HOSTNAME_LENGTH:
        max_source_length = MAX_HOSTNAME_LENGTH - HOSTNAME_SUFFIX_LENGTH - 1
        raise ValueError(
            "Hostname must be {} characters or fewer when randomization is enabled.".format(
                max_source_length
            )
        )
    return result


def random_hostname_suffix():
    return "".join(
        secrets.choice(HOSTNAME_SUFFIX_ALPHABET)
        for _ in range(HOSTNAME_SUFFIX_LENGTH)
    )


def flash_firmware(firmware_path):
    run_esptool(esptool_args("erase_flash"))
    run_esptool(esptool_args("write_flash", "-z", "0x0", str(firmware_path)))


def push_micro_files(config_path, clean=False):
    if config_path is not None:
        config_path = validate_config_file(config_path)

    if clean:
        run_mpremote(mpremote_args("exec", CLEAN_BOARD_CODE))

    files = sorted(MICRO_DIR.glob("*.py"))
    run_mpremote(mpremote_args("exec", BOOTSTRAP_PREPARE_CODE))
    for path in files:
        run_mpremote(mpremote_args(
            "cp",
            str(path),
            ":" + BOOTSTRAP_DIR + "/" + path.name,
        ))

    if config_path is not None:
        run_mpremote(mpremote_args(
            "cp",
            str(config_path),
            ":" + BOOTSTRAP_DIR + "/config.json",
        ))

    run_mpremote(mpremote_args("exec", BOOTSTRAP_COMMIT_CODE))
    run_mpremote(mpremote_args("reset"))


def mpremote_args(*args):
    return list(args)


def esptool_args(*args):
    return ["--chip", "esp32c3"] + list(args)


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
    if not firmware_path.is_file():
        raise ValueError("Choose a firmware .bin file.")
    if firmware_path.suffix.lower() != ".bin":
        raise ValueError("Firmware file must end in .bin.")
    return firmware_path


def first_firmware_file():
    firmware_files = sorted(DEFAULT_FIRMWARE_DIR.glob("*.bin"))
    if firmware_files:
        return firmware_files[0]

    return ""


if __name__ == "__main__":
    main()
