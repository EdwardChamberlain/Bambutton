try:
    import ujson as json
except ImportError:
    import json

import random


HOSTNAME_PREFIX = "bambutton"
HOSTNAME_SUFFIX_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
HOSTNAME_SUFFIX_LENGTH = 4


def generate_hostname():
    suffix = "".join(
        HOSTNAME_SUFFIX_ALPHABET[random.getrandbits(32) % len(HOSTNAME_SUFFIX_ALPHABET)]
        for _ in range(HOSTNAME_SUFFIX_LENGTH)
    )
    return "{}-{}".format(HOSTNAME_PREFIX, suffix)


DEFAULT_HOSTNAME = generate_hostname()


DEFAULT_CONFIG = {
    "wifi": {
        "ssid": "",
        "password": "",
        "hostname": DEFAULT_HOSTNAME,
        "timeout_seconds": 10,
        "ap_password": "bambutton",
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
    "web": {
        "password": "bambutton",
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
