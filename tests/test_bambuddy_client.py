import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


BAMBUDDY_API_PATH = Path(__file__).parents[1] / "micro" / "bambuddy_api.py"


def load_bambuddy_api(monkeypatch):
    class API:
        def __init__(self, *args, **kwargs):
            pass

        def api_get(self, path):
            raise NotImplementedError

        def api_post(self, path, payload=None):
            raise NotImplementedError

    monkeypatch.setitem(sys.modules, "api", SimpleNamespace(API=API))
    spec = importlib.util.spec_from_file_location(
        "test_bambuddy_client", BAMBUDDY_API_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_public_methods_use_printer_routes_and_status_fields(monkeypatch):
    module = load_bambuddy_api(monkeypatch)
    api = module.BambuddyAPI()
    get_calls = []
    post_calls = []
    monkeypatch.setattr(
        api, "_get", lambda path: get_calls.append(path) or {
            "awaiting_plate_clear": True, "chamber_light": True,
        }
    )
    monkeypatch.setattr(
        api, "_post", lambda path, payload=None: post_calls.append((path, payload))
    )

    assert api.get_printers()["awaiting_plate_clear"] is True
    assert api.get_printer(7)["chamber_light"] is True
    assert api.get_printer_status(7)["awaiting_plate_clear"] is True
    assert api.printer_is_awaiting_plate_clear(7) is True
    assert api.chamber_light_is_lit(7) is True
    api.clear_plate(7)

    assert get_calls == [
        "printers/", "printers/7", "printers/7/status",
        "printers/7/status", "printers/7/status",
    ]
    assert post_calls == [("printers/7/clear-plate", None)]


def test_api_errors_preserve_status_and_server_message(monkeypatch):
    module = load_bambuddy_api(monkeypatch)
    api = module.BambuddyAPI()
    monkeypatch.setattr(api, "api_get", lambda path: (409, '{"detail":"not awaiting"}'))

    with pytest.raises(module.BambuddyAPIError, match="not awaiting") as error:
        api.get_printer_status(7)

    assert error.value.status_code == 409
    assert error.value.body == {"detail": "not awaiting"}


def test_invalid_json_response_is_returned_as_text(monkeypatch):
    module = load_bambuddy_api(monkeypatch)
    api = module.BambuddyAPI()
    monkeypatch.setattr(api, "api_get", lambda path: (200, "plain response"))

    assert api.get_printer(7) == "plain response"


def test_transport_exception_is_wrapped_as_api_error(monkeypatch):
    module = load_bambuddy_api(monkeypatch)
    api = module.BambuddyAPI()

    def fail_request(path):
        raise OSError("offline")

    monkeypatch.setattr(api, "api_post", fail_request)

    with pytest.raises(module.BambuddyAPIError, match="API POST request failed"):
        api.clear_plate(7)
