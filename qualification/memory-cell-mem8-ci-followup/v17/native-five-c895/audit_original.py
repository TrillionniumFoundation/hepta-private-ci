"""Independently inspect the one admitted run's artifacts; never execute them."""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import uuid
import xml.etree.ElementTree as ET
import zipfile
import zlib


ROOT = Path(__file__).resolve().parent
SOURCE = "c89540598693697577cda8cba31cb07f6ce65317"
TREE = "5a7c897a33e4eef48ea8f4bf52eaf48ea7c866ae"
HARNESS = "5529aeaace80458fb0b1ecae776f95de78c5f9c3"
HARNESS_TREE = "df8a39e57da777a0d59f597cc678230be49414cb"
RUN = "43047914262"
JOB = 130616746852
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
TERMINAL = re.compile(r"^\s*(PASS|FAIL|TIMEOUT|EXECFAIL|LEAK|SKIP)\s+\[[^\]\n]+\]\s+(?:\(\s*\d+/\d+\)\s+)?(\S+)\s+(\S+)\s*$", re.M)


def digest(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def blob(raw):
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()


def dump_new(path, data):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, indent=2, sort_keys=True)
        stream.write("\n")


def extract_original(path, output):
    output.mkdir(exist_ok=False)
    archive_raw = path.read_bytes()
    rows = []
    seen = set()
    with zipfile.ZipFile(path) as archive:
        if sum(info.file_size for info in archive.infolist()) > 512 * 1024 * 1024:
            raise ValueError("artifact exceeds the bounded extraction size")
        for info in archive.infolist():
            relative = PurePosixPath(info.filename)
            if (relative.is_absolute() or ".." in relative.parts or "\\" in info.filename
                    or ":" in info.filename or info.filename in seen
                    or stat.S_ISLNK(info.external_attr >> 16)):
                raise ValueError("unsafe, duplicate or linked artifact member")
            seen.add(info.filename)
            if info.is_dir():
                continue
            if str(relative) != info.filename:
                raise ValueError("noncanonical artifact member")
            data = archive.read(info)
            if len(data) != info.file_size or zlib.crc32(data) & 0xffffffff != info.CRC:
                raise ValueError("artifact member bytes or CRC differ")
            destination = output.joinpath(*relative.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("xb") as stream:
                stream.write(data)
            rows.append({"path": relative.as_posix(), "zip_crc32": f"{info.CRC:08x}", **digest(data)})
    dump_new(output.parent / "ZIP_MEMBER_AUDIT.json", {
        "archive": {"path": path.name, **digest(archive_raw)}, "all_member_crc_and_lengths_checked": True,
        "member_count": len(rows), "members": rows,
    })
    return rows


def audit(directory, rows):
    plan = json.loads((ROOT / "FROZEN_PLAN.json").read_text())
    report = {
        "schema": "mem-native-five-independent-original-audit-v1",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "run_id": int(RUN), "attempt": 1, "job_id": JOB,
        "source_head": SOURCE, "source_tree": TREE, "harness_head": HARNESS,
        "checks": [], "phases": [], "findings": [],
        "native_executions_started_by_auditor": 0, "model_requests_started_by_auditor": 0,
    }

    def check(name, condition, detail=None):
        report["checks"].append({"name": name, "passed": bool(condition), "detail": detail})
        return bool(condition)

    def read(name):
        path = directory / name
        return json.loads(path.read_text(encoding="utf-8-sig")) if path.is_file() else None

    def exact_source(value):
        return (isinstance(value, dict) and value.get("commit") == SOURCE and value.get("tree") == TREE
                and value.get("dirty") is False and value.get("locks") == {
                    name: {key: plan["files"][name][key] for key in ("bytes", "sha256")}
                    for name in ("codex-rs/Cargo.lock", "MODULE.bazel.lock")
                })

    manifest = read("FILE_MANIFEST.json")
    actual_members = {row["path"]: {key: row[key] for key in ("bytes", "sha256")} for row in rows if row["path"] != "FILE_MANIFEST.json"}
    declared = {row["path"]: {key: row[key] for key in ("bytes", "sha256")} for row in manifest} if isinstance(manifest, list) else {}
    check("complete_original_member_manifest", manifest is not None and len(declared) == len(manifest) and declared == actual_members)
    anchor = read("JOB_ANCHOR.json") or {}
    check("original_budget_identity", anchor.get("run_id") == RUN and anchor.get("run_attempt") == "1"
          and anchor.get("harness_sha") == HARNESS and anchor.get("source_head") == SOURCE
          and anchor.get("source_tree") == TREE and anchor.get("job_timeout_minutes") == 65)
    result = read("RESULT.json") or {}
    report["original_driver_status"] = result.get("status", "MISSING_UNKNOWN")
    report["original_driver_error"] = result.get("error")
    check("original_run_and_source_identity", result.get("run_id") == RUN and result.get("run_attempt") == "1"
          and result.get("harness_sha") == HARNESS and result.get("source_head") == SOURCE and result.get("source_tree") == TREE)
    harness = result.get("harness", {})
    rendered = ROOT.parent / "mem-five-native-harness-preparation/rendered-c895405"
    expected_harness = {
        "driver": ".github/scripts/mem_native_five.py", "support": ".github/scripts/mem_native_five_support.py",
        "workflow": ".github/workflows/hepta-mem-native-five.yml", "input": ".github/fixtures/mem-native-five-plan.json",
    }
    check("actual_harness_files_bound", harness.get("head") == HARNESS and harness.get("tree") == HARNESS_TREE
          and all(harness.get(key) == digest((rendered / path).read_bytes()) for key, path in expected_harness.items()))
    before = read("source-before/identity.json")
    check("source_before_exact_and_clean", exact_source(before))
    tools = read("tools-before/tools.json")
    check("required_actual_tools_recorded", isinstance(tools, dict) and set(tools) == {
        "rustc", "cargo", "clippy-driver", "just", "cargo-nextest", "python", "python3"})
    expected_prefixes = {"rustc": "rustc 1.96.0 ", "cargo": "cargo 1.96.0 ", "clippy-driver": "clippy 0.1.96 ",
                         "just": "just 1.51.0", "cargo-nextest": "cargo-nextest 0.9.103", "python": "Python 3.", "python3": "Python 3."}
    if tools:
        check("pinned_tool_versions_and_hash_shapes", all(
            value.get("version", "").startswith(expected_prefixes[name]) and value.get("bytes", 0) > 0
            and re.fullmatch(r"[0-9a-f]{64}", value.get("sha256", "")) for name, value in tools.items()))
    helper_binding = None
    seen_uuids, terminal_cases, native_passed, clean_fixes = set(), [], [], []
    stages = [("phase-1-build-sandbox-helpers", "helpers", None)]
    stages += [(f"phase-{i + 2}-{group['id']}", "native", group) for i, group in enumerate(plan["groups"])]
    stages += [(f"phase-{i + 5}-fix-{package}", "fix", package) for i, package in enumerate(plan["scoped_fix_packages"])]
    for prefix, kind, scope in stages:
        phase = read(prefix + ".json")
        if phase is None:
            intent, not_run = read(prefix + ".intent.json"), read(prefix + ".not-run.json")
            report["phases"].append({"id": prefix, "kind": kind,
                "state": "INTENT_WITHOUT_TERMINAL_UNKNOWN" if intent else "EXPLICIT_NOT_RUN" if not_run else "NO_PHASE_EVIDENCE",
                "intent": intent, "not_run": not_run})
            continue
        item = {"id": prefix, "kind": kind, "driver_status": phase.get("status"),
                "exit_code": phase.get("command_exit_code"), "error": phase.get("error"),
                "integrity_error": phase.get("integrity_error"), "elapsed_seconds": phase.get("elapsed_seconds")}
        report["phases"].append(item)
        intent = read(prefix + ".intent.json")
        check(prefix + ":original_intent_bound", isinstance(intent, dict) and all(
            intent.get(key) == phase.get(key) for key in ("kind", "command", "cwd", "started_at", "before", "helpers_before", "remaining_job_seconds_before"))
            and intent.get("command_exit_code") is None and intent.get("status") == "running")
        if phase.get("status") == "passed_clean":
            check(prefix + ":same_remaining_budget", all(isinstance(phase.get(key), (float, int)) and 0 < phase[key] <= 3900
                  for key in ("remaining_job_seconds_before", "remaining_job_seconds_after")))
        raw_path = directory / (prefix + ".raw.log")
        raw = raw_path.read_bytes() if raw_path.is_file() else b""
        check(prefix + ":full_raw_bound", phase.get("raw_log") == {"path": raw_path.name, **digest(raw)} and raw_path.is_file())
        text = ANSI.sub("", raw.decode("utf-8", errors="replace"))
        exact = exact_source(phase.get("before")) and exact_source(phase.get("after")) and phase.get("before") == phase.get("after")
        item["exact_source_and_locks_before_after"] = check(prefix + ":source_clean", exact)
        item["tools_unchanged"] = check(prefix + ":tools_unchanged", read(prefix + "-tools-before/tools.json") == tools == read(prefix + "-tools-after/tools.json") and tools is not None)
        if kind == "helpers":
            helper_binding = phase.get("helper_binding")
            valid_helpers = isinstance(helper_binding, list) and len(helper_binding) == 2 and {
                row.get("name") for row in helper_binding} == {"codex-windows-sandbox-setup", "codex-command-runner"}
            check("two_actual_helper_bindings", valid_helpers and all(row.get("bytes", 0) > 0
                  and re.fullmatch(r"[0-9a-f]{64}", row.get("sha256", "")) for row in helper_binding or []))
            if valid_helpers:
                compiler_artifacts = []
                for line in text.splitlines():
                    try:
                        cargo = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(cargo, dict) and cargo.get("reason") == "compiler-artifact" and cargo.get("target", {}).get("name") in {row["name"] for row in helper_binding}:
                        compiler_artifacts.append(cargo)
                for helper in helper_binding:
                    matches = [entry for entry in compiler_artifacts if entry.get("target", {}).get("name") == helper["name"]
                               and entry.get("executable", "").replace("\\", "/").lower() == helper["source"].replace("\\", "/").lower()]
                    check("helper_artifact:" + helper["name"], bool(matches) and all(
                        entry["target"].get("kind") == ["bin"] and not entry.get("profile", {}).get("test")
                        and entry.get("manifest_path", "").replace("\\", "/").endswith("/source/codex-rs/windows-sandbox-rs/Cargo.toml") for entry in matches))
        if helper_binding:
            item["helper_bindings_unchanged"] = check(prefix + ":helper_bindings", phase.get("helpers_after") == helper_binding
                and (kind == "helpers" or phase.get("helpers_before") == helper_binding))
        if kind == "native":
            selected = re.findall(r"Starting (\d+) tests? across", text)
            terminals = TERMINAL.findall(text)
            observed = [{"status": status, "binary_id": binary, "case": name} for status, binary, name in terminals]
            item.update(selected_counts=[int(value) for value in selected], original_terminal_lines=observed,
                        observed_terminal_status_counts=dict(Counter(row["status"] for row in observed)))
            terminal_cases.extend({**row, "phase": prefix} for row in observed if row["status"] != "SKIP")
            expected_command = ["just", "test", "--locked", "-p", scope["package"], *scope["target_args"],
                "--cargo-profile", "dev-small", "-E", scope["filter"], "--test-threads", "1", "--no-tests", "fail", "--retries", "0"]
            command_ok = check(prefix + ":exact_native_command", phase.get("command") == expected_command)
            raw_ok = (selected == [str(len(scope["cases"]))] and len(observed) == len(scope["cases"])
                      and sorted(row["case"] for row in observed) == sorted(scope["cases"])
                      and all(row["status"] == "PASS" and row["binary_id"] == scope["binary_id"] for row in observed)
                      and phase.get("command_exit_code") == 0)
            item["independent_raw_all_pass"] = raw_ok
            junit_path = directory / (prefix + ".junit.xml")
            junit_ok = False
            if junit_path.is_file():
                xml = junit_path.read_bytes()
                observed_junit_path = directory / (prefix + "-observed-source") / "postimages/codex-rs/target/nextest/local/junit.xml"
                immediate = phase.get("source_immediately_after_command", {})
                check(prefix + ":original_junit_before_move_retained", observed_junit_path.is_file()
                    and observed_junit_path.read_bytes() == xml and immediate.get("commit") == SOURCE
                    and immediate.get("tree") == TREE and immediate.get("dirty") is True
                    and immediate.get("locks") == (before or {}).get("locks")
                    and read(prefix + "-observed-source/identity.json") == immediate)
                try:
                    if b"<!DOCTYPE" in xml or b"<!ENTITY" in xml:
                        raise ValueError("JUnit document declaration")
                    root = ET.fromstring(xml)
                    jid = str(uuid.UUID(root.attrib["uuid"]))
                    timestamp = datetime.fromisoformat(root.attrib["timestamp"].replace("Z", "+00:00"))
                    start = datetime.fromisoformat(phase["started_at"])
                    finish = datetime.fromisoformat(phase["command_finished_at"])
                    cases = list(root.iter("testcase"))
                    suites = root.findall("testsuite")
                    junit_ok = (root.tag == "testsuites" and jid not in seen_uuids and
                        set(re.findall(r"Nextest run ID\s+([0-9a-fA-F-]{36})", text)) == {jid} and
                        timestamp.tzinfo is not None and int(start.timestamp()*1000) <= int(timestamp.timestamp()*1000) <= int(finish.timestamp()*1000) and
                        int(root.attrib["tests"]) == len(scope["cases"]) and int(root.attrib["failures"]) == int(root.attrib["errors"]) == 0 and
                        sorted(case.attrib["name"] for case in cases) == sorted(scope["cases"]) and
                        all(case.attrib.get("classname") == scope["binary_id"] and all(child.tag in {"system-out", "system-err"} for child in case) for case in cases) and
                        len(suites) == 1 and suites[0].attrib.get("name") == scope["binary_id"] and int(suites[0].attrib.get("disabled", "0")) == 0 and
                        phase.get("junit_artifact") == {"original_path": "codex-rs/target/nextest/local/junit.xml", "retained_path": junit_path.name,
                            **digest(xml), "source_artifact_was_absent_before_command": True, "same_volume_rename": True})
                    item["original_junit"] = {"path": junit_path.name, **digest(xml), "uuid": jid,
                        "case_names": [case.attrib["name"] for case in cases], "attributes": root.attrib,
                        "testcase_status_elements": {case.attrib["name"]: [child.tag for child in case] for case in cases}}
                    seen_uuids.add(jid)
                except (ValueError, KeyError, ET.ParseError) as error:
                    item["junit_parse_error"] = str(error)
            item["independent_junit_all_pass"] = junit_ok
            if raw_ok and junit_ok and command_ok and exact and item["tools_unchanged"] and item.get("helper_bindings_unchanged") and phase.get("status") == "passed_clean":
                native_passed.extend(scope["cases"])
        elif kind == "fix":
            command_ok = check(prefix + ":exact_fix_command", phase.get("command") == ["just", "fix", "--locked", "-p", scope])
            if command_ok and phase.get("command_exit_code") == 0 and phase.get("status") == "passed_clean" and exact and item["tools_unchanged"] and item.get("helper_bindings_unchanged"):
                clean_fixes.append(scope)
    after = read("source-after/identity.json")
    collection = read("COLLECTION.json") or {}
    final_ok = check("source_final_and_collection_exact", exact_source(after) and before == after == collection.get("source")
                     and exact_source(read("source-at-collection/identity.json")))
    all_cases = [case for group in plan["groups"] for case in group["cases"]]
    report.update(observed_terminal_test_executions=terminal_cases,
        observed_terminal_execution_count=len(terminal_cases), observed_unique_terminal_case_count=len({row["case"] for row in terminal_cases}),
        observed_status_counts=dict(Counter(row["status"] for row in terminal_cases)),
        independently_qualified_native_cases=native_passed, clean_scoped_fix_packages=clean_fixes,
        actual_helper_bindings=helper_binding, original_collection_status=collection.get("status", "MISSING_UNKNOWN"))
    passed = (sorted(native_passed) == sorted(all_cases) and clean_fixes == plan["scoped_fix_packages"] and final_ok
              and all(row["passed"] for row in report["checks"]) and result.get("status") == "passed_five_named_cases_and_three_clean_scoped_fixes"
              and collection.get("status") == "qualified_results_retained")
    report["qualification"] = "PASS_FIVE_NATIVE_AND_THREE_CLEAN_FIXES" if passed else "NOT_QUALIFIED_RETAIN_ORIGINAL_FAILURE_OR_UNKNOWN"
    report["count_boundary"] = "Only original terminal lines are counted as observed executions. Absent or interrupted groups remain explicitly unevidenced; selected counts and the driver's accepted-pass count are not executed counts."
    report["binary_boundary"] = "Helper/tool full SHA values were computed by the original frozen runner and independently checked for receipt/source/artifact consistency; the executable bytes themselves are not included in this artifact."
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zip", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(exist_ok=False)
    rows = extract_original(args.zip, args.output / "files")
    report = audit(args.output / "files", rows)
    dump_new(args.output / "INDEPENDENT_AUDIT.json", report)
    print(json.dumps({key: report[key] for key in ("qualification", "original_driver_status", "observed_terminal_execution_count", "observed_status_counts", "clean_scoped_fix_packages")}, indent=2))


if __name__ == "__main__":
    main()
