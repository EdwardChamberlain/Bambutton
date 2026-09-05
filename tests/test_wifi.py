import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace


WIFI_PATH = Path(__file__).parents[1] / "micro" / "wifi.py"


def load_wifi_module(monkeypatch, events):
    class FakeWLAN:
        PM_NONE = "pm-none"

        def __init__(self, interface):
            self.connected = False
            self.config_calls = []

        def active(self, enabled):
            events.append(("active", enabled))

        def config(self, **kwargs):
            self.config_calls.append(kwargs)
            events.append(("config", kwargs))

        def connect(self, ssid, password):
            events.append(("connect", ssid, password))
            self.connected = True

        def isconnected(self):
            return self.connected

        def ifconfig(self):
            return ("192.168.1.20", "255.255.255.0", "192.168.1.1", "192.168.1.1")

    def set_hostname(hostname):
        events.append(("hostname", hostname))

    fake_network = SimpleNamespace(STA_IF=0, WLAN=FakeWLAN, hostname=set_hostname)
    fake_time = SimpleNamespace(
        ticks_ms=lambda: 0,
        ticks_diff=lambda current, start: current - start,
        sleep=lambda seconds: None,
    )
    monkeypatch.setitem(sys.modules, "network", fake_network)
    monkeypatch.setitem(sys.modules, "time", fake_time)

    spec = importlib.util.spec_from_file_location("test_wifi_module", WIFI_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_connect_sets_default_hostname_before_activating_wifi(monkeypatch):
    events = []
    wifi_module = load_wifi_module(monkeypatch, events)

    wifi_module.WiFi("ssid", "password").connect()

    assert events[:4] == [
        ("hostname", "bambutton"),
        ("active", True),
        ("config", {"pm": "pm-none"}),
        ("connect", "ssid", "password"),
    ]


def test_connect_disables_wifi_power_management(monkeypatch):
    wifi_module = load_wifi_module(monkeypatch, [])
    wifi = wifi_module.WiFi("ssid", "password")

    wlan = wifi.connect()

    assert wlan.config_calls == [{"pm": "pm-none"}]
