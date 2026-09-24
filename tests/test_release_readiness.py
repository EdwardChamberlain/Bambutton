import json
import runpy
import sys
from pathlib import Path

import pytest

from scripts import verify_release_readiness


RECORD_PATH = Path(__file__).parents[1] / "docs" / "release-validation.json"
SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "verify_release_readiness.py"


def passing_record():
    return {
        "release_tag": "v1.0.0",
        "tested_at_utc": "2026-09-24T12:00:00Z",
        "tested_commit": "a" * 40,
        "board": "ESP32-C3 Super Mini revision A",
        "micropython_firmware": "ESP32_GENERIC_C3 v1.28.0",
        "result": "passed",
        "checks": {name: True for name in verify_release_readiness.REQUIRED_CHECKS},
    }


def test_release_record_must_match_tag_and_pass_every_check():
    record = passing_record()
    expected_commit = record["tested_commit"]

    assert verify_release_readiness.release_readiness_errors(
        record, "v1.0.0", expected_commit
    ) == []
    record["checks"]["web_ota_install"] = False

    errors = verify_release_readiness.release_readiness_errors(
        record, "v1.0.0", expected_commit
    )

    assert errors == ["check web_ota_install is incomplete"]
    assert verify_release_readiness.release_readiness_errors(
        passing_record(), "v1.0.1", expected_commit
    ) == ["release_tag must match v1.0.1"]
    assert verify_release_readiness.release_readiness_errors(
        passing_record(), "v1.0.0", "b" * 40
    ) == ["tested_commit must match the release commit"]


def test_pending_template_blocks_release_until_hardware_results_are_recorded():
    record = json.loads(RECORD_PATH.read_text())

    errors = verify_release_readiness.release_readiness_errors(
        record, "v1.0.0", "a" * 40
    )

    assert "result must be passed" in errors
    assert "check fresh_usb_install is incomplete" in errors
    assert "board must be recorded" in errors


def test_release_gate_cli_accepts_passing_record(tmp_path, monkeypatch, capsys):
    record_path = tmp_path / "release-validation.json"
    record_path.write_text(json.dumps(passing_record()))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "verify_release_readiness.py",
            "v1.0.0",
            "--expected-commit",
            "a" * 40,
            "--record",
            str(record_path),
        ],
    )

    runpy.run_path(str(SCRIPT_PATH), run_name="__main__")

    assert "passed for v1.0.0" in capsys.readouterr().out


def test_release_gate_cli_rejects_pending_record(tmp_path, monkeypatch):
    record_path = tmp_path / "release-validation.json"
    record_path.write_text(json.dumps({"result": "pending"}))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "verify_release_readiness.py",
            "v1.0.0",
            "--expected-commit",
            "a" * 40,
            "--record",
            str(record_path),
        ],
    )

    with pytest.raises(SystemExit) as error:
        runpy.run_path(str(SCRIPT_PATH), run_name="__main__")

    assert error.value.code == 1
