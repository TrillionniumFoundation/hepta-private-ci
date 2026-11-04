#!/usr/bin/env python3
"""Independently inspect retained current Memory artifacts; execute no archived code."""
import argparse
import ast
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from verify import GitBytes, canonical, emit_raw, fetch_artifact, require, sha, verify_sources

PACKAGES = ("codex-utils-path", "codex-state", "codex-hepta-memory")
TARGETS = {
    "path": "//codex-rs/utils/path-utils:path-utils-unit-tests",
    "state": "//codex-rs/state:state-unit-tests",
    "memory": "//codex-rs/hepta-memory:hepta-memory-unit-tests",
}
BAD_XML = {"failure", "error", "skipped", "rerunFailure", "rerunError", "flakyFailure", "flakyError"}
SCOPE = "qualification/windows-memory-recovery-current/scope.json"
NATIVE_READER = "qualification/windows-memory-recovery-current/run_native.py"


def unique(pairs):
    value = {}
    for key, item in pairs:
        require(key not in value, "duplicate JSON key: " + key)
        value[key] = item
    return value


def parse(raw):
    return json.loads(raw, object_pairs_hook=unique)


def verify_output_set(receipt, members):
    outputs = receipt["outputs"]
    require(set(outputs) == set(members) - {"receipt.json"}, "unbound or missing retained output")
    for name, value in outputs.items():
        raw = members[name]
        require(value == {"bytes": len(raw), "sha256": sha(raw)}, "output bytes differ: " + name)
    commands = receipt["commands"]
    by_name = {row["name"]: row for row in commands}
    require(len(by_name) == len(commands), "duplicate original command")
    for name, row in by_name.items():
        require(isinstance(row["argv"], list) and row["argv"] and
                all(isinstance(arg, str) for arg in row["argv"]), "invalid command argv")
        require(type(row["exit_code"]) is int, "invalid command exit")
        require(all(name + "." + suffix in outputs for suffix in ("stdout", "stderr")),
                "original command streams missing: " + name)
    return by_name, outputs


def inventory(raw, package, ignored):
    data = parse(raw)
    require(len(data["rust-suites"]) == 1, "more than the selected library")
    suite_id, suite = next(iter(data["rust-suites"].items()))
    require(suite["package-name"] == package and suite["kind"] == "lib" and suite["status"] == "listed",
            "wrong or unlisted library")
    cases = suite["testcases"]
    require(cases and data["test-count"] == len(cases), "empty/inconsistent test universe")
    ignored = set(ignored)
    observed = set()
    for name, case in cases.items():
        require(type(case["ignored"]) is bool and case.get("kind") in (None, "test"), "invalid case kind")
        if case["ignored"]:
            observed.add(name)
        expected_filter = {"status": "mismatch", "reason": "ignored"} if case["ignored"] else {"status": "matches"}
        require(case["filter-match"] == expected_filter, "unapproved test filter: " + name)
    require(observed == ignored, "original ignored case set changed")
    expected = set(cases) - ignored
    require(expected, "zero executable cases")
    return {"suite": suite_id, "binary": suite["binary-path"], "all_cases": sorted(cases),
            "expected": sorted(expected), "original_ignored": sorted(ignored)}


def junit(raw, expected):
    root = ET.fromstring(raw)
    suites = list(root.iter("testsuite"))
    require(suites, "no JUnit suite")
    require(not any(node.tag in BAD_XML for node in root.iter()), "failed, skipped or retried JUnit case")
    cases = list(root.iter("testcase"))
    names = [node.get("name") for node in cases]
    require(len(names) == len(set(names)) and set(names) == set(expected["expected"]),
            "JUnit is not the complete selected nonignored universe")
    require(sum(int(node.get("tests", "-1")) for node in suites) == len(names), "JUnit case counter mismatch")
    require(all(int(node.get(key, "0")) == 0 for node in suites for key in ("failures", "errors", "skipped")),
            "JUnit failure/skip counter")
    return {"passed": len(names), "failed": 0, "errors": 0, "skipped": 0, "retried": 0,
            "executed": names, "original_ignored": expected["original_ignored"]}


def static_windows_cases(raw):
    module = ast.parse(raw)
    for statement in module.body:
        if isinstance(statement, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "WINDOWS_REQUIRED"
                for target in statement.targets):
            result = ast.literal_eval(statement.value)
            require(set(result) == set(PACKAGES), "Windows required-package set changed")
            require(all(isinstance(value, set) and value and all(isinstance(x, str) for x in value)
                        for value in result.values()), "bad required Windows cases")
            return result
    raise RuntimeError("required Windows controls not bound")


def require_command(by_name, name, argv):
    require(name in by_name and by_name[name]["exit_code"] == 0 and by_name[name]["argv"] == argv,
            "original command changed or failed: " + name)


def inspect_native(receipt, members, git, by_name, spec):
    require(set(receipt["libraries"]) == set(PACKAGES), "missing or additional original libraries")
    require(all(row["exit_code"] == 0 for row in by_name.values()), "original command failed")
    require_command(by_name, "rustc-version", ["rustc", "-Vv"])
    require(members["rustc-version.stdout"].startswith(b"rustc 1.96.0 "), "compiler pin changed")
    require_command(by_name, "nextest-version", ["cargo", "nextest", "--version"])
    require(members["nextest-version.stdout"].startswith(b"cargo-nextest 0.9.151 "), "nextest pin changed")
    config = parse(git.read(SCOPE))
    required = static_windows_cases(git.read(NATIVE_READER))
    expected_host = {"windows": "Windows", "macos": "macOS", "linux": "Linux"}[spec["host"]]
    host = receipt["host"]
    require((expected_host in host) or (spec["host"] == "macos" and "Darwin" in host), "native host mismatch")
    counts = {}
    for package in PACKAGES:
        require_command(by_name, package + "-inventory", [
            "cargo", "nextest", "list", "--locked", "-p", package, "--lib", "--message-format=json"])
        allow = config["original_ignored_memory_cases"] if package == "codex-hepta-memory" else []
        listed = inventory(members[package + "-inventory.stdout"], package, allow)
        actual = receipt["libraries"][package]
        require(actual["status"] == "passed" and actual["inventory"] == listed, "recorded inventory differs")
        if spec["host"] == "windows":
            suffixes = {name.rsplit("::", 1)[-1] for name in listed["expected"]}
            require(required[package] <= suffixes, "required Windows cases did not compile")
        require_command(by_name, package + "-original-tests", [
            "just", "test", "--locked", "-p", package, "--lib", "--no-tests=fail",
            "--retries", "0", "--success-output=final"])
        text = members[package + "-original-tests.stdout"] + members[package + "-original-tests.stderr"]
        require(b"skipping test:" not in text.lower(), "early-return skip")
        result = junit(members[package + "-junit.xml"], listed)
        require(actual["result"] == result, "JUnit differs from the original result receipt")
        require(re.fullmatch(r"[0-9a-f]{64}", actual["binary_sha256_before"]) is not None and
                actual["binary_sha256_before"] == actual["binary_sha256_after"], "recorded binary changed")
        counts[package] = {"executed": result["passed"], "original_ignored": listed["original_ignored"],
                           "inventory_cases": len(listed["all_cases"]),
                           "junit_sha256": sha(members[package + "-junit.xml"]),
                           "case_names_sha256": sha(canonical(result["executed"])),
                           "recorded_binary_sha256": actual["binary_sha256_before"]}
    require_command(by_name, "original-scoped-clippy", [
        "just", "fix", "--locked", "-p", PACKAGES[0], "-p", PACKAGES[1], "-p", PACKAGES[2], "--no-deps"])
    return {"mode": "native", "libraries": counts, "total_executed": sum(x["executed"] for x in counts.values()),
            "failed": 0, "skipped": 0, "retried": 0,
            "boundary": "Exact original Cargo inventory versus JUnit. Binary equality is the original recorded before/after hash; binaries are not retained in this artifact."}


def rust_counts(raw, ignored):
    text = raw.decode("utf-8").replace("\r\n", "\n")
    values = re.findall(
        r"test result: (ok|FAILED)\. (\d+) passed; (\d+) failed; (\d+) ignored; (\d+) measured; (\d+) filtered out", text)
    require(values and values[-1][0] == "ok", "missing or failed final Rust summary")
    passed, failed, skipped, measured, filtered = map(int, values[-1][1:])
    require(passed > 0 and failed == measured == filtered == 0, "incomplete original Rust target")
    names = re.findall(r"^test (\S+) \.\.\. ignored(?:,.*)?$", text, re.M)
    require(len(names) == len(set(names)) == skipped and set(names) == set(ignored), "ignored set changed")
    require("skipping test:" not in text.lower(), "early-return Rust skip")
    return {"passed": passed, "failed": failed, "original_ignored": names,
            "measured": measured, "filtered": filtered, "rust_summaries": [list(value) for value in values]}


def inspect_bazel(receipt, members, git, by_name):
    require("Linux" in receipt["host"], "not the original Linux GNU host")
    require(set(receipt["targets"]) == set(TARGETS), "missing original target")
    require(all(row["exit_code"] == 0 for row in by_name.values()), "original command failed")
    for name, argv in [("committed-lock-first", ["just", "bazel-lock-check"]),
                       ("original-lock-update", ["just", "bazel-lock-update"]),
                       ("original-lock-check", ["just", "bazel-lock-check"])]:
        require_command(by_name, name, argv)
    wrapper = [receipt["bash_executable"], "./.github/scripts/run-bazel-ci.sh", "--print-failed-test-logs",
               "--print-failed-action-summary", "--remote-download-toplevel", "--"]
    require_command(by_name, "original-library-targets", [
        *wrapper, "test", "--keep_going", "--nocache_test_results", "--test_output=all", "--", *TARGETS.values()])
    command_log = members["original-library-targets.stdout"] + members["original-library-targets.stderr"]
    require(re.search(rb"Executed 3 out of 3 tests?: 3 tests? pass", command_log), "not all original targets executed")
    allow = parse(git.read(SCOPE))["original_ignored_memory_cases"]
    results = {}
    for name in TARGETS:
        result = rust_counts(members[name + ".log"], allow if name == "memory" else [])
        require(receipt["targets"][name] == result, "target summary differs")
        root = ET.fromstring(members[name + ".xml"])
        require(list(root.iter("testcase")), "empty Bazel wrapper XML")
        require(not any(node.tag in BAD_XML for node in root.iter()), "Bazel XML failure/skip")
        suites = list(root.iter("testsuite"))
        require(suites and all(int(node.get(key, "0")) == 0 for node in suites
                               for key in ("failures", "errors", "skipped")), "bad Bazel XML counters")
        results[name] = result
    require_command(by_name, "original-scoped-clippy", [
        *wrapper, "build", "--config=clippy", "--", *(target + "-bin" for target in TARGETS.values())])
    return {"mode": "bazel", "targets": results,
            "total_executed": sum(value["passed"] for value in results.values()),
            "boundary": "Original unfiltered targets, actual 3/3 execution, complete Rust summaries and wrapper XML. There is no independent Bazel case-universe enumeration."}


def main():
    require(__debug__, "optimized Python is not accepted")
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--key", required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    matches = [item for item in parse(args.manifest.read_bytes()) if item["key"] == args.key]
    require(len(matches) == 1, "unknown or duplicate artifact key")
    spec = matches[0]
    args.output.mkdir(parents=True, exist_ok=False)
    metadata, raw, members = fetch_artifact(spec)
    (args.output / "original.zip").write_bytes(raw)
    receipt = parse(members["receipt.json"])
    require(receipt["source_commit"] == spec["source"], "wrong original source")
    require(receipt["status"] == spec["expected_original_status"], "unexpected original verdict")
    require(receipt["run_id"] == str(spec["run_id"]), "wrong original run in receipt")
    source_before = parse(members["source-before.json"])
    bound_receipt = {**receipt, "source_before": source_before}
    git = GitBytes(args.source, spec["source"])
    try:
        # Both original Memory readers import the raw-link snapshot from generate.py.
        source = verify_sources({**spec, "kind": "generation"}, bound_receipt, members, git)
        by_name, outputs = verify_output_set(receipt, members)
        if receipt["status"] == "passed":
            for name in ("initial-clean-source", "final-clean-source"):
                require_command(by_name, name, ["git", "--no-replace-objects", "diff", "--exit-code", "HEAD", "--"])
            if spec["kind"] == "memory-native":
                result = inspect_native(receipt, members, git, by_name, spec)
            elif spec["kind"] == "memory-bazel":
                result = inspect_bazel(receipt, members, git, by_name)
            else:
                raise RuntimeError("unsupported current Memory artifact kind")
        else:
            require(receipt["status"] == "failed", "unsupported original failure state")
            result = {"mode": "negative-evidence", "original_commands": receipt["commands"],
                      "original_libraries": receipt.get("libraries"), "original_targets": receipt.get("targets"),
                      "original_problems": receipt.get("problems"), "failed_streams": {}}
            failed = [row for row in by_name.values() if row["exit_code"] != 0]
            incomplete = (spec["kind"] == "memory-bazel" and set(receipt.get("targets", {})) != set(TARGETS))
            require(failed or receipt.get("problems") or incomplete, "no recorded original failure")
            result["observed_junit"] = {}
            for package in PACKAGES:
                name = package + "-junit.xml"
                if name in members:
                    root = ET.fromstring(members[name])
                    cases = list(root.iter("testcase"))
                    result["observed_junit"][package] = {
                        "cases": len(cases), "sha256": sha(members[name]),
                        "failures": [{"name": case.get("name"),
                                      "details": [{"tag": child.tag, "attributes": child.attrib, "text": child.text}
                                                  for child in case if child.tag in BAD_XML or child.tag in {"system-out", "system-err"}]}
                                     for case in cases if any(child.tag in BAD_XML for child in case)]
                    }
            if spec["kind"] == "memory-bazel":
                for suffix in ("stdout", "stderr"):
                    name = "original-library-targets." + suffix
                    if name in members:
                        emit_raw(name, members[name])
            for row in failed:
                for suffix in ("stdout", "stderr"):
                    name = row["name"] + "." + suffix
                    result["failed_streams"][name] = outputs[name]
                    emit_raw(name, members[name])
    finally:
        git.close()
    report = {"schema": 1, "repository": spec["repository"], "source": spec["source"],
              "original_run": spec["run_id"], "artifact_id": spec["artifact_id"],
              "original_qualification_status": receipt["status"], "key": spec["key"],
              "zip_bytes": len(raw), "zip_sha256": sha(raw), "all_member_crc": True,
              "source_verification": source, "output_verification": outputs, "result": result,
              "evidence_verification": "passed",
              "scope": "Read-only verification of original retained evidence; no new product execution or whole-CI admission."}
    rendered = json.dumps(report, indent=2).encode() + b"\n"
    (args.output / "VERIFIED.json").write_bytes(rendered)
    (args.output / "receipt.json").write_bytes(members["receipt.json"])
    (args.output / "artifact-metadata.json").write_bytes(json.dumps(metadata, indent=2).encode() + b"\n")
    compact = {key: value for key, value in report.items() if key != "output_verification"}
    if compact["result"].get("mode") == "negative-evidence":
        compact["result"] = dict(compact["result"])
        compact["result"]["original_libraries"] = {
            name: {"status": value.get("status"),
                   "inventory_count": len(value.get("inventory", {}).get("all_cases", [])),
                   "expected_count": len(value.get("inventory", {}).get("expected", [])),
                   "result_passed": value.get("result", {}).get("passed")}
            for name, value in (compact["result"].get("original_libraries") or {}).items()
        }
    compact["output_count"] = len(outputs)
    compact["verified_report_sha256"] = sha(rendered)
    print("MEMORY_EVIDENCE_VERIFIED_JSON=" + json.dumps(compact, separators=(",", ":")), flush=True)


if __name__ == "__main__":
    main()
