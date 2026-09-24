#!/usr/bin/env python3
"""Fail when shipped Python files lack meaningful automated coverage."""

import argparse
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIRECTORIES = ("micro", "scripts", "src")
MIN_FILE_COVERAGE = 25.0
MIN_TOTAL_COVERAGE = 70.0


def shipped_python_files(project_root=PROJECT_ROOT):
    files = set()
    for directory in SOURCE_DIRECTORIES:
        files.update((project_root / directory).rglob("*.py"))
    return sorted(path for path in files if "__pycache__" not in path.parts)


def audit_coverage(report_path, project_root=PROJECT_ROOT):
    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    measured_files = {}
    for filename, details in report.get("files", {}).items():
        path = Path(filename)
        if not path.is_absolute():
            path = project_root / path
        measured_files[path.resolve()] = details

    errors = []
    for path in shipped_python_files(project_root):
        details = measured_files.get(path.resolve())
        percent = (
            details.get("summary", {}).get("percent_covered", 0.0)
            if details
            else 0.0
        )
        if percent < MIN_FILE_COVERAGE:
            errors.append(
                "{} has {:.1f}% coverage; requires at least {:.0f}%".format(
                    path.relative_to(project_root), percent, MIN_FILE_COVERAGE
                )
            )

    total = report.get("totals", {}).get("percent_covered", 0.0)
    if total < MIN_TOTAL_COVERAGE:
        errors.append(
            "total coverage is {:.1f}%; requires at least {:.0f}%".format(
                total, MIN_TOTAL_COVERAGE
            )
        )
    return errors, total


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path, nargs="?", default=Path("coverage.json"))
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT)
    args = parser.parse_args()

    try:
        errors, total = audit_coverage(args.report, args.root.resolve())
    except (OSError, ValueError) as exc:
        parser.error("could not read coverage report: {}".format(exc))

    print("Total Python source coverage: {:.1f}%".format(total))
    if errors:
        for error in errors:
            print("Coverage gate failed:", error)
        raise SystemExit(1)
    print("Every shipped Python module meets the coverage floor.")


if __name__ == "__main__":
    main()
