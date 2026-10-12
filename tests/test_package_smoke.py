import runpy
import sys
from email.message import Message
from pathlib import PurePosixPath
from pathlib import Path
from types import SimpleNamespace

import pytest


SMOKE_PATH = Path(__file__).parents[1] / "scripts" / "smoke_installed_package.py"
REQUIRED_FILES = (
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
    "micro/app_main.py",
    "micro/boot.py",
    "micro/config_example.json",
    "micro/ota_manager.py",
    "micro/web_config.py",
    "firmware/ESP32_GENERIC_C3-20260406-v1.28.0.bin",
)


def fake_distribution():
    package_metadata = Message()
    package_metadata["License-Expression"] = "MIT"
    package_metadata["License-File"] = "LICENSE"
    for name in (
        "Homepage",
        "Repository",
        "Documentation",
        "Issues",
        "Support",
        "Changelog",
    ):
        package_metadata["Project-URL"] = (
            "{}, https://github.com/EdwardChamberlain/Bambutton".format(name)
        )
    return SimpleNamespace(
        metadata=package_metadata,
        files=[PurePosixPath("bambutton-1.0.dist-info/licenses/LICENSE")],
    )


def fake_package(tmp_path, include_all=True):
    package_root = tmp_path / "site-packages" / "bambutton"
    for filename in REQUIRED_FILES if include_all else REQUIRED_FILES[:-1]:
        path = package_root / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("resource")
    return SimpleNamespace(__file__=str(package_root / "__init__.py"))


def test_installed_package_smoke_finds_wheel_resources(tmp_path, monkeypatch):
    package = fake_package(tmp_path)
    monkeypatch.setitem(sys.modules, "bambutton", package)
    module = runpy.run_path(str(SMOKE_PATH), run_name="installed_package_smoke")
    monkeypatch.setattr(module["metadata"], "distribution", lambda name: fake_distribution())

    assert module["check_installed_package"]() == Path(package.__file__).parent


def test_installed_package_smoke_rejects_missing_resource(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "bambutton", fake_package(tmp_path, False))
    module = runpy.run_path(str(SMOKE_PATH), run_name="installed_package_smoke")
    monkeypatch.setattr(module["metadata"], "distribution", lambda name: fake_distribution())

    with pytest.raises(RuntimeError, match="Installed package is missing"):
        module["check_installed_package"]()


def test_smoke_script_entrypoint_prints_success(tmp_path, monkeypatch, capsys):
    package = fake_package(tmp_path)
    monkeypatch.setitem(sys.modules, "bambutton", package)
    module = runpy.run_path(str(SMOKE_PATH), run_name="installed_package_smoke")
    monkeypatch.setattr(module["metadata"], "distribution", lambda name: fake_distribution())

    runpy.run_path(str(SMOKE_PATH), run_name="__main__")

    assert "Installed Bambutton package is ready" in capsys.readouterr().out
