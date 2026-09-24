import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


TIMER_PATH = Path(__file__).parents[1] / "micro" / "periodic_timer.py"


def load_periodic_timer(monkeypatch):
    class FakeTimer:
        PERIODIC = "periodic"
        instances = []

        def __init__(self, timer_id):
            self.timer_id = timer_id
            self.init_args = None
            self.deinit_count = 0
            self.instances.append(self)

        def init(self, **kwargs):
            self.init_args = kwargs

        def deinit(self):
            self.deinit_count += 1

    monkeypatch.setitem(sys.modules, "machine", SimpleNamespace(Timer=FakeTimer))
    spec = importlib.util.spec_from_file_location("test_periodic_timer", TIMER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, FakeTimer


def test_periodic_timer_starts_once_stops_and_releases_id(monkeypatch):
    module, fake_timer = load_periodic_timer(monkeypatch)
    ticks = []
    timer = module.PeriodicTimer(500, lambda: ticks.append("tick"))

    timer.start()
    timer.start()
    assert timer.timer.init_args == {
        "period": 500,
        "mode": fake_timer.PERIODIC,
        "callback": timer._tick,
    }
    timer.timer.init_args["callback"](timer.timer)
    assert ticks == ["tick"]

    timer.stop()
    timer.stop()
    assert timer.timer.deinit_count == 1
    timer.close()
    assert timer.running is False
    assert module.PeriodicTimer._available_timer_ids == [0, 1, 2, 3]


def test_periodic_timer_rejects_exhausted_timer_ids(monkeypatch):
    module, _ = load_periodic_timer(monkeypatch)
    timers = [module.PeriodicTimer(100, lambda: None) for _ in range(4)]

    with pytest.raises(RuntimeError, match="No available timer ids"):
        module.PeriodicTimer(100, lambda: None)

    for timer in timers:
        timer.close()
