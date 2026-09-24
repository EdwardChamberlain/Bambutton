import base64
import hashlib
import json
import sys

from scripts import build_ota_bundle


def test_build_bundle_contains_hashable_allowlisted_application_files(monkeypatch, tmp_path):
    source = tmp_path / "micro"
    source.mkdir()
    for filename in build_ota_bundle.APP_FILES:
        (source / filename).write_bytes((filename + "\n").encode())
    monkeypatch.setattr(build_ota_bundle, "MICRO_DIR", source)

    result = build_ota_bundle.build_bundle("9.9.9", "notes")

    assert result["format"] == 1
    assert result["version"] == "9.9.9"
    assert set(result["files"]) == set(build_ota_bundle.APP_FILES)
    for filename, info in result["files"].items():
        content = base64.b64decode(info["content"])
        assert info["size"] == len(content)
        assert info["sha256"] == hashlib.sha256(content).hexdigest()


def test_build_bundle_cli_writes_the_requested_artifact(monkeypatch, tmp_path):
    source = tmp_path / "micro"
    source.mkdir()
    for filename in build_ota_bundle.APP_FILES:
        (source / filename).write_bytes((filename + "\n").encode())
    output = tmp_path / "release" / "bundle.json"
    monkeypatch.setattr(build_ota_bundle, "MICRO_DIR", source)
    monkeypatch.setattr(
        sys,
        "argv",
        ["build_ota_bundle.py", "--version", "1.2.3", "--output", str(output)],
    )

    build_ota_bundle.main()

    artifact = json.loads(output.read_text())
    assert artifact["version"] == "1.2.3"
    assert set(artifact["files"]) == set(build_ota_bundle.APP_FILES)
