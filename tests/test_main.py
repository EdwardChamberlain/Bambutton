import runpy
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


MAIN_PATH = Path(__file__).parents[1] / "micro" / "main.py"


def test_stable_main_entrypoint_launches_ota_manager(monkeypatch):
    events = []

    class Manager:
        def __init__(self, reset):
            events.append(("manager", reset))

        def launch(self):
            events.append(("launch",))

    def reset():
        events.append(("reset",))

    monkeypatch.setitem(sys.modules, "machine", SimpleNamespace(reset=reset))
    monkeypatch.setitem(
        sys.modules,
        "ota_manager",
        SimpleNamespace(OTAUpdateManager=Manager, OTAError=RuntimeError),
    )

    runpy.run_path(str(MAIN_PATH))

    assert events == [("manager", reset), ("launch",)]


def test_stable_main_logs_and_reraises_boot_failure(monkeypatch, capsys):
    class OTAError(Exception):
        pass

    class Manager:
        def __init__(self, reset):
            pass

        def launch(self):
            raise OTAError("rollback requested")

    monkeypatch.setitem(sys.modules, "machine", SimpleNamespace(reset=lambda: None))
    monkeypatch.setitem(
        sys.modules,
        "ota_manager",
        SimpleNamespace(OTAUpdateManager=Manager, OTAError=OTAError),
    )

    with pytest.raises(OTAError, match="rollback"):
        runpy.run_path(str(MAIN_PATH))

    assert "Bambutton boot error: rollback requested" in capsys.readouterr().out
