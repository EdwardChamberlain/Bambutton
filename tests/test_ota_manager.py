import base64
import hashlib
import json

import pytest

from micro import ota_manager


def bundle(version="1.2.3", files=None):
    files = files or {
        "app_main.py": b"print('new app')\n",
        "web_config.py": b"WEB_VERSION = 'new'\n",
    }
    encoded = {}
    for name, content in files.items():
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

    assert json.loads((tmp_path / ".bambutton/active.json").read_text()) == {
        "slot": "app_a"
    }
    assert json.loads((tmp_path / ".bambutton/pending.json").read_text())["candidate"] == "app_a"


def test_legacy_migration_copies_root_files_before_switching_pointer(tmp_path):
    for filename in ota_manager.APP_FILES:
        (tmp_path / filename).write_bytes((filename + "\n").encode())
    manager = ota_manager.OTAUpdateManager(root=str(tmp_path))

    assert manager.migrate_legacy() is True
    assert json.loads((tmp_path / ".bambutton/active.json").read_text()) == {
        "slot": "app_a"
    }
    assert json.loads((tmp_path / ".bambutton/pending.json").read_text())["previous"] is None
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
    assert not (tmp_path / ".bambutton/active.json").exists()
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
