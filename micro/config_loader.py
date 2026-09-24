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
        # A printer must be selected in setup. Never guess a device ID: a
        # default ID can send a button press to an unrelated printer.
        "id": None,
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


_STRING_FIELDS = {
    "wifi": ("ssid", "password", "hostname", "ap_password"),
    "api": ("base_url", "key"),
    "button": ("pull", "trigger"),
    "web": ("password",),
}
_NUMBER_FIELDS = {
    "wifi": ("timeout_seconds",),
    "api": ("request_timeout_seconds",),
    "printer": ("poll_interval_seconds",),
    "led": ("pin", "flash_interval_ms"),
    "button": ("pin", "debounce_ms"),
}
_KNOWN_SECTIONS = tuple(DEFAULT_CONFIG.keys())


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


def is_runtime_config_ready(config):
    """Return whether the settings can safely address a printer API."""
    if not isinstance(config, dict):
        return False

    wifi = config.get("wifi")
    api = config.get("api")
    printer = config.get("printer")
    if not isinstance(wifi, dict) or not isinstance(api, dict):
        return False
    if not isinstance(printer, dict):
        return False

    printer_id = printer.get("id")
    return bool(
        wifi.get("ssid")
        and api.get("base_url")
        and api.get("key")
        and isinstance(printer_id, int)
        and not isinstance(printer_id, bool)
        and printer_id >= 0
    )


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
    if not _is_valid_config_shape(loaded_config):
        return None
    return loaded_config


def _is_valid_config_shape(config):
    if not isinstance(config, dict):
        return False

    for section in _KNOWN_SECTIONS:
        if section in config and not isinstance(config[section], dict):
            return False

    for section, fields in _STRING_FIELDS.items():
        values = config.get(section, {})
        for field in fields:
            if field in values and not isinstance(values[field], str):
                return False

    for section, fields in _NUMBER_FIELDS.items():
        values = config.get(section, {})
        for field in fields:
            value = values.get(field)
            if field in values and (
                not isinstance(value, (int, float)) or isinstance(value, bool)
            ):
                return False

    if "id" in config.get("printer", {}):
        printer_id = config["printer"]["id"]
        if printer_id is not None and (
            not isinstance(printer_id, int)
            or isinstance(printer_id, bool)
            or printer_id < 0
        ):
            return False

    return True


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
