try:
    import ujson as json
except ImportError:
    import json


# Multi-station schema. Wi-Fi/API are shared; each station is one printer with
# its own button + LED. A fresh flash ships this stub (no secrets, no printer
# assigned) so the board boots straight into the setup portal.
DEFAULT_CONFIG = {
    "wifi": {
        "ssid": "",
        "password": "",
        "timeout_seconds": 10,
    },
    "hostname": "bambutton",
    "api": {
        "base_url": "",
        "key": "",
        "request_timeout_seconds": 3,
    },
    "poll_interval_seconds": 3,
    "led": {
        "flash_interval_ms": 250,
    },
    "button": {
        "debounce_ms": 150,
        "pull": "down",
        "trigger": "rising",
    },
    "ap": {
        "ssid": "Bambutton-Setup",
        "password": "bambutton",
    },
    "update": {
        "url": "",
    },
    "stations": [
        {"printer_id": "", "led_pin": 3, "button_pin": 4},
        {"printer_id": "", "led_pin": 5, "button_pin": 6},
    ],
}


def load_config(path="config.json"):
    config = _copy_value(DEFAULT_CONFIG)
    try:
        with open(path) as config_file:
            loaded = json.load(config_file)
    except OSError:
        print("Config file not found, using defaults:", path)
        return config
    _deep_update(config, loaded)
    _migrate_legacy(config)
    return config


def save_config(config, path="config.json"):
    with open(path, "w") as config_file:
        config_file.write(json.dumps(config))


def config_complete(config):
    """True when the board has enough to run normally (skip the setup portal)."""
    wifi = config.get("wifi", {})
    api = config.get("api", {})
    if not str(wifi.get("ssid", "")).strip():
        return False
    if not str(api.get("base_url", "")).strip():
        return False
    if not str(api.get("key", "")).strip():
        return False
    for station in config.get("stations", []):
        if str(station.get("printer_id", "")).strip():
            return True  # at least one station has a printer assigned
    return False


def _migrate_legacy(config):
    """Fold an old single-printer config (printer{}/led.pin/button.pin, as the
    desktop setup assistant still writes) into station 0 so existing setups keep
    working after the multi-station schema change."""
    legacy_id = str(config.get("printer", {}).get("id", "")).strip()
    if not legacy_id:
        return
    stations = config.get("stations") or []
    if any(str(s.get("printer_id", "")).strip() for s in stations):
        return  # already migrated / explicitly configured
    if not stations:
        stations = [{"printer_id": "", "led_pin": 3, "button_pin": 4}]
        config["stations"] = stations
    stations[0]["printer_id"] = legacy_id
    led_pin = config.get("led", {}).get("pin")
    if led_pin is not None:
        stations[0]["led_pin"] = led_pin
    button_pin = config.get("button", {}).get("pin")
    if button_pin is not None:
        stations[0]["button_pin"] = button_pin
    poll = config.get("printer", {}).get("poll_interval_seconds")
    if poll is not None:
        config["poll_interval_seconds"] = poll


def _copy_value(value):
    if isinstance(value, dict):
        return {key: _copy_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_copy_value(item) for item in value]
    return value


def _deep_update(target, source):
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_update(target[key], value)
        else:
            target[key] = _copy_value(value)
