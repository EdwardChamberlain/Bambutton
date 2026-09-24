try:
    import ujson as json
except ImportError:
    import json

import os
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

    path = str(path)
    loaded_config = _load_config_file(path)
    source_path = path
    if loaded_config is None:
        backup_path = path + ".bak"
        loaded_config = _load_config_file(backup_path)
        if loaded_config is not None:
            source_path = backup_path

    if loaded_config is None:
        print("Config file missing or invalid, using defaults:", path)
        return config

    _deep_update(config, loaded_config)
    if source_path != path:
        print("Recovered configuration from backup:", source_path)
    return config


def save_config(path, config):
    """Replace a config atomically, retaining the previous copy until verified."""
    path = str(path)
    if not isinstance(config, dict):
        raise ValueError("Configuration must be an object")

    temporary_path = path + ".tmp"
    backup_path = path + ".bak"
    serialized = json.dumps(config)
    with open(temporary_path, "w") as config_file:
        config_file.write(serialized)
        config_file.write("\n")
    sync = getattr(os, "sync", None)
    if sync is not None:
        sync()

    staged_config = _load_config_file(temporary_path)
    if staged_config != config:
        _remove_file(temporary_path)
        raise ValueError("Could not verify saved configuration")

    if _load_config_file(path) is not None:
        _remove_file(backup_path)
        os.rename(path, backup_path)
    else:
        # Keep any valid prior backup until the new config is installed.
        _remove_file(path)

    try:
        os.rename(temporary_path, path)
    except OSError:
        # Restore a known-good config when the replacement could not be made.
        if (
            _load_config_file(path) is None
            and _load_config_file(backup_path) is not None
        ):
            try:
                os.rename(backup_path, path)
            except OSError:
                pass
        _remove_file(temporary_path)
        raise

    if _load_config_file(path) != config:
        _remove_file(path)
        if _load_config_file(backup_path) is not None:
            try:
                os.rename(backup_path, path)
            except OSError:
                pass
        raise ValueError("Could not verify active configuration")
    _remove_file(backup_path)


def _load_config_file(path):
    try:
        with open(path) as config_file:
            loaded_config = json.load(config_file)
    except (OSError, ValueError, TypeError):
        return None
    return loaded_config if isinstance(loaded_config, dict) else None


def _remove_file(path):
    try:
        os.remove(path)
    except OSError:
        pass


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
