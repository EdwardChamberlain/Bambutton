import json
import re

import pytest

from micro import config_loader


def test_web_setup_default_hostname_has_four_character_suffix():
    assert re.fullmatch(r"bambutton-[A-Z0-9]{4}", config_loader.DEFAULT_HOSTNAME)


def test_partial_config_keeps_explicit_settings_and_fills_defaults(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"wifi": {"hostname": "shop-button"}}))

    config = config_loader.load_config(config_path)

    assert config["wifi"]["hostname"] == "shop-button"
    assert config["wifi"]["ssid"] == ""
    assert config["api"]["base_url"] == ""
    assert config["printer"]["id"] is None
    assert not config_loader.is_runtime_config_ready(config)


def test_malformed_config_recovers_from_valid_backup(tmp_path):
    config_path = tmp_path / "config.json"
    backup_path = tmp_path / "config.json.bak"
    config_path.write_text('{"wifi":')
    backup_path.write_text(json.dumps({
        "wifi": {"ssid": "shop"},
        "api": {"base_url": "http://bambuddy/api/v1"},
        "printer": {"id": 7},
    }))

    config = config_loader.load_config(config_path)

    assert config["wifi"]["ssid"] == "shop"
    assert config["printer"]["id"] == 7


def test_malformed_config_without_backup_uses_bootable_defaults(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text('{"wifi":')

    config = config_loader.load_config(config_path)

    assert config["wifi"]["ssid"] == ""
    assert config["api"]["base_url"] == ""
    assert config["printer"]["id"] is None
    assert config["web"]["password"]
    assert not config_loader.is_runtime_config_ready(config)


def test_nested_invalid_active_config_recovers_from_valid_backup(tmp_path):
    config_path = tmp_path / "config.json"
    backup_path = tmp_path / "config.json.bak"
    config_path.write_text(json.dumps({"wifi": None}))
    backup_path.write_text(json.dumps({
        "wifi": {"ssid": "shop"},
        "api": {"base_url": "http://bambuddy/api/v1", "key": "secret"},
        "printer": {"id": 7},
    }))

    config = config_loader.load_config(config_path)

    assert config["wifi"]["ssid"] == "shop"
    assert config["printer"]["id"] == 7
    assert config_loader.is_runtime_config_ready(config)


def test_incomplete_config_never_inherits_a_printer_id(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "wifi": {"ssid": "shop"},
        "api": {"base_url": "http://bambuddy/api/v1", "key": "secret"},
    }))

    config = config_loader.load_config(config_path)

    assert config["printer"]["id"] is None
    assert not config_loader.is_runtime_config_ready(config)


def test_non_numeric_printer_id_is_rejected_and_uses_safe_defaults(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"printer": {"id": "3"}}))

    config = config_loader.load_config(config_path)

    assert config["printer"]["id"] is None
    assert not config_loader.is_runtime_config_ready(config)


@pytest.mark.parametrize("value", ["invalid", "upside-down", 1])
def test_invalid_button_pull_recovers_to_safe_defaults(tmp_path, value):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"button": {"pull": value}}))

    config = config_loader.load_config(config_path)

    assert config["button"]["pull"] == "down"
    assert not config_loader.is_runtime_config_ready(config)


@pytest.mark.parametrize(
    "section,field,value",
    [
        ("button", "pin", 4.5),
        ("button", "pin", 22),
        ("led", "pin", -1),
        ("api", "request_timeout_seconds", 0),
        ("printer", "poll_interval_seconds", 1.5),
        ("wifi", "timeout_seconds", 121),
        ("wifi", "hostname", "bad hostname"),
    ],
)
def test_invalid_hardware_and_timer_values_are_rejected(
    tmp_path, section, field, value
):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({section: {field: value}}))

    config = config_loader.load_config(config_path)

    assert config == config_loader._copy_dict(config_loader.DEFAULT_CONFIG)


def test_invalid_active_values_recover_from_a_valid_backup(tmp_path):
    config_path = tmp_path / "config.json"
    backup_path = tmp_path / "config.json.bak"
    config_path.write_text(json.dumps({"button": {"trigger": "sideways"}}))
    backup_path.write_text(json.dumps({"button": {"trigger": "both"}}))

    config = config_loader.load_config(config_path)

    assert config["button"]["trigger"] == "both"


def test_config_validation_reports_the_invalid_field():
    with pytest.raises(ValueError, match="button.pull"):
        config_loader.validate_config({"button": {"pull": "invalid"}})
