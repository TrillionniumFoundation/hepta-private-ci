"""Offline verification of the completed Objective owner job; executes no product code."""
from pathlib import Path, PurePosixPath
import argparse
import hashlib
import io
import json
import re
import stat
import textwrap
import zipfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent
SOURCE = "67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed"
TREE = "3982ba56dc5a3f1da0c1de7ea57992f88125c359"
BASE = "63652be658ebed8d3052eb789b951793384fd5e4"
RUN, JOB, ARTIFACT = 42123581408, 127581904963, 13471885720
ZIP_SHA256 = "4d41426b73b32fa6235034e1183dbb7168ed096e2e4a03f22ce81d26ad22eab2"
CONSOLE_ID = {
    "bytes": 1606119, "git_blob": "5ca1c1c9543c21ff9647dcb90dfd32ada53e9f22",
    "sha256": "74fbbd060d64f9a1ae18bd91f3a483ca0a8f62fc5e7bab58828d89a5bf33c370",
}
SOURCE_BLOBS = {
    ".github/workflows/hepta-objective-owner.yml": "22b551a58fa9900560767a2b39da5d3f1d01aeea",
    "codex-rs/hepta-memory/src/objective_sender_tests.rs": "bdc6765e6f6c48d78963f1ace5a23cdd6f97e309",
    "codex-rs/hepta-agentd/src/objective_control_tests.rs": "4c404113a3a8dc5711a90c9a15c2b0650673e773",
    "codex-rs/hepta-agentd/src/desktop_objective_ui_tests.rs": "52c2989f076e9ce1cf4c891d65e3ce2911f9091f",
}
REQUIRED_MEMORY = {
    "checked_concurrent_history_keeps_one_publication_and_idempotent_acknowledgement",
    "checked_negative_control_separate_prechecks_allow_conflicting_generic_appends",
    "snapshot_acknowledged_does_not_promote_a_committed_observation_without_checkpoint_ack",
    "snapshot_acknowledged_holds_the_original_write_lock_through_the_current_cut_ack",
    "snapshot_acknowledged_recovers_local_cancellation_without_a_new_cancellation_right",
    "checkpoint_current_cancelled_future_releases_lock_without_creating_sender_state",
    "checkpoint_current_holds_the_original_write_lock_through_acknowledgement",
    "checkpoint_current_invalid_deadline_and_terminal_leases_never_call_the_publisher",
    "checkpoint_current_refusal_timeout_mismatch_and_live_revocation_preserve_the_cut",
    "checkpoint_current_without_a_request_uses_the_original_fence_and_changes_no_rows",
}
REQUIRED_CONTROL = {
    "original_sender_reaches_real_control_admission_history_and_cancellation_once",
    "real_control_lost_ack_recovers_exact_admission_without_replaying_submission",
    "original_checkpoint_refusal_prevents_transport_and_recovery_keeps_unknown",
    "local_cancel_recovers_permanent_fence_without_a_network_request",
    "closing_original_window_retires_callbacks_before_retention_or_transport",
    "actual_kernel_peer_mismatch_cannot_write_a_control_frame",
    "a_multiline_original_is_rejected_before_retention_in_the_line_framed_profile",
}
REQUIRED_BRIDGE = {
    "uninstalled_original_objective_sender_refuses_without_a_new_owner",
    "installed_original_objective_sender_reuses_same_writer_and_live_verifier",
    "retained_signed_body_hash_matches_original_agentd_wire_projection",
}
REQUIRED_BOOTSTRAP = {
    "production_composition::tests::checkpoint_failures_and_post_ack_live_refusals_never_install_recovered_hosts",
    "production_composition::tests::invalid_checkpoint_deadline_refuses_before_consulting_external_inputs",
    "production_composition::notes_tests::attached_notes_ack_then_checkpoint_refusal_publishes_no_host_and_closes_target",
}
REQUIRED_DESKTOP = {
    "real_workspace_submit_duplicate_click_and_cancel_use_one_original_owner",
    "real_workspace_lost_ack_and_recovered_window_never_send_a_second_request",
    "signed_window_generation_and_draft_binding_reject_cross_window_adoption",
    "owner_session_rotation_closes_a_waiting_checkpoint_without_late_dispatch",
    "real_workspace_cancel_before_submit_keeps_draft_and_never_dispatches",
}
GROUPS = {
    "production_composition::tests::": 9,
    "production_composition::notes_tests::": 6,
    "production_composition::objective_sender_tests::": 3,
    "production_authority::tests::": 5,
    "final_use_issuer::tests::": 7,
}


def identity(body):
    return {"bytes": len(body), "git_blob": hashlib.sha1(
        b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest(),
        "sha256": hashlib.sha256(body).hexdigest()}


def unwrap(value):
    if "structuredContent" in value:
        value = value["structuredContent"]
    elif isinstance(value.get("content"), list):
        value = json.loads(next(item["text"] for item in value["content"] if item["type"] == "text"))
    if isinstance(value.get("content"), str):
        value = json.loads(value["content"])
    return value


def raw_blob(value):
    value = value.get("structuredContent") or json.loads(
        next(item["text"] for item in value["content"] if item["type"] == "text"))
    return value["content"].encode()


def tree_hash(entries):
    ordered = sorted(entries, key=lambda item: item["name"].encode()
                     + (b"/" if item["mode"] == "40000" else b""))
    data = b"".join(item["mode"].encode() + b" " + item["name"].encode()
                    + b"\0" + bytes.fromhex(item["sha"]) for item in ordered)
    return hashlib.sha1(b"tree " + str(len(data)).encode() + b"\0" + data).hexdigest()


def full_tree(rows):
    directories = {"": []}
    for row in rows:
        parent = row["path"].rpartition("/")[0]
        while parent:
            directories.setdefault(parent, [])
            parent = parent.rpartition("/")[0]
    for row in rows:
        parent, _, name = row["path"].rpartition("/")
        directories[parent].append({"name": name, "mode": row["mode"], "sha": row["git_blob"]})
    for path in sorted((path for path in directories if path), key=lambda path: (-path.count("/"), path)):
        parent, _, name = path.rpartition("/")
        directories[parent].append({"name": name, "mode": "40000", "sha": tree_hash(directories[path])})
    return tree_hash(directories[""]), len(directories)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--console", type=Path, default=ROOT / "job-127581904963.original.log",
                        help="exact original decoded console from the shared 0244 packet")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    console = args.console.read_bytes()
    assert identity(console) == CONSOLE_ID
    assert console.count(b"\r") == 0
    assert SOURCE.encode() in console and BASE.encode() in console
    artifact_api = unwrap(json.loads((ROOT / "artifacts-page-1.original.json").read_bytes()))
    assert artifact_api["total_count"] == len(artifact_api["artifacts"]) == 1
    artifact = artifact_api["artifacts"][0]
    assert artifact["id"] == ARTIFACT and not artifact["expired"]
    assert artifact["workflow_run"]["id"] == RUN
    assert artifact["workflow_run"]["head_sha"] == SOURCE
    assert artifact["digest"] == "sha256:" + ZIP_SHA256
    jobs_api = unwrap(json.loads((ROOT / "run-42123581408-jobs.original.json").read_bytes()))
    assert jobs_api["total_count"] == len(jobs_api["jobs"]) == 1
    job = jobs_api["jobs"][0]
    assert (job["id"], job["run_id"], job["run_attempt"]) == (JOB, RUN, 1)
    assert job["head_sha"] == SOURCE and job["status"] == "completed" and job["conclusion"] == "success"
    assert job["labels"] == ["ubuntu-24.04"]
    assert all(step["status"] == "completed" and step["conclusion"] == "success" for step in job["steps"])
    zip_body = (ROOT / "artifact-13471885720.original.zip").read_bytes()
    assert len(zip_body) == artifact["size_in_bytes"] == 1071142
    assert hashlib.sha256(zip_body).hexdigest() == ZIP_SHA256
    members, member_proof = {}, []
    with zipfile.ZipFile(io.BytesIO(zip_body)) as archive:
        assert archive.testzip() is None
        assert len(archive.infolist()) == 52
        for info in archive.infolist():
            path = PurePosixPath(info.filename)
            assert not path.is_absolute() and ".." not in path.parts and not info.is_dir()
            assert "\\" not in info.filename and info.filename not in members
            assert not stat.S_ISLNK(info.external_attr >> 16)
            data = archive.read(info)
            members[info.filename] = data
            member_proof.append({"path": info.filename, "crc32": f"{info.CRC:08x}", **identity(data)})
    inventory = json.loads(members["artifact-inventory.json"])
    assert len(inventory) == 51
    assert {entry["path"] for entry in inventory} == set(members) - {"artifact-inventory.json"}
    for entry in inventory:
        actual = identity(members[entry["path"]])
        assert actual["bytes"] == entry["bytes"] and actual["sha256"] == entry["sha256"]
    attempt, source, result = (json.loads(members[name]) for name in ("attempt.json", "source.json", "result.json"))
    assert attempt["SOURCE_SHA"] == SOURCE and attempt["BASE_SHA"] == BASE
    assert attempt["GITHUB_RUN_ID"] == str(RUN) and attempt["GITHUB_RUN_ATTEMPT"] == "1"
    assert attempt["GITHUB_REPOSITORY"] == "TrillionniumFoundation/hepta-private-ci"
    assert attempt["RUNNER_OS"] == "Linux" and attempt["RUNNER_ARCH"] == "X64"
    assert source["head"] == SOURCE and source["tree"] == TREE
    assert not source["errors"] and source["git_status"] == ""
    rows = source["files"]
    assert len(rows) == source["tracked_blobs"] == 10582
    assert len({row["path"] for row in rows}) == 10582
    assert hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest() == source["files_sha256"]
    computed_tree, tree_nodes = full_tree(rows)
    assert computed_tree == TREE
    commit = unwrap(json.loads((ROOT / "authority/main67-commit.GET.original.json").read_bytes()))
    assert commit == json.loads((ROOT / "authority/main67-commit.json").read_bytes())
    assert commit["sha"] == SOURCE and commit["tree"]["sha"] == TREE
    root_api = unwrap(json.loads((ROOT / "authority/main67-root-tree.GET.original.json").read_bytes()))
    assert root_api["sha"] == TREE and not root_api["truncated"]
    assert tree_hash([{"name": e["path"], "sha": e["sha"],
                       "mode": "40000" if e["type"] == "tree" else e["mode"]}
                      for e in root_api["tree"]]) == TREE
    row_map = {entry["path"]: entry for entry in rows}
    locks = [row for row in rows if PurePosixPath(row["path"]).name in
             {"Cargo.lock", "MODULE.bazel.lock", "uv.lock", "pnpm-lock.yaml", "package-lock.json"}]
    assert locks == source["locks"] and len(locks) == 17
    source_records = []
    raw_source_api = {}
    for api_file in sorted((ROOT / "source-api").glob("*.original.json")):
        original = json.loads(api_file.read_bytes())
        raw_source_api[original["path"]] = original
    assert set(raw_source_api) == set(SOURCE_BLOBS)
    for path, expected in SOURCE_BLOBS.items():
        body = (ROOT / "sources" / path).read_bytes()
        actual = identity(body)
        assert actual["git_blob"] == expected == row_map[path]["git_blob"]
        assert actual["sha256"] == row_map[path]["sha256"] and actual["bytes"] == row_map[path]["bytes"]
        assert raw_blob(raw_source_api[path]["original_tool_return"]) == body
        source_records.append({"path": path, **actual, "actual_blob_GET_full_bytes_equal": True})
    workflow = (ROOT / "sources/.github/workflows/hepta-objective-owner.yml").read_text()
    match = re.search(r"^          cat > [^\n]*run_owner\.py[^\n]*<<'PY'\n(.*?)^          PY\n", workflow, re.M | re.S)
    assert match is not None
    assert textwrap.dedent(match.group(1)).encode() == members["run_owner.py"]
    assert 'timeout-minutes: 240' in workflow and 'CARGO_BUILD_JOBS: "1"' in workflow
    assert 'ref: ${{ env.SOURCE_SHA }}' in workflow and 'fetch-depth: 0' in workflow
    assert members["source-drift.patch"] == b""
    shared_source = {key: source[key] for key in ("head", "tree", "tracked_blobs", "files_sha256", "locks", "errors", "git_status")}
    def check_source(value):
        assert value == {**shared_source, "unchanged": True}
    check_source(result["source_final"])
    assert result["source_sha"] == SOURCE and result["owning_packages_qualified"] is True
    for key in ("full_workspace_qualified", "bazel_qualified", "native_guest_qualified", "production_checkpoint_implemented"):
        assert result[key] is False
    assert all(value["outcome"] == value["conclusion"] == "success" for value in result["steps"].values())
    plan = json.loads(members["command-plan.json"])
    assert len(plan) == len(result["commands"]) == 12
    command_proof = []
    for name, planned in plan.items():
        receipt = json.loads(members[name + ".json"])
        assert receipt == result["commands"][name]
        assert receipt["name"] == name and receipt["source_sha"] == SOURCE
        assert receipt["argv"] == planned["argv"]
        assert receipt["status"] == "passed" and receipt["exit_code"] == 0
        check_source(receipt["source_before"])
        check_source(receipt["source_after"])
        for phase in ("before", "after"):
            resources = receipt["resources_" + phase]
            assert resources["build_jobs"] == resources["test_threads"] == 1 and resources["cargo_profile"] == "dev-small"
        for stream in ("stdout", "stderr"):
            stream_receipt = receipt[stream]
            actual = identity(members[stream_receipt["file"]])
            assert actual["bytes"] == stream_receipt["bytes"] and actual["sha256"] == stream_receipt["sha256"]
        command_proof.append({"name": name, "argv": receipt["argv"], "exit_code": 0,
                              "source_before_after_unchanged": True,
                              "stdout": receipt["stdout"], "stderr": receipt["stderr"]})
    assert plan["format"]["argv"] == plan["format-final"]["argv"] == ["just", "fmt", "--check", "--base", BASE]
    base_test = ["just", "test", "--locked", "--cargo-profile", "dev-small", "--build-jobs", "1", "--test-threads", "1", "--retries", "0"]
    test_proof, executed = {}, {}
    for label, package, expected_count, expected_skips in (
        ("memory", "codex-hepta-memory", 327, 8), ("agentd", "codex-hepta-agentd", 242, 1),
        ("desktop-ui", "codex-hepta-agentd", 247, 1),
    ):
        expected_argv = base_test + ["-p", package, "--lib"]
        if label == "desktop-ui":
            expected_argv += ["--features", "desktop-objective-ui"]
        expected_argv += ["--no-tests", "fail"]
        assert plan[label]["argv"] == expected_argv
        xml_bytes = members[label + ".junit.xml"]
        xml = ET.fromstring(xml_bytes)
        cases = xml.findall(".//testcase")
        names = [case.attrib["name"] for case in cases]
        assert len(cases) == len(set(names)) == int(xml.attrib["tests"]) == expected_count
        assert int(xml.attrib["failures"]) == int(xml.attrib["errors"]) == 0
        disallowed = {"failure", "error", "skipped", "flakyFailure", "flakyError", "rerunFailure", "rerunError"}
        assert not any(node.tag in disallowed for node in xml.iter())
        stderr = members[label + ".stderr"].decode()
        pass_names = re.findall(r"^\s*PASS\s+\[[^\]]+\]\s+" + re.escape(package) + r"\s+(\S+)\s*$", stderr, re.M)
        assert len(pass_names) == expected_count and sorted(pass_names) == sorted(names)
        starts = re.findall(r"Starting (\d+) tests across (\d+) binar(?:y|ies) \((\d+) tests? skipped\)", stderr)
        summary = re.findall(r"Summary \[\s*[0-9.]+s\] (\d+) tests run: (\d+) passed(?: \([^)]*\))?, (\d+) skipped", stderr)
        assert starts == [(str(expected_count), "1", str(expected_skips))]
        assert summary == [(str(expected_count), str(expected_count), str(expected_skips))]
        index = json.loads(members[label + "-test-index.json"])
        assert index == result["commands"][label]["tests"]
        assert index["bytes"] == len(xml_bytes) and index["sha256"] == identity(xml_bytes)["sha256"]
        assert index["junit_attributes"] == xml.attrib
        assert index["executed_test_names"] == sorted(names)
        assert index["required_test_names_missing"] == index["retry_nodes"] == []
        assert index["required_owning_tests_present_and_passed"] is True
        summaries = [line for line in stderr.splitlines() if "Summary" in line or "Starting" in line]
        assert summaries == index["nextest_summary_lines"]
        if label == "memory":
            required = {"production_writer::objective_sender::tests::" + name for name in REQUIRED_MEMORY}
            groups = {}
        else:
            required = REQUIRED_BOOTSTRAP | {"production_composition::objective_sender_tests::" + name for name in REQUIRED_BRIDGE}
            required |= {"production_composition::objective_control_tests::" + name for name in REQUIRED_CONTROL}
            if label == "desktop-ui":
                required |= {"production_composition::desktop_objective_ui_tests::" + name for name in REQUIRED_DESKTOP}
            groups = {prefix: sum(name.startswith(prefix) for name in names) for prefix in GROUPS}
            assert groups == GROUPS
        assert groups == index["required_groups"] and required <= set(names)
        executed[label] = set(names)
        test_proof[label] = {
            "junit": identity(xml_bytes), "uuid": xml.attrib["uuid"],
            "executed": expected_count, "passed": expected_count, "failed": 0, "errors": 0,
            "nextest_skipped": expected_skips, "junit_skipped_nodes": 0,
            "skipped_names_available_in_retained_originals": False,
            "retry_nodes": [], "raw_PASS_rows_equal_complete_JUnit_set": True,
            "required_tests_present_and_passed": sorted(required), "groups": groups,
            "nextest_summary_original_lines": summaries, "all_executed_cases": sorted(names),
        }
    desktop_extra = {"production_composition::desktop_objective_ui_tests::" + name for name in REQUIRED_DESKTOP}
    assert executed["desktop-ui"] - executed["agentd"] == desktop_extra
    assert not executed["agentd"] - executed["desktop-ui"]
    metadata = json.loads(members["metadata.stdout"])
    assert len(metadata["workspace_members"]) == 193
    report = {
        "schema": "objective-owner-main67-completed-native-originals-offline-verification-v1",
        "scope": "Original owner package libraries and scoped fix/fmt on the existing GitHub job; no new native execution",
        "run_id": RUN, "job_id": JOB, "run_attempt": 1,
        "job_status": job["status"], "job_conclusion": job["conclusion"],
        "job_started_at": job["started_at"], "job_completed_at": job["completed_at"],
        "artifact_id": ARTIFACT, "zip_identity": identity(zip_body),
        "official_artifact_digest_matches": True, "zip_members": sorted(member_proof, key=lambda item: item["path"]),
        "all_zip_member_crc_checks_passed": True, "artifact_inventory_members": 51,
        "complete_shared_console": {**CONSOLE_ID, "CR_count": 0},
        "source": {"head": SOURCE, "tree": TREE, "all_recorded_leaves": len(rows),
                   "all_tree_nodes_recomputed": tree_nodes, "source_files_sha256": source["files_sha256"],
                   "actual_commit_API_matches": True, "fixed_full_source_GETs": source_records,
                   "workflow_inline_runner_full_bytes_equal_artifact": True,
                   "before_after_command_guards": 24, "final_source_guard": True,
                   "unchanged_lockfiles": 17, "source_drift_patch_empty": True},
        "commands": command_proof, "tests": test_proof,
        "desktop_feature_additional_case_names": sorted(desktop_extra),
        "workspace_metadata_member_count": len(metadata["workspace_members"]),
        "qualified": {"original_owner_package_libraries_and_scoped_fix_fmt": True,
                      "full_workspace": False, "bazel": False, "native_guest": False,
                      "production_checkpoint": False, "private_build_jobs_4_resource_gate": False},
        "limits": ["816 case executions across three commands include the repeated Agentd cases; not 816 unique tests",
                   "8/1/1 nextest skipped occurrences remain; JUnit omits skipped identities",
                   "The generic-append negative and checked-append positive share the original writer fixture",
                   "No independent-pool/process-crash/Root54/production checkpoint acceptance is supplied",
                   "CARGO_BUILD_JOBS=1 and test_threads=1 do not qualify a required private full-jobs=4 run"],
        "product_code_executed_by_this_verifier": False,
    }
    output = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.write_text(output)
    print(output, end="")


if __name__ == "__main__":
    main()
