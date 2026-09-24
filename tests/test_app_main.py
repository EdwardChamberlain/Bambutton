import sys
from pathlib import Path
from types import SimpleNamespace


APP_MAIN = Path(__file__).parents[1] / "micro" / "app_main.py"


class StopAppLoop(BaseException):
    pass


class FakeAPI:
    def __init__(self):
        self.clear_outcomes = []
        self.statuses = []
        self.clear_calls = 0
        self.status_calls = 0

    def clear_plate_with_reconciliation(self, printer_id):
        self.clear_calls += 1
        result = self.clear_outcomes.pop(0)
        if isinstance(result, BaseException):
            status = self.get_printer_status(printer_id)
            return {
                "resolved": not status["awaiting_plate_clear"],
                "status": status,
                "request_error": result,
            }
        return result

    def get_printer_status(self, printer_id):
        self.status_calls += 1
        result = self.statuses.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


def load_app_main(monkeypatch, api, advance_to_ap_retry=False, recover_wifi=True):
    clock = {"ms": 0, "sleeps": 0}
    button_handlers = []

    class FakeNetwork:
        def __init__(self):
            self.ap_mode = True
            self.retry_calls = 0

        def connect_with_fallback(self, watchdog_feed=None):
            return self

        def is_ap_mode(self):
            return self.ap_mode

        def is_connected(self):
            return not self.ap_mode

        def ensure_connected(self, watchdog_feed=None, fallback_to_ap=False):
            if self.ap_mode:
                return self
            return self

        def retry_station_from_access_point(self, watchdog_feed=None):
            self.retry_calls += 1
            self.ap_mode = not recover_wifi
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

    class FakeWDT:
        def __init__(self, timeout):
            self.timeout = timeout

        def feed(self):
            return None

    class FakeButton:
        def __init__(self, on_press, **kwargs):
            button_handlers.append(on_press)

        def start(self):
            return None

    class FakeFlasher:
        def __init__(self, should_flash, **kwargs):
            self.should_flash = should_flash

        def start(self):
            return None

        def on(self):
            return None

    class FakeOTA:
        def __init__(self, reset=None):
            return None

        def status(self):
            return {"current_version": "test"}

        def confirm_boot(self):
            return True

    class FakeWebServer:
        def __init__(self, **kwargs):
            return None

        def poll(self):
            return False

    def sleep_ms(delay):
        clock["sleeps"] += 1
        if advance_to_ap_retry and clock["sleeps"] == 1:
            clock["ms"] = 30_000
        else:
            raise StopAppLoop()

    fake_time = SimpleNamespace(
        ticks_ms=lambda: clock["ms"],
        ticks_diff=lambda left, right: left - right,
        ticks_add=lambda value, delta: value + delta,
        sleep_ms=sleep_ms,
        sleep=lambda delay: None,
    )
    fake_modules = {
        "machine": SimpleNamespace(WDT=FakeWDT, reset=lambda: None),
        "time": fake_time,
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
    for name, module in fake_modules.items():
        monkeypatch.setitem(sys.modules, name, module)

    namespace = {"__name__": "bambutton_app_main_test"}
    try:
        exec(compile(APP_MAIN.read_text(), str(APP_MAIN), "exec"), namespace)
    except StopAppLoop:
        pass
    return namespace, network, button_handlers[0], clock


def unresolved_outcome():
    return {
        "resolved": False,
        "status": {"awaiting_plate_clear": True, "chamber_light": True},
        "request_error": RuntimeError("offline"),
    }


def test_repeated_button_presses_keep_one_pending_intent_and_led_signal(monkeypatch):
    api = FakeAPI()
    namespace, _, press, _ = load_app_main(monkeypatch, api)
    namespace["PRINTER_AWAITING_PLATE_CLEAR"] = True

    press(None)
    press(None)

    assert namespace["PENDING_BUTTON_PRESS"] is True
    assert namespace["should_flash_plate_clear"]() is True


def test_failed_request_stays_pending_then_recovers_without_losing_press(monkeypatch):
    api = FakeAPI()
    api.clear_outcomes = [unresolved_outcome(), {
        "resolved": True, "status": None, "request_error": None,
    }]
    namespace, network, press, clock = load_app_main(monkeypatch, api)
    namespace["PRINTER_AWAITING_PLATE_CLEAR"] = True
    press(None)
    network.ap_mode = False

    namespace["handle_pending_button_press"]()
    namespace["handle_pending_button_press"]()

    assert namespace["PENDING_BUTTON_PRESS"] is True
    assert api.clear_calls == 1
    assert namespace["should_flash_plate_clear"]() is True

    clock["ms"] += 5_001
    namespace["handle_pending_button_press"]()

    assert namespace["PENDING_BUTTON_PRESS"] is False
    assert namespace["PRINTER_AWAITING_PLATE_CLEAR"] is False
    assert api.clear_calls == 2


def test_unknown_outcome_is_reconciled_before_any_retry(monkeypatch):
    api = FakeAPI()
    api.clear_outcomes = [RuntimeError("connection lost")]
    api.statuses = [RuntimeError("status unavailable"), {
        "awaiting_plate_clear": False, "chamber_light": False,
    }]
    namespace, network, press, clock = load_app_main(monkeypatch, api)
    namespace["PRINTER_AWAITING_PLATE_CLEAR"] = True
    press(None)
    network.ap_mode = False

    namespace["handle_pending_button_press"]()
    assert namespace["PENDING_BUTTON_PRESS"] is True
    assert namespace["BUTTON_PRESS_NEEDS_RECONCILIATION"] is True

    clock["ms"] += 5_001
    namespace["handle_pending_button_press"]()

    assert namespace["PENDING_BUTTON_PRESS"] is False
    assert api.clear_calls == 1
    assert api.status_calls == 2


def test_setup_ap_retries_saved_station_connection(monkeypatch):
    api = FakeAPI()
    api.statuses = [{"awaiting_plate_clear": False, "chamber_light": False}]
    namespace, network, _, _ = load_app_main(
        monkeypatch, api, advance_to_ap_retry=True, recover_wifi=True
    )

    assert network.retry_calls == 1
    assert network.is_ap_mode() is False
