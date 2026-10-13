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
        ("button", "pin", 17),
        ("led", "pin", -1),
        ("api", "request_timeout_seconds", 0),
        ("api", "request_timeout_seconds", 11),
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


@pytest.mark.parametrize("section", ("led", "button"))
@pytest.mark.parametrize("pin", (14, 15, 16, 17, 18, 19))
def test_gpio_pins_missing_from_shipped_firmware_are_rejected(section, pin):
    with pytest.raises(ValueError, match="supported by the shipped ESP32-C3"):
        config_loader.validate_config({section: {"pin": pin}})


@pytest.mark.parametrize("pin", (0, 3, 13, 20, 21))
def test_gpio_pins_supported_by_shipped_firmware_are_accepted(pin):
    config_loader.validate_config({"led": {"pin": pin}})


def test_invalid_gpio_in_active_config_recovers_from_safe_backup(tmp_path):
    config_path = tmp_path / "config.json"
    backup_path = tmp_path / "config.json.bak"
    config_path.write_text(json.dumps({"led": {"pin": 17}}))
    backup_path.write_text(json.dumps({"led": {"pin": 3}, "button": {"pin": 4}}))

    config = config_loader.load_config(config_path)

    assert config["led"]["pin"] == 3
    assert config["button"]["pin"] == 4


def test_api_timeout_is_bounded_below_the_watchdog_budget():
    config_loader.validate_config(
        {
            "api": {
                "request_timeout_seconds": config_loader.MAX_API_REQUEST_TIMEOUT_SECONDS
            }
        }
    )
    with pytest.raises(ValueError, match="request_timeout_seconds must be between"):
        config_loader.validate_config(
            {
                "api": {
                    "request_timeout_seconds": (
                        config_loader.MAX_API_REQUEST_TIMEOUT_SECONDS + 1
                    )
                }
            }
        )


def test_station_psk_64_digit_hex_is_allowed_but_ap_password_is_not():
    config_loader.validate_config({"wifi": {"password": "a" * 64}})
    with pytest.raises(ValueError, match="ap_password must be empty or 8 to 63 bytes"):
        config_loader.validate_config({"wifi": {"ap_password": "a" * 64}})


def test_ap_password_maximum_supported_length_is_accepted():
    config_loader.validate_config({"wifi": {"ap_password": "a" * 63}})
