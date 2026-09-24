import base64
import hashlib
import json

import pytest

from micro import ota_manager, web_config


def base_config():
    return {
        "wifi": {
            "ssid": "old-network",
            "password": "old-password",
            "hostname": "bambutton",
            "timeout_seconds": 10,
        },
        "api": {
            "base_url": "http://old-host:8000/api/v1",
            "key": "old-key",
            "request_timeout_seconds": 3,
        },
        "printer": {"id": 1, "poll_interval_seconds": 3},
        "led": {"pin": 3, "flash_interval_ms": 250},
        "button": {"pin": 4, "debounce_ms": 150, "pull": "down", "trigger": "rising"},
        "web": {"password": "old-web-password"},
    }


def valid_form():
    return {
        "hostname": "shop-button",
        "wifi_ssid": "new network",
        "wifi_password": "new-password",
        "api_base_url": "http://new-host:8000/api/v1/",
        "api_key": "new-key",
        "printer_id": "7",
        "led_pin": "5",
        "button_pin": "6",
        "web_password": "new-web-password",
    }


def auth_headers(password="old-web-password"):
    credentials = base64.b64encode(("admin:" + password).encode("utf-8")).decode("ascii")
    return {"authorization": "Basic " + credentials}


def test_parse_form_decodes_url_encoded_values():
    assert web_config.parse_form("wifi_ssid=shop+wifi&api_key=a%2Bb") == {
        "wifi_ssid": "shop wifi",
        "api_key": "a+b",
    }


def test_parse_form_decodes_utf8_values():
    assert web_config.parse_form("wifi_ssid=Caf%C3%A9&wifi_password=p%C3%A5ss") == {
        "wifi_ssid": "Café",
        "wifi_password": "påss",
    }


def test_build_config_updates_web_fields_and_preserves_other_settings():
    current = base_config()

    updated = web_config.build_config(valid_form(), current)

    assert updated["wifi"] == {
        "ssid": "new network",
        "password": "new-password",
        "hostname": "shop-button",
        "timeout_seconds": 10,
    }
    assert updated["api"]["base_url"] == "http://new-host:8000/api/v1"
    assert updated["api"]["key"] == "new-key"
    assert updated["printer"]["id"] == 7
    assert updated["led"]["pin"] == 5
    assert updated["button"]["pin"] == 6
    assert current["printer"]["id"] == 1
    assert current["api"]["base_url"] == "http://old-host:8000/api/v1"


def test_blank_secrets_keep_existing_values():
    current = base_config()
    form = valid_form()
    form["wifi_password"] = ""
    form["api_key"] = ""

    updated = web_config.build_config(form, current)

    assert updated["wifi"]["password"] == "old-password"
    assert updated["api"]["key"] == "old-key"


def test_blank_web_password_keeps_existing_value_and_submitted_password_updates_it():
    current = base_config()
    form = valid_form()
    form["web_password"] = ""

    assert web_config.build_config(form, current)["web"]["password"] == "old-web-password"

    form["web_password"] = "newer-web-password"
    assert web_config.build_config(form, current)["web"]["password"] == "newer-web-password"


@pytest.mark.parametrize(
    "field,value,error",
    [
        ("hostname", "bad name", "Hostname may contain only letters, numbers, and hyphens."),
        ("api_base_url", "new-host:8000", "API base URL must start with http:// or https:// and contain no spaces."),
        ("led_pin", "22", "LED pin must be between 0 and 21."),
        ("button_pin", "5", "LED pin and button pin must be different."),
    ],
)
def test_build_config_rejects_invalid_values(field, value, error):
    form = valid_form()
    form[field] = value

    with pytest.raises(ValueError, match=error):
        web_config.build_config(form, base_config())


def test_save_config_writes_json(tmp_path):
    path = tmp_path / "config.json"
    config = base_config()

    web_config.save_config(str(path), config)

    assert json.loads(path.read_text()) == config


def test_config_page_contains_form_and_does_not_require_formatting_js():
    page = web_config.render_config_page(base_config())

    assert 'action="/save"' in page
    assert 'name="hostname"' in page
    assert 'fetch("/api/printers", {' in page
    assert 'name="web_password"' in page
    assert "__HOSTNAME__" not in page


def test_web_pages_use_mobile_first_responsive_layout():
    pages = (
        web_config.render_config_page(base_config()),
        web_config.render_debug_page(base_config(), {}),
    )
    for page in pages:
        assert (
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            in page
        )
        assert "*, *::before, *::after { box-sizing: border-box; }" in page
        assert "input, select {" in page
        assert "display: block; width: 100%;" in page
        assert "fieldset {" in page
        assert "min-width: 0;" in page
        assert "overflow-wrap: anywhere;" in page
        assert "@media (min-width: 40rem)" in page
        button_rule = page.split("    button {", 1)[1].split("}", 1)[0]
        assert "display: block;" in button_rule
        assert "width: 100%;" in button_rule


def test_debug_page_does_not_expose_secrets():
    page = web_config.render_debug_page(base_config(), {"IP address": "192.168.1.20"})

    assert "old-password" not in page
    assert "old-key" not in page
    assert "old-web-password" not in page
    assert "192.168.1.20" in page


def test_all_routes_require_basic_authentication():
    server = object.__new__(web_config.WebConfigServer)
    server.config = base_config()
    server.api = None
    server.status_provider = lambda: {}
    server.restart_requested = False

    status, content_type, body = server.handle_request("GET", "/")

    assert status == 401
    assert content_type.startswith("text/html")
    assert "Authentication required" in body


def test_basic_authentication_allows_authenticated_requests():
    server = object.__new__(web_config.WebConfigServer)
    server.config = base_config()
    server.api = None
    server.status_provider = lambda: {}
    server.restart_requested = False
    credentials = base64.b64encode(b"admin:old-web-password").decode("ascii")

    status, content_type, body = server.handle_request(
        "GET",
        "/debug",
        headers={"authorization": "Basic " + credentials},
    )

    assert status == 200
    assert content_type.startswith("text/html")
    assert "Bambutton debug information" in body


def test_basic_authentication_rejects_wrong_password():
    server = object.__new__(web_config.WebConfigServer)
    server.config = base_config()
    server.api = None
    server.status_provider = lambda: {}
    server.restart_requested = False
    credentials = base64.b64encode(b"admin:wrong-password").decode("ascii")

    status, _, _ = server.handle_request(
        "GET",
        "/debug",
        headers={"authorization": "Basic " + credentials},
    )

    assert status == 401


def test_save_request_sets_restart_flag_and_returns_updated_page(tmp_path):
    server = object.__new__(web_config.WebConfigServer)
    server.config = base_config()
    server.api = None
    server.status_provider = lambda: {}
    server.config_path = str(tmp_path / "config.json")
    server.restart_requested = False

    status, content_type, page = server.handle_request(
        "POST",
        "/save",
        "&".join("{}={}".format(key, value) for key, value in valid_form().items()),
        headers=auth_headers(),
    )

    assert status == 200
    assert content_type.startswith("text/html")
    assert server.restart_requested is True
    assert "shop-button" in page
    assert json.loads((tmp_path / "config.json").read_text())["printer"]["id"] == 7


def test_printer_discovery_uses_submitted_api_settings():
    calls = []

    class FakeAPI:
        def __init__(self, api_key, base_url, request_timeout_seconds):
            calls.append((api_key, base_url, request_timeout_seconds))

        def get_printers(self):
            return [{"id": 7, "friendly_name": "New API printer"}]

    server = object.__new__(web_config.WebConfigServer)
    server.config = base_config()
    server.api = FakeAPI("old-key", "http://old-host:8000/api/v1", 3)
    server.status_provider = lambda: {}
    server.restart_requested = False

    status, content_type, body = server.handle_request(
        "POST",
        "/api/printers",
        "api_base_url=http%3A%2F%2Fnew-host%3A8000%2Fapi%2Fv1&api_key=new-key",
        headers=auth_headers(),
    )

    assert status == 200
    assert content_type == "application/json"
    assert "New API printer" in body
    assert calls[-1] == ("new-key", "http://new-host:8000/api/v1", 3)


def test_config_page_preserves_printer_selection_when_loading_printers():
    page = web_config.render_config_page(base_config())

    assert 'const currentPrinterId = String(printerSelect.value);' in page
    assert 'option.selected = String(printer.id) === currentPrinterId;' in page
    assert 'Current printer (" + currentPrinterId + ", not returned)' in page


def update_bundle():
    files = {}
    contents = {name: (name + "\n").encode() for name in ota_manager.APP_FILES}
    contents["app_main.py"] = b"print('updated')\n"
    contents["web_config.py"] = b"WEB = True\n"
    for name, content in contents.items():
        files[name] = {
            "size": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
            "content": base64.b64encode(content).decode("ascii"),
        }
    return {
        "format": 1,
        "version": "2.0.0",
        "minimum_bootloader": 1,
        "files": files,
    }


def test_config_page_contains_atomic_update_controls():
    page = web_config.render_config_page(base_config(), update_status={})

    assert 'id="check-update"' in page
    assert 'id="upload-update"' in page
    assert 'id="install-update"' in page
    assert "inactive application slot" in page


def test_update_page_shows_inactive_slot_and_transfer_progress():
    status = {
        "current_version": "1.0.0",
        "active_slot": "app_a",
        "staged_slot": None,
        "slots": {
            "app_a": {"ready": True, "version": "1.0.0"},
            "app_b": {"ready": True, "version": "0.9.0"},
        },
    }

    page = web_config.render_update_page(status)

    assert '<strong id="update-inactive-slot">app_b — ready (version 0.9.0)</strong>' in page
    assert '<progress id="update-progress"' in page
    assert 'request.upload.addEventListener("progress"' in page
    assert '"Uploading local bundle: " + percent + "%"' in page
    assert 'id="install-update" disabled' in page

    status["staged_slot"] = "app_b"
    status["slots"]["app_b"] = {"ready": True, "version": "2.0.0"}
    page = web_config.render_update_page(status)

    assert '<strong id="update-inactive-slot">app_b — staged (version 2.0.0)</strong>' in page
    assert 'id="install-update" disabled' not in page


def test_update_routes_stage_and_commit_without_touching_config(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(base_config()))
    manager = ota_manager.OTAUpdateManager(root=str(tmp_path))
    server = object.__new__(web_config.WebConfigServer)
    server.config = base_config()
    server.api = None
    server.status_provider = lambda: {}
    server.config_path = str(config_path)
    server.update_manager = manager
    server.restart_requested = False

    status, content_type, body = server.handle_request(
        "POST",
        "/api/update/upload",
        json.dumps(update_bundle()),
        headers=auth_headers(),
    )
    assert status == 200
    assert content_type == "application/json"
    assert json.loads(body)["staged_slot"] == "app_a"

    status, _, body = server.handle_request(
        "POST",
        "/api/update/install",
        headers=auth_headers(),
    )
    assert status == 200
    assert server.restart_requested is True
    assert json.loads(body)["pending"]["candidate"] == "app_a"
    assert json.loads(config_path.read_text()) == base_config()
