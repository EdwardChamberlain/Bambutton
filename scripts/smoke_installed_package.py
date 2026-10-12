#!/usr/bin/env python3
"""Smoke-test runtime resources in an installed wheel or source distribution."""

from importlib import metadata
from pathlib import Path
from urllib.parse import urlsplit


def check_installed_package():
    import bambutton

    package_root = Path(bambutton.__file__).resolve().parent
    required_files = (
        "LICENSE",
        "THIRD_PARTY_NOTICES.md",
        "micro/app_main.py",
        "micro/boot.py",
        "micro/config_example.json",
        "micro/ota_manager.py",
        "micro/web_config.py",
        "firmware/ESP32_GENERIC_C3-20260406-v1.28.0.bin",
    )
    missing = [name for name in required_files if not (package_root / name).is_file()]
    if missing:
        raise RuntimeError(
            "Installed package is missing: {}".format(", ".join(missing))
        )

    check_distribution_metadata()
    return package_root


def check_distribution_metadata():
    distribution = metadata.distribution("bambutton")
    package_metadata = distribution.metadata
    if package_metadata.get("License-Expression") != "MIT":
        raise RuntimeError("Installed package metadata must declare the MIT licence")

    required_urls = {
        "Homepage",
        "Repository",
        "Documentation",
        "Issues",
        "Support",
        "Changelog",
    }
    project_urls = {}
    for entry in package_metadata.get_all("Project-URL", []):
        name, separator, url = entry.partition(",")
        if separator:
            project_urls[name.strip()] = url.strip()

    missing_urls = sorted(required_urls - project_urls.keys())
    invalid_urls = sorted(
        name
        for name in required_urls & project_urls.keys()
        if urlsplit(project_urls[name]).scheme != "https"
        or urlsplit(project_urls[name]).netloc != "github.com"
    )
    if missing_urls or invalid_urls:
        details = []
        if missing_urls:
            details.append("missing project URLs: {}".format(", ".join(missing_urls)))
        if invalid_urls:
            details.append("invalid project URLs: {}".format(", ".join(invalid_urls)))
        raise RuntimeError("Installed package metadata has " + "; ".join(details))

    license_files = [
        Path(str(file))
        for file in (distribution.files or ())
        if "licenses" in [part.lower() for part in Path(str(file)).parts[:-1]]
        and Path(str(file)).name.lower() == "license"
    ]
    if not license_files:
        raise RuntimeError("Installed package metadata is missing its licence file")


def main():
    package_root = check_installed_package()
    print("Installed Bambutton package is ready:", package_root)


if __name__ == "__main__":
    main()
