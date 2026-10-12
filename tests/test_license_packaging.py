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

    source_files = project["tool"]["hatch"]["build"]["targets"]["sdist"]["include"]
    assert "/LICENSE" in source_files
    assert "/THIRD_PARTY_NOTICES.md" in source_files


def test_desktop_build_collects_runtime_dependency_licences(tmp_path, monkeypatch):
    class Distribution:
        def __init__(self, name, requires=()):
            self.root = tmp_path / name
            self.root.mkdir()
            self.license_file = self.root / "licenses" / "LICENSE.txt"
            self.license_file.parent.mkdir()
            self.license_file.write_text("upstream licence")
            self.files = [PurePosixPath("licenses/LICENSE.txt")]
            self.requires = list(requires)

        def locate_file(self, file):
            return self.root / str(file)

    distributions = {
        "esptool": Distribution("esptool", ("cryptography>=1",)),
        "freesimplegui": Distribution("freesimplegui"),
        "mpremote": Distribution("mpremote"),
        "cryptography": Distribution("cryptography"),
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

    args = build_gui.third_party_license_data_args()

    assert len(args) == 8
    joined_args = "\n".join(args)
    assert "bambutton/third_party_licenses/esptool/LICENSE.txt" in joined_args
    assert "bambutton/third_party_licenses/cryptography/LICENSE.txt" in joined_args
    assert "bambutton/third_party_licenses/freesimplegui/LICENSE.txt" in joined_args
    assert "bambutton/third_party_licenses/mpremote/LICENSE.txt" in joined_args


def test_firmware_and_application_notice_files_exist():
    assert (PROJECT_ROOT / "LICENSE").read_text().startswith("MIT License\n")
    notices = (PROJECT_ROOT / "THIRD_PARTY_NOTICES.md").read_text()
    assert "GPL-2.0-or-later" in notices
    assert "v1.28.0" in (PROJECT_ROOT / "firmware" / "THIRD_PARTY_NOTICES.md").read_text()


def test_open_legal_document_uses_the_default_browser(tmp_path, monkeypatch):
    path = tmp_path / "LICENSE"
    path.write_text("terms")
    opened = []
    import bambutton.gui as gui

    monkeypatch.setattr(gui.webbrowser, "open", lambda uri: opened.append(uri) or True)

    gui.open_legal_document({}, path)

    assert opened == [path.resolve().as_uri()]
