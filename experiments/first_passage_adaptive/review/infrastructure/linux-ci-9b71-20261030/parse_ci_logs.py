"""Inventory retained GNU/musl logs without running builds or tests."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re


TIMESTAMP = re.compile(r"^\ufeff?\d{4}-\d\d-\d\dT\S+Z ")
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
STATUS = re.compile(
    r"^(//\S+)\s+(?:\([^)]*cached\)\s+)?"
    r"(FAILED TO BUILD|FAILED|FLAKY|PASSED|NO STATUS|TIMEOUT|SKIPPED)\b(.*)"
)
OUTPUT = re.compile(
    r"^(?:=+ Test output for |##\[group\]Bazel test log tail for )(//\S+)"
)
RESULT = re.compile(r"^test (.+) \.\.\. FAILED$")
LISTED_CASE = re.compile(r"^    ([A-Za-z_][A-Za-z_0-9:]*)$")
AGGREGATE = re.compile(
    r"^Executed (\d+) out of (\d+) tests: (\d+) tests pass, "
    r"(\d+) fail to build, (\d+) fail remotely, and (\d+) were skipped\."
)


def parse(path):
    data = gzip.decompress(path.read_bytes())
    lines = [ANSI.sub("", TIMESTAMP.sub("", line)).replace("\r", "")
             for line in data.decode("utf-8").splitlines()]
    targets, cases, compiler = {}, {}, {}
    target, in_failures, aggregate = None, False, None
    for number, line in enumerate(lines, 1):
        match = STATUS.match(line)
        if match:
            targets[match[1]] = {
                "target": match[1], "status": match[2],
                "line": number, "detail": match[3].strip(),
            }
        match = OUTPUT.match(line)
        if match:
            target = match[1].rstrip(":")
            in_failures = False
        elif re.match(r"^={20,}$", line) or line == "##[endgroup]":
            target, in_failures = None, False
        if line == "failures:":
            in_failures = True
            continue
        match = RESULT.match(line)
        listed = LISTED_CASE.match(line) if in_failures else None
        if target and (match or listed):
            name = (match or listed)[1]
            cases.setdefault(target, {}).setdefault(name, []).append(number)
        if in_failures and line and not listed:
            in_failures = False
        if re.match(r"^error(?:\[[A-Z][0-9]+\])?:", line):
            if "aborting due to" not in line:
                compiler.setdefault(line, []).append(number)
        match = AGGREGATE.match(line)
        if match:
            aggregate = dict(zip(
                ("executed_now", "total", "passed", "failed_build", "failed_runtime", "skipped"),
                map(int, match.groups()),
            ))
    if aggregate is None:
        raise ValueError("Missing final Bazel aggregate")
    counts = {status: sum(row["status"] == status for row in targets.values())
              for status in {row["status"] for row in targets.values()}}
    if counts.get("FAILED", 0) != aggregate["failed_runtime"]:
        raise ValueError("Final runtime target count does not reconcile")
    if counts.get("PASSED", 0) + counts.get("FLAKY", 0) != aggregate["passed"]:
        raise ValueError("Final successful target count does not reconcile")
    if counts.get("SKIPPED", 0) != aggregate["skipped"]:
        raise ValueError("Final skipped target count does not reconcile")
    failed = []
    for name, row in sorted(targets.items()):
        if row["status"] != "FAILED":
            continue
        row = dict(row)
        row["cases"] = [{"name": case, "lines": sorted(set(observations))}
                        for case, observations in sorted(cases.get(name, {}).items())]
        if not row["cases"]:
            raise ValueError(f"No failed case evidence for final target {name}")
        failed.append(row)
    return {
        "log": path.name, "decoded_utf8_bytes": len(data),
        "decoded_utf8_sha256": hashlib.sha256(data).hexdigest(),
        "line_count": len(lines), "aggregate": aggregate,
        "observed_final_status_counts": counts,
        "failed_runtime_targets": failed,
        "listed_failed_build_targets": [row for row in targets.values()
                                        if row["status"] == "FAILED TO BUILD"],
        "build_target_list_incomplete": counts.get("FAILED TO BUILD", 0) < aggregate["failed_build"],
        "excluded_final_flaky": [row for row in targets.values() if row["status"] == "FLAKY"],
        "compiler_diagnostics": [{"message": message, "lines": numbers}
                                 for message, numbers in compiler.items()],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("logs", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = {"schema": "hepta.retained-linux-ci-inventory.v1",
              "jobs": [parse(path) for path in args.logs]}
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
