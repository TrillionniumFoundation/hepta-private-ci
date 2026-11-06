#!/usr/bin/env python3
"""Offline qualification of original source17 Supervisor P0 logs and official JUnit."""
import argparse
import collections
import hashlib
import io
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile

HEAD = "17c6b903a5d5d470b72035f95bb6e087291d7e04"
TREE = "25020dc30888fa3ffa6f6e8d1073d91edded1756"
PARENT = "840e8b5dbffca017753cdf87482ce325938f313c"
MERGE = "26cfdcaa70cbd2daecd165137e3b84d2ad1a7284"
BASE = "63652be658ebed8d3052eb789b951793384fd5e4"
RUN = 42201989809
WORKFLOW_PATH = ".github/workflows/hepta-supervisor-p0-crossplatform.yml"
WORKFLOW_BLOB = "fdeb340099f9f720a353aa8b69372e75a335387e"
COMMANDS = {
    "supervisor": "just test --locked -p codex-hepta-supervisor --test restart_budget --test restart_budget_recovery --test signed_intent_recovery --no-tests fail --retries 0 --status-level all --final-status-level all",
    "protocol": "just test --locked -p codex-hepta-agent-protocol --profile default --test-threads 2 --no-tests fail --retries 0 --status-level all --final-status-level all",
    "clippy": "cargo +1.95.0 clippy --locked -p codex-hepta-supervisor --all-targets -- -D warnings",
    "Linux_format": "cargo +1.95.0 fmt --all -- --check",
    "Windows_format": "cargo +1.95.0 fmt -p codex-hepta-supervisor -- --check",
}
SUPERVISOR = {
    ("codex-hepta-supervisor::restart_budget", "unexpected_agent_crashes_back_off_and_stop_after_three_restarts"),
    ("codex-hepta-supervisor::restart_budget_recovery", "restart_budget_survives_repeated_supervisord_recovery"),
    ("codex-hepta-supervisor::signed_intent_recovery", "unsigned_digest_abort_directive_cannot_clear_signed_production_recovery_fence"),
}
PROTOCOL = {("codex-hepta-agent-protocol", name) for name in [
    "capabilities::tests::negotiation_is_intersection_with_minor_downgrade",
    "capabilities::tests::duplicate_and_invalid_ids_are_rejected",
    "objective_tests::history::history_query_preserves_historical_body_and_current_outer_generation",
    "objective_tests::history::history_unknown_is_nested_and_cannot_decode_as_non_admission",
    "objective_tests::objective_start_outcomes_are_strict_wire_types",
    "objective_tests::signed_objective_control_request_round_trips_inside_frame_bound",
    "tests::automation_effect_wire_round_trip_is_strict_and_bounded",
    "tests::automation_wire_round_trip_is_strict_and_bounded",
    "tests::capabilities_endpoint_is_additive_and_bounded",
    "tests::cognitive_context_response_stays_v2_compatible_and_revalidation_is_additive",
    "tests::health_wire_round_trip_is_strict_and_bounded",
    "tests::host_turn_authority_binding_is_strict_and_fail_closed",
    "tests::memory_federation_control_is_typed_strict_and_bounded",
    "tests::run_lifecycle_wire_round_trip_is_strict_and_bounded",
]}
PAIRS = [
    (127839244015, "Linux", "ubuntu-24.04", 13496027607, 13496491391),
    (127839244401, "Windows", "windows-latest", 13495024668, 13495728233),
]


def identity(data):
    return {"bytes": len(data), "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(), "sha256": hashlib.sha256(data).hexdigest()}


def load(root, path):
    return json.loads((root / path).read_bytes())


def unpack(value):
    if "raw" in value:
        value = value["raw"]
    assert not value.get("isError", False)
    return json.loads(value["structuredContent"]["content"])


def merkle(tree):
    assert tree["truncated"] is False and tree["sha"] == TREE
    entries = {item["path"]: item for item in tree["tree"]}
    assert len(entries) == len(tree["tree"])
    children = collections.defaultdict(list)
    for path, entry in entries.items():
        parent, _, name = path.rpartition("/")
        children[parent].append((name, entry))
    def visit(path):
        out = []
        for name, entry in sorted(children[path], key=lambda item: (item[0] + ("/" if item[1]["type"] == "tree" else "")).encode()):
            if entry["type"] == "tree":
                sha = visit(entry["path"])
                assert sha == entry["sha"]
                mode = "40000"
            else:
                sha = entry["sha"]
                mode = entry["mode"]
            out.append(mode.encode() + b" " + name.encode() + b"\0" + bytes.fromhex(sha))
        data = b"".join(out)
        return hashlib.sha1(b"tree " + str(len(data)).encode() + b"\0" + data).hexdigest()
    assert visit("") == TREE
    leaves = {path: item for path, item in entries.items() if item["type"] != "tree"}
    assert len(leaves) == 10804
    return leaves


def command_section(console, command):
    start_marker = "##[group]Run " + command
    lines = console.splitlines()
    starts = [i for i, line in enumerate(lines) if line == start_marker]
    assert len(starts) == 1, (command, starts)
    start = starts[0]
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("##[group]")), len(lines))
    return "\n".join(lines[start:end])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    root = parser.parse_args().root
    freeze = load(root, "ORIGINALS-FREEZE.json")
    assert len(freeze["files"]) == len({item["path"] for item in freeze["files"]}) == 23
    for item in freeze["files"]:
        assert identity((root / item["path"]).read_bytes()) == {k: item[k] for k in ("bytes", "git_blob", "sha256")}, item["path"]
    leaves = merkle(load(root, "authority/full-tree-25020.json"))
    commit = unpack(load(root, "authority/commit.actual.original.json"))
    merge = unpack(load(root, "authority/merge.actual.original.json"))
    ref = unpack(load(root, "authority/ref.after.original.json"))
    pr = unpack(load(root, "authority/pr.after.original.json"))
    assert commit["sha"] == HEAD and commit["tree"]["sha"] == TREE
    assert [p["sha"] for p in commit["parents"]] == [PARENT]
    assert merge["sha"] == MERGE and merge["tree"]["sha"] == TREE
    assert [p["sha"] for p in merge["parents"]] == [BASE, HEAD]
    assert ref["object"]["sha"] == pr["head"]["sha"] == HEAD
    assert pr["number"] == 4936 and pr["merge_commit_sha"] == MERGE and pr["base"]["sha"] == BASE
    publication = load(root, "authority/publication-verified.json")
    assert publication["head"] == HEAD and publication["tree"] == TREE and publication["merge_commit"] == MERGE
    workflow_bytes = (root / "source" / WORKFLOW_PATH).read_bytes()
    workflow_raw = load(root, "authority/workflow-full-GET.original.json")
    assert workflow_raw["structuredContent"]["content"].encode() == workflow_bytes
    assert identity(workflow_bytes)["git_blob"] == leaves[WORKFLOW_PATH]["sha"] == WORKFLOW_BLOB
    workflow = workflow_bytes.decode()
    for command in COMMANDS.values():
        assert "run: " + command in workflow
    for required in ["timeout-minutes: 45", 'CARGO_BUILD_JOBS: "2"', "persist-credentials: false", "test \"$(git rev-parse HEAD)\" = \"$EXPECTED_SOURCE_SHA\"", "git diff --exit-code", "git status --porcelain --untracked-files=no"]:
        assert required in workflow

    # Retain the prior complete head-list solely for this run's ordinary PR trigger.
    # Its old status/18-run denominator is not combined with this terminal cut.
    earlier_runs = unpack(load(root, "authority/earlier-runs-full.original.json"))
    run_matches = [run for run in earlier_runs["workflow_runs"] if run["id"] == RUN]
    assert len(run_matches) == 1
    run = run_matches[0]
    assert run["head_sha"] == HEAD and run["event"] == "pull_request" and run["run_attempt"] == 1
    jobs_original = load(root, f"jobs-{RUN}.original.json")
    artifacts_original = load(root, f"artifacts-{RUN}.original.json")
    jobs = unpack(jobs_original)
    artifacts = unpack(artifacts_original)
    assert jobs["total_count"] == len(jobs["jobs"]) == 2
    assert artifacts["total_count"] == len(artifacts["artifacts"]) == 4
    job_map = {j["id"]: j for j in jobs["jobs"]}
    artifact_map = {a["id"]: a for a in artifacts["artifacts"]}
    assert set(job_map) == {pair[0] for pair in PAIRS}
    assert set(artifact_map) == {aid for pair in PAIRS for aid in pair[3:]}
    results = []
    for jid, platform, runner, supervisor_aid, protocol_aid in PAIRS:
        job = job_map[jid]
        assert job["run_id"] == RUN and job["head_sha"] == HEAD and job["run_attempt"] == 1
        assert job["status"] == "completed" and job["conclusion"] == "success" and job["labels"] == [runner]
        steps = {step["name"]: step for step in job["steps"]}
        assert len(steps) == len(job["steps"]) == 19
        format_step = "Verify full-workspace canonical Rust format on Linux" if platform == "Linux" else "Verify Supervisor canonical Rust format on Windows"
        skipped_step = "Verify Supervisor canonical Rust format on Windows" if platform == "Linux" else "Verify full-workspace canonical Rust format on Linux"
        for name, step in steps.items():
            assert step["status"] == "completed" and step["conclusion"] == ("skipped" if name == skipped_step else "success"), name
        raw_log = (root / f"job-{jid}.original.log").read_bytes()
        raw_response = load(root, f"job-{jid}-tool-return.original.json")
        assert not raw_response.get("isError", False)
        assert raw_response["structuredContent"]["content"].encode() == raw_log
        original_lines = raw_log.decode().splitlines()
        clean_lines = [re.sub(r"\x1b\[[0-9;]*m", "", re.sub(r"^\d{4}-\d\d-\d\dT\S+Z ", "", line)) for line in original_lines]
        console = "\n".join(clean_lines)
        marker = f"source={HEAD} tree={TREE} parents={PARENT}"
        assert clean_lines.count(marker) == 1
        source_line = clean_lines.index(marker) + 1
        pass_lines = re.findall(r"^\s*PASS\s+\[[^\]]+\]\s+(\S+)\s+(\S+)\s*$", console, re.M)
        assert collections.Counter(pass_lines) == collections.Counter({case: 2 for case in SUPERVISOR | PROTOCOL})
        summaries = re.findall(r"^\s*Summary\s+\[[^\]]+\]\s+(\d+) tests run: (\d+) passed, (\d+) skipped\s*$", console, re.M)
        assert summaries == [("3", "3", "0"), ("14", "14", "0")]
        for kind, expected in [("supervisor", SUPERVISOR), ("protocol", PROTOCOL)]:
            section = command_section(console, COMMANDS[kind])
            selected = re.findall(r"^\s*PASS\s+\[[^\]]+\]\s+(\S+)\s+(\S+)\s*$", section, re.M)
            assert collections.Counter(selected) == collections.Counter({case: 2 for case in expected})
            assert not re.search(r"^\s*(FAIL|TIMEOUT|SKIP)\s+\[", section, re.M)
        clippy = command_section(console, COMMANDS["clippy"])
        assert re.search(r"^\s*Finished `dev` profile .* target\(s\) in ", clippy, re.M)
        assert "##[error]" not in clippy and steps["Strict Supervisor Clippy"]["conclusion"] == "success"
        formatter = command_section(console, COMMANDS[platform + "_format"])
        assert "Diff in " not in formatter and "##[error]" not in formatter and steps[format_step]["conclusion"] == "success"
        native_receipts = [json.loads(line) for line in clean_lines if line.startswith('{"passed":')]
        assert len(native_receipts) == 2
        assert [(r["passed"], r["platform"], r["source_sha"]) for r in native_receipts] == [(3, platform, HEAD), (14, platform, HEAD)]
        assert set(native_receipts[0]["required_tests"]) == {name for _, name in SUPERVISOR}
        assert native_receipts[1]["required_test"] == "tests::automation_effect_wire_round_trip_is_strict_and_bounded"
        qualified = []
        for aid, kind, expected in [(supervisor_aid, "supervisor", SUPERVISOR), (protocol_aid, "protocol", PROTOCOL)]:
            api = artifact_map[aid]
            assert api["workflow_run"]["id"] == RUN and api["workflow_run"]["head_sha"] == HEAD
            prefix = "hepta-supervisor-p0" if kind == "supervisor" else "hepta-agent-protocol"
            assert api["name"] == f"{prefix}-{runner}-{HEAD}" and api["expired"] is False
            assert f"/actions/runs/{RUN}/artifacts/{aid}" in console
            archive = (root / f"artifacts/artifact-{aid}.original.zip").read_bytes()
            assert len(archive) == api["size_in_bytes"] and "sha256:" + hashlib.sha256(archive).hexdigest() == api["digest"]
            with zipfile.ZipFile(io.BytesIO(archive)) as zf:
                assert zf.namelist() == ["junit.xml"] and zf.testzip() is None
                xml = zf.read("junit.xml")
            assert xml == (root / f"artifacts/{aid}/junit.xml").read_bytes()
            report = ET.fromstring(xml)
            cases = report.findall(".//testcase")
            observed = [(case.attrib["classname"], case.attrib["name"]) for case in cases]
            assert len(observed) == len(set(observed)) == len(expected) and set(observed) == expected
            assert int(report.attrib["tests"]) == len(expected)
            assert int(report.attrib["failures"]) == int(report.attrib["errors"]) == 0
            assert not any(report.findall(".//" + tag) for tag in ("failure", "error", "skipped"))
            assert sum(int(s.attrib["tests"]) for s in report.findall("testsuite")) == len(expected)
            qualified.append({"scope": kind, "artifact_id": aid, "name": api["name"], "zip": identity(archive), "official_digest_equal": True, "CRC_all_members_valid": True, "XML": identity(xml), "passed": len(expected), "failed": 0, "errors": 0, "skipped": 0, "cases": [{"classname": cls, "name": name} for cls, name in sorted(expected)]})
        results.append({"job_id": jid, "runner": runner, "platform": platform, "status": job["status"], "conclusion": job["conclusion"], "started_at": job["started_at"], "completed_at": job["completed_at"], "run_attempt": 1, "actual_checkout": HEAD, "actual_tree": TREE, "actual_parents": [PARENT], "actual_source_line": source_line, "full_log": identity(raw_log), "full_log_CR_count": raw_log.count(b"\r"), "full_MCP_decoded_bytes_equal": True, "raw_PASS_occurrences": 34, "unique_raw_cases": 17, "raw_duplicate_reason": "original --status-level all plus --final-status-level all", "raw_summaries": summaries, "native_source_receipts": native_receipts, "strict_clippy": {"command": COMMANDS["clippy"], "status": "success", "Finished_dev_in_actual_command_section": True, "all_targets_is_not_test_execution": True}, "formatter": {"command": COMMANDS[platform + "_format"], "status": "success", "actual_diff_blocks": 0, "scope": "full_workspace" if platform == "Linux" else "Supervisor_package"}, "checkout_immutable_step": steps["Ensure test checkout remained immutable"]["conclusion"], "qualified_JUnit": qualified, "steps": [{"name": s["name"], "status": s["status"], "conclusion": s["conclusion"]} for s in job["steps"]]})
    print(json.dumps({"schema": "hepta-source17-supervisor-P0-native-qualification-v1", "repository": "TrillionniumFoundation/hepta-private-ci", "current_product_head": HEAD, "current_product_tree": TREE, "source_parent": PARENT, "actual_PR_merge": MERGE, "target_base": BASE, "actual_jobs_checkout_HEAD_not_merge": True, "publication_ref_PR_commit_merge_binding_equal": True, "full_tree_Merkle": TREE, "complete_product_leaves": len(leaves), "workflow_path": WORKFLOW_PATH, "workflow_blob": WORKFLOW_BLOB, "workflow_original_timeout_minutes": 45, "workflow_original_CARGO_BUILD_JOBS": 2, "workflow_original_commands": COMMANDS, "workflow_run_id": RUN, "event": run["event"], "complete_jobs": 2, "complete_artifacts": 4, "jobs_API_observed_before_utc": jobs_original["capture_completed_before_utc"], "artifact_API_observed_before_utc": artifacts_original["capture_completed_before_utc"], "prior_head_run_list_used_only_for_event_binding": True, "original_frozen_files_verified": len(freeze["files"]), "jobs": results, "scope": {"native_formatter_qualification_for_current_17": True, "selected_supervisor_integration_cases_per_platform": 3, "complete_agent_protocol_cases_per_platform": 14, "new_six_Unix_unit_tests": "NOT_SELECTED", "original_paired_process_product": "NOT_SELECTED", "Clippy_all_targets_is_not_test_execution": True, "build_or_test_uncached_qualification": False, "old_840_formatter_failures_preserved_in_previous_packet": True, "results_transferred_from_old_head": False, "all_required_original_CI_passed": False, "whole_candidate_qualified": False, "newly_closed_blockers": []}, "operations": {"manual_CI": [], "private_capacity_query": False, "Rust_Cargo_Bazel_or_native_execution_during_offline_replay": False, "source_or_ref_mutations": []}}, indent=2) + "")


if __name__ == "__main__":
    main()
