import base64
import hashlib
import json

import pytest

from micro import ota_manager


def bundle(version="1.2.3", files=None):
    complete_files = {
        name: (name + "\n").encode()
        for name in ota_manager.APP_FILES
    }
    complete_files["app_main.py"] = b"print('new app')\n"
    complete_files["web_config.py"] = b"WEB_VERSION = 'new'\n"
    complete_files.update(files or {})
    encoded = {}
    for name, content in complete_files.items():
        encoded[name] = {
            "size": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
            "content": base64.b64encode(content).decode("ascii"),
        }
    return {
        "format": 1,
        "version": version,
        "minimum_bootloader": 1,
        "release_notes": "test release",
        "files": encoded,
    }


def test_stage_and_commit_use_inactive_slot_and_preserve_config(tmp_path):
    config = tmp_path / "config.json"
    config.write_text('{"wifi":{"ssid":"keep-me"}}\n')
    manager = ota_manager.OTAUpdateManager(root=str(tmp_path))

    staged = manager.stage_bundle(bundle())

    assert staged["staged_slot"] == "app_a"
    assert (tmp_path / ".bambutton/app_a/app_main.py").read_bytes() == b"print('new app')\n"
    assert config.read_text() == '{"wifi":{"ssid":"keep-me"}}\n'
    assert not (tmp_path / ".bambutton/active.json").exists()

    manager.commit_staged()

    assert manager.status()["active_slot"] == "app_a"
    assert manager.status()["pending"]["candidate"] == "app_a"


def test_legacy_migration_copies_root_files_before_switching_pointer(tmp_path):
    for filename in ota_manager.APP_FILES:
        (tmp_path / filename).write_bytes((filename + "\n").encode())
    manager = ota_manager.OTAUpdateManager(root=str(tmp_path))

    assert manager.migrate_legacy() is True
    assert manager.status()["active_slot"] == "app_a"
    assert manager.status()["pending"]["candidate"] == "app_a"
    for filename in ota_manager.APP_FILES:
        assert (tmp_path / ".bambutton/app_a" / filename).read_bytes() == (
            filename + "\n"
        ).encode()


def test_confirmed_candidate_clears_pending_state(tmp_path):
    manager = ota_manager.OTAUpdateManager(root=str(tmp_path))
    manager.stage_bundle(bundle())
    manager.commit_staged()

    assert manager.confirm_boot() is True
    assert not (tmp_path / ".bambutton/pending.json").exists()
    assert manager.status()["pending"] is None


def test_unconfirmed_candidate_rolls_back_before_launch(tmp_path):
    resets = []
    manager = ota_manager.OTAUpdateManager(
        root=str(tmp_path),
        reset=lambda: resets.append(True),
    )
    manager.stage_bundle(bundle())
    manager.commit_staged()

    manager.launch()
    with pytest.raises(ota_manager.OTAError, match="rollback"):
        manager.launch()

    assert resets == [True]
    assert manager.status()["active_slot"] is None
    assert manager.status()["last_error"]["candidate"] == "app_a"


def test_candidate_import_error_rolls_back_immediately(tmp_path, monkeypatch):
    resets = []
    manager = ota_manager.OTAUpdateManager(
        root=str(tmp_path),
        reset=lambda: resets.append(True),
    )
    manager.stage_bundle(bundle(files={
        "app_main.py": b"raise RuntimeError('broken candidate')\n",
        "web_config.py": b"WEB = True\n",
    }))
    manager.commit_staged()
    monkeypatch.delitem(__import__("sys").modules, "app_main", raising=False)

    with pytest.raises(ota_manager.OTAError, match="rollback"):
        manager.launch()

    assert resets == [True]
    assert manager.status()["active_slot"] is None


def test_bootstrap_candidate_failure_returns_to_legacy_main(tmp_path, monkeypatch):
    bootstrap = tmp_path / ".bambutton/bootstrap"
    bootstrap.mkdir(parents=True)
    for filename in ota_manager.APP_FILES:
        content = (filename + "\n").encode()
        if filename == "app_main.py":
            content = b"raise RuntimeError('broken bootstrap')\n"
        (bootstrap / filename).write_bytes(content)
    (bootstrap / "main.py").write_text("stable loader\n")
    (tmp_path / "main.py").write_text("LEGACY_BOOTED = True\n")

    resets = []
    monkeypatch.delitem(__import__("sys").modules, "app_main", raising=False)
    monkeypatch.syspath_prepend(str(tmp_path))
    manager = ota_manager.OTAUpdateManager(
        root=str(tmp_path),
        reset=lambda: resets.append(True),
    )

    with pytest.raises(ota_manager.OTAError, match="rollback"):
        manager.launch()

    assert resets == [True]
    assert manager.status()["active_slot"] is None
    assert manager._read_active()["legacy_entry"] == "main"

    monkeypatch.delitem(__import__("sys").modules, "main", raising=False)
    manager.reset = None
    manager._launch_legacy()
    assert __import__("main").LEGACY_BOOTED is True


def test_failed_replacement_does_not_modify_active_slot(tmp_path):
    manager = ota_manager.OTAUpdateManager(root=str(tmp_path))
    manager.stage_bundle(bundle("1.0.0"))
    manager.commit_staged()
    manager.confirm_boot()
    active_content = (tmp_path / ".bambutton/app_a/app_main.py").read_bytes()

    invalid = bundle("2.0.0")
    invalid["files"]["app_main.py"]["sha256"] = "0" * 64
    with pytest.raises(ota_manager.OTAError, match="checksum"):
        manager.stage_bundle(invalid)

    assert (tmp_path / ".bambutton/app_a/app_main.py").read_bytes() == active_content
    assert manager.status()["active_slot"] == "app_a"
    assert "checksum" in manager.status()["last_error"]["message"]


def test_pointer_records_ignore_an_interrupted_new_record(tmp_path):
    manager = ota_manager.OTAUpdateManager(root=str(tmp_path))
    manager.stage_bundle(bundle("1.0.0"))
    manager.commit_staged()
    manager.confirm_boot()

    active_records = sorted((tmp_path / ".bambutton").glob("active.*.json"))
    assert active_records
    (tmp_path / ".bambutton/active.999999.json").write_text('{"slot":')

    assert manager.status()["active_slot"] == "app_a"


def test_bootstrap_migration_uses_staged_files_and_cleans_up(tmp_path, monkeypatch):
    bootstrap = tmp_path / ".bambutton/bootstrap"
    bootstrap.mkdir(parents=True)
    for filename in ota_manager.APP_FILES:
        content = (filename + "\n").encode()
        if filename == "app_main.py":
            content = b"BOOTSTRAPPED = True\n"
        (bootstrap / filename).write_bytes(content)
    (tmp_path / ".bambutton/bootstrap-install.marker").write_text(
        "bambutton-bootstrap-v1\n"
    )

    monkeypatch.delitem(__import__("sys").modules, "app_main", raising=False)
    manager = ota_manager.OTAUpdateManager(root=str(tmp_path))
    manager.launch()

    assert manager.status()["active_slot"] == "app_a"
    assert not bootstrap.exists()
    assert not (tmp_path / ".bambutton/bootstrap-install.marker").exists()
    assert (tmp_path / ".bambutton/app_a/app_main.py").read_bytes() == (
        b"BOOTSTRAPPED = True\n"
    )


@pytest.mark.parametrize(
    "filename",
    ["../config.json", "nested/app_main.py", "main.py", "ota_manager.py"],
)
def test_bundle_rejects_files_outside_application_allowlist(filename):
    with pytest.raises(ota_manager.OTAError, match="allowlisted"):
        ota_manager.validate_bundle(bundle(files={
            "app_main.py": b"ok",
            "web_config.py": b"ok",
            filename: b"bad",
        }))


def test_remote_check_uses_https_and_same_staging_pipeline(tmp_path):
    payload = json.dumps(bundle("3.0.0"))

    class Response:
        status_code = 200
        text = payload

        def close(self):
            self.closed = True

    requested = []
    manager = ota_manager.OTAUpdateManager(
        root=str(tmp_path),
        request_get=lambda url: requested.append(url) or Response(),
    )

    status = manager.check_remote("https://updates.example.test/bambutton-ota.json")

    assert requested == ["https://updates.example.test/bambutton-ota.json"]
    assert status["staged_slot"] == "app_a"

    with pytest.raises(ota_manager.OTAError, match="HTTPS"):
        manager.check_remote("http://updates.example.test/bambutton-ota.json")
