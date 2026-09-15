import sys

from scripts import push_micro


def test_push_micro_stages_runtime_before_installing_bootloader(tmp_path, monkeypatch):
    micro_dir = tmp_path / "micro"
    micro_dir.mkdir()
    for filename in ("app_main.py", "boot.py", "main.py", "ota_manager.py", "web_config.py"):
        (micro_dir / filename).write_text(filename)
    config = micro_dir / "config.json"
    config.write_text("{}")
    calls = []

    monkeypatch.setattr(push_micro, "MICRO_DIR", micro_dir)
    monkeypatch.setattr(push_micro, "CONFIG_FILE", config)
    monkeypatch.setattr(push_micro, "run", lambda command: calls.append(command))
    monkeypatch.setattr(sys, "argv", ["push_micro.py", "--clean"])

    push_micro.main()

    assert calls[0][0:2] == ["mpremote", "exec"]
    assert calls[1][0:2] == ["mpremote", "exec"]
    staged_paths = [call[-1] for call in calls[2:8]]
    assert staged_paths == [
        ":.bambutton/bootstrap/app_main.py",
        ":.bambutton/bootstrap/boot.py",
        ":.bambutton/bootstrap/main.py",
        ":.bambutton/bootstrap/ota_manager.py",
        ":.bambutton/bootstrap/web_config.py",
        ":.bambutton/bootstrap/config.json",
    ]
    assert calls[8][0:2] == ["mpremote", "exec"]
    assert calls[9] == ["mpremote", "reset"]


def test_push_micro_no_main_keeps_development_path_without_boot(tmp_path, monkeypatch):
    micro_dir = tmp_path / "micro"
    micro_dir.mkdir()
    for filename in ("app_main.py", "boot.py", "main.py", "ota_manager.py"):
        (micro_dir / filename).write_text(filename)
    config = micro_dir / "config.json"
    config.write_text("{}")
    calls = []

    monkeypatch.setattr(push_micro, "MICRO_DIR", micro_dir)
    monkeypatch.setattr(push_micro, "CONFIG_FILE", config)
    monkeypatch.setattr(push_micro, "run", lambda command: calls.append(command))
    monkeypatch.setattr(sys, "argv", ["push_micro.py", "--no-main"])

    push_micro.main()

    copied = [call[-1] for call in calls if call[1:2] == ["cp"]]
    assert copied == [":", ":", ":config.json"]
    assert all("boot.py" not in " ".join(call) for call in calls)


def test_bootstrap_commit_preserves_legacy_main_until_boot_hook_is_ready(tmp_path, monkeypatch):
    bootstrap = tmp_path / ".bambutton/bootstrap"
    bootstrap.mkdir(parents=True)
    for filename in ("app_main.py", "boot.py", "ota_manager.py", "web_config.py"):
        (bootstrap / filename).write_text(filename)
    legacy_main = tmp_path / "main.py"
    legacy_main.write_text("legacy application")

    monkeypatch.chdir(tmp_path)
    exec(push_micro.BOOTSTRAP_COMMIT_CODE, {})

    assert legacy_main.read_text() == "legacy application"
    assert (tmp_path / "boot.py").read_text() == "boot.py"
    assert (tmp_path / "ota_manager.py").read_text() == "ota_manager.py"
