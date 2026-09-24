import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


MICRO_DIR = Path(__file__).parents[1] / "micro"


def load_bambuddy_api():
    previous_api = sys.modules.get("api")
    previous_requests = sys.modules.get("urequests")
    sys.modules["urequests"] = SimpleNamespace()
    try:
        api_spec = importlib.util.spec_from_file_location("api", MICRO_DIR / "api.py")
        api_module = importlib.util.module_from_spec(api_spec)
        sys.modules["api"] = api_module
        api_spec.loader.exec_module(api_module)

        bambuddy_spec = importlib.util.spec_from_file_location(
            "bambuddy_api_test_module", MICRO_DIR / "bambuddy_api.py"
        )
        bambuddy_module = importlib.util.module_from_spec(bambuddy_spec)
        bambuddy_spec.loader.exec_module(bambuddy_module)
        return bambuddy_module.BambuddyAPI, bambuddy_module.BambuddyAPIError
    finally:
        if previous_api is None:
            sys.modules.pop("api", None)
        else:
            sys.modules["api"] = previous_api
        if previous_requests is None:
            sys.modules.pop("urequests", None)
        else:
            sys.modules["urequests"] = previous_requests


BambuddyAPI, BambuddyAPIError = load_bambuddy_api()


def failure(error):
    def raise_error(printer_id):
        raise error

    return raise_error


def make_api(monkeypatch, clear, status=None):
    api = BambuddyAPI("key", "http://bambuddy/api/v1")
    monkeypatch.setattr(api, "clear_plate", clear)
    if status is not None:
        monkeypatch.setattr(api, "get_printer_status", status)
    return api


def test_successful_plate_clear_does_not_issue_a_status_request(monkeypatch):
    calls = []
    api = make_api(
        monkeypatch,
        lambda printer_id: calls.append(("clear", printer_id)),
        lambda printer_id: calls.append(("status", printer_id)),
    )

    outcome = api.clear_plate_with_reconciliation(7)

    assert outcome == {"resolved": True, "status": None, "request_error": None}
    assert calls == [("clear", 7)]


def test_rejected_clear_keeps_the_press_when_status_still_awaits_clear(monkeypatch):
    api = make_api(
        monkeypatch,
        failure(RuntimeError("request rejected")),
        lambda printer_id: {"awaiting_plate_clear": True, "chamber_light": True},
    )

    outcome = api.clear_plate_with_reconciliation(7)

    assert outcome["resolved"] is False
    assert outcome["status"]["awaiting_plate_clear"] is True
    assert str(outcome["request_error"]) == "request rejected"


def test_lost_response_is_resolved_without_a_duplicate_clear(monkeypatch):
    calls = []

    def lost_response(printer_id):
        calls.append(("clear", printer_id))
        raise TimeoutError("response lost after server applied request")

    def status(printer_id):
        calls.append(("status", printer_id))
        return {"awaiting_plate_clear": False, "chamber_light": False}

    api = make_api(monkeypatch, lost_response, status)

    outcome = api.clear_plate_with_reconciliation(7)

    assert outcome["resolved"] is True
    assert outcome["status"]["awaiting_plate_clear"] is False
    assert calls == [("clear", 7), ("status", 7)]


def test_press_can_be_retried_after_the_api_recovers(monkeypatch):
    clear_results = [RuntimeError("offline"), None]
    calls = []

    def clear(printer_id):
        calls.append(("clear", printer_id))
        result = clear_results.pop(0)
        if result:
            raise result

    api = make_api(
        monkeypatch,
        clear,
        lambda printer_id: {"awaiting_plate_clear": True, "chamber_light": False},
    )

    first = api.clear_plate_with_reconciliation(7)
    second = api.clear_plate_with_reconciliation(7)

    assert first["resolved"] is False
    assert second["resolved"] is True
    assert calls == [("clear", 7), ("clear", 7)]


def test_status_failure_does_not_assume_clear_succeeded(monkeypatch):
    api = make_api(
        monkeypatch,
        failure(RuntimeError("offline")),
        failure(RuntimeError("status unavailable")),
    )

    with pytest.raises(RuntimeError, match="status unavailable"):
        api.clear_plate_with_reconciliation(7)


def test_malformed_reconciliation_status_fails_closed(monkeypatch):
    api = make_api(
        monkeypatch,
        failure(RuntimeError("offline")),
        lambda printer_id: {"chamber_light": True},
    )

    with pytest.raises(BambuddyAPIError, match="verify plate-clear"):
        api.clear_plate_with_reconciliation(7)
