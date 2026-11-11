"""Write a Markdown summary of the CI build and unit-test results.

Usage: unit_test_summary.py <junit-xml> <docker-image-tag>
The output is meant to be appended to the GitHub Actions job summary.
"""

import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def image_line(tag: str) -> str:
    result = subprocess.run(
        ["docker", "image", "inspect", tag, "--format", "{{.Size}}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return f"Docker image `{tag}`: **not built**"
    size_mb = int(result.stdout.strip()) / 1_000_000
    return f"Docker image `{tag}`: **built**, {size_mb:.0f} MB"


def test_lines(report: Path) -> list[str]:
    if not report.exists():
        return ["Unit tests: **no report produced** (the tests did not run)."]

    root = ET.parse(report).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    total = sum(int(suite.get("tests", 0)) for suite in suites)
    failures = sum(int(suite.get("failures", 0)) for suite in suites)
    errors = sum(int(suite.get("errors", 0)) for suite in suites)
    skipped = sum(int(suite.get("skipped", 0)) for suite in suites)
    duration = sum(float(suite.get("time", 0)) for suite in suites)
    passed = total - failures - errors - skipped
    verdict = "passed" if failures == 0 and errors == 0 else "FAILED"

    lines = [
        f"Unit tests: **{verdict}**",
        "",
        "| Total | Passed | Failed | Errors | Skipped | Duration |",
        "| ---: | ---: | ---: | ---: | ---: | ---: |",
        f"| {total} | {passed} | {failures} | {errors} | {skipped} | {duration:.2f} s |",
    ]

    broken = [
        f"- `{case.get('classname')}::{case.get('name')}`"
        for case in root.iter("testcase")
        if case.find("failure") is not None or case.find("error") is not None
    ]
    if broken:
        lines += ["", "Failing tests:", *broken]
    return lines


def main() -> None:
    report, tag = Path(sys.argv[1]), sys.argv[2]
    print("## Build and unit tests")
    print()
    print(image_line(tag))
    print()
    print("\n".join(test_lines(report)))


if __name__ == "__main__":
    main()
