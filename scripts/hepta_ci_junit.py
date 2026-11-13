"""Retain a fresh native JUnit report and bind it to one CI execution record.

This checks recorded observations on a trusted runner. It cannot authenticate
an arbitrary command, host, or report as a product qualification authority.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import xml.etree.ElementTree as ET


class NoDoctypeTreeBuilder(ET.TreeBuilder):
    def doctype(self, _name: str, _pubid: str | None, _system: str | None) -> None:
        raise ValueError("JUnit must not contain document type declarations")


def collect(execution: Path, junit: Path, output: Path) -> int:
    summary = {
        "schema_version": 1,
        "kind": "native-junit-collection",
        "execution_file": execution.name,
        "native_path": str(junit),
        "status": "rejected",
    }
    exit_code = 1
    # Claim the summary before retaining XML. A prior failed collection may
    # have a summary without XML; a retry must not pair it with a new report.
    try:
        summary_stream = output.with_suffix(".summary.json").open("x", encoding="utf-8")
    except OSError as error:
        summary["error"] = str(error)
        print(json.dumps(summary, sort_keys=True))
        return exit_code
    try:
        with execution.open("rb") as stream:
            raw_execution = stream.read(1024 * 1024 + 1)
        if len(raw_execution) > 1024 * 1024:
            raise ValueError("execution record exceeds its bound")
        record = json.loads(raw_execution)
        summary["execution_sha256"] = hashlib.sha256(raw_execution).hexdigest()
        source = os.environ.get("SOURCE_SHA", "")
        before = record["before"]
        if (
            type(record["schema_version"]) is not int
            or record["schema_version"] != 1
            or re.fullmatch(r"[0-9a-f]{40}", source) is None
            or record["source_sha"] != source
            or record["tested_sha"] != source
            or record["lane"] != "source-head"
            or before != record["after"]
            or before["commit"] != source
            or before["dirty"] is not False
            or re.fullmatch(r"[0-9a-f]{40}", before["tree"]) is None
            or record["command"][:3] != ["just", "test", "--locked"]
        ):
            raise ValueError("execution does not bind a clean source-head test")
        summary.update(
            source_sha=source,
            source_tree=before["tree"],
            command=record["command"],
            run_id=record.get("run_id"),
            run_attempt=record.get("run_attempt"),
            job=record.get("job"),
        )
        started = datetime.fromisoformat(record["started_at"])
        finished = datetime.fromisoformat(record["finished_at"])
        if started.tzinfo is None or finished.tzinfo is None or finished < started:
            raise ValueError("execution timestamps must form an aware interval")
        with junit.open("rb") as stream:
            stat_before = os.fstat(stream.fileno())
            data = stream.read(64 * 1024 * 1024 + 1)
            stat_after = os.fstat(stream.fileno())
        stable_fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        if (
            len(data) > 64 * 1024 * 1024
            or not stat.S_ISREG(stat_before.st_mode)
            or any(
                getattr(stat_before, field) != getattr(stat_after, field)
                for field in stable_fields
            )
        ):
            raise ValueError("JUnit exceeded its bound or changed while reading")
        if not started.timestamp() <= stat_after.st_mtime <= finished.timestamp():
            raise ValueError("JUnit is not fresh within this execution interval")
        if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
            raise ValueError("JUnit must not contain document type declarations")
        # The parser callback also rejects declarations in encodings such as
        # UTF-16, where an ASCII byte search cannot identify the declaration.
        root = ET.fromstring(data, parser=ET.XMLParser(target=NoDoctypeTreeBuilder()))
        if root.tag not in ("testsuite", "testsuites"):
            raise ValueError("unexpected JUnit root element")
        cases = list(root.iter("testcase"))
        failures = sum(case.find("failure") is not None for case in cases)
        errors = sum(case.find("error") is not None for case in cases)
        skipped = sum(case.find("skipped") is not None for case in cases)
        summary.update(
            junit_sha256=hashlib.sha256(data).hexdigest(),
            junit_bytes=len(data),
            junit_mtime_ns=stat_after.st_mtime_ns,
            total_testcases=len(cases),
            failures=failures,
            errors=errors,
            skipped_in_xml=skipped,
        )
        with output.open("xb") as stream:
            stream.write(data)
        if len(cases) - skipped <= 0:
            raise ValueError("JUnit contains no executed test cases")
        for field in ("observed_passed_tests", "observed_failed_tests"):
            if type(record[field]) is not int or record[field] < 0:
                raise ValueError("terminal runner counts must be nonnegative integers")
        if (
            record["observed_passed_tests"] != len(cases) - failures - errors - skipped
            or record["observed_failed_tests"] != failures + errors
        ):
            raise ValueError("JUnit counts differ from the terminal runner summary")
        summary["status"] = "retained-failed"
        if (
            record["status"] == "passed"
            and record["exit_code"] == 0
            and record["command_exit_code"] == 0
            and failures == errors == 0
        ):
            summary["status"] = "passed"
            exit_code = 0
    except (OSError, ValueError, KeyError, TypeError, ET.ParseError) as error:
        summary["status"] = "rejected"
        summary["error"] = str(error)
    with summary_stream as stream:
        json.dump(summary, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps(summary, sort_keys=True))
    return exit_code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execution", type=Path, required=True)
    parser.add_argument("--junit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    return collect(args.execution, args.junit, args.output)


if __name__ == "__main__":
    sys.exit(main())
