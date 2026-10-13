from pathlib import Path, PurePosixPath
import tomllib

from scripts import build_gui


PROJECT_ROOT = Path(__file__).parents[1]


def test_project_metadata_and_archives_declare_and_include_licence():
    with (PROJECT_ROOT / "pyproject.toml").open("rb") as source:
        project = tomllib.load(source)

    metadata = project["project"]
    assert metadata["license"] == "MIT"
    assert "LICENSE" in metadata["license-files"]
    urls = metadata["urls"]
    url_keys = (
        "Homepage",
        "Repository",
        "Documentation",
        "Issues",
        "Support",
        "Changelog",
    )
    for key in url_keys:
        assert urls[key].startswith("https://github.com/EdwardChamberlain/Bambutton")

    wheel_files = project["tool"]["hatch"]["build"]["targets"]["wheel"][
        "force-include"
    ]
    assert wheel_files["LICENSE"] == "bambutton/LICENSE"
    assert wheel_files["THIRD_PARTY_NOTICES.md"] == "bambutton/THIRD_PARTY_NOTICES.md"
    assert wheel_files["THIRD_PARTY_LICENSES"] == "bambutton/third_party_licenses"
    assert wheel_files["firmware"] == "bambutton/firmware"

    source_files = project["tool"]["hatch"]["build"]["targets"]["sdist"]["include"]
    assert "/LICENSE" in source_files
    assert "/THIRD_PARTY_NOTICES.md" in source_files
    assert "/THIRD_PARTY_LICENSES" in source_files
    assert "/firmware" in source_files


def test_desktop_build_collects_actual_runtime_dependency_licences(tmp_path, monkeypatch):
    class Distribution:
        def __init__(self, name, files=(), requires=(), license_text=""):
            self.root = tmp_path / name
            self.root.mkdir()
            self.files = []
            for relative, content in files:
                file_path = self.root / relative
                file_path.parent.mkdir(parents=True, exist_ok=True)
                file_path.write_text(content, encoding="utf-8")
                self.files.append(PurePosixPath(relative))
            self.requires = list(requires)
            self.metadata = {"License": license_text}

        def locate_file(self, file):
            return self.root / str(file)

    distributions = {
        "esptool": Distribution(
            "esptool",
            files=(("esptool-5.2.0.dist-info/licenses/LICENSE.txt", "GPL terms"),),
            requires=(
                "pyserial>=3.3; python_version >= '3.11'",
                "dev-only; extra == 'dev'",
            ),
        ),
        "freesimplegui": Distribution(
            "freesimplegui",
            files=(("NOTICE", "FreeSimpleGUI attribution"),),
            license_text="Full LGPL terms " + ("L" * 900),
        ),
        "mpremote": Distribution(
            "mpremote", files=(("licenses/LICENSE.txt", "mpremote MIT terms"),)
        ),
        "pyserial": Distribution("pyserial", license_text="BSD License"),
        "dev-only": Distribution("dev-only"),
    }

    def get_distribution(name):
        try:
            return distributions[name.lower().replace("_", "-")]
        except KeyError as exc:
            raise build_gui.metadata.PackageNotFoundError(name) from exc

    monkeypatch.setattr(build_gui.metadata, "distribution", get_distribution)
    monkeypatch.setattr(
        build_gui,
        "RUNTIME_DISTRIBUTIONS",
        ("esptool", "FreeSimpleGUI", "mpremote"),
    )
    monkeypatch.setattr(build_gui, "PYINSTALLER_CONFIG_DIR", tmp_path / "cache")

    args = build_gui.third_party_license_data_args()

    joined_args = "\n".join(args)
    assert "bambutton/third_party_licenses/esptool/esptool-5.2.0.dist-info/licenses" in joined_args
    assert "bambutton/third_party_licenses/freesimplegui" in joined_args
    assert "bambutton/third_party_licenses/mpremote/licenses" in joined_args
    assert "bambutton/third_party_licenses/pyserial" in joined_args
    assert "dev-only" not in joined_args
    generated_license = (
        tmp_path / "cache" / "licenses" / "freesimplegui" / "LICENSE-METADATA.txt"
    )
    assert generated_license.read_text(encoding="utf-8").startswith("Full LGPL terms")
    assert "pyserial-3.5-LICENSE.txt" in joined_args


def test_firmware_and_application_notice_files_exist():
    assert (PROJECT_ROOT / "LICENSE").read_text().startswith("MIT License\n")
    notices = (PROJECT_ROOT / "THIRD_PARTY_NOTICES.md").read_text()
    assert "GPL-2.0-or-later" in notices
    assert "pyserial" in notices
    firmware_notices = (PROJECT_ROOT / "firmware" / "THIRD_PARTY_NOTICES.md").read_text()
    assert "v1.28.0" in firmware_notices
    assert "v5.5.1" in firmware_notices
    assert "Firmware Components" in (
        PROJECT_ROOT
        / "firmware"
        / "LICENSES"
        / "ESP-IDF-COPYRIGHT-v5.5.1.rst"
    ).read_text()
    assert "Copyright (c) 2001-2020 Chris Liechti" in (
        PROJECT_ROOT / "THIRD_PARTY_LICENSES" / "pyserial-3.5-LICENSE.txt"
    ).read_text()


def test_release_workflow_publishes_matching_esptool_source_archive():
    workflow = (PROJECT_ROOT / ".github" / "workflows" / "release.yml").read_text()
    assert "Download corresponding esptool source archive" in workflow
    assert "--no-binary=:all:" in workflow
    assert "esptool==" in workflow


def test_open_legal_document_uses_the_default_browser(tmp_path, monkeypatch):
    path = tmp_path / "LICENSE"
    path.write_text("terms")
    opened = []
    import bambutton.gui as gui

    monkeypatch.setattr(gui.webbrowser, "open", lambda uri: opened.append(uri) or True)

    gui.open_legal_document({}, path)

    assert opened == [path.resolve().as_uri()]
