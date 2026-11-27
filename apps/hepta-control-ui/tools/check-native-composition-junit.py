"""Require the exact new composition tests in a fresh original nextest report.

The original UI installer pins nextest 0.9.146, not the backend's 0.9.103.
Its reporter (commit 8af696ddcce8fff2962d6a5168b6d138b8616a35) uses the
package name as the library suite/classname and the full Rust test name.
Root `skipped` is optional; testcase children and exact names decide success.
This supplements hepta_ci_exec.py, preserving its complete --lib command.
"""

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import uuid
import xml.etree.ElementTree as ET

PACKAGE = "hepta-robrix-ui"
HEADLESS = {
    "chat_source::tests::adoption_does_not_replace_an_existing_draft_or_construct_a_second_source",
    "chat_source::tests::embedded_adoption_borrows_the_original_draft_and_exits_once",
    "native_presentation::tests::explicit_shutdown_and_later_drop_close_only_once",
    "native_presentation::tests::failed_adoption_or_abnormal_drop_also_closes_the_client",
    "native_presentation::tests::console_bound_is_utf8_safe_explicit_and_does_not_clear_pending",
}
LAUNCH = {
    "native_launch::tests::reentrant_admission_cannot_replace_the_first_composition",
    "native_launch::tests::an_unadopted_loop_cannot_report_success_and_releases_pending_state",
    "native_launch::tests::an_unwound_loop_releases_admission_and_closes_the_pending_client_once",
}
MODES = {"headless": HEADLESS, "native": HEADLESS | LAUNCH}
MAX_REPORT = 8 * 1024 * 1024


def require(condition, message):
    if not condition:
        raise ValueError(message)


def command(mode):
    result = ["just", "test", "--locked", "--manifest-path",
              "../apps/hepta-control-ui/rust/Cargo.toml", "-p", PACKAGE]
    if mode == "headless":
        result += ["--no-default-features", "--features", "native-presentation"]
    elif mode == "native":
        result += ["--features", "ui,native-host,native-presentation"]
    else:
        raise ValueError("unknown composition test mode")
    return result + ["--lib", "--profile", "native-composition-" + mode]


def date(value):
    result = datetime.fromisoformat(value)
    require(result.tzinfo is not None, "timestamps need a timezone")
    return result


def prepare(path, junit, mode, tested_sha):
    require(mode in MODES, "unknown composition test mode")
    require(bool(re.fullmatch(r"[0-9a-f]{40}", tested_sha)), "invalid tested SHA")
    require(junit.is_absolute() and not junit.exists() and not junit.is_symlink(),
            "JUnit path must be absolute and absent before the command")
    record = {"schema": 1, "mode": mode, "tested_sha": tested_sha,
              "junit": str(junit), "command": command(mode),
              "prepared_at": datetime.now(timezone.utc).isoformat()}
    with path.open("x", encoding="utf-8") as stream:
        json.dump(record, stream, indent=2)
        stream.write("\n")


def check_xml(raw, mode, started, finished, expected_passed):
    require(len(raw) <= MAX_REPORT and b"<!DOCTYPE" not in raw and b"<!ENTITY" not in raw,
            "unbounded or non-nextest XML")
    root = ET.fromstring(raw)
    require(root.tag == "testsuites" and root.get("name") == "hepta-native-composition-" + mode,
            "wrong nextest report or mode")
    run_id = str(uuid.UUID(root.attrib["uuid"]))
    stamp = date(root.attrib["timestamp"])
    # Nextest serializes timestamps to milliseconds, while the execution
    # recorder retains microseconds. This allowance is only that truncation.
    require(started - timedelta(milliseconds=1) <= stamp <= finished,
            "JUnit report is not from this execution interval")
    for counter in ("failures", "errors"):
        require(root.get(counter) == "0", "unsuccessful nextest aggregate")
    require(root.get("skipped", "0") == "0" and root.get("disabled", "0") == "0",
            "nextest aggregate contains skipped tests")
    suites = root.findall("testsuite")
    require(len(suites) == 1 and suites[0].get("name") == PACKAGE,
            "expected the complete original library suite")
    suite = suites[0]
    for counter in ("failures", "errors"):
        require(suite.get(counter) == "0", "unsuccessful library aggregate")
    require(suite.get("skipped", "0") == "0" and suite.get("disabled", "0") == "0",
            "library aggregate contains skipped tests")
    cases = suite.findall("testcase")
    require(len(root.findall(".//testcase")) == len(cases), "nested/foreign testcase")
    require(root.get("tests") == str(len(cases)) and suite.get("tests") == str(len(cases))
            and len(cases) == expected_passed, "runner and JUnit test counts differ")
    names = set()
    for case in cases:
        name = case.get("name")
        require(name and name not in names and case.get("classname") == PACKAGE,
                "duplicate, unnamed or foreign-library test")
        names.add(name)
        require(all(child.tag in {"system-out", "system-err", "properties"} for child in case),
                f"test was skipped, failed, retried or otherwise unsuccessful: {name}")
        elapsed = float(case.attrib["time"])
        require(math.isfinite(elapsed) and elapsed >= 0, "invalid testcase elapsed time")
        require(stamp <= date(case.attrib["timestamp"]) <= finished,
                "testcase timestamp is outside this run")
    missing = MODES[mode] - names
    require(not missing, "required composition tests missing: " + ", ".join(sorted(missing)))
    require(mode != "headless" or not (LAUNCH & names), "UI launch tests in a headless report")
    return {"run_uuid": run_id, "total_passed_tests": len(cases),
            "required_passed_tests": sorted(MODES[mode])}


def verify(start_path, execution_path, output_path):
    start = json.loads(start_path.read_text())
    mode = start["mode"]
    require(start.get("schema") == 1 and mode in MODES, "invalid pre-execution record")
    expected = command(mode)
    receipt = json.loads(execution_path.read_text())
    require(start["command"] == expected and receipt.get("command") == expected,
            "the original complete --lib command changed or was filtered")
    require(receipt.get("status") == "passed" and receipt.get("exit_code") == 0
            and receipt.get("command_exit_code") == 0 and receipt.get("returncode") == 0
            and receipt.get("timed_out") is False and receipt.get("output_limit_exceeded") is False
            and receipt.get("observed_failed_tests") == 0, "original execution did not pass")
    before = receipt["before"]
    require(before == receipt["after"] and before.get("dirty") is False
            and before.get("commit") == start["tested_sha"] == receipt.get("tested_sha"),
            "source identity changed or differs from pre-execution record")
    started, finished = date(receipt["started_at"]), date(receipt["finished_at"])
    require(date(start["prepared_at"]) <= started <= finished, "invalid execution interval")
    log_name = receipt["log_file"]
    require(Path(log_name).name == log_name, "execution log must be a sibling file")
    log = (execution_path.parent / log_name).read_bytes()
    require(len(log) == receipt["log_bytes"] and hashlib.sha256(log).hexdigest() == receipt["log_sha256"],
            "original execution log changed")
    junit = Path(start["junit"])
    require(junit.is_absolute() and junit.is_file() and not junit.is_symlink(), "fresh JUnit missing")
    with junit.open("rb") as stream:
        raw = stream.read(MAX_REPORT + 1)
    archive = output_path.with_suffix(".xml")
    with archive.open("xb") as stream:
        stream.write(raw)
    details = check_xml(raw, mode, started, finished, receipt["observed_passed_tests"])
    return {"status": "passed", "mode": mode, "tested_sha": start["tested_sha"],
            "junit_sha256": hashlib.sha256(raw).hexdigest(), "junit_bytes": len(raw),
            "junit_file": archive.name, "execution_file": execution_path.name, **details,
            "scope": "Exact executed test-name coverage in this original --lib run; not renderer/device qualification"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    start = sub.add_parser("prepare")
    start.add_argument("--start", type=Path, required=True)
    start.add_argument("--junit", type=Path, required=True)
    start.add_argument("--mode", choices=MODES, required=True)
    start.add_argument("--tested-sha", required=True)
    check = sub.add_parser("verify")
    check.add_argument("--start", type=Path, required=True)
    check.add_argument("--execution", type=Path, required=True)
    check.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.action == "prepare":
        prepare(args.start, args.junit, args.mode, args.tested_sha)
        return 0
    require(not args.output.exists(), "refusing to overwrite a previous validation result")
    try:
        result = verify(args.start, args.execution, args.output)
    except (OSError, ValueError, KeyError, TypeError, ET.ParseError) as error:
        result = {"status": "failed", "error": str(error)}
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(json.dumps(result))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
