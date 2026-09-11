import runpy
from pathlib import Path


def test_release_gui_includes_all_micro_python_modules():
    project_root = Path(__file__).parents[1]
    build_script = runpy.run_path(str(project_root / "scripts" / "build_gui.py"))

    assert "web_config.py" in build_script["MICRO_FILES"]
    assert "config_example.json" in build_script["MICRO_FILES"]
