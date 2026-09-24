import runpy
from pathlib import Path
import tomllib


def test_release_gui_includes_all_micro_python_modules():
    project_root = Path(__file__).parents[1]
    build_script = runpy.run_path(str(project_root / "scripts" / "build_gui.py"))

    assert "web_config.py" in build_script["MICRO_FILES"]
    assert "boot.py" in build_script["MICRO_FILES"]
    assert "app_main.py" in build_script["MICRO_FILES"]
    assert "ota_manager.py" in build_script["MICRO_FILES"]
    assert "config_example.json" in build_script["MICRO_FILES"]


def test_desktop_and_python_packages_include_all_runtime_files():
    project_root = Path(__file__).parents[1]
    build_script = runpy.run_path(str(project_root / "scripts" / "build_gui.py"))
    pyproject = tomllib.loads((project_root / "pyproject.toml").read_text())
    runtime_files = {
        path.name for path in (project_root / "micro").iterdir()
        if path.suffix == ".py"
    } | {"config_example.json"}

    assert set(build_script["MICRO_FILES"]) == runtime_files

    wheel_files = pyproject["tool"]["hatch"]["build"]["targets"]["wheel"][
        "force-include"
    ]
    wheel_micro_files = {
        Path(source).name for source in wheel_files
        if source.startswith("micro/")
    }
    assert wheel_micro_files == runtime_files

    sdist_files = set(pyproject["tool"]["hatch"]["build"]["targets"]["sdist"][
        "include"
    ])
    assert {"/micro/" + filename for filename in runtime_files} <= sdist_files
