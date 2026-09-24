import sys
from pathlib import Path
from types import SimpleNamespace


APP_MAIN = Path(__file__).parents[1] / "micro" / "app_main.py"


class StopMainLoop(BaseException):
    pass


class FakeAPI:
    def __init__(self):
        self.clears = 0
        self.status = {"awaiting_plate_clear": False, "chamber_light": False}

    def clear_plate(self, printer_id):
        self.clears += 1

    def clear_plate_with_reconciliation(self, printer_id):
        self.clears += 1
        return {"resolved": True, "status": None, "request_error": None}

    def get_printer_status(self, printer_id):
        return self.status


def load_app_main(monkeypatch, api):
    button_handlers = []
    clock = {"ticks": 100}

    class FakeNetwork:
        ap_mode = True

        def connect_with_fallback(self, watchdog_feed=None):
            return self

        def is_ap_mode(self):
            return self.ap_mode

        def is_connected(self):
            return not self.ap_mode

        def ensure_connected(self, watchdog_feed=None, fallback_to_ap=False):
            return self

        def ifconfig(self):
            return ("192.168.4.1", "255.255.255.0", "192.168.4.1", "192.168.4.1")

        def mode(self):
            return "access point" if self.ap_mode else "station"

    network = FakeNetwork()
    config = {
        "wifi": {"ssid": "shop", "password": "password", "hostname": "button",
                 "timeout_seconds": 1},
        "api": {"key": "key", "base_url": "http://bambuddy/api/v1",
                "request_timeout_seconds": 1},
        "printer": {"id": 7, "poll_interval_seconds": 5},
        "led": {"pin": 3, "flash_interval_ms": 250},
        "button": {"pin": 4, "debounce_ms": 100, "pull": "down",
                   "trigger": "rising"},
    }

    class FakeButton:
        def __init__(self, on_press, **kwargs):
            button_handlers.append(on_press)

        def start(self):
            return None

    class FakeFlasher:
        def __init__(self, **kwargs):
            pass

        def start(self):
            return None

        def on(self):
            return None

    class FakeWDT:
        def __init__(self, timeout):
            self.timeout = timeout

        def feed(self):
            return None

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

    modules = {
        "machine": SimpleNamespace(WDT=FakeWDT, reset=lambda: None),
        "time": SimpleNamespace(
            ticks_ms=lambda: clock["ticks"],
            ticks_diff=lambda left, right: left - right,
            ticks_add=lambda value, delta: value + delta,
            sleep_ms=lambda delay: (_ for _ in ()).throw(StopMainLoop()),
        ),
        "bambuddy_api": SimpleNamespace(BambuddyAPI=lambda *args: api),
        "config_loader": SimpleNamespace(
            load_config=lambda: config,
            is_runtime_config_ready=lambda loaded: True,
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

    namespace = {"__name__": "app_main_coverage_test"}
    try:
        exec(compile(APP_MAIN.read_text(), str(APP_MAIN), "exec"), namespace)
    except StopMainLoop:
        pass
    return namespace, network, button_handlers[0]


def test_press_interrupt_queues_a_single_pending_request(monkeypatch):
    namespace, _, press = load_app_main(monkeypatch, FakeAPI())
    namespace["PRINTER_AWAITING_PLATE_CLEAR"] = True

    press(None)
    press(None)

    assert namespace["PENDING_BUTTON_PRESS"] is True
    assert namespace["PRINTER_AWAITING_PLATE_CLEAR"] is False


def test_pending_request_sends_clear_and_updates_poll_state(monkeypatch):
    api = FakeAPI()
    namespace, network, press = load_app_main(monkeypatch, api)
    namespace["PRINTER_AWAITING_PLATE_CLEAR"] = True
    press(None)
    network.ap_mode = False

    namespace["handle_pending_button_press"]()

    assert api.clears == 1
    assert namespace["PENDING_BUTTON_PRESS"] is False
    assert namespace["PRINTER_STATUS_UPDATE_REQUIRED"] is True


def test_printer_status_updates_led_and_debug_information(monkeypatch):
    api = FakeAPI()
    api.status = {"awaiting_plate_clear": True, "chamber_light": True}
    namespace, network, _ = load_app_main(monkeypatch, api)
    network.ap_mode = False

    namespace["handle_printer_status_update"]()
    status = namespace["debug_status"]()

    assert namespace["should_flash_plate_clear"]() is True
    assert status["Network mode"] == "station"
    assert status["Awaiting plate clear"] is True
    assert status["Chamber light on"] is True
    assert status["Application version"] == "test"
    assert namespace["PRINTER_STATUS_UPDATE_REQUIRED"] is False
