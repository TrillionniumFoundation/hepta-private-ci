#!/usr/bin/env python3
"""A separate real rejection control for the native Windows Git fixture.

The original Git33/Queue35/idle3 qualification must already have passed.
Only this temporary mutant omits the production Job Object; the same two
original tests must then reject surviving real descendants. No original
assertion, timeout, command, or result is changed by this control.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "codex-rs/git-utils/src/git_process.rs"
FIXTURE = ROOT / "codex-rs/git-utils/src/git_process_tests.rs"
PRODUCTION_BLOB = "3ce0431434d0c0e4bbde65eb68bce27cc572d9c6"
CASES = {
    "git_process::tests::timed_out_git_wrapper_does_not_leave_child_process_running",
    "git_process::tests::timed_out_exited_git_wrapper_does_not_leave_child_process_running",
}


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def git_blob(raw):
    return hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()


def validate_rejection(raw):
    log = raw.decode("utf-8-sig").replace("\r\n", "\n")
    summaries = re.findall(
        r"^test result: (ok|FAILED)\. (\d+) passed; (\d+) failed; (\d+) ignored; "
        r"(\d+) measured; (\d+) filtered out;", log, re.M
    )
    require(summaries == [("FAILED", "0", "2", "0", "0", "31")],
            "mutant did not execute exactly the two original cases")
    rows = re.findall(r"^test ([^\r\n]+?) \.\.\. (ok|FAILED|ignored)$", log, re.M)
    require(len(rows) == 2 and {name for name, _ in rows} == CASES
            and all(status == "FAILED" for _, status in rows),
            "mutant failed-case set differs")
    pids = re.findall(r"^Git wrapper child process (\d+) survived timeout cleanup$", log, re.M)
    require(len(pids) == 2 and len(set(pids)) == 2
            and all(0 < int(pid) < 2**32 for pid in pids),
            "both original survival assertions must reject actual descendants")
    require("skipping test:" not in log.lower(), "mutant skipped a case")
    return {"failed_cases": sorted(CASES), "surviving_descendants": len(pids),
            "passed": 0, "failed": 2, "ignored": 0, "measured": 0,
            "other_original_cases_filtered": 31,
            "scope": "Two separate negative controls, not product pass counts."}


def reader_controls():
    rows = "".join("test " + name + " ... FAILED\n" for name in sorted(CASES))
    good = (rows + "Git wrapper child process 101 survived timeout cleanup\n"
            + "Git wrapper child process 102 survived timeout cleanup\n"
            + "test result: FAILED. 0 passed; 2 failed; 0 ignored; 0 measured; 31 filtered out;\n")
    validate_rejection(good.encode())
    bad = [
        good.replace("0 passed; 2 failed", "2 passed; 0 failed"),
        good.replace("31 filtered", "32 filtered"),
        good.replace("101 survived", "102 survived"),
        good.replace("survived timeout cleanup", "exited during readiness", 1),
        good.replace("... FAILED", "... ignored", 1),
        good + rows.splitlines()[0] + "\n",
        good.replace(sorted(CASES)[0], "unrelated_case", 1),
    ]
    for value in bad:
        try:
            validate_rejection(value.encode())
        except RuntimeError:
            continue
        raise RuntimeError("negative-control reader accepted a synthetic counterexample")
    return {"synthetic_accepted": 1, "synthetic_rejected": len(bad),
            "synthetic_cases_are_native_evidence": False}


def validate_mutant_wrapper_xml(raw, log_raw):
    # Bazel 9's Windows wrapper represents Rust exit 101 as an XML error.
    # Require that exact wrapper and independently require both original panics.
    validate_rejection(log_raw)
    text = raw.decode("utf-8-sig")
    require("<!DOCTYPE" not in text.upper() and "<!ENTITY" not in text.upper(),
            "mutant XML contains a document type")
    xml = ET.fromstring(text)
    require(xml.tag == "testsuites" and not xml.attrib
            and len(xml) == 1 and xml[0].tag == "testsuite",
            "mutant XML must contain one wrapper suite")
    suite = xml[0]
    name = r"codex-rs\git-utils\git-utils-unit-tests.bat"
    require(suite.attrib == {"name": name, "tests": "1", "failures": "0", "errors": "1"}
            and [child.tag for child in suite] == ["testcase", "system-out"],
            "mutant Bazel wrapper counters differ from the actual Windows error shape")
    case, stdout = suite
    require(set(case.attrib) == {"name", "status", "duration", "time"}
            and case.get("name") == name and case.get("status") == "run"
            and all(re.fullmatch(r"\d+(?:\.\d+)?", case.get(field, ""))
                    for field in ("duration", "time"))
            and len(case) == 1 and case[0].tag == "error"
            and case[0].attrib == {"message": "exited with error code 101"}
            and not list(case[0]) and case[0].text in (None, ""),
            "mutant wrapper must record exactly the original Rust failure exit 101")
    require(not stdout.attrib and not list(stdout)
            and (stdout.text or "").replace("\r\n", "\n").strip()
                == log_raw.decode("utf-8-sig").replace("\r\n", "\n").strip(),
            "mutant XML and raw log differ")
    return {"wrapper_tests": 1, "wrapper_failures": 0, "wrapper_errors": 1,
            "rust_exit_code": 101, "exact_original_log_bound": True}


def xml_reader_controls():
    rows = "".join("test " + name + " ... FAILED\n" for name in sorted(CASES))
    log = (rows + "Git wrapper child process 101 survived timeout cleanup\n"
           + "Git wrapper child process 102 survived timeout cleanup\n"
           + "test result: FAILED. 0 passed; 2 failed; 0 ignored; 0 measured; 31 filtered out;\n").encode()
    name = r"codex-rs\git-utils\git-utils-unit-tests.bat"
    root = ET.Element("testsuites")
    suite = ET.SubElement(root, "testsuite", {
        "name": name, "tests": "1", "failures": "0", "errors": "1"})
    case = ET.SubElement(suite, "testcase", {
        "name": name, "status": "run", "duration": "3", "time": "3"})
    error = ET.SubElement(case, "error", {"message": "exited with error code 101"})
    ET.SubElement(suite, "system-out").text = log.decode()
    good = ET.tostring(root)
    validate_mutant_wrapper_xml(good, log)
    validate_mutant_wrapper_xml(good.replace(b"\n", b"\r\n"), log.replace(b"\n", b"\r\n"))
    case_raw, error_raw, suite_raw = (ET.tostring(node) for node in (case, error, suite))
    bad = [
        (good.replace(b'errors="1"', b'errors="0"'), log),
        (good.replace(b'failures="0"', b'failures="1"'), log),
        (good.replace(b'tests="1"', b'tests="2"'), log),
        (good.replace(b"error code 101", b"error code 1"), log),
        (good.replace(b'status="run"', b'status="notrun"'), log),
        (good.replace(name.encode(), b"unrelated-wrapper"), log),
        (good.replace(case_raw, case_raw + case_raw), log),
        (good.replace(suite_raw, suite_raw + suite_raw), log),
        (good.replace(error_raw, b""), log),
        (good.replace(error_raw, error_raw + b"<failure/>"), log),
        (good.replace(error_raw, error_raw + b"<skipped/>"), log),
        (good.replace(b"</testsuite>", b"<system-err/></testsuite>"), log),
        (good.replace(b"101 survived", b"999 survived"), log),
        (good, b""),
        (good, log.replace(b"31 filtered", b"32 filtered")),
        (good.replace(b"</testsuites>", b"<testcase/></testsuites>"), log),
        (suite_raw, log),
        (b'<!DOCTYPE testsuites [<!ENTITY x "bad">]>' + good, log),
    ]
    for xml, raw_log in bad:
        try:
            validate_mutant_wrapper_xml(xml, raw_log)
        except (RuntimeError, ET.ParseError):
            continue
        raise RuntimeError("mutant XML reader accepted a synthetic counterexample")
    return {"synthetic_accepted": 2, "synthetic_rejected": len(bad),
            "synthetic_cases_are_native_evidence": False}


def reports(base, suffix):
    return sorted(base.glob(
        "*/bazel-out/*/testlogs/codex-rs/git-utils/git-utils-unit-tests/test." + suffix
    ))



def remove_generated_report(path):
    metadata = path.lstat()
    attributes = getattr(metadata, "st_file_attributes", 0)
    require(stat.S_ISREG(metadata.st_mode)
            and not (attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)),
            "generated report must be a regular non-reparse file")
    raw = path.read_bytes()
    readonly = bool(attributes & getattr(stat, "FILE_ATTRIBUTE_READONLY", 0))
    if os.name == "nt" and readonly:
        # Bazel can materialize read-only outputs. Only clear that Windows
        # attribute on these generated reports; do not suppress other errors.
        path.chmod(stat.S_IWRITE)
    path.unlink()
    require(not path.exists() and not path.is_symlink(),
            "old generated report remains")
    return {"bytes": len(raw), "sha256": digest(raw),
            "windows_readonly_attribute_observed": readonly,
            "windows_readonly_attribute_cleared": os.name == "nt" and readonly}


def report_cleanup_controls(output):
    root = output / "report-cleanup-controls"
    root.mkdir()
    path = root / "readonly-test.log"
    path.write_bytes(b"owned generated report\n")
    path.chmod(stat.S_IREAD)
    require(bool(path.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_READONLY),
            "the real cleanup control is not read-only")
    observed = remove_generated_report(path)
    require(observed["windows_readonly_attribute_cleared"] is True,
            "the real read-only attribute was not handled")
    directory = root / "not-a-report"
    directory.mkdir()
    try:
        remove_generated_report(directory)
    except RuntimeError:
        pass
    else:
        raise RuntimeError("a directory was accepted as a generated report")
    require(directory.is_dir(), "the rejected directory was modified")
    directory.rmdir()
    return {"real_readonly_report_removed": True,
            "nonregular_directory_rejected_without_removal": True,
            "native_product_acceptance": False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--positive-receipt", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    receipt = {"schema": "hepta.windows-native-process-rejection.v1",
               "status": "failed", "native_product_acceptance": False,
               "source_restored": False, "commands": []}
    original = None
    mutated = False
    try:
        require(os.name == "nt", "native Windows required")
        receipt["reader_controls"] = reader_controls()
        receipt["xml_reader_controls"] = xml_reader_controls()
        receipt["report_cleanup_controls"] = report_cleanup_controls(output)
        head = subprocess.check_output(
            ["git", "--no-replace-objects", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
        require(head == os.environ["HEPTA_EXPECTED_COMMIT"], "source commit mismatch")
        receipt["source_commit"] = head
        receipt["source_tree"] = subprocess.check_output(
            ["git", "--no-replace-objects", "rev-parse", "HEAD^{tree}"], cwd=ROOT, text=True
        ).strip()
        subprocess.run(["git", "--no-replace-objects", "diff", "--exit-code", "HEAD", "--"],
                       cwd=ROOT, check=True)
        positive_raw = args.positive_receipt.read_bytes()
        positive = json.loads(positive_raw)
        require(positive["status"] == "passed" and positive["source_commit"] == head
                and positive["source_unchanged"] is True,
                "the current complete original qualification must have passed first")
        for target, count in (("git-utils-unit-tests", 33), ("queue-queue_service-test", 35)):
            row = positive["tests"][target]
            require((row["outer_passed"], row["outer_failed"], row["outer_ignored"],
                     row["outer_filtered"]) == (count, 0, 0, 0),
                    "the original full suite did not pass")
        require(positive["idle_controls"]["passed"] == 3
                and positive["idle_controls"]["failed"] == 0
                and positive["idle_controls"]["ignored"] == 0,
                "the separate idle controls did not pass")
        receipt["positive_receipt_sha256"] = digest(positive_raw)
        original = SOURCE.read_bytes()
        committed = subprocess.check_output(
            ["git", "--no-replace-objects", "show", "HEAD:codex-rs/git-utils/src/git_process.rs"],
            cwd=ROOT
        )
        require(original == committed and git_blob(original) == PRODUCTION_BLOB,
                "the original production bytes are not the bound source")
        fixture = FIXTURE.read_bytes()
        committed_fixture = subprocess.check_output(
            ["git", "--no-replace-objects", "show",
             "HEAD:codex-rs/git-utils/src/git_process_tests.rs"], cwd=ROOT
        )
        require(fixture == committed_fixture, "fixture differs from committed source")
        receipt["production"] = {"git_blob_sha": git_blob(original),
                                  "sha256": digest(original), "bytes": len(original)}
        receipt["fixture"] = {"git_blob_sha": git_blob(fixture),
                               "sha256": digest(fixture), "bytes": len(fixture)}
        start = original.index(b"    #[cfg(windows)]\n    let (child, job) = match JobObject::create()")
        end = original.index(b"    #[cfg(not(windows))]\n    let child", start)
        mutant = (original[:start]
                  + b"    #[cfg(windows)]\n    let (child, job) = (command.spawn().ok()?, None);\n"
                  + original[end:])
        receipt["mutant"] = {"git_blob_sha": git_blob(mutant),
                             "sha256": digest(mutant), "bytes": len(mutant),
                             "only_change": "Do not put the wrapper into its owned Job Object."}
        base = Path(os.environ["BAZEL_OUTPUT_BASE"]) / "execroot"
        receipt["removed_prior_reports"] = {}
        for suffix in ("log", "xml"):
            paths = reports(base, suffix)
            require(len(paths) == 1, "missing or ambiguous prior generated report")
            receipt["removed_prior_reports"][suffix] = remove_generated_report(paths[0])
        bash = Path(os.environ["HEPTA_BASH"])
        require(bash.is_absolute() and bash.name.casefold() == "bash.exe" and bash.is_file(),
                "the workflow Git Bash executable is required")
        receipt["bash"] = {"bytes": bash.stat().st_size, "sha256": digest(bash.read_bytes())}
        argv = [str(bash), ".github/scripts/run-bazel-ci.sh",
                "--print-failed-action-summary", "--print-failed-test-logs",
                "--windows-msvc-host-platform", "--remote-download-toplevel", "--",
                "test", "--platforms=//:windows_x86_64_msvc",
                "--test_tag_filters=-argument-comment-lint",
                "--nocache_test_results", "--test_output=all",
                "--test_sharding_strategy=disabled", "--test_arg=git_process::tests", "--",
                "//codex-rs/git-utils:git-utils-unit-tests"]
        mutated = True
        SOURCE.write_bytes(mutant)
        log_path = output / "mutant-command.log"
        begin = time.monotonic()
        with log_path.open("wb") as stream:
            command = subprocess.run(argv, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
        receipt["commands"].append({"argv": argv, "exit_code": command.returncode,
                                    "seconds": time.monotonic() - begin,
                                    "log_sha256": digest(log_path.read_bytes())})
        retained = {}
        for suffix in ("log", "xml"):
            paths = reports(base, suffix)
            require(len(paths) == 1, "missing or ambiguous fresh mutant report")
            raw = paths[0].read_bytes()
            (output / ("mutant-test." + suffix)).write_bytes(raw)
            retained[suffix] = raw
        require(command.returncode == 3, "Bazel did not report an actual test failure")
        receipt["rejection"] = validate_rejection(retained["log"])
        receipt["wrapper"] = validate_mutant_wrapper_xml(retained["xml"], retained["log"])
        receipt["retained"] = {
            suffix: {"bytes": len(raw), "sha256": digest(raw)}
            for suffix, raw in retained.items()
        }
        receipt["status"] = "rejection-demonstrated"
    finally:
        if mutated:
            SOURCE.write_bytes(original)
            receipt["source_restored"] = SOURCE.read_bytes() == original
        else:
            receipt["source_restored"] = True
        clean = subprocess.run(
            ["git", "--no-replace-objects", "diff", "--exit-code", "HEAD", "--"],
            cwd=ROOT, capture_output=True
        )
        (output / "restored-worktree.stdout").write_bytes(clean.stdout)
        (output / "restored-worktree.stderr").write_bytes(clean.stderr)
        receipt["clean_exit_code"] = clean.returncode
        if not receipt["source_restored"] or clean.returncode:
            receipt["status"] = "failed"
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        print("NATIVE_PROCESS_REJECTION=" + json.dumps({
            "status": receipt["status"],
            "source_commit": receipt.get("source_commit"),
            "source_restored": receipt["source_restored"],
            "clean_exit_code": clean.returncode,
            "reader_controls": receipt.get("reader_controls"),
            "xml_reader_controls": receipt.get("xml_reader_controls"),
            "report_cleanup_controls": receipt.get("report_cleanup_controls"),
            "removed_prior_reports": receipt.get("removed_prior_reports"),
            "rejection": receipt.get("rejection"),
            "wrapper": receipt.get("wrapper"),
            "native_product_acceptance": False,
        }), flush=True)
    require(receipt["status"] == "rejection-demonstrated", "rejection control did not qualify")


if __name__ == "__main__":
    main()
