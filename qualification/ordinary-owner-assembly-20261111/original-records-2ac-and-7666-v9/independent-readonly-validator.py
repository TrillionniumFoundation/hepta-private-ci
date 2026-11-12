"""Independently inspect one immutable native-record archive, read-only.

No extraction to the filesystem, subprocess, network, native test, source access,
permission change, cleanup, or output file. Output is a derived JSON review.
Original failing attempts remain failures.
"""
import base64
import gzip
import hashlib
import io
import json
import os
from pathlib import PurePosixPath
import re
import stat
import sys
import tarfile
import traceback
import xml.etree.ElementTree as ET

def require(condition, message):
    if not condition:
        raise ValueError(message)

def pairs(items):
    result = {}
    for key, value in items:
        require(key not in result, "duplicate JSON key: " + key)
        result[key] = value
    return result

def bad_constant(value):
    raise ValueError("non-finite JSON number: " + value)

def parse_json(raw):
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=bad_constant)

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def git_blob(raw):
    return hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()

def stat_fields(value):
    return tuple(getattr(value, key) for key in
                 ("st_dev", "st_ino", "st_mode", "st_nlink", "st_size",
                  "st_mtime_ns", "st_ctime_ns"))

def file_version(value):
    return ":".join(str(getattr(value, key)) for key in
                    ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns"))

def safe_name(value):
    require(isinstance(value, str) and 0 < len(value.encode("utf-8")) <= 4096,
            "invalid member name")
    path = PurePosixPath(value)
    require(not path.is_absolute() and str(path) == value
            and all(part not in ("", ".", "..") for part in path.parts)
            and "\\" not in value and "\0" not in value,
            "unsafe or noncanonical archive member: " + repr(value))
    return value

C = parse_json("".join(sys.argv[1:]))
require(set(C) == {
    "archive", "archive_version", "archive_bytes", "archive_sha256", "archive_git_blob",
    "members", "payload_files", "manifest_sha256", "anchor_source", "anchor_tree",
    "max_member_bytes", "max_total_bytes", "max_inventory_bytes", "excluded",
    "sources", "expected_requests", "expected_observations", "known_original_members",
    "formatter_payloads", "formatter_preimages", "root_expected_counts",
    "root_expected_parents", "scope"
}, "configuration keys differ")
require(__debug__, "optimized Python execution is not the reviewed request")
require(os.path.isabs(C["archive"]) and os.path.realpath(C["archive"]) == C["archive"],
        "original archive path is not canonical")
require(C["archive_bytes"] == 2392536 and C["members"] == 116
        and C["payload_files"] == 115, "wrong fixed original archive bounds")
require(C["max_member_bytes"] == 32 * 1024 * 1024
        and C["max_total_bytes"] == 128 * 1024 * 1024
        and C["max_inventory_bytes"] == 64 * 1024 * 1024,
        "unexpected read bounds")
report = {
    "schema": "hepta.original-records.v9.independent-readonly-archive-review.v1",
    "status": "not-completed",
    "scope": C["scope"],
    "archive": {"path": C["archive"], "version": C["archive_version"],
                "bytes": C["archive_bytes"], "sha256": C["archive_sha256"],
                "git_blob": C["archive_git_blob"]},
    "native_tests_started": False,
    "source_or_ref_mutation": False,
    "filesystem_extraction": False,
    "output_file_written": False,
    "business_acceptance": {
        "ordinary_complete_chains": 0,
        "positive_adoption_chains": 0,
        "ordinary_no_update_rollback_chains": 0,
        "independent_consumer_accepted": False,
        "physical_daemon_root_restart_accepted": False,
        "full_native_qualification_accepted": False,
    },
}
fd = None
try:
    report["stage"] = "open-original-archive"
    fd = os.open(C["archive"], os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    before = os.fstat(fd)
    require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1,
            "original archive is not a single-link regular file")
    require(before.st_size == C["archive_bytes"] and file_version(before) == C["archive_version"],
            "original archive version changed before read")
    require(stat_fields(os.stat(C["archive"], follow_symlinks=False)) == stat_fields(before),
            "original path and opened descriptor differ")
    blocks = []
    received = 0
    while received <= C["archive_bytes"]:
        block = os.read(fd, min(1024 * 1024, C["archive_bytes"] + 1 - received))
        if not block:
            break
        blocks.append(block)
        received += len(block)
    data = b"".join(blocks)
    require(len(data) == C["archive_bytes"], "original archive length differs")
    require(os.read(fd, 1) == b"", "unexpected original archive trailing byte")
    require(sha(data) == C["archive_sha256"] and git_blob(data) == C["archive_git_blob"],
            "original archive whole SHA256 or Git blob differs")
    require(stat_fields(os.fstat(fd)) == stat_fields(before),
            "original archive changed during read")

    report["stage"] = "read-only-tar-members"
    payloads = {}
    member_proofs = []
    total = 0
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:xz") as archive:
        members = archive.getmembers()
        require(len(members) == C["members"], "archive member count differs")
        for member in members:
            name = safe_name(member.name)
            require(name not in payloads, "duplicate archive member: " + name)
            require(member.isfile() and not member.issym() and not member.islnk()
                    and not getattr(member, "sparse", None),
                    "archive member is not an ordinary regular file: " + name)
            require(type(member.size) is int and 0 <= member.size <= C["max_member_bytes"],
                    "archive member exceeds original bound: " + name)
            require(member.mode == 0o644 and member.mtime == 0
                    and member.uid == 0 and member.gid == 0 and member.linkname == "",
                    "original deterministic tar metadata differs: " + name)
            total += member.size
            require(total <= C["max_total_bytes"], "uncompressed archive exceeds original bound")
            # Read the decompressed tar stream in memory. Never call extract/extractall.
            archive.fileobj.seek(member.offset_data)
            raw = archive.fileobj.read(member.size)
            require(len(raw) == member.size, "truncated tar member: " + name)
            payloads[name] = raw
            member_proofs.append({"path": name, "bytes": len(raw),
                                  "sha256": sha(raw), "git_blob": git_blob(raw)})
    require("MANIFEST.json" in payloads
            and sha(payloads["MANIFEST.json"]) == C["manifest_sha256"],
            "original manifest SHA differs")
    manifest = parse_json(payloads["MANIFEST.json"])
    require(manifest["status"] == "verified-original-record-export"
            and manifest["business_acceptance"] is False,
            "original exporter status differs")
    require(manifest["anchor_source"] == C["anchor_source"]
            and manifest["anchor_tree"] == C["anchor_tree"],
            "original exporter anchor differs")
    clean_anchor = {"head": C["anchor_source"], "tree": C["anchor_tree"], "status": ""}
    require(manifest["source_before"] == clean_anchor
            and manifest["source_after"] == clean_anchor,
            "original exporter anchor was not stable and clean")
    require(manifest["excluded"] == C["excluded"], "original exclusion list differs")
    rows = manifest["files"]
    require(len(rows) == C["payload_files"], "manifest payload count differs")
    index = {}
    for row in rows:
        name = safe_name(row["path"])
        require(name not in index and name != "MANIFEST.json", "duplicate manifest payload")
        index[name] = row
    require(set(index) == set(payloads) - {"MANIFEST.json"},
            "manifest and archive payload sets differ")
    for name, row in index.items():
        raw = payloads[name]
        require(len(raw) == row["bytes"] and sha(raw) == row["sha256"]
                and git_blob(raw) == row["git_blob"],
                "original member does not match manifest: " + name)

    def raw(name):
        require(name in payloads, "required original member absent: " + name)
        return payloads[name]

    def doc(name):
        return parse_json(raw(name))

    def recorded_file(source, metadata):
        prefix = source["records"] + "/"
        path = metadata["path"]
        require(isinstance(path, str) and path.startswith(prefix),
                "recorded path leaves its original records directory")
        relative = safe_name(path[len(prefix):])
        name = source["name"] + "/" + relative
        value = raw(name)
        require(len(value) == metadata["bytes"] and sha(value) == metadata["sha256"],
                "side file differs from original progress binding: " + name)
        require(index[name].get("original_path") == path,
                "manifest original path differs: " + name)
        return name, value

    def source_inventory(source, label):
        base = source["name"] + "/" + label
        summary = doc(base + ".json")
        require(summary["head"] == source["head"] and summary["tree"] == source["tree"]
                and summary["status"] == "", "physical inventory source differs")
        _, compressed = recorded_file(source, summary["inventory"])
        with gzip.GzipFile(fileobj=io.BytesIO(compressed), mode="rb") as stream:
            encoded = stream.read(C["max_inventory_bytes"] + 1)
        require(len(encoded) <= C["max_inventory_bytes"], "inventory uncompressed limit exceeded")
        require(sha(encoded) == summary["inventory_sha256"], "physical inventory digest differs")
        values = parse_json(encoded)
        require(isinstance(values, list) and len(values) == summary["files"],
                "physical inventory count differs")
        paths = {}
        for value in values:
            path = safe_name(value["path"])
            require(path not in paths and value["mode"] in ("100644", "100755", "120000"),
                    "physical inventory path/mode differs")
            require(type(value["bytes"]) is int and value["bytes"] >= 0
                    and re.fullmatch(r"[0-9a-f]{40}", value["git_blob"])
                    and re.fullmatch(r"[0-9a-f]{64}", value["sha256"]),
                    "invalid physical inventory digest row")
            paths[path] = value
        return summary, encoded, paths

    for name, expected in C["known_original_members"].items():
        value = raw(name)
        require(len(value) == expected["bytes"] and sha(value) == expected["sha256"]
                and git_blob(value) == expected["git_blob"],
                "independently pinned original bytes differ: " + name)
    for name, expected in C["expected_requests"].items():
        require(doc("requests/" + name + ".json") == expected,
                "retained native request object differs: " + name)
    for name, expected in C["expected_observations"].items():
        require(doc("observations/" + name + ".json") == expected,
                "retained original observation object differs: " + name)
    # Exporter-normalized request/observation JSON is compared structurally.
    # Its original byte hashes remain separately pinned, not relabeled as these members.

    source_by_name = {value["name"]: value for value in C["sources"]}
    require(len(source_by_name) == 2, "expected exactly two distinct terminal attempts")
    terminal_rows = {value["name"]: value for value in manifest["terminal_records"]}
    require(set(terminal_rows) == set(source_by_name), "terminal source set differs")
    progress = {}
    inventory_before = {}
    report["sources"] = []
    for source in C["sources"]:
        prefix = source["name"] + "/"
        value = doc(prefix + "progress.json")
        require(value["source_sha"] == source["head"] and value["source_tree"] == source["tree"]
                and value["status"] == source["status"], "terminal progress identity/status differs")
        require(sha(raw(prefix + "progress.json")) == source["progress_sha256"],
                "terminal progress original hash differs")
        terminal = terminal_rows[source["name"]]
        require(terminal["source_sha"] == source["head"] and terminal["status"] == source["status"]
                and terminal["sha256"] == source["progress_sha256"],
                "manifest terminal binding differs")
        require(not value.get("completion_unknown") and not value.get("awaiting_original"),
                "original command completion is unknown")
        require(all(item.get("state") == "completed" and item.get("timed_out") is False
                    for item in value["steps"]), "an original launcher is nonterminal or timed out")
        for step in value["steps"]:
            recorded_file(source, step["log"])
        for record in value["execution_records"]:
            recorded_file(source, record["record"])
        require(value["external_tools_before"] == value["external_tools_after"],
                "original external tool bytes changed")
        require(value["reference_before"] == value["reference_after"]
                and value["reference_after"]["status"] == "",
                "original donor changed")
        require(doc(prefix + "tools-before.json") == doc(prefix + "tools-after.json"),
                "original tool/checker sources changed")
        initial_summary, initial_bytes, initial_rows = source_inventory(source, "source-before")
        inventory_before[source["name"]] = (initial_summary, initial_bytes, initial_rows)
        for path, metadata in doc(prefix + "tools-before.json").items():
            require(path in initial_rows and initial_rows[path]["sha256"] == metadata["sha256"]
                    and initial_rows[path]["bytes"] == metadata["bytes"],
                    "original checker/tool digest differs from physical source inventory")
        progress[source["name"]] = value
        report["sources"].append({
            "source": source["head"], "tree": source["tree"], "status": value["status"],
            "progress_sha256": sha(raw(prefix + "progress.json")),
            "original_errors": value["errors"], "cleanup": value["cleanup"],
            "external_tool_paths": len(value["external_tools_before"]),
            "external_tools_equal": True, "reference_equal": True,
            "physical_initial_files": initial_summary["files"],
            "physical_initial_inventory_sha256": initial_summary["inventory_sha256"],
        })

    report["stage"] = "formatter-failed-attempt"
    old = C["sources"][0]
    old_prefix = old["name"] + "/"
    old_progress = progress[old["name"]]
    require(old_progress["status"] == "failed", "formatter attempt unexpectedly accepted")
    fmt = doc(old_prefix + "fmt-before.execution.json")
    require(fmt["source_sha"] == old["head"] and fmt["tested_sha"] == old["head"]
            and fmt["command_exit_code"] == 0 and fmt["status"] == "failed"
            and fmt["timed_out"] is False and fmt["output_limit_exceeded"] is False,
            "formatter original command/executor outcome differs")
    require(next(s for s in old_progress["steps"] if s["name"] == "fmt-before")["exit_code"] == 1,
            "original formatter executor did not fail")
    require(all(s["name"] not in ("ordinary", "root") for s in old_progress["steps"])
            and old_prefix + "ordinary.junit.xml" not in payloads
            and old_prefix + "root.junit.xml" not in payloads,
            "unrecorded test execution appears in formatter-only attempt")
    require(next(s for s in old_progress["cleanup"]
                 if s["name"] == "final-physical-source")["status"] == "failed",
            "original dirty-source failure was lost")
    final_old = doc(old_prefix + "final-source-identity.json")
    require(final_old["head"] == old["head"] and final_old["tree"] == old["tree"]
            and final_old["status"] != "", "original dirty source was relabeled clean")
    outputs = doc(old_prefix + "maintenance-postimages.json")
    expected_outputs = {p["path"]: p for p in C["formatter_payloads"]}
    require(len(outputs) == 7 and len(expected_outputs) == 7
            and {o["path"] for o in outputs} == set(expected_outputs),
            "seven original formatter postimages differ")
    for output in outputs:
        value = base64.b64decode(output["base64"], validate=True)
        expected = expected_outputs[output["path"]]
        require(len(value) == output["bytes"] == expected["bytes"]
                and sha(value) == output["sha256"] == expected["sha256"]
                and git_blob(value) == output["git_blob"] == expected["git_blob"],
                "original formatter postimage bytes differ")
        require(inventory_before[old["name"]][2][output["path"]]["git_blob"]
                == C["formatter_preimages"][output["path"]],
                "formatter preimage differs from original physical inventory")
    dirty = final_old["status"].splitlines()
    require(all(line.startswith(" M ") for line in dirty)
            and {line[3:] for line in dirty} == set(expected_outputs),
            "dirty source path set differs from original formatter outputs")
    recorded_file(old, old_progress["maintenance_patch"])
    report["formatter_attempt"] = {
        "command_exit": 0, "executor_exit": 1, "native_tests": 0,
        "postimage_count": 7, "dirty_source_preserved": True,
        "original_final_physical_source_check": "failed",
        "final_source_identity": final_old,
    }

    report["stage"] = "root-diagnostic-failed-attempt"
    root = C["sources"][1]
    root_prefix = root["name"] + "/"
    root_progress = progress[root["name"]]
    clean = {"head": root["head"], "tree": root["tree"], "status": ""}
    require(root_progress["before_tests"] == clean and root_progress["after_tests"] == clean
            and doc(root_prefix + "final-source-identity.json") == clean,
            "Root diagnostic source was not clean and stable")
    final_summary, final_bytes, final_rows = source_inventory(root, "source-final")
    require(final_bytes == inventory_before[root["name"]][1],
            "Root physical source inventory changed")
    for path, expected in expected_outputs.items():
        require(final_rows[path]["git_blob"] == expected["git_blob"],
                "Root source differs from original committed formatter postimage")
    binaries_before = doc(root_prefix + "root-binaries-before.json")
    binaries_after = doc(root_prefix + "root-binaries-after.json")
    require(binaries_before == binaries_after and binaries_before["source"] == root["head"]
            and binaries_before["tree"] == root["tree"] and binaries_before["builder_uid"] == 0,
            "actual Root test binary custody changed")
    executed = doc(root_prefix + "root.execution.json")
    require(executed["source_sha"] == root["head"] and executed["tested_sha"] == root["head"]
            and executed["lane"] == "source-head" and executed["status"] == "failed"
            and executed["command_exit_code"] == 100 and executed["timed_out"] is False
            and executed["output_limit_exceeded"] is False,
            "original Root execution outcome differs")
    require(executed["before"] == executed["after"]
            and executed["before"]["commit"] == root["head"]
            and executed["before"]["tree"] == root["tree"]
            and executed["before"]["dirty"] is False,
            "original Root recorder lacks identical clean source")
    uid = doc(root_prefix + "root.uid.json")
    require(uid["uid"] == 0 and uid["euid"] == 0, "original test was not actual UID0")
    for binding in root_progress["root_uid_proofs"]:
        _, value = recorded_file(root, binding)
        proof = parse_json(value)
        require(proof["uid"] == 0 and proof["euid"] == 0, "original Root proof differs")
    log_prefix = root["records"] + "/"
    require(executed["log_file"].startswith(log_prefix), "original execution log escapes records")
    log_name = root_prefix + safe_name(executed["log_file"][len(log_prefix):])
    require(len(raw(log_name)) == 86411
            and sha(raw(log_name)) == "44be455d3f9da9c493ef23cbe02f376a5d88d1f1e61dddf8b291d0148507caed"
            and git_blob(raw(log_name)) == "cb2d654ea6ca913fcdf329e134dae6794e9e5b4a",
            "independently pinned original Root log differs")
    junit = raw(root_prefix + "root.junit.xml")
    require(b"<!DOCTYPE" not in junit and b"<!ENTITY" not in junit,
            "unexpected XML declaration")
    cases = list(ET.fromstring(junit).iter("testcase"))
    live = [case for case in cases if case.find("skipped") is None]
    failures = sum(case.find("failure") is not None for case in cases)
    errors = sum(case.find("error") is not None for case in cases)
    counts = {"total": len(cases), "executed": len(live),
              "passed": len(live) - failures - errors, "failed": failures,
              "errors": errors, "skipped": len(cases) - len(live)}
    require(counts == C["root_expected_counts"] == root_progress["root_counts"]
            == doc(root_prefix + "root.counts.json"), "original Root counts differ")
    names = [case.attrib["name"] for case in live]
    require(len(names) == len(set(names)) == 17
            and sorted(names) == sorted(C["root_expected_parents"]),
            "original distinct Root parent roster differs")
    coverage = doc(root_prefix + "root-parent-coverage.json")
    require(sorted(coverage["expected"]) == sorted(names)
            and sorted(coverage["observed"]) == sorted(names),
            "original Root coverage differs")
    require(len(root_progress["cleanup"]) == 9
            and all(value["status"] == "passed" for value in root_progress["cleanup"]),
            "an original Root cleanup did not pass")
    cleanup_steps = [step for step in root_progress["steps"]
                     if step["name"].startswith("cleanup-")]
    require(len(cleanup_steps) == 4 and all(step["exit_code"] == 0 for step in cleanup_steps),
            "an original cleanup command failed")
    _, helper_bytes = recorded_file(root, root_progress["helper_manifest_before"])
    helper_manifest = parse_json(helper_bytes)
    for name in ("same-source-helper-build", "same-source-helper-preverify",
                 "same-source-helper-postverify"):
        item = next(item for item in root_progress["execution_records"] if item["name"] == name)
        require(item["passed"] is True, "original helper execution was not accepted")
        _, value = recorded_file(root, item["record"])
        helper_execution = parse_json(value)
        require(helper_execution["status"] == "passed"
                and helper_execution["command_exit_code"] == 0
                and helper_execution["timed_out"] is False
                and helper_execution["output_limit_exceeded"] is False,
                "original helper execution differs")
    require(root_progress["full_qualification_accepted"] is False
            and root_progress["ordinary_complete_chains"] == 0
            and root_progress["positive_adoption_chains"] == 0
            and root_progress["ordinary_no_update_rollback_chains"] == 0
            and root_progress["independent_consumer_accepted"] is False
            and root_progress["physical_daemon_root_restart_accepted"] is False,
            "original non-acceptance boundary differs")
    report["root_attempt"] = {
        "source": root["head"], "tree": root["tree"],
        "status": root_progress["status"], "counts": counts,
        "failed_parent_names": [case.attrib["name"] for case in cases
                                if case.find("failure") is not None or case.find("error") is not None],
        "uid": uid, "command_exit": executed["command_exit_code"],
        "original_errors": root_progress["errors"],
        "not_run": root_progress["not_run"],
        "physical_inventory_unchanged": True,
        "physical_inventory_files": final_summary["files"],
        "physical_inventory_sha256": final_summary["inventory_sha256"],
        "test_binary_custody_equal": True,
        "test_binary_custody": binaries_after,
        "helper_manifest": helper_manifest,
        "helper_build_and_both_verifiers": "original executions passed",
        "cleanup": root_progress["cleanup"],
        "cleanup_command_results": [{"name": s["name"], "exit_code": s["exit_code"]}
                                    for s in cleanup_steps],
    }

    report["stage"] = "final-original-file-stability"
    require(stat_fields(os.fstat(fd)) == stat_fields(before)
            and stat_fields(os.stat(C["archive"], follow_symlinks=False)) == stat_fields(before)
            and os.path.realpath(C["archive"]) == C["archive"],
            "original archive metadata/path changed during independent parsing")
    report["archive_before_after"] = {
        "version": file_version(before), "regular_single_link": True, "stable": True,
        "bytes": len(data), "sha256": sha(data), "git_blob": git_blob(data),
    }
    report["manifest_sha256"] = sha(payloads["MANIFEST.json"])
    report["member_count"] = len(member_proofs)
    report["payload_files"] = len(rows)
    report["uncompressed_total_bytes"] = total
    report["member_proofs"] = member_proofs
    report["request_member_comparison"] = (
        "Exporter-normalized JSON objects equal the pre-pinned original request/observation "
        "objects. Their separate original raw blobs are not mislabeled as byte-identical members."
    )
    report["status"] = "verified-original-records-still-failed-native-attempts"
    report["stage"] = "complete"
except BaseException as error:
    report["status"] = "independent-archive-review-failed"
    report["error"] = type(error).__name__ + ": " + str(error)
    report["traceback"] = traceback.format_exc()
finally:
    if fd is not None:
        os.close(fd)
print(json.dumps(report, indent=2, sort_keys=True), flush=True)
raise SystemExit(0 if report["status"] == "verified-original-records-still-failed-native-attempts" else 1)
