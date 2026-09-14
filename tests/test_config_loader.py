import json
import re

from micro import config_loader


def test_web_setup_default_hostname_has_four_character_suffix():
    assert re.fullmatch(r"bambutton-[A-Z0-9]{4}", config_loader.DEFAULT_HOSTNAME)


def test_explicit_hostname_is_preserved_when_loading_config(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"wifi": {"hostname": "shop-button"}}))

    config = config_loader.load_config(config_path)

    assert config["wifi"]["hostname"] == "shop-button"
