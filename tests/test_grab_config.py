import subprocess
import sys
from pathlib import Path

import pytest

from scripts import grab_config


@pytest.fixture
def project_root(tmp_path, monkeypatch):
    root = tmp_path / "checkout with spaces"
    root.mkdir()
    monkeypatch.setattr(grab_config, "PROJECT_ROOT", root)
    monkeypatch.chdir(tmp_path)
    return root


@pytest.mark.parametrize("device", [None, "/dev/tty.example", "COM4"])
def test_grab_copies_remote_config_to_project_folder(
    project_root, monkeypatch, capsys, device
):
    contents = b'{\r\n  "wifi": {"password": "private-secret"}\r\n}\r\n'
    calls = []

    def download(command, check):
        assert check is True
        calls.append(command)
        Path(command[-1]).write_bytes(contents)

    monkeypatch.setattr(grab_config.subprocess, "run", download)
    argv = ["grab_config.py"]
    if device:
        argv.extend(["--device", device])
    monkeypatch.setattr(sys, "argv", argv)

    grab_config.main()

    captures = list((project_root / "grabbed configs").glob("*.json"))
    assert len(captures) == 1
    assert captures[0].read_bytes() == contents
    prefix = ["mpremote", "connect", device] if device else ["mpremote"]
    assert calls == [prefix + ["cp", ":config.json", str(captures[0])]]
    output = capsys.readouterr().out
    assert "Saved configuration to {}".format(captures[0]) in output
    assert "private-secret" not in output


def test_repeated_grabs_preserve_captures_and_local_config(project_root, monkeypatch):
    local_config = project_root / "micro" / "config.json"
    local_config.parent.mkdir()
    local_config.write_bytes(b"local settings")
    contents = iter([b"first board config", b"second board config"])

    def download(command, check):
        Path(command[-1]).write_bytes(next(contents))

    monkeypatch.setattr(grab_config.subprocess, "run", download)
    monkeypatch.setattr(sys, "argv", ["grab_config.py"])

    grab_config.main()
    grab_config.main()

    captures = list((project_root / "grabbed configs").glob("*.json"))
    assert len(captures) == 2
    assert {path.read_bytes() for path in captures} == {
        b"first board config", b"second board config",
    }
    assert local_config.read_bytes() == b"local settings"


@pytest.mark.parametrize(
    "failure",
    [FileNotFoundError("mpremote unavailable"), subprocess.CalledProcessError(1, ["mpremote"])],
)
def test_failed_grab_removes_partial_download(project_root, monkeypatch, capsys, failure):
    def download(command, check):
        Path(command[-1]).write_bytes(b"partial config")
        raise failure

    monkeypatch.setattr(grab_config.subprocess, "run", download)
    monkeypatch.setattr(sys, "argv", ["grab_config.py"])

    with pytest.raises(SystemExit) as exc:
        grab_config.main()

    assert exc.value.code == 1
    assert list((project_root / "grabbed configs").iterdir()) == []
    output = capsys.readouterr()
    assert "Could not grab config.json" in output.err
    assert "Saved configuration" not in output.out


def test_interrupted_grab_removes_partial_download(project_root, monkeypatch):
    def download(command, check):
        Path(command[-1]).write_bytes(b"partial config")
        raise KeyboardInterrupt

    monkeypatch.setattr(grab_config.subprocess, "run", download)
    monkeypatch.setattr(sys, "argv", ["grab_config.py"])

    with pytest.raises(KeyboardInterrupt):
        grab_config.main()

    assert list((project_root / "grabbed configs").iterdir()) == []


def test_output_directory_error_stops_before_contacting_board(project_root, monkeypatch, capsys):
    (project_root / "grabbed configs").write_text("not a directory")

    def unexpected_download(*args, **kwargs):
        pytest.fail("Output preparation must succeed before contacting the board")

    monkeypatch.setattr(grab_config.subprocess, "run", unexpected_download)
    monkeypatch.setattr(sys, "argv", ["grab_config.py"])

    with pytest.raises(SystemExit) as exc:
        grab_config.main()

    assert exc.value.code == 1
    assert "Could not prepare config download" in capsys.readouterr().err
