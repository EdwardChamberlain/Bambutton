import json
import re
import sys

import pytest

from bambutton import gui
from bambutton.gui import run_python_entrypoint


def test_random_hostname_suffix_is_four_uppercase_alphanumeric_characters():
    assert re.fullmatch(r"[A-Z0-9]{4}", gui.random_hostname_suffix())


def test_run_python_entrypoint_exposes_utf8_stream_encoding():
    def entrypoint():
        sys.stdout.write(b"ok".decode(sys.stdout.encoding))
        sys.stderr.write(b"warn".decode(sys.stderr.encoding))

    result = run_python_entrypoint("tool", entrypoint, [])

    assert result.stdout == "ok"
    assert result.stderr == "warn"


def test_web_setup_uses_firmware_defaults_without_a_saved_config():
    assert gui.config_path_for_mode({"-WEB-": True}) is None


def test_web_setup_does_not_require_serial_port():
    assert gui.collect_basic_errors({"-WEB-": True}) == []


def test_config_setup_requires_a_config_file_before_flashing():
    assert gui.collect_basic_errors({"-CONFIG-": True}) == ["Choose a config.json file."]


def test_update_action_states_disables_config_controls_in_web_mode(tmp_path):
    class Element:
        def __init__(self):
            self.updates = []

        def update(self, **kwargs):
            self.updates.append(kwargs)

    class Window:
        def __init__(self):
            self.elements = {
                key: Element()
                for key in (
                    "-CONFIG_PATH-",
                    "-CONFIG_BROWSE-",
                    "-SAVE_EXAMPLE-",
                    "-RANDOMIZE_HOSTNAME-",
                    "-FLASH-",
                    "-STATUS-",
                )
            }

        def __getitem__(self, key):
            return self.elements[key]

    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"wifi": {}}))
    window = Window()

    gui.update_action_states(window, {"-WEB-": True})
    assert window.elements["-CONFIG_PATH-"].updates[-1] == {"disabled": True}
    assert window.elements["-CONFIG_BROWSE-"].updates[-1] == {"disabled": True}
    assert window.elements["-SAVE_EXAMPLE-"].updates[-1] == {"disabled": True}
    assert window.elements["-RANDOMIZE_HOSTNAME-"].updates[-1] == {"disabled": True}
    assert window.elements["-FLASH-"].updates[-1] == {"disabled": False}
    assert window.elements["-STATUS-"].updates[-1] == {"value": "Ready"}

    gui.update_action_states(
        window,
        {"-CONFIG-": True, "-CONFIG_PATH-": str(config_path)},
    )
    assert window.elements["-CONFIG_PATH-"].updates[-1] == {"disabled": False}
    assert window.elements["-CONFIG_BROWSE-"].updates[-1] == {"disabled": False}
    assert window.elements["-SAVE_EXAMPLE-"].updates[-1] == {"disabled": False}
    assert window.elements["-RANDOMIZE_HOSTNAME-"].updates[-1] == {"disabled": False}
    assert window.elements["-FLASH-"].updates[-1] == {"disabled": False}
    assert window.elements["-STATUS-"].updates[-1] == {"value": "Ready"}


def test_update_action_states_prompts_for_config_file():
    class Element:
        def __init__(self):
            self.updates = []

        def update(self, **kwargs):
            self.updates.append(kwargs)

    class Window:
        def __init__(self):
            self.elements = {
                key: Element()
                for key in (
                    "-CONFIG_PATH-",
                    "-CONFIG_BROWSE-",
                    "-SAVE_EXAMPLE-",
                    "-RANDOMIZE_HOSTNAME-",
                    "-FLASH-",
                    "-STATUS-",
                )
            }

        def __getitem__(self, key):
            return self.elements[key]

    window = Window()

    gui.update_action_states(window, {"-CONFIG-": True})

    assert window.elements["-FLASH-"].updates[-1] == {"disabled": True}
    assert window.elements["-STATUS-"].updates[-1] == {
        "value": "Select a config.json file to continue."
    }


def test_save_example_config_copies_template(tmp_path, monkeypatch):
    example_path = tmp_path / "config_example.json"
    example_path.write_text('{"wifi": {"ssid": "example"}}')
    target_path = tmp_path / "saved" / "config.json"
    target_path.parent.mkdir()

    monkeypatch.setattr(gui, "CONFIG_EXAMPLE_PATH", example_path)

    assert gui.save_example_config(target_path) == target_path
    assert target_path.read_text() == example_path.read_text()


def test_handle_save_example_config_populates_path(tmp_path, monkeypatch):
    class Element:
        def __init__(self):
            self.updates = []

        def update(self, **kwargs):
            self.updates.append(kwargs)

    class Window:
        def __init__(self):
            self.elements = {
                key: Element()
                for key in (
                    "-CONFIG_PATH-",
                    "-CONFIG_BROWSE-",
                    "-SAVE_EXAMPLE-",
                    "-RANDOMIZE_HOSTNAME-",
                    "-FLASH-",
                    "-STATUS-",
                )
            }

        def __getitem__(self, key):
            return self.elements[key]

    example_path = tmp_path / "config_example.json"
    example_path.write_text('{"wifi": {"ssid": "example"}}')
    target_path = tmp_path / "config.json"
    window = Window()

    monkeypatch.setattr(gui, "CONFIG_EXAMPLE_PATH", example_path)
    monkeypatch.setattr(gui, "select_example_config_path", lambda window: str(target_path))

    gui.handle_save_example_config(window)

    assert target_path.read_text() == example_path.read_text()
    assert {"value": str(target_path)} in window.elements["-CONFIG_PATH-"].updates
    assert window.elements["-STATUS-"].updates[-1] == {
        "value": "Example config saved; edit it before flashing."
    }
    assert window.elements["-FLASH-"].updates[-1] == {"disabled": False}


def test_handle_flash_shows_progress_before_flashing(tmp_path, monkeypatch):
    class Element:
        def __init__(self):
            self.updates = []

        def update(self, **kwargs):
            self.updates.append(kwargs)

    class Window:
        def __init__(self):
            self.elements = {
                key: Element()
                for key in (
                    "-CONFIG_PATH-",
                    "-CONFIG_BROWSE-",
                    "-SAVE_EXAMPLE-",
                    "-RANDOMIZE_HOSTNAME-",
                    "-FLASH-",
                    "-STATUS-",
                )
            }
            self.refresh_calls = 0

        def __getitem__(self, key):
            return self.elements[key]

        def refresh(self):
            self.refresh_calls += 1

    firmware_path = tmp_path / "firmware.bin"
    firmware_path.write_bytes(b"firmware")
    events = []
    window = Window()

    monkeypatch.setattr(gui, "first_firmware_file", lambda: firmware_path)
    monkeypatch.setattr(gui, "config_path_for_mode", lambda values: None)
    monkeypatch.setattr(
        gui,
        "flash_board",
        lambda firmware, config, randomize_hostname=False: events.append(
            (firmware, config, randomize_hostname)
        ),
    )
    monkeypatch.setattr(gui.sg, "popup", lambda *args: None, raising=False)

    gui.handle_flash(window, {"-WEB-": True})

    assert events == [(firmware_path, None, False)]
    assert window.refresh_calls == 1
    assert window.elements["-STATUS-"].updates == [
        {"value": "Flashing..."},
        {"value": "Flash complete."},
    ]
    assert window.elements["-FLASH-"].updates[0] == {"disabled": True}
    assert window.elements["-FLASH-"].updates[-1] == {"disabled": False}


def test_config_setup_requires_a_json_object(tmp_path):
    config_path = tmp_path / "saved-config.json"
    config_path.write_text(json.dumps({"wifi": {"ssid": "shop"}}))

    assert gui.config_path_for_mode({"-CONFIG-": True, "-CONFIG_PATH-": str(config_path)}) == config_path


@pytest.mark.parametrize(
    "contents,error",
    [
        ("not json", "valid JSON"),
        ("[]", "JSON object"),
    ],
)
def test_validate_config_file_rejects_invalid_files(tmp_path, contents, error):
    config_path = tmp_path / "config.json"
    config_path.write_text(contents)

    with pytest.raises(ValueError, match=error):
        gui.validate_config_file(config_path)


def test_push_micro_files_installs_selected_file_as_config_json(tmp_path, monkeypatch):
    micro_dir = tmp_path / "micro"
    micro_dir.mkdir()
    (micro_dir / "b_module.py").write_text("# b")
    (micro_dir / "a_module.py").write_text("# a")
    config_path = tmp_path / "saved-config.json"
    config_path.write_text(json.dumps({"wifi": {"ssid": "shop"}}))
    calls = []

    monkeypatch.setattr(gui, "MICRO_DIR", micro_dir)
    monkeypatch.setattr(gui, "run_mpremote", lambda args, capture=False: calls.append(args))

    gui.push_micro_files(config_path, clean=True)

    assert calls[0][0] == "exec"
    assert calls[1][1:] == [str(micro_dir / "a_module.py"), ":"]
    assert calls[2][1:] == [str(micro_dir / "b_module.py"), ":"]
    assert calls[3][1:] == [str(config_path), ":config.json"]
    assert calls[4] == ["reset"]


def test_push_micro_files_omits_config_for_web_gui_setup(tmp_path, monkeypatch):
    micro_dir = tmp_path / "micro"
    micro_dir.mkdir()
    (micro_dir / "main.py").write_text("# main")
    calls = []

    monkeypatch.setattr(gui, "MICRO_DIR", micro_dir)
    monkeypatch.setattr(gui, "run_mpremote", lambda args, capture=False: calls.append(args))

    gui.push_micro_files(None, clean=True)

    assert [call[0] for call in calls] == ["exec", "cp", "reset"]


def test_mpremote_args_uses_auto_detection():
    assert gui.mpremote_args("reset") == ["reset"]


def test_esptool_args_uses_auto_detection():
    assert gui.esptool_args("erase_flash") == ["--chip", "esp32c3", "erase_flash"]


def test_flash_board_flashes_firmware_before_application_files(tmp_path, monkeypatch):
    firmware_path = tmp_path / "firmware.bin"
    firmware_path.write_bytes(b"firmware")
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"wifi": {}}))
    events = []

    monkeypatch.setattr(gui, "flash_firmware", lambda path: events.append(("firmware", path)))
    monkeypatch.setattr(gui.time, "sleep", lambda seconds: events.append(("sleep", seconds)))
    monkeypatch.setattr(
        gui,
        "push_micro_files",
        lambda path, clean=False: events.append(("files", path, clean)),
    )

    gui.flash_board(firmware_path, config_path)

    assert events == [
        ("firmware", firmware_path),
        ("sleep", gui.FIRMWARE_RESTART_DELAY_SECONDS),
        ("files", config_path, True),
    ]


def test_create_randomized_config_only_changes_hostname(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    source_config = {
        "wifi": {"hostname": "shop-button", "ssid": "shop"},
        "api": {"base_url": "http://bambuddy"},
    }
    config_path.write_text(json.dumps(source_config))
    monkeypatch.setattr(gui, "random_hostname_suffix", lambda: "ABCD")

    randomized_path = gui.create_randomized_config(config_path)

    try:
        randomized_config = json.loads(randomized_path.read_text())
        assert randomized_config["wifi"]["hostname"] == "shop-button-ABCD"
        assert randomized_config["wifi"]["ssid"] == source_config["wifi"]["ssid"]
        assert randomized_config["api"] == source_config["api"]
        assert json.loads(config_path.read_text()) == source_config
    finally:
        randomized_path.unlink(missing_ok=True)


def test_flash_board_cleans_randomized_config_after_flashing(tmp_path, monkeypatch):
    firmware_path = tmp_path / "firmware.bin"
    firmware_path.write_bytes(b"firmware")
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"wifi": {"hostname": "shop-button"}}))
    flashed_config = {}

    monkeypatch.setattr(gui, "random_hostname_suffix", lambda: "ABCD")
    monkeypatch.setattr(gui, "flash_firmware", lambda path: None)
    monkeypatch.setattr(gui.time, "sleep", lambda seconds: None)

    def capture_config(path, clean=False):
        flashed_config["path"] = path
        flashed_config["contents"] = json.loads(path.read_text())

    monkeypatch.setattr(gui, "push_micro_files", capture_config)

    gui.flash_board(firmware_path, config_path, randomize_hostname=True)

    assert flashed_config["contents"]["wifi"]["hostname"] == "shop-button-ABCD"
    assert not flashed_config["path"].exists()
    assert json.loads(config_path.read_text())["wifi"]["hostname"] == "shop-button"
