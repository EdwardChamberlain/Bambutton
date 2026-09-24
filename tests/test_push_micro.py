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


def test_bootstrap_commit_hands_off_legacy_main_to_stable_loader(tmp_path, monkeypatch):
    bootstrap = tmp_path / ".bambutton/bootstrap"
    bootstrap.mkdir(parents=True)
    for filename in (
        "api.py",
        "app_main.py",
        "bambuddy_api.py",
        "boot.py",
        "config_loader.py",
        "gpio_button.py",
        "led_flasher.py",
        "main.py",
        "ota_manager.py",
        "periodic_timer.py",
        "web_config.py",
        "wifi.py",
    ):
        (bootstrap / filename).write_text(filename)
    legacy_main = tmp_path / "main.py"
    legacy_main.write_text("legacy application")

    monkeypatch.chdir(tmp_path)
    exec(push_micro.BOOTSTRAP_COMMIT_CODE, {})

    assert not legacy_main.exists()
    assert (tmp_path / ".bambutton/legacy_main.py").read_text() == "legacy application"
    assert (tmp_path / "main.py").read_text() == "main.py"
    assert (tmp_path / "boot.py").read_text() == "boot.py"
    assert (tmp_path / "ota_manager.py").read_text() == "ota_manager.py"


def test_bootstrap_commit_recovers_after_manager_was_installed_first(tmp_path, monkeypatch):
    bootstrap = tmp_path / ".bambutton/bootstrap"
    bootstrap.mkdir(parents=True)
    for filename in (
        "api.py",
        "app_main.py",
        "bambuddy_api.py",
        "boot.py",
        "config_loader.py",
        "gpio_button.py",
        "led_flasher.py",
        "main.py",
        "ota_manager.py",
        "periodic_timer.py",
        "web_config.py",
        "wifi.py",
    ):
        (bootstrap / filename).write_text("new " + filename)
    (tmp_path / "main.py").write_text("legacy application")
    (tmp_path / "ota_manager.py").write_text("partial manager")
    (tmp_path / ".bambutton/bootstrap-install.marker").write_text(
        "bambutton-bootstrap-v1\n"
    )

    monkeypatch.chdir(tmp_path)
    marker_writes = []
    real_open = open

    def tracked_open(path, mode="r", *args, **kwargs):
        if path == ".bambutton/bootstrap-install.marker" and "w" in mode:
            marker_writes.append(path)
        return real_open(path, mode, *args, **kwargs)

    exec(push_micro.BOOTSTRAP_COMMIT_CODE, {"open": tracked_open})

    assert (tmp_path / "ota_manager.py").read_text() == "new ota_manager.py"
    assert (tmp_path / "boot.py").read_text() == "new boot.py"
    assert (tmp_path / "main.py").read_text() == "new main.py"
    assert (tmp_path / ".bambutton/legacy_main.py").read_text() == "legacy application"
    assert marker_writes == []
    assert (tmp_path / ".bambutton/bootstrap-install.marker").read_text() == (
        "bambutton-bootstrap-v1\n"
    )
