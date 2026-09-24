import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


WIFI_PATH = Path(__file__).parents[1] / "micro" / "wifi.py"


def load_wifi_module(
    monkeypatch,
    events,
    connect_results=None,
    tick_increment_ms=0,
    connection_states=None,
):
    connect_results = list(connect_results or [True])
    connection_states = list(connection_states or [])
    current_time_ms = 0

    class FakeWLAN:
        PM_NONE = "pm-none"

        def __init__(self, interface):
            self.interface = interface
            self.connected = False
            self.config_calls = []

        def active(self, enabled):
            events.append(("active", enabled))

        def config(self, **kwargs):
            self.config_calls.append(kwargs)
            events.append(("config", kwargs))

        def connect(self, ssid, password):
            events.append(("connect", ssid, password))
            result = connect_results.pop(0)
            if isinstance(result, BaseException):
                raise result
            self.connected = result

        def disconnect(self):
            events.append(("disconnect",))
            self.connected = False

        def isconnected(self):
            if connection_states:
                self.connected = connection_states.pop(0)
            return self.connected

        def ifconfig(self):
            if self.interface == 1:
                return ("192.168.4.1", "255.255.255.0", "192.168.4.1", "192.168.4.1")
            return ("192.168.1.20", "255.255.255.0", "192.168.1.1", "192.168.1.1")

    def set_hostname(hostname):
        events.append(("hostname", hostname))

    fake_network = SimpleNamespace(
        STA_IF=0,
        AP_IF=1,
        WLAN=FakeWLAN,
        hostname=set_hostname,
    )

    def ticks_ms():
        nonlocal current_time_ms
        current_time_ms += tick_increment_ms
        return current_time_ms

    def sleep(seconds):
        events.append(("sleep", seconds))

    fake_time = SimpleNamespace(
        ticks_ms=ticks_ms,
        ticks_diff=lambda current, start: current - start,
        sleep=sleep,
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


def test_connect_uses_configured_hostname(monkeypatch):
    events = []
    wifi_module = load_wifi_module(monkeypatch, events)

    wifi_module.WiFi("ssid", "password", hostname="shop-button").connect()

    assert events[0] == ("hostname", "shop-button")


def test_connect_raises_connection_timeout_after_attempt_deadline(monkeypatch):
    events = []
    wifi_module = load_wifi_module(
        monkeypatch,
        events,
        connect_results=[False],
        tick_increment_ms=10_001,
    )

    wifi = wifi_module.WiFi("ssid", "password", timeout_seconds=10)

    with pytest.raises(wifi_module.ConnectionTimeout, match="timed out"):
        wifi.connect()


def test_connect_forever_retries_after_ten_second_backoff(monkeypatch):
    events = []
    wifi_module = load_wifi_module(
        monkeypatch,
        events,
        connect_results=[False, True],
        tick_increment_ms=10_001,
    )
    watchdog_feeds = []
    wifi = wifi_module.WiFi("ssid", "password", timeout_seconds=10)

    wlan = wifi.connect_forever(watchdog_feed=lambda: watchdog_feeds.append(True))

    assert wlan.isconnected()
    assert events.count(("connect", "ssid", "password")) == 2
    assert events.count(("disconnect",)) == 1
    assert sum(item[1] for item in events if item[0] == "sleep") == 10
    assert watchdog_feeds


def test_connect_forever_retries_after_wlan_oserror(monkeypatch):
    events = []
    wifi_module = load_wifi_module(
        monkeypatch,
        events,
        connect_results=[OSError("Wifi Internal Error"), True],
    )
    watchdog_feeds = []
    wifi = wifi_module.WiFi("ssid", "password")

    wlan = wifi.connect_forever(watchdog_feed=lambda: watchdog_feeds.append(True))

    assert wlan.isconnected()
    assert events.count(("connect", "ssid", "password")) == 2
    assert events.count(("disconnect",)) == 1
    assert sum(item[1] for item in events if item[0] == "sleep") == 10
    assert len(watchdog_feeds) >= 10


def test_connect_feeds_watchdog_while_waiting_for_wifi(monkeypatch):
    events = []
    wifi_module = load_wifi_module(
        monkeypatch,
        events,
        connect_results=[False],
        tick_increment_ms=1,
        connection_states=[False, False, True],
    )
    watchdog_feeds = []
    wifi = wifi_module.WiFi("ssid", "password")

    assert wifi.connect(watchdog_feed=lambda: watchdog_feeds.append(True))
    assert watchdog_feeds


def test_ensure_connected_retries_until_wifi_returns(monkeypatch):
    events = []
    wifi_module = load_wifi_module(
        monkeypatch,
        events,
        connect_results=[False, True],
        tick_increment_ms=10_001,
    )
    wifi = wifi_module.WiFi("ssid", "password", timeout_seconds=10)
    wifi.wlan.connected = False

    assert wifi.ensure_connected().isconnected()


def test_connect_with_fallback_starts_setup_access_point_after_timeout(monkeypatch):
    events = []
    wifi_module = load_wifi_module(
        monkeypatch,
        events,
        connect_results=[False],
        tick_increment_ms=10_001,
    )
    wifi = wifi_module.WiFi("ssid", "password", timeout_seconds=10)

    access_point = wifi.connect_with_fallback()

    assert access_point.interface == 1
    assert wifi.is_ap_mode() is True
    assert wifi.mode() == "access point"
    assert wifi.ifconfig()[0] == "192.168.4.1"
    assert ("active", False) in events
    assert ("config", {
        "essid": "bambutton",
        "password": "bambutton",
    }) in events
    assert wifi.ensure_connected() is access_point


def test_setup_access_point_uses_configured_hostname(monkeypatch):
    events = []
    wifi_module = load_wifi_module(
        monkeypatch,
        events,
        connect_results=[False],
        tick_increment_ms=10_001,
    )
    wifi = wifi_module.WiFi(
        "ssid",
        "password",
        hostname="bambutton-ABCD",
        timeout_seconds=10,
    )

    wifi.connect_with_fallback()

    assert ("config", {
        "essid": "bambutton-ABCD",
        "password": "bambutton",
    }) in events


def test_station_retry_restores_wifi_when_saved_network_returns(monkeypatch):
    events = []
    wifi_module = load_wifi_module(
        monkeypatch,
        events,
        connect_results=[False, True],
        tick_increment_ms=10_001,
    )
    wifi = wifi_module.WiFi("ssid", "password", timeout_seconds=10)
    wifi.connect_with_fallback()
    access_point = wifi.ap

    result = wifi.retry_station_from_access_point()

    assert result is wifi.wlan
    assert access_point is not wifi.ap
    assert access_point.interface == 1
    assert wifi.is_ap_mode() is False
    assert wifi.is_connected() is True


def test_station_retry_keeps_setup_access_point_when_network_is_still_down(
    monkeypatch,
):
    events = []
    wifi_module = load_wifi_module(
        monkeypatch,
        events,
        connect_results=[False, False],
        tick_increment_ms=10_001,
    )
    wifi = wifi_module.WiFi("ssid", "password", timeout_seconds=10)
    wifi.connect_with_fallback()
    setup_access_point = wifi.ap

    access_point = wifi.retry_station_from_access_point()

    assert access_point is setup_access_point
    assert wifi.is_ap_mode() is True
    assert wifi.ap is setup_access_point
