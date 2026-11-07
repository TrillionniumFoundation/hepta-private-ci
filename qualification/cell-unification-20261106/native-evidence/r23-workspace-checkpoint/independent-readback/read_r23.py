#!/usr/bin/env python3
"""Independently read a closed r23 archive; no tools, builds or source writes."""

import argparse
import collections
import gzip
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("retained_independent_tree_reader", ROOT / "reused_source_reader.py")
READER = importlib.util.module_from_spec(spec)
spec.loader.exec_module(READER)
READER.ROOT = ROOT
READER.SPECS["r23"] = {
    "archive_sha": "0e7f39f14a68e20bdaefa9646177bc5879098285e45ca42c6d13b81180fa7ee6",
    "archive_bytes": 2165685,
    "members": 211,
    "sources": 188,
    "source_manifest": "native-candidate-r22-source.json",
    "source_manifest_sha": "8cd1ec59c95d6c777d887f3302b257dc5230a7bfa5570fe9df0f0b2ef361aba5",
    "stage": 49,
    "commit": "50dd4bedefcd1b8e2e8cd5cf5023c60a86d38d0a",
    "tree": "be34ab1afe622ad3b8f030c8c5018f4f54fbc304",
    "parent": "07699df6fb5bfb46562ecb0c2eccd0d232d18eac",
}
TREE = READER.SPECS["r23"]["tree"]
COMMIT = READER.SPECS["r23"]["commit"]
COMMAND = ["just", "test", "--locked", "--retries", "0"]
PREFIX = "evidence/native-workspace-r23"
JOB = "1a1b0f18be6-fc05-7441"


def write_json(path, value):
    return READER.write_json(ROOT / path, value)


def packed_json(path, value):
    raw = (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()
    data = gzip.compress(raw, mtime=0)
    assert gzip.decompress(data) == raw
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        assert target.read_bytes() == data
    else:
        target.write_bytes(data)
    return {"path": path, **READER.pin(data), "git_blob": READER.blob(data),
            "compression": "gzip mtime=0", "uncompressed": READER.pin(raw)}


def phase_read(items):
    names = {kind: PREFIX + suffix for kind, suffix in {
        "receipt": "-tests-receipt.json", "raw_result": "-tests-raw-process-result.json",
        "resources": "-tests-resources.txt", "log": "-tests.log",
        "environment": "-environment.json", "pre": "-source-pre-verification.json",
        "post": "-source-post-test-verification.json", "outer": "-terminal-process-status.json",
    }.items()}
    receipt = json.loads(items[names["receipt"]])
    raw = json.loads(items[names["raw_result"]])
    env = json.loads(items[names["environment"]])
    resource = items[names["resources"]].decode()
    terminal = json.loads(items[names["outer"]])
    for obj in (receipt, raw, env):
        assert obj["source_tree"] == TREE and obj["source_commit"] == COMMIT
    for obj in (receipt, raw):
        assert obj["exit_code"] == 100 and obj["command"] == COMMAND
        assert obj["cwd"] == "/home/alex/work/hepta-cell-unified-20261106-a/source/codex-rs"
    for field in ("start_unix", "end_unix"):
        assert receipt[field] == raw[field]
    assert math.isclose(receipt["elapsed_seconds"], receipt["end_unix"] - receipt["start_unix"], abs_tol=1e-6)
    assert receipt["elapsed_seconds"] > 0
    assert receipt["log_sha256"] == READER.sha(items[names["log"]]) == "eb06c476d928ec2a6ebc95d3b3b84aa219ddd3a533d5a04d11aa4a217164d78e"
    assert receipt["resources_sha256"] == READER.sha(items[names["resources"]]) == "0cbaa54be8b81bb184ffcf9d3c7ff38657f571ed7352f51be438d4be72781785"
    assert re.findall(r"(?m)^\s*Exit status: (\d+)\s*$", resource) == ["100"]
    assert re.findall(r'^\s*Command being timed: "(.*)"\s*$', resource, re.M) == [" ".join(COMMAND)]
    assert receipt["source_manifest"] == env["source_manifest"] == "native-candidate-r22-source.json"
    assert env["source_manifest_sha256"] == READER.sha(items["evidence/native-candidate-r22-source.json"])
    assert receipt["retries"] == 0 and receipt["features"] == "unchanged_defaults"
    assert receipt["filters"] == "no_additions" and receipt["test_scope"] == "original_default_workspace"
    guards = {}
    for label in ("pre", "post"):
        guard = json.loads(items[names[label]])
        assert guard["pass"] is True and guard["expected_tree"] == guard["actual_tree"] == TREE
        assert guard["changed_file_count"] == 188 and guard["lock_sha256"] == READER.LOCK_SHA
        for field in ("unstaged_paths", "untracked_paths", "file_mismatches"):
            assert guard[field] == []
        if label == "post":
            assert guard["gate_exit_code"] == 100 and guard["source_commit"] == COMMIT
        guards[label] = {"path": names[label], **READER.pin(items[names[label]]), "pass": True}
    assert terminal["job_id"] == JOB and terminal["exit_code"] == 100 and terminal["state"] == "failed"
    for key in ("automatic_retry", "cancelled", "timed_out"):
        assert terminal[key] is False
    for key in ("output_complete", "output_durable", "terminal_publication_confirmed"):
        assert terminal[key] is True
    assert terminal["at_unix_ms"] / 1000 >= receipt["end_unix"]
    stdout_name = PREFIX + "-process.stdout.txt"
    stderr_name = PREFIX + "-process.stderr.txt"
    for stream, name in (("stdout", stdout_name), ("stderr", stderr_name)):
        assert terminal["log_bytes"][stream]["seen"] == terminal["log_bytes"][stream]["stored"] == len(items[name])
        assert terminal["log_synced"][stream] is True and terminal["log_truncated"][stream] is False
        assert terminal["log_errors"][stream] is None
    prerequisites = []
    for previous in env["project_gate_prerequisites"]:
        p = "input/" + previous["path"]
        assert READER.sha(items[p]) == previous["sha256"]
        result = json.loads(items[p])
        assert result["exit_code"] == previous["exit_code"] == 0
        assert result["source_tree"] == previous["source_tree"] == TREE
        assert result["source_commit"] == COMMIT
        for field in ("log_sha256", "resources_sha256"):
            assert result[field] == previous[field]
        prerequisites.append({"path": p, **READER.pin(items[p]), "exit_code": 0})
    assert len(prerequisites) == 2
    assert READER.sha(items["input/native-app-server-client-r22-complete.json"]) == env["project_complete_sha256"]
    assert READER.sha(items["input/native-app-server-client-r22-result-review.json"]) == env["project_readback_sha256"]
    assert READER.sha(items["input/native-run-r23.py"]) == "2911377daa62a5ceab83a18d4258edf9d2224219605e473b8e9e4e74ae9754f8"
    return {"command": COMMAND, "raw_exit_code": 100, "resource_exit_code": 100, "outer_exit_code": 100,
            "elapsed_seconds": receipt["elapsed_seconds"], "start_unix": receipt["start_unix"], "end_unix": receipt["end_unix"],
            "source_guards": guards, "job_id": JOB, "outer_state": "failed",
            "outer_natural_terminal_no_timeout_cancel_retry": True, "outer_complete_durable": True,
            "prior_project_same_source_receipts": prerequisites,
            "runner": {"path": "input/native-run-r23.py", **READER.pin(items["input/native-run-r23.py"])},
            "inputs": {k: {"path": v, **READER.pin(items[v])} for k, v in names.items()},
            "scope_boundary": "Prior r22 full logs were separately verified; here their exact successful receipts and hashes are bound. Full workspace r23 remains FAILED, and the one per-test TIMEOUT is distinct from outer timed_out=false."}


def workspace_read(items):
    metadata_name = PREFIX + "-metadata.json"
    scope_name = PREFIX + "-scope.json"
    metadata = json.loads(items[metadata_name])
    scope = json.loads(items[scope_name])
    members, defaults = metadata["workspace_members"], metadata["workspace_default_members"]
    assert len(members) == len(defaults) == len(set(members)) == len(set(defaults)) == 193
    assert set(members) == set(defaults)
    assert scope["metadata_sha256"] == READER.sha(items[metadata_name])
    assert scope["metadata_command"] == ["cargo", "metadata", "--locked", "--no-deps", "--format-version", "1"]
    names = {p["id"]: p["name"] for p in metadata["packages"]}
    for field, ids in (("workspace_members", members), ("workspace_default_members", defaults)):
        assert scope[field] == [{"id": i, "name": names[i]} for i in ids]
    return {"metadata": {"path": metadata_name, **READER.pin(items[metadata_name])},
            "scope": {"path": scope_name, **READER.pin(items[scope_name])},
            "member_count": 193, "default_member_count": 193, "member_sets_equal": True,
            "exact_test_command_has_no_package_selector_or_added_filter": COMMAND == ["just", "test", "--locked", "--retries", "0"]}


def log_read(items):
    log_name = PREFIX + "-tests.log"
    raw = items[log_name]
    assert len(raw) == 2503794
    line_re = re.compile(rb"^\s*(PASS|FAIL|TIMEOUT)\s+\[\s*(\d+(?:\.\d+)?)s\]\s+(\S+)\s+(.+?)\s*$")
    start_re = re.compile(rb"^\s*Starting (\d+) tests across (\d+) binaries \((\d+) tests skipped\)\s*$")
    summary_re = re.compile(rb"^\s*Summary \[\s*(\d+(?:\.\d+)?)s\] (\d+) tests run: (\d+) passed(?: \((\d+) slow\))?, (\d+) failed, (\d+) timed out, (\d+) skipped\s*$")
    starts, summaries, rows, footer = [], [], [], []
    offset = 0
    for lineno, line in enumerate(raw.splitlines(keepends=True), 1):
        start = start_re.match(line)
        if start:
            starts.append({"line": lineno, "byte_offset": offset, "text": line.decode().rstrip("\n"),
                           "tests": int(start[1]), "binaries": int(start[2]), "skipped": int(start[3])})
        summary = summary_re.match(line)
        if summary:
            summaries.append({"line": lineno, "byte_offset": offset, "text": line.decode().rstrip("\n"),
                "seconds": float(summary[1]), "run": int(summary[2]), "pass": int(summary[3]),
                "slow": int(summary[4] or 0), "fail": int(summary[5]), "timeout": int(summary[6]), "skipped": int(summary[7])})
        match = line_re.match(line)
        if match:
            row = {"status": match[1].decode(), "seconds": float(match[2]), "binary": match[3].decode(),
                   "name": match[4].decode(), "line": lineno, "byte_offset": offset}
            (footer if summaries else rows).append(row)
        offset += len(line)
    assert len(starts) == len(summaries) == 1
    assert starts[0]["tests"] == 20228 and starts[0]["binaries"] == 366 and starts[0]["skipped"] == 130
    assert len(rows) == len({(r["binary"], r["name"]) for r in rows}) == 20228
    counts = collections.Counter(row["status"] for row in rows)
    assert counts == {"PASS": 20220, "FAIL": 7, "TIMEOUT": 1}
    summary = summaries[0]
    assert (summary["run"], summary["pass"], summary["fail"], summary["timeout"], summary["skipped"], summary["slow"]) == (20228, 20220, 7, 1, 130, 4)
    assert starts[0]["byte_offset"] < rows[0]["byte_offset"] < rows[-1]["byte_offset"] < summary["byte_offset"]
    failing = [r for r in rows if r["status"] != "PASS"]
    assert len(footer) == 8
    assert {(r["binary"], r["name"], r["status"], r["seconds"]) for r in footer} == {(r["binary"], r["name"], r["status"], r["seconds"]) for r in failing}
    original_rows = json.loads(items[PREFIX + "-closed-test-results.json"])
    assert rows == original_rows
    original_blocks = json.loads(items[PREFIX + "-closed-failure-blocks.json"])
    assert len(original_blocks) == 8
    by_id = {(row["binary"], row["name"]): (index, row) for index, row in enumerate(rows)}
    blocks = []
    for block in original_blocks:
        index, row = by_id[(block["binary"], block["name"])]
        assert row["status"] == block["status"] != "PASS"
        start = row["byte_offset"]
        end = rows[index + 1]["byte_offset"] if index + 1 < len(rows) else summary["byte_offset"]
        assert (start, end) == (block["start_byte"], block["end_byte"])
        text = raw[start:end]
        assert READER.sha(text) == block["sha256"] and text.decode() == block["text"]
        blocks.append({**block, "independently_recomputed_row_boundary_and_sha256": True})
    assert {(r["binary"], r["name"]) for r in failing} == {(r["binary"], r["name"]) for r in blocks}
    row_pin = packed_json("PARSED-EXECUTION-ROWS.json.gz", rows)
    block_pin = write_json("FAILURE-BLOCKS.json", blocks)
    by_binary = collections.defaultdict(collections.Counter)
    for row in rows:
        by_binary[row["binary"]][row["status"]] += 1
    binary_pin = write_json("PER-BINARY-COUNTS.json", {key: dict(value) for key, value in sorted(by_binary.items())})
    return {"full_log": {"path": log_name, **READER.pin(raw)}, "starting": starts[0], "summary": summary,
            "unique_execution_count": len(rows), "observed_binary_count": len(by_binary),
            "counts": dict(counts), "reported_skipped": 130,
            "skipped_test_identities_inferred": False,
            "footer_duplicates_excluded": len(footer), "footer_rows": footer,
            "unique_failed_or_timed_out_ids": [{key: value for key, value in r.items()} for r in failing],
            "execution_rows": row_pin, "failure_blocks": block_pin, "per_binary_counts": binary_pin,
            "native_derived_rows_exactly_match_independent_parse": True,
            "all_eight_original_failure_block_bytes_offsets_sha256_match": True,
            "test_execution_did_start": True, "qualification": "FAIL"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--native-results", type=Path, required=True)
    args = parser.parse_args()
    original = READER.load_original()
    items, archive = READER.archive_read("r23", args.native_results)
    source = READER.source_read("r23", items, original)
    phases = phase_read(items)
    workspace = workspace_read(items)
    tests = log_read(items)
    result = {
        "schema": "hepta.r23-independent-full-readback.v1", "source_stage": 49,
        "archive_and_source": "VERIFIED", "test_gate": "FAIL", "archive": archive,
        "source": source, "original_framework_validation": original["report_pin"],
        "phases_and_outer": phases, "workspace_scope": workspace, "full_log_test_results": tests,
        "tree_rebuild_used_root_result_or_target_tree_as_input": False,
        "raw_archive_and_all_source_files_read_independently": True,
        "no_build_test_or_native_command_executed": True, "no_active_log_read": True,
        "no_original_evidence_or_source_modified": True,
        "final_fix_fmt_eligible": False,
        "scientific_or_authority_disposition_changed": False,
        "scope": "A new independent r23 audit. Reuses exact retained independent framework/Git inputs and source-reader code, rerunning all archive and tree hashes. No root result readback is consumed. Failures remain failures; no repair candidate was executed by this reader.",
    }
    report = write_json("INDEPENDENT-READBACK.json", result)
    print(json.dumps({"report": report, "source_tree": source["computed_tree"], "source_files": source["source_count"],
        "archive_members": archive["members"], "test_counts": tests["counts"], "reported_skipped": tests["reported_skipped"],
        "raw_exit": phases["raw_exit_code"], "outer_exit": phases["outer_exit_code"]}, indent=2))


if __name__ == "__main__":
    main()
