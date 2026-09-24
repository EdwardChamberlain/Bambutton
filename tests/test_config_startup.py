import copy
import sys
from pathlib import Path
from types import SimpleNamespace

from micro import config_loader


APP_MAIN = Path(__file__).parents[1] / "micro" / "app_main.py"


class StopMainLoop(BaseException):
    pass


def test_incomplete_config_starts_setup_ap_without_printer_api_requests(monkeypatch):
    config = copy.deepcopy(config_loader.DEFAULT_CONFIG)
    api_calls = []

    class FakeNetwork:
        def __init__(self):
            self.ap_starts = 0
            self.ap_mode = False

        def connect_with_fallback(self, watchdog_feed=None):
            raise AssertionError("incomplete settings must not connect to Wi-Fi")

        def start_access_point(self):
            self.ap_starts += 1
            self.ap_mode = True

        def is_ap_mode(self):
            return self.ap_mode

        def is_connected(self):
            return False

        def ifconfig(self):
            return ("192.168.4.1", "255.255.255.0", "192.168.4.1", "192.168.4.1")

        def mode(self):
            return "access point"

    class FakeAPI:
        def clear_plate(self, printer_id):
            api_calls.append(("clear", printer_id))

        def get_printer_status(self, printer_id):
            api_calls.append(("status", printer_id))

    class FakeButton:
        def __init__(self, **kwargs):
            pass

        def start(self):
            pass

    class FakeFlasher:
        def __init__(self, **kwargs):
            pass

        def start(self):
            pass

        def on(self):
            pass

    class FakeWDT:
        def __init__(self, timeout):
            pass

        def feed(self):
            pass

    class FakeOTA:
        def __init__(self, reset=None):
            pass

        def status(self):
            return {"current_version": "test"}

        def confirm_boot(self):
            return True

    class FakeWebServer:
        def __init__(self, **kwargs):
            pass

        def poll(self):
            return False

    network = FakeNetwork()
    modules = {
        "machine": SimpleNamespace(WDT=FakeWDT, reset=lambda: None),
        "time": SimpleNamespace(
            ticks_ms=lambda: 0,
            ticks_diff=lambda left, right: left - right,
            ticks_add=lambda value, delta: value + delta,
            sleep_ms=lambda delay: (_ for _ in ()).throw(StopMainLoop()),
        ),
        "bambuddy_api": SimpleNamespace(BambuddyAPI=lambda *args: FakeAPI()),
        "config_loader": SimpleNamespace(
            load_config=lambda: config,
            is_runtime_config_ready=config_loader.is_runtime_config_ready,
        ),
        "gpio_button": SimpleNamespace(GPIOButton=FakeButton),
        "led_flasher": SimpleNamespace(LedFlasher=FakeFlasher),
        "ota_manager": SimpleNamespace(OTAUpdateManager=FakeOTA),
        "wifi": SimpleNamespace(
            WiFi=lambda **kwargs: network,
            DEFAULT_HOSTNAME="bambutton",
            DEFAULT_AP_PASSWORD="bambutton",
            AP_RETRY_INTERVAL_SECONDS=30,
        ),
        "periodic_timer": SimpleNamespace(
            PeriodicTimer=lambda **kwargs: SimpleNamespace(start=lambda: None)
        ),
        "web_config": SimpleNamespace(WebConfigServer=FakeWebServer),
    }
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)

    namespace = {"__name__": "app_main_config_gate_test"}
    try:
        exec(compile(APP_MAIN.read_text(), str(APP_MAIN), "exec"), namespace)
    except StopMainLoop:
        pass

    assert network.ap_starts == 1
    assert network.is_ap_mode() is True
    assert api_calls == []
