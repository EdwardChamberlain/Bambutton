import json
import re

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
    assert config["printer"]["id"] == 3


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
    assert config["printer"]["id"] == 3
    assert config["web"]["password"]
