import hashlib
import json
import runpy
import sys
from pathlib import Path

import pytest

from scripts import verify_release_artifacts, verify_release_readiness


RECORD_PATH = Path(__file__).parents[1] / "docs" / "release-validation.json"
SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "verify_release_readiness.py"


def passing_record():
    return {
        "candidate_version": "1.0.0",
        "release_tag": "v1.0.0",
        "tested_at_utc": "2026-09-24T12:00:00Z",
        "tested_commit": "a" * 40,
        "board": "ESP32-C3 Super Mini revision A",
        "micropython_firmware": "ESP32_GENERIC_C3 v1.28.0",
        "result": "passed",
        "artifacts": {
            name: "a" * 64
            for name in verify_release_readiness.REQUIRED_ARTIFACT_HASHES
        },
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
    ) == [
        "release_tag must match v1.0.1",
        "candidate_version must match v1.0.1",
    ]
    assert verify_release_readiness.release_readiness_errors(
        passing_record(), "v1.0.0", "b" * 40
    ) == ["tested_commit must match the release commit"]
    record = passing_record()
    record["candidate_version"] = "1.0.1"
    assert verify_release_readiness.release_readiness_errors(
        record, "v1.0.0", record["tested_commit"]
    ) == ["candidate_version must match v1.0.0"]


def test_pending_template_blocks_release_until_hardware_results_are_recorded():
    record = json.loads(RECORD_PATH.read_text())

    errors = verify_release_readiness.release_readiness_errors(
        record, "v1.0.0", "a" * 40
    )

    assert "result must be passed" in errors
    assert "check fresh_usb_install is incomplete" in errors
    assert "board must be recorded" in errors
    assert "artifact windows_setup_tool_sha256 must record a SHA-256 digest" in errors


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


def test_release_artifacts_must_match_tested_sha256_digests(tmp_path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    contents = {
        "Bambutton-windows.zip": b"windows candidate",
        "Bambutton-macos.zip": b"macOS candidate",
        "bambutton-ota.json": b"OTA candidate",
    }
    record = {"artifacts": {}}
    for name, content in contents.items():
        (artifacts / name).write_bytes(content)
    for field, filename in verify_release_artifacts.ARTIFACTS.items():
        record["artifacts"][field] = hashlib.sha256(contents[filename]).hexdigest()

    assert verify_release_artifacts.release_artifact_errors(record, artifacts) == []
    (artifacts / "Bambutton-windows.zip").write_bytes(b"changed after test")
    errors = verify_release_artifacts.release_artifact_errors(record, artifacts)

    assert errors == [
        "release candidate artifact digest does not match: Bambutton-windows.zip"
    ]


def test_release_artifact_verifier_reports_missing_assets_and_hashes(tmp_path):
    errors = verify_release_artifacts.release_artifact_errors(
        {"artifacts": {}}, tmp_path
    )

    assert len(errors) == len(verify_release_artifacts.ARTIFACTS)
    assert all("must record a SHA-256 digest" in error for error in errors)


def test_release_artifact_verifier_reports_missing_candidate_file(tmp_path):
    record = {
        "artifacts": {
            name: "a" * 64
            for name in verify_release_artifacts.ARTIFACTS
        },
    }

    errors = verify_release_artifacts.release_artifact_errors(record, tmp_path)

    assert len(errors) == len(verify_release_artifacts.ARTIFACTS)
    assert all("release candidate artifact is missing" in error for error in errors)
