#!/usr/bin/env python3
"""Read-only verification of the original B21 Intel run and its causal limits."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile

import zstandard


HEAD = "cc65856cc0b20d03db506c19495d53d61162102d"
TREE = "eaded1870d080eaa55efae6208354729140e784c"
PARENT = "67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed"
PARENT_TREE = "3982ba56dc5a3f1da0c1de7ea57992f88125c359"
MERGE = "f0355601e362e2ad4947b40d51215e5c4d075fc3"
TARGET = "//codex-rs/utils/pty:pty-unit-tests"
RUN = 42138373221
JOB = 127632180031
ARTIFACT = 13466574706
ADDED_CASE = "tests::output_collector_waits_for_exit_after_output_closes"
WORKFLOW = ".github/workflows/b21-intel-original-pty.yml"


def identity(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def un(response):
    assert not response.get("isError", False)
    return response.get("structuredContent") or json.loads(next(x["text"] for x in response["content"] if x["type"] == "text"))


def varint(data, pos):
    value = shift = 0
    while True:
        assert pos < len(data) and shift <= 63
        byte = data[pos]
        pos += 1
        value |= (byte & 127) << shift
        if not byte & 128:
            return value, pos
        shift += 7


def fields(data):
    pos = 0
    result = {}
    while pos < len(data):
        key, pos = varint(data, pos)
        number, wire = key >> 3, key & 7
        assert number
        if wire == 0:
            value, pos = varint(data, pos)
        elif wire == 2:
            size, pos = varint(data, pos)
            assert pos + size <= len(data)
            value, pos = data[pos:pos + size], pos + size
        elif wire in (1, 5):
            size = 8 if wire == 1 else 4
            assert pos + size <= len(data)
            value, pos = data[pos:pos + size], pos + size
        else:
            raise ValueError(f"unsupported wire type {wire}")
        result.setdefault(number, []).append(value)
    assert pos == len(data)
    return result


def one(message, number, default=b""):
    values = message.get(number, [])
    assert len(values) <= 1
    return values[0] if values else default


def integers(message, number):
    result = []
    for value in message.get(number, []):
        if isinstance(value, int):
            result.append(value)
        else:
            pos = 0
            while pos < len(value):
                integer, pos = varint(value, pos)
                result.append(integer)
    return result


def merkle(document):
    rows = {row["path"]: row for row in document["tree"]}
    assert not document["truncated"] and len(rows) == len(document["tree"])
    children = {"": []}
    for path, row in rows.items():
        parent, _, name = path.rpartition("/")
        children.setdefault(parent, []).append((name, row))
        if row["type"] == "tree":
            children.setdefault(path, [])
    computed = {}
    for directory in sorted(children, key=lambda p: (p.count("/") + bool(p), p), reverse=True):
        raw = b""
        for name, row in sorted(children[directory], key=lambda p: (p[0] + ("/" if p[1]["type"] == "tree" else "")).encode()):
            path = directory + "/" + name if directory else name
            sha = computed[path] if row["type"] == "tree" else row["sha"]
            if row["type"] == "tree":
                assert sha == row["sha"], path
            mode = "40000" if row["type"] == "tree" else row["mode"]
            raw += mode.encode() + b" " + name.encode() + b"\0" + bytes.fromhex(sha)
        computed[directory] = hashlib.sha1(b"tree " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    assert computed[""] == document["sha"]
    return {p: (r["mode"], r["type"], r["sha"]) for p, r in rows.items() if r["type"] != "tree"}, len(computed)


def cases(raw):
    rows = re.findall(rb"(?m)^(?:\d{4}-\S+Z )?test ([A-Za-z0-9_:]+) \.\.\. (ok|FAILED|ignored)\s*$", raw)
    result = {name.decode(): status.decode() for name, status in rows}
    assert len(result) == len(rows)
    return result


def main(root):
    def read(name):
        return (root / name).read_bytes()
    def js(name):
        return json.loads(read(name))
    run = json.loads(un(js("originals/run-detail-terminal.original.json"))["content"])
    assert (run["id"], run["run_attempt"], run["event"], run["status"], run["conclusion"], run["head_sha"]) == (RUN, 1, "pull_request", "completed", "success", HEAD)
    assert run["head_commit"]["tree_id"] == TREE and run["path"] == WORKFLOW
    job_rows = un(js("originals/jobs-terminal.original.json"))["jobs"]
    assert len(job_rows) == 1
    job = job_rows[0]
    assert (job["id"], job["run_id"], job["status"], job["conclusion"]) == (JOB, RUN, "completed", "success")
    assert all(row["status"] == "completed" and row["conclusion"] == "success" for row in job["steps"])
    original_job = read("originals/full-job.original.log")
    assert un(js("originals/full-job-log.original.json"))["content"].encode() == original_job
    artifact_rows = un(js("originals/artifacts-terminal.original.json"))["artifacts"]
    assert len(artifact_rows) == 1
    artifact = artifact_rows[0]
    assert artifact["id"] == ARTIFACT and artifact["name"] == f"b21-original-intel-pty-{RUN}-1"
    assert artifact["workflow_run"]["id"] == RUN and artifact["workflow_run"]["head_sha"] == HEAD
    archive_bytes = read(f"originals/b21-original-intel-pty-{RUN}-1.original.zip")
    archive_identity = identity(archive_bytes)
    assert archive_identity["bytes"] == artifact["size_in_bytes"] == 1551105
    assert artifact["digest"] == "sha256:" + archive_identity["sha256"]
    assert archive_identity["sha256"] == "26d153e60b60e8206261da3819a9f1a8ac235fd2e3b82d3a709de8bdb9373309"
    archive = zipfile.ZipFile(io.BytesIO(archive_bytes))
    assert archive.testzip() is None and len(archive.infolist()) == 17
    members = {}
    zip_rows = []
    for entry in archive.infolist():
        assert not entry.is_dir() and not Path(entry.filename).is_absolute() and ".." not in Path(entry.filename).parts
        assert entry.filename not in members
        raw = archive.read(entry)
        assert len(raw) == entry.file_size
        members[entry.filename] = raw
        zip_rows.append({"path": entry.filename, "bytes": entry.file_size, "compressed_bytes": entry.compress_size, "crc32": entry.CRC})
    assert zip_rows == js("originals/zip-members.original.json")
    observed = "b21-original-intel-pty/"
    assert members[observed + "source-head-tree.txt"].decode().splitlines() == [HEAD, TREE, PARENT, PARENT_TREE]
    assert members[observed + "source-final-head-tree.txt"].decode().splitlines() == [HEAD, TREE]
    assert members[observed + "changed-paths.txt"].decode().splitlines() == [WORKFLOW]
    assert members[observed + "source-status-before.txt"] == members[observed + "source-status-after.txt"] == b""
    assert members[observed + "original-bazel-exit-code.txt"] == members[observed + "console-copy-exit-code.txt"] == b"0\n"
    parent_doc, after_doc = js("publication/parent-full-tree.json"), js("publication/intended-full-tree.json")
    parent, parent_dirs = merkle(parent_doc)
    after, after_dirs = merkle(after_doc)
    assert parent_doc["sha"] == PARENT_TREE and after_doc["sha"] == TREE
    assert len(parent) == 10582 and len(after) == 10583 and parent_dirs == after_dirs == 1571
    assert set(after) - set(parent) == {WORKFLOW} and all(after[p] == value for p, value in parent.items())
    actual_leaves = {}
    for line in members[observed + "source-leaves.txt"].decode().splitlines():
        entry, path = line.split("\t")
        mode, kind, sha = entry.split()
        assert path not in actual_leaves
        actual_leaves[path] = (mode, kind, sha)
    assert actual_leaves == after
    source_commit = js("publication/commit-ref-actual.json")["actualCommit"]
    actual_merge = js("publication/actual-merge-commit.json")["response"]
    assert (source_commit["sha"], source_commit["tree"]["sha"]) == (HEAD, TREE)
    assert [x["sha"] for x in source_commit["parents"]] == [PARENT]
    assert (actual_merge["sha"], actual_merge["tree"]["sha"]) == (MERGE, TREE)
    assert [x["sha"] for x in actual_merge["parents"]] == [PARENT, HEAD]
    workflow = read("source/workflow.yml")
    assert identity(workflow)["git_blob"] == after[WORKFLOW][2] == "77387b7a3e8a15efe11cca02bf4185377ff0a86f"
    assert b"test \"$(uname -s)\" = Darwin" in workflow and b"test \"$(uname -m)\" = x86_64" in workflow
    assert b'test "$RUNNER_ARCH" = X64' in workflow
    uname, cpu, macos = [members[observed + n].decode().strip() for n in ["uname.txt", "cpu-brand.txt", "macos-version.txt"]]
    assert uname.startswith("Darwin ") and uname.endswith(" x86_64") and "Intel(R)" in cpu
    assert "15.7.9" in macos
    argv = members[observed + "command.argv0"].decode().split("\0")
    assert argv[-1] == ""
    argv.pop()
    expected_argv = ["./.github/scripts/run-bazel-ci.sh", "--print-failed-action-summary", "--print-failed-test-logs", "--", "test", "--test_tag_filters=-argument-comment-lint", "--test_verbose_timeout_warnings", "--nocache_test_results", "--flaky_test_attempts=1", "--build_metadata=COMMIT_SHA=" + HEAD, "--", TARGET]
    assert argv == expected_argv
    console = members[observed + "console.log"]
    manifest_paths = [p for p in members if p.endswith("manifest.json")]
    assert manifest_paths == ["bazel-execution-logs/selected-target-test-logs/invocation-g966bhtk/manifest.json"]
    manifest_path = manifest_paths[0]
    manifest = json.loads(members[manifest_path])
    assert manifest["complete_for_selected_targets"] and manifest["complete_case_inventory"] is False
    assert manifest["errors"] == [] and manifest["retention"]["selection_errors"] == []
    assert manifest["selected_targets"] == [TARGET]
    assert manifest["source"] == {"commit": HEAD, "tracked_worktree_dirty": False, "tree": TREE}
    assert len(manifest["files"]) == 2
    retained_console_size = manifest["retention"]["console_bytes"]
    retained_console_hash = manifest["retention"]["console_sha256"]
    matching_console_offsets = [start for start in range(len(console) - retained_console_size + 1)
        if hashlib.sha256(console[start:start + retained_console_size]).hexdigest() == retained_console_hash]
    assert matching_console_offsets == [67]
    selected = manifest["retention"]["targets"][TARGET]
    assert selected["status"] == "PASSED" and selected["cached_marker"] is False
    target_logs = {}
    for row in manifest["files"]:
        path = str(Path(manifest_path).parent / row["archive_relative_path"])
        raw = members[path]
        assert len(raw) == row["bytes"] and hashlib.sha256(raw).hexdigest() == row["sha256"]
        assert row["target"] == TARGET
        target_logs[Path(path).name] = raw
    reported = cases(target_logs["test.log"])
    assert len(reported) == 31 and set(reported.values()) == {"ok"}
    assert b"31 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 3.65s" in target_logs["test.log"]
    old30 = cases(read("old-roster/original-pty-test.log"))
    assert len(old30) == 30 and set(old30) == set(reported) - {ADDED_CASE}
    xml = ET.fromstring(target_logs["test.xml"])
    assert len(list(xml.iter("testcase"))) == 1
    assert not any(list(xml.iter(tag)) for tag in ["failure", "error", "skipped"])
    assert target_logs["test.log"].strip().decode() in next(xml.iter("system-out")).text
    compressed_path = next(p for p in members if p.endswith(".zst"))
    decoder = zstandard.ZstdDecompressor().decompressobj()
    compact = decoder.decompress(members[compressed_path]) + decoder.flush()
    assert decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail
    assert identity(compact) == js("derived/execution-projection.json")["uncompressed"]
    entries, frames, entry_ids, file_rows, invocations = 0, [], {}, {}, []
    pos = 0
    while pos < len(compact):
        start = pos
        size, pos = varint(compact, pos)
        assert pos + size <= len(compact)
        record = fields(compact[pos:pos + size])
        pos += size
        entries += 1
        if 1 in record:
            key = one(record, 1)
            assert key not in entry_ids
            entry_ids[key] = record
        if 2 in record:
            invocations.append(fields(one(record, 2)))
        if 3 in record:
            file = fields(one(record, 3))
            path = one(file, 1).decode()
            if path.endswith("/pty-unit-tests/test.log") or path.endswith("/pty-unit-tests/test.xml"):
                file_rows[path] = (one(record, 1), file)
        if 7 not in record:
            continue
        spawn = fields(one(record, 7))
        if one(spawn, 7).decode() != TARGET or one(spawn, 8) != b"TestRunner":
            continue
        frame = compact[start:pos]
        assert frame == read(f"derived/action-{len(frames):02d}.protobuf")
        environment = {}
        for item in spawn.get(2, []):
            parsed = fields(item)
            name = one(parsed, 1).decode()
            assert name not in environment
            environment[name] = one(parsed, 2).decode()
        frames.append({"entry_number": entries, "start_byte": start, "end_byte": pos, "identity": identity(frame),
            "args": [x.decode() for x in spawn.get(1, [])], "environment": environment,
            "exit_code": one(spawn, 9, 0), "status": one(spawn, 10).decode(),
            "runner": one(spawn, 11).decode(), "cache_hit": bool(one(spawn, 12, 0)),
            "timeout_millis": one(spawn, 17, 0), "input_set_id": one(spawn, 4, 0),
            "output_ids": [one(fields(x), 5, None) for x in spawn.get(6, []) if 5 in fields(x)]})
    assert pos == len(compact) and entries == 14846 and len(frames) == 2
    assert len(invocations) == 1 and one(invocations[0], 1) == b"SHA-256"
    invocation_id = one(invocations[0], 4).decode()
    assert invocation_id == "21969864-0d2a-42f0-a2bc-7a5e541e7e2b" and invocation_id.encode() in console
    test, xml_action = frames
    assert test["args"] == ["external/bazel_tools/tools/test/test-setup.sh", "codex-rs/utils/pty/pty-unit-tests"]
    assert xml_action["args"][0] == "external/bazel_tools/tools/test/generate-xml.sh"
    assert test["timeout_millis"] == 300000 and test["environment"]["TEST_TIMEOUT"] == "300"
    assert all(f["runner"] == "darwin-sandbox" and f["exit_code"] == 0 and not f["cache_hit"] and f["status"] == "" for f in frames)
    assert not {"TESTBRIDGE_TEST_ONLY", "TEST_FILTER", "RUST_TEST_THREADS", "RUST_TEST_NOCAPTURE"} & set(test["environment"])
    input_record = entry_ids[xml_action["input_set_id"]]
    input_fields = fields(one(input_record, 6))
    xml_inputs = integers(input_fields, 5)
    output_bindings = []
    for path, (key, row) in sorted(file_rows.items()):
        raw = target_logs[Path(path).name]
        digest = fields(one(row, 2))
        assert one(digest, 1).decode() == hashlib.sha256(raw).hexdigest() and one(digest, 2, 0) == len(raw)
        if path.endswith("test.log"):
            assert key in xml_inputs
            binding = "exact input of the same invocation's XML-generation action"
        else:
            assert key in xml_action["output_ids"]
            binding = "exact output of the same invocation's XML-generation action"
        output_bindings.append({"path": path, "entry_id": key, "binding": binding, **identity(raw)})
    assert len(output_bindings) == 2
    primary = read("primary/bazel-9.3.0-spawn.proto.source.txt")
    primary_response = un(js("primary/bazel-9.3.0-spawn-proto-GitHub-original-response.json"))
    assert primary_response["content"].encode() == primary and identity(primary)["git_blob"] == "19f68f22a4d62c4fd1aa28fd1c7c0217aa6a7cb0"
    assert read("source/.bazelversion") == b"9.3.0\n" and identity(read("source/.bazelversion"))["git_blob"] == after[".bazelversion"][2]
    assert b"Starting local Bazel server (9.3.0)" in console
    source_rows = []
    for path in sorted((root / "source/current").glob("*.rs")):
        raw = path.read_bytes()
        source_path = "codex-rs/utils/pty/src/" + path.name
        got = identity(raw)
        assert got["git_blob"] == after[source_path][2]
        assert un(js("source/current/" + path.name + ".full-GET.original.json"))["content"].encode() == raw
        source_rows.append({"path": source_path, **got})
    assert len(source_rows) == 9
    current_tests, old_tests = [read("source/" + p + "/tests.rs") for p in ["current", "old-0e139"]]
    insertion = b'        eprintln!(\n            "PTY dropped receiver: backend={backend} io_snapshot={}",\n            session.pty_io_diagnostic_snapshot(),\n        );\n'
    assert current_tests.count(insertion) == 1 and current_tests.replace(insertion, b"") == old_tests
    assert identity(old_tests)["git_blob"] == "42fc028d6e710dab9f9390ad7ee1b711ba1927d6"
    for required in [b"from_secs(2), exit_rx", b"/*timeout_ms*/ 5_000", b"4 * 1024 * 1024", b"for inherited_fds in [&[][..], &[preserved_fd.as_raw_fd()][..]]", b"child should finish even when output is discarded"]:
        assert required in current_tests
    group_source = read("source/current/process_group.rs")
    assert b'#[cfg(all(test, target_os = "macos"))]\n#[path = "process_group_tests.rs"]\nmod tests;' in group_source
    mac_cases = sorted(p for p in reported if p.startswith("process_group::tests::"))
    assert len(mac_cases) == 2 and all(reported[p] == "ok" for p in mac_cases)
    old_job = read("old-drain/original-job-full.log")
    assert identity(old_job)["sha256"] == "dc3b6664bc61ef353c4fe2d231efc198182536671a6297f2c89b0dfa0e57c49a"
    assert un(js("old-drain/original-job-full-log-tool.json"))["content"].encode() == old_job
    old_block = read("old-drain/original-2s-failure-block.log")
    assert old_block == b"".join(old_job.splitlines(keepends=True)[1367:1415])
    assert identity(old_block)["sha256"] == "65b4c2f87c1884ae35fae23c446a63bfd1759c6d71587bc9281d3ad8dabf1d2d"
    old_cases = cases(old_block)
    assert len(old_cases) == 31 and set(old_cases) == set(reported)
    assert [p for p in old_cases if old_cases[p] == "FAILED"] == ["tests::pty_dropped_output_receiver_keeps_draining_child"]
    assert b"wait_elapsed=2.023066511s outcome=deadline_elapsed has_exited=false exit_code=None" in old_block
    assert b'child_phase=Ok("python_started")' in old_block
    assert not any(marker in target_logs["test.log"] for marker in [b"io_snapshot=", b"read_calls=", b"read_bytes=", b"child_phase=", b"PTY dropped receiver:"])
    assert b"let Some(python) = find_python() else" in current_tests and b"if !setsid_available()" in current_tests
    first_cut = un(js("originals/runs-cut-001.original.json"))["workflow_runs"]
    blocking = next(r for r in first_cut if r["name"] == "blocking-ci")
    assert blocking["status"] == "queued" and blocking["conclusion"] is None
    result = {
        "schema": "b21-original-intel-terminal-independent-offline-proof-v1",
        "B21": "OPEN", "decision": "ORIGINAL_INTEL_LIBTEST_RESULT_VERIFIED_CAUSAL_AND_VISIBILITY_LIMITS_RETAINED",
        "source_head_actually_checked_out": HEAD, "source_tree": TREE,
        "parent": PARENT, "parent_tree": PARENT_TREE,
        "PR_merge_is_not_actual_checkout": MERGE,
        "one_added_workflow_and_10582_prior_leaves_unchanged": True,
        "all_directory_Merkle_nodes_verified": parent_dirs,
        "runtime_all_10583_source_leaves_equal_expected_tree": True,
        "tracked_worktree_before_after_empty_and_final_clean_step_success": True,
        "run_id": RUN, "run_attempt": 1, "job_id": JOB, "run_event": "pull_request",
        "workflow_conclusion": "success", "artifact_id": ARTIFACT,
        "artifact_official_digest_equal": True, "original_zip": archive_identity,
        "archive_members": [{"path": p, **identity(raw)} for p, raw in sorted(members.items())],
        "platform": {"uname": uname, "cpu": cpu, "macos": macos, "Darwin_x86_64_RUNNER_ARCH_X64_guard_step_succeeded": True},
        "wrapper_argv": argv, "original_bazel_exit": 0, "console_copy_exit": 0,
        "selected_target_collector": {"manifest_member": manifest_path, "complete_for_selected_targets": True,
            "complete_case_inventory_original_flag": False, "errors": [], "files_verified": 2,
            "retained_console_exact_slice_in_outer_tee": {"start_byte": 67, "bytes": retained_console_size,
                "sha256": retained_console_hash, "outer_tee_bytes": len(console)},
            "retained_original_limitation": manifest["retention"]["limitations"]},
        "original_test_log": identity(target_logs["test.log"]), "original_test_xml": identity(target_logs["test.xml"]),
        "actual_cases_from_complete_libtest_log": [{"name": p, "status": s, "original_30_subset": p in old30, "macos_only": p in mac_cases} for p, s in sorted(reported.items())],
        "actual_counts": {"passed": 31, "failed": 0, "ignored": 0, "measured": 0, "filtered_out": 0, "reported_seconds": 3.65},
        "original_30_subset_all_reported_ok": True, "existing_added_collector_case": ADDED_CASE,
        "macos_only_cases_reported_ok": mac_cases, "XML_testcase_nodes_are_one_wrapper_not_31_case_nodes": True,
        "compact": {"compressed_member": compressed_path, "compressed_identity": identity(members[compressed_path]),
            "uncompressed_identity": identity(compact), "full_stream_entries": entries, "full_stream_consumed_bytes": pos,
            "invocation_id": invocation_id, "actual_test_actions": 1, "separate_XML_generation_actions": 1,
            "frames": frames, "exact_log_XML_digest_bindings": output_bindings,
            "official_bazel_9_3_0_schema": identity(primary)},
        "current_source_files_actual_full_GET": source_rows,
        "tests_old0e_to_current_only_one_diagnostic_print_insertion": True,
        "original_2s_5s_4MiB_exit_and_FD_assertions_unchanged": True,
        "old_2s_failure": {"run_id": 41975255726, "job_id": 127089468985,
            "full_log_retrieved_by_original_GitHub_job_API_and_historical_hash_equal": identity(old_job),
            "block_identity": identity(old_block), "block_original_lines": [1368, 1415],
            "direct_old_blob_GET_returned_404_preserved_separately": True,
            "actual31": {"passed": 30, "failed": 1}, "original30": {"passed": 29, "failed": 1},
            "wait_elapsed_seconds": "2.023066511", "phase": "python_started", "production_root_cause": "UNKNOWN"},
        "limits": [
            "Current passing libtest output does not expose the per-session diagnostic counters or child phases.",
            "Existing find_python/setsid early-return preconditions remain. Captured successful output cannot independently rule out these branches; absent skip text is not proof that every guarded body ran.",
            "No new causal attribution to scheduling, load, throughput, readiness, collector or a specific production repair follows from this single pass.",
            "The two Mac-only process-group cases have actual ok result rows and no new skip/filter was introduced.",
            "This focused HEAD diagnostic does not replace original full required CI or qualify the PR merge/main; blocking-ci was queued at the single cut."
        ],
        "new_native_driver_call": False, "host_resource_query": False,
        "manual_workflow_dispatch_rerun_cancel": False, "ref_mutation": False,
        "all_blockers_closed": False,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    main(args.root.resolve())
