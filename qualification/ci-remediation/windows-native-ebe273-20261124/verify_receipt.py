#!/usr/bin/env python3
"""Verify the public CI artifact and count unique cases/attempts, not log echoes."""

import hashlib
import io
import json
from pathlib import Path
import re
import zipfile


CASE = re.compile(
    r"^\s*(?:TRY (\d+) )?(PASS|FAIL) \[\s*[\d.]+s\] (\S+) (\S+)\s*$"
)
SUMMARY = re.compile(
    r"Summary \[.*?\] (\d+) tests run: (\d+) passed, "
    r"(?:(\d+) failed, )?(\d+) skipped"
)


def summarize(text):
    cases = {}
    summary = None
    for line in text.splitlines():
        match = CASE.match(line)
        if match:
            attempt, outcome, package, test = match.groups()
            key = f"{package} {test}"
            attempts = cases.setdefault(key, {})
            number = int(attempt or 1)
            assert attempts.get(number, outcome) == outcome, (key, number)
            attempts[number] = outcome
        match = SUMMARY.search(line)
        if match:
            assert summary is None, "expected one nextest invocation per log"
            summary = tuple(int(value or 0) for value in match.groups())
    assert summary is not None, "missing nextest summary"
    passed, failed = [], []
    for name, attempts in sorted(cases.items()):
        assert set(attempts) == set(range(1, max(attempts) + 1)), name
        assert len(set(attempts.values())) == 1, "unexpected flaky case"
        (passed if attempts[max(attempts)] == "PASS" else failed).append(name)
    run, pass_count, fail_count, excluded = summary
    assert (len(cases), len(passed), len(failed)) == (run, pass_count, fail_count)
    return {
        "run": run,
        "passed_count": pass_count,
        "failed_count": fail_count,
        "outside_selector": excluded,
        "unique_attempts": sum(map(len, cases.values())),
        "passed": passed,
        "failed": failed,
    }


def main():
    root = Path(__file__).resolve().parent
    receipt = json.loads((root / "receipt.json").read_text())
    raw = (root / "artifact.zip").read_bytes()
    assert len(raw) == receipt["artifact"]["bytes"]
    assert hashlib.sha256(raw).hexdigest() == receipt["artifact"]["sha256"]
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        assert set(archive.namelist()) == set(receipt["artifact"]["files"])
        for name, expected in receipt["artifact"]["files"].items():
            data = archive.read(name)
            assert len(data) == expected["bytes"], name
            assert hashlib.sha256(data).hexdigest() == expected["sha256"], name
        assert archive.read("head.txt").decode().strip() == receipt["source"]["head"]
        seen = set()
        for name, expected in receipt["selections"].items():
            actual = summarize(archive.read(name).decode())
            assert actual == expected, name
            names = set(actual["passed"] + actual["failed"])
            assert not seen.intersection(names), "case repeated across selections"
            seen.update(names)
    print(json.dumps({
        "verified_source": receipt["source"]["head"],
        "artifact_sha256": receipt["artifact"]["sha256"],
        "unique_cases": sum(x["run"] for x in receipt["selections"].values()),
        "unique_failures": sum(x["failed_count"] for x in receipt["selections"].values()),
        "unique_attempts": sum(x["unique_attempts"] for x in receipt["selections"].values()),
        "workflow_conclusion": receipt["run"]["conclusion"],
    }, indent=2))


if __name__ == "__main__":
    main()
