import base64
import hashlib
import json
from pathlib import Path

import pytest

from micro import ota_manager
from scripts import build_ota_bundle, validate_ota_bundle


def file_info(content):
    return {
        "size": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "content": base64.b64encode(content).decode("ascii"),
    }


def write_artifact(path, bundle):
    path.write_text(json.dumps(bundle, indent=2) + "\n", encoding="utf-8")


def test_current_release_candidate_artifact_passes_device_validation(tmp_path):
    artifact_path = tmp_path / "bambutton-ota.json"
    write_artifact(artifact_path, build_ota_bundle.build_bundle("1.0.0"))

    validated = validate_ota_bundle.validate_ota_artifact(artifact_path)

    assert validated["version"] == "1.0.0"
    assert len(artifact_path.read_bytes()) <= ota_manager.MAX_BUNDLE_BODY_BYTES
    assert (Path(__file__).parents[1] / "micro" / "web_config.py").stat().st_size < (
        ota_manager.MAX_FILE_BYTES
    )


def test_device_validator_allows_web_ui_growth_past_previous_limit():
    bundle = build_ota_bundle.build_bundle("1.0.1")
    larger_ui = b"x" * (32 * 1024 + 1)
    bundle["files"]["web_config.py"] = file_info(larger_ui)

    validated = ota_manager.validate_bundle(bundle)

    assert validated["files"]["web_config.py"]["size"] == 32 * 1024 + 1


def test_device_validator_rejects_file_over_new_limit():
    bundle = build_ota_bundle.build_bundle("1.0.1")
    bundle["files"]["web_config.py"] = file_info(
        b"x" * (ota_manager.MAX_FILE_BYTES + 1)
    )

    with pytest.raises(ota_manager.OTAError, match="file is too large"):
        ota_manager.validate_bundle(bundle)


def test_new_maximum_web_ui_fits_download_payload_limit(tmp_path):
    artifact_path = tmp_path / "largest-web-ui.json"
    bundle = build_ota_bundle.build_bundle("1.0.1")
    bundle["files"]["web_config.py"] = file_info(
        b"x" * ota_manager.MAX_FILE_BYTES
    )
    write_artifact(artifact_path, bundle)

    validated = validate_ota_bundle.validate_ota_artifact(artifact_path)

    assert validated["files"]["web_config.py"]["size"] == (
        ota_manager.MAX_FILE_BYTES
    )
    assert artifact_path.stat().st_size <= ota_manager.MAX_BUNDLE_BODY_BYTES


def test_release_validator_rejects_oversized_json_artifact(tmp_path):
    artifact_path = tmp_path / "oversized.json"
    write_artifact(
        artifact_path,
        build_ota_bundle.build_bundle("1.0.0", "n" * ota_manager.MAX_BUNDLE_BODY_BYTES),
    )

    with pytest.raises(ota_manager.OTAError, match="payload limit"):
        validate_ota_bundle.validate_ota_artifact(artifact_path)


def test_release_validator_rejects_malformed_json(tmp_path):
    artifact_path = tmp_path / "malformed.json"
    artifact_path.write_text('{"format":', encoding="utf-8")

    with pytest.raises(ota_manager.OTAError, match="valid JSON"):
        validate_ota_bundle.validate_ota_artifact(artifact_path)


def test_release_validator_rejects_incomplete_bundle(tmp_path):
    artifact_path = tmp_path / "incomplete.json"
    bundle = build_ota_bundle.build_bundle("1.0.0")
    del bundle["files"]["wifi.py"]
    write_artifact(artifact_path, bundle)

    with pytest.raises(ota_manager.OTAError, match="missing: wifi.py"):
        validate_ota_bundle.validate_ota_artifact(artifact_path)
