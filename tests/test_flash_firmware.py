import runpy
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from esptool.bin_image import LoadFirmwareImage
import pytest
from serial.tools import list_ports

from scripts import flash_firmware


BUNDLED_FIRMWARE = (
    Path(__file__).parents[1] / "firmware" / "ESP32_GENERIC_C3-20260406-v1.28.0.bin"
)


@pytest.fixture
def firmware(tmp_path):
    path = tmp_path / "firmware with spaces.bin"
    path.write_bytes(BUNDLED_FIRMWARE.read_bytes())
    return path


@pytest.fixture
def calls(monkeypatch):
    commands = []
    monkeypatch.setattr(
        flash_firmware.subprocess, "run",
        lambda command, check: commands.append((command, check)),
    )
    monkeypatch.setattr(list_ports, "comports", lambda: [SimpleNamespace(device="/dev/test")])
    return commands


def invoke(monkeypatch, firmware, *options):
    monkeypatch.setattr(sys, "argv", ["flash_firmware.py", str(firmware), *options])
    flash_firmware.main()


@pytest.mark.parametrize("device", [None, "/dev/tty.example", "COM4"])
def test_clean_flash_validates_image_and_erases_and_writes_in_one_connection(
    firmware, calls, monkeypatch, capsys, device
):
    options = ["--clean"]
    if device:
        options.extend(["--device", device])

        def unexpected_scan():
            pytest.fail("An explicit port must not trigger automatic selection")

        monkeypatch.setattr(list_ports, "comports", unexpected_scan)

    invoke(monkeypatch, firmware, *options)

    selected_port = device or "/dev/test"
    prefix = [sys.executable, "-m", "esptool", "--chip", "esp32c3", "--port", selected_port]
    assert calls == [
        (prefix + ["write-flash", "--erase-all", "-z", "0x0", str(firmware)], True),
    ]
    output = capsys.readouterr().out
    assert "all settings will be erased" in output
    assert "Firmware flashed successfully" in output
    assert "push_micro.py --clean" in output


def test_clean_flag_required_before_validation_or_contacting_board(firmware, calls, monkeypatch, capsys):
    monkeypatch.setattr(
        flash_firmware, "validate_firmware",
        lambda path: pytest.fail("--clean must be checked first"),
    )
    with pytest.raises(SystemExit) as exc:
        invoke(monkeypatch, firmware)

    assert exc.value.code == 2
    assert calls == []
    assert "back up config.json" in capsys.readouterr().err


@pytest.mark.parametrize(
    "problem, message",
    [
        ("missing", "existing ESP32-C3 firmware .bin"),
        ("directory", "existing ESP32-C3 firmware .bin"),
        ("extension", "existing ESP32-C3 firmware .bin"),
        ("empty", "Could not read firmware image"),
        ("truncated", "Could not read firmware image"),
        ("magic", "Could not read firmware image"),
        ("chip", "not for an ESP32-C3"),
        ("checksum", "checksum is invalid"),
        ("digest", "validation hash is invalid"),
    ],
)
def test_invalid_firmware_fails_before_contacting_board(
    firmware, calls, monkeypatch, capsys, problem, message
):
    raw = bytearray(firmware.read_bytes())
    if problem == "missing":
        firmware.unlink()
    elif problem == "directory":
        firmware.unlink()
        firmware.mkdir()
    elif problem == "extension":
        firmware = firmware.rename(firmware.with_suffix(".json"))
    else:
        if problem == "empty":
            raw = b""
        elif problem == "truncated":
            raw = raw[:10]
        elif problem == "magic":
            raw[0] = 0
        elif problem == "chip":
            raw[12:14] = b"\x00\x00"
        elif problem == "checksum":
            raw[32] ^= 1
        elif problem == "digest":
            image = LoadFirmwareImage("esp32c3", str(firmware))
            raw[image.data_length] ^= 1
        firmware.write_bytes(raw)

    monkeypatch.setattr(
        list_ports, "comports", lambda: pytest.fail("Invalid firmware must not contact the board"),
    )
    with pytest.raises(SystemExit) as exc:
        invoke(monkeypatch, firmware, "--clean")

    assert exc.value.code == 2
    assert calls == []
    assert message in capsys.readouterr().err


def test_unreadable_image_fails_before_erase(firmware, calls, monkeypatch, capsys):
    def unreadable(*args):
        raise PermissionError("image is not readable")

    monkeypatch.setattr("esptool.bin_image.get_bytes", unreadable)
    with pytest.raises(SystemExit) as exc:
        invoke(monkeypatch, firmware, "--clean")

    assert exc.value.code == 2
    assert calls == []
    assert "image is not readable" in capsys.readouterr().err


@pytest.mark.parametrize("ports", [[], ["COM3", "COM4"]])
def test_automatic_selection_requires_exactly_one_port(firmware, calls, monkeypatch, capsys, ports):
    monkeypatch.setattr(list_ports, "comports", lambda: [SimpleNamespace(device=p) for p in ports])
    with pytest.raises(SystemExit) as exc:
        invoke(monkeypatch, firmware, "--clean")

    assert exc.value.code == 2
    assert calls == []
    assert "--device" in capsys.readouterr().err


def test_empty_explicit_device_rejected(firmware, calls, monkeypatch, capsys):
    with pytest.raises(SystemExit) as exc:
        invoke(monkeypatch, firmware, "--clean", "--device", " ")

    assert exc.value.code == 2
    assert calls == []
    assert "--device must name a serial port" in capsys.readouterr().err


@pytest.mark.parametrize("failure", [OSError("serial port unavailable"), subprocess.CalledProcessError(2, "esptool")])
def test_failed_flash_stops_without_reporting_success(
    firmware, monkeypatch, capsys, failure
):
    commands = []

    def fail(command, check):
        commands.append(command)
        raise failure

    monkeypatch.setattr(flash_firmware.subprocess, "run", fail)
    with pytest.raises(SystemExit) as exc:
        invoke(monkeypatch, firmware, "--clean", "--device", "COM4")

    assert exc.value.code == 1
    assert len(commands) == 1
    output = capsys.readouterr()
    assert "Firmware re-flash failed" in output.err
    assert "successfully" not in output.out


def test_interrupted_flash_reports_recovery(firmware, monkeypatch, capsys):
    def interrupt(command, check):
        raise KeyboardInterrupt

    monkeypatch.setattr(flash_firmware.subprocess, "run", interrupt)
    with pytest.raises(SystemExit) as exc:
        invoke(monkeypatch, firmware, "--clean", "--device", "COM4")

    assert exc.value.code == 130
    assert "re-run the clean flash to recover" in capsys.readouterr().err


def test_missing_dependency_reports_install_command(firmware, calls, monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "esptool.bin_image", None)
    with pytest.raises(SystemExit) as exc:
        invoke(monkeypatch, firmware, "--clean")

    assert exc.value.code == 1
    assert calls == []
    assert "pip install -r requirements.txt" in capsys.readouterr().err


def test_relative_path_is_resolved_from_working_directory(firmware, monkeypatch):
    monkeypatch.chdir(firmware.parent)
    assert flash_firmware.validate_firmware(firmware.name) == firmware


def test_script_entrypoint_can_show_help_without_flashing(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["flash_firmware.py", "--help"])
    with pytest.raises(SystemExit) as exc:
        runpy.run_path(str(Path(flash_firmware.__file__)), run_name="__main__")

    assert exc.value.code == 0
    assert "--clean" in capsys.readouterr().out
