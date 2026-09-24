import runpy
from pathlib import Path


BOOT_PATH = Path(__file__).parents[1] / "micro" / "boot.py"


def test_boot_recovery_moves_old_main_and_installs_staged_loader(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    marker = Path(".bambutton/bootstrap-install.marker")
    marker.parent.mkdir(parents=True)
    marker.write_text("bambutton-bootstrap-v1\n")
    staged_main = Path(".bambutton/bootstrap/main.py")
    staged_main.parent.mkdir(parents=True)
    staged_main.write_text("new loader")
    Path("main.py").write_text("old application")

    runpy.run_path(str(BOOT_PATH))

    assert Path("main.py").read_text() == "new loader"
    assert Path(".bambutton/legacy_main.py").read_text() == "old application"


def test_boot_recovery_restores_legacy_main_if_staging_was_lost(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    marker = Path(".bambutton/bootstrap-install.marker")
    marker.parent.mkdir(parents=True)
    marker.write_text("bambutton-bootstrap-v1\n")
    legacy_main = Path(".bambutton/legacy_main.py")
    legacy_main.write_text("old application")

    runpy.run_path(str(BOOT_PATH))

    assert Path("main.py").read_text() == "old application"


def test_boot_ignores_unknown_install_marker(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    marker = Path(".bambutton/bootstrap-install.marker")
    marker.parent.mkdir(parents=True)
    marker.write_text("unrecognized marker")
    Path("main.py").write_text("current application")

    runpy.run_path(str(BOOT_PATH))

    assert Path("main.py").read_text() == "current application"
