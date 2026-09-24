import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


GPIO_BUTTON_PATH = Path(__file__).parents[1] / "micro" / "gpio_button.py"


def load_gpio_button(monkeypatch, clock):
    class FakePin:
        IN = "in"
        PULL_DOWN = "down"
        PULL_UP = "up"
        IRQ_FALLING = 1
        IRQ_RISING = 2
        instances = []

        def __init__(self, *args):
            self.args = args
            self.handler = None
            self.trigger = None
            self.instances.append(self)

        def irq(self, trigger=None, handler=None):
            self.trigger = trigger
            self.handler = handler

    monkeypatch.setitem(sys.modules, "machine", SimpleNamespace(Pin=FakePin))
    monkeypatch.setitem(
        sys.modules,
        "time",
        SimpleNamespace(
            ticks_ms=lambda: clock[0],
            ticks_diff=lambda current, previous: current - previous,
        ),
    )
    spec = importlib.util.spec_from_file_location("test_gpio_button", GPIO_BUTTON_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, FakePin


def test_button_uses_configured_pull_trigger_and_debounce(monkeypatch):
    clock = [100]
    module, pin_type = load_gpio_button(monkeypatch, clock)
    presses = []
    button = module.GPIOButton(
        4, presses.append, debounce_ms=100, pull="up", trigger="both"
    )

    button.start()
    button.pin.handler(button.pin)
    clock[0] = 150
    button.pin.handler(button.pin)
    clock[0] = 200
    button.pin.handler(button.pin)

    assert button.pin.args == (4, pin_type.IN, pin_type.PULL_UP)
    assert button.pin.trigger == pin_type.IRQ_FALLING | pin_type.IRQ_RISING
    assert presses == [button.pin, button.pin]

    button.stop()
    assert button.pin.handler is None


def test_button_can_disable_internal_pull(monkeypatch):
    module, _ = load_gpio_button(monkeypatch, [100])

    button = module.GPIOButton(4, lambda pin: None, pull="none")

    assert button.pin.args == (4, module.Pin.IN)


@pytest.mark.parametrize(
    "field,value",
    [("pull", "sideways"), ("trigger", "invalid")],
)
def test_button_rejects_unknown_pull_or_trigger(monkeypatch, field, value):
    module, _ = load_gpio_button(monkeypatch, [100])
    kwargs = {field: value}

    with pytest.raises(ValueError, match="Unsupported button"):
        module.GPIOButton(4, lambda pin: None, **kwargs)
