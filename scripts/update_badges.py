"""Regenerate the shields.io endpoint-badge JSON files under .github/badges/
from a real `pytest --cov` run's own output.

Why this instead of a third-party badge service: the numbers shown in
README.md must be the actual, current test/coverage results, verifiable by
anyone from files committed in this repo - not a number that can drift from
reality or depend on an external dashboard being configured correctly. CI
runs this after every test run on `main` and commits the result if it
changed, so the README badges always reflect the latest run on main.

Badge JSON follows shields.io's "endpoint" schema (schemaVersion 1):
https://shields.io/badges/endpoint-badge
README references it as:
  https://img.shields.io/endpoint?url=<raw-github-url-to-this-json>

Usage:
  python scripts/update_badges.py --coverage-json coverage.json --junit-xml junit.xml
"""

from __future__ import annotations

import argparse
import json
import xml.etree.ElementTree as ET
from pathlib import Path

BADGES_DIR = Path(__file__).resolve().parent.parent / ".github" / "badges"


def _color_for_coverage(percent: float) -> str:
    if percent >= 90:
        return "brightgreen"
    if percent >= 80:
        return "green"
    if percent >= 70:
        return "yellowgreen"
    if percent >= 60:
        return "yellow"
    if percent >= 50:
        return "orange"
    return "red"


def _write_badge(name: str, label: str, message: str, color: str) -> None:
    BADGES_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"schemaVersion": 1, "label": label, "message": message, "color": color}
    path = BADGES_DIR / f"{name}.json"
    path.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"wrote {path}: {label} = {message} ({color})")


def update_coverage_badge(coverage_json_path: Path) -> None:
    data = json.loads(coverage_json_path.read_text())
    percent = data["totals"]["percent_covered"]
    _write_badge("coverage", "coverage", f"{percent:.0f}%", _color_for_coverage(percent))


def update_tests_badge(junit_xml_path: Path) -> None:
    root = ET.parse(junit_xml_path).getroot()
    # pytest's junit output is a single <testsuite>, or a <testsuites> wrapping
    # one - handle both so this doesn't break on a pytest-version quirk.
    suite = root if root.tag == "testsuite" else root.find("testsuite")
    total = int(suite.get("tests", 0))
    failed = int(suite.get("failures", 0)) + int(suite.get("errors", 0))
    skipped = int(suite.get("skipped", 0))
    passed = total - failed - skipped

    if failed:
        message, color = f"{failed} failed, {passed} passed", "red"
    elif skipped:
        message, color = f"{passed} passed, {skipped} skipped", "green"
    else:
        message, color = f"{passed} passed", "brightgreen"
    _write_badge("tests", "tests", message, color)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coverage-json", type=Path, required=True)
    parser.add_argument("--junit-xml", type=Path, required=True)
    args = parser.parse_args()

    update_coverage_badge(args.coverage_json)
    update_tests_badge(args.junit_xml)


if __name__ == "__main__":
    main()
