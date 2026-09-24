import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace


API_PATH = Path(__file__).parents[1] / "micro" / "api.py"


def load_api_module(monkeypatch, requests):
    monkeypatch.setitem(sys.modules, "urequests", requests)
    spec = importlib.util.spec_from_file_location("test_micro_api", API_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Response:
    def __init__(self, status_code=200, text="ok"):
        self.status_code = status_code
        self.text = text
        self.closed = False

    def close(self):
        self.closed = True


def test_api_get_uses_headers_timeout_and_closes_response(monkeypatch):
    response = Response(202, '{"ready": true}')
    calls = []
    requests = SimpleNamespace(
        get=lambda *args, **kwargs: calls.append((args, kwargs)) or response
    )
    api_module = load_api_module(monkeypatch, requests)
    api = api_module.API("secret", "http://bambuddy/api/v1/", 5)

    result = api.api_get("printers/7/status", {"X-Test": "yes"})

    assert result == (202, '{"ready": true}')
    assert calls == [(("http://bambuddy/api/v1/printers/7/status",), {
        "headers": {"X-API-Key": "secret", "X-Test": "yes"},
        "timeout": 5,
    })]
    assert response.closed is True


def test_api_post_sends_json_and_closes_response(monkeypatch):
    response = Response(201, "created")
    calls = []
    requests = SimpleNamespace(
        post=lambda *args, **kwargs: calls.append((args, kwargs)) or response
    )
    api_module = load_api_module(monkeypatch, requests)
    api = api_module.API("secret", "https://bambuddy/api/v1")
    payload = {"printer_id": 7}

    result = api.api_post("printers/7/clear-plate", payload)

    assert result == (201, "created")
    assert calls[0][0] == ("https://bambuddy/api/v1/printers/7/clear-plate",)
    assert calls[0][1]["json"] == payload
    assert calls[0][1]["headers"] == {
        "X-API-Key": "secret",
        "Content-Type": "application/json",
    }
    assert response.closed is True


def test_api_urls_preserve_absolute_links_and_normalize_relative_paths(monkeypatch):
    api_module = load_api_module(monkeypatch, SimpleNamespace())
    api = api_module.API("key", "http://bambuddy/api/v1/")

    assert api.api_url("/printers") == "http://bambuddy/api/v1/printers"
    assert api.api_url("https://other.example/status") == (
        "https://other.example/status"
    )
