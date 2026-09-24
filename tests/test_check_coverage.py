import json

from scripts import check_coverage


def test_coverage_gate_requires_each_shipped_file_and_total_to_meet_floor(
    tmp_path, monkeypatch
):
    source = tmp_path / "micro"
    source.mkdir()
    module = source / "runtime.py"
    module.write_text("print('runtime')\n")
    report = tmp_path / "coverage.json"
    report.write_text(json.dumps({
        "files": {
            "micro/runtime.py": {
                "summary": {"percent_covered": 30.0},
            },
        },
        "totals": {"percent_covered": 71.0},
    }))
    monkeypatch.setattr(check_coverage, "SOURCE_DIRECTORIES", ("micro",))

    errors, total = check_coverage.audit_coverage(report, tmp_path)

    assert errors == []
    assert total == 71.0


def test_coverage_gate_reports_uncovered_module_and_low_total(
    tmp_path, monkeypatch
):
    source = tmp_path / "scripts"
    source.mkdir()
    (source / "uncovered.py").write_text("main()\n")
    report = tmp_path / "coverage.json"
    report.write_text(json.dumps({"files": {}, "totals": {"percent_covered": 0}}))
    monkeypatch.setattr(check_coverage, "SOURCE_DIRECTORIES", ("scripts",))

    errors, _ = check_coverage.audit_coverage(report, tmp_path)

    assert any("uncovered.py has 0.0%" in error for error in errors)
    assert any("total coverage is 0.0%" in error for error in errors)
