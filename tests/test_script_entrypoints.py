import runpy
import sys
from pathlib import Path

from bambutton import gui
from scripts import build_gui, run_main


def test_build_gui_main_invokes_pyinstaller_with_bundled_resources(
    tmp_path, monkeypatch
):
    entrypoint = tmp_path / "src" / "bambutton" / "gui.py"
    entrypoint.parent.mkdir(parents=True)
    entrypoint.write_text("# setup GUI")
    micro_dir = tmp_path / "micro"
    micro_dir.mkdir()
    firmware_dir = tmp_path / "firmware"
    firmware_dir.mkdir()
    calls = []

    monkeypatch.setattr(build_gui, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(build_gui, "ENTRYPOINT", entrypoint)
    monkeypatch.setattr(build_gui, "MICRO_DIR", micro_dir)
    monkeypatch.setattr(build_gui, "FIRMWARE_DIR", firmware_dir)
    monkeypatch.setattr(build_gui.subprocess, "run", lambda *args, **kwargs: calls.append(args))

    build_gui.main()

    command = calls[0][0]
    assert command[:3] == [sys.executable, "-m", "PyInstaller"]
    assert "--windowed" in command
    assert str(entrypoint) == command[-1]
    assert any("bambutton/micro" in item for item in command)
    assert any("bambutton/firmware" in item for item in command)


def test_run_main_passes_selected_device_to_mpremote(tmp_path, monkeypatch):
    main_file = tmp_path / "main.py"
    main_file.write_text("# entrypoint")
    calls = []
    monkeypatch.setattr(run_main, "MAIN_FILE", main_file)
    monkeypatch.setattr(run_main.subprocess, "run", lambda command, check: calls.append(command))
    monkeypatch.setattr(sys, "argv", ["run_main.py", "--device", "/dev/test"])

    run_main.main()

    assert calls == [["mpremote", "connect", "/dev/test", "run", str(main_file)]]


def test_run_main_reports_missing_entrypoint(tmp_path, monkeypatch):
    monkeypatch.setattr(run_main, "MAIN_FILE", tmp_path / "missing.py")
    monkeypatch.setattr(sys, "argv", ["run_main.py"])

    try:
        run_main.main()
    except SystemExit as exc:
        assert "main.py not found" in str(exc)
    else:
        raise AssertionError("Missing entrypoint should stop the command")


def test_package_entrypoint_calls_gui_main(monkeypatch):
    calls = []
    monkeypatch.setattr(gui, "main", lambda: calls.append("package"))

    runpy.run_module("bambutton", run_name="__main__")

    assert calls == ["package"]


def test_legacy_config_gui_entrypoint_calls_gui_main(monkeypatch):
    calls = []
    monkeypatch.setattr(gui, "main", lambda: calls.append("legacy"))
    shim = Path(__file__).parents[1] / "src" / "bambutton_config_gui.py"

    runpy.run_path(str(shim), run_name="__main__")

    assert calls == ["legacy"]
