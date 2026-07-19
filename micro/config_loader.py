try:
    import ujson as json
except ImportError:
    import json


DEFAULT_CONFIG = {
    "wifi": {
        "ssid": "",
        "password": "",
        "timeout_seconds": 10,
    },
    "api": {
        "base_url": "",
        "key": "",
        "request_timeout_seconds": 3,
    },
    "printer": {
        "id": 3,
        "poll_interval_seconds": 5,
    },
    "led": {
        "pin": 3,
        "flash_interval_ms": 250,
    },
    "button": {
        "pin": 4,
        "debounce_ms": 150,
        "pull": "down",
        "trigger": "rising",
    },
}


def load_config(path="config.json"):
    config = _copy_dict(DEFAULT_CONFIG)

    try:
        with open(path) as config_file:
            loaded_config = json.load(config_file)
    except OSError:
        print("Config file not found, using defaults:", path)
        return config

    _deep_update(config, loaded_config)
    return config


def _copy_dict(source):
    result = {}

    for key, value in source.items():
        if isinstance(value, dict):
            result[key] = _copy_dict(value)
        else:
            result[key] = value

    return result


def _deep_update(target, source):
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_update(target[key], value)
        else:
            target[key] = value
