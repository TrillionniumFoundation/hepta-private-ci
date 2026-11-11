#!/usr/bin/env python3
"""Audit the completed d0f Architecture original run, without executing recorded commands."""
from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import shlex

import audit_completed_records as common
import audit_command_receipts as command_reader
from audit_arch_candidate_preflight import audit_raw
from tree_identity import listing, tree_hash

HERE = Path(__file__).resolve().parent
RUN = 43062473103
BASE_JOB, SOURCE_JOB, REQUIRED_JOB = 130668436789, 130668437162, 130692482183
NATIVE_EXPECTED = {
    "browser.json": 3, "eval.json": 17, "final-use.json": 1, "full-lifecycle.json": 1,
    "inference-scale.json": 1, "inference.json": 94, "ledger.json": 122, "migration-rollback.json": 1,
    "migration.json": 1, "objective.json": 66, "operation-timer-fence.json": 3, "operations.json": 53,
    "optional-process-restart.json": 1, "prompt.json": 32, "retirement.json": 4,
    "runtime-module-abi.json": 15, "runtime-module-catalog.json": 7, "runtime-module-supervisor.json": 17,
    "runtime-tasks.json": 11, "selected-ranker.json": 1, "selector-role.json": 1,
    "self-evolution-selection.json": 7, "stateless-lifecycle.json": 1, "topology-contract.json": 3,
    "topology-proposal.json": 52, "writer-handoff-generations.json": 11,
}


def api(name):
    return json.loads(common.load(HERE / name)["structuredContent"]["content"])


def cleaned_job(job_id):
    raw = (HERE / "original" / f"job-{job_id}.log").read_bytes()
    text = command_reader.ANSI.sub("", re.sub(r"^\d{4}-\d{2}-\d{2}T\S+Z ", "", raw.decode(), flags=re.M))
    return raw, text


def canonical_binary(command, binary):
    packages = [command[i + 1] for i, value in enumerate(command[:-1]) if value == "-p"]
    assert packages and binary is not None
    matched = [name for name in packages if binary in (name, name.replace("-", "_"))]
    if matched:
        assert len(matched) == 1
        return matched[0] + "::lib"
    assert len(packages) == 1
    return packages[0] + "::integration:" + binary


def main():
    run = api("RUN_43062473103_TERMINAL.json")
    jobs = api("ARCH_JOBS_TERMINAL.json")["jobs"]
    assert run["id"] == RUN and run["head_sha"] == common.HEAD and run["run_attempt"] == 1
    assert run["status"] == "completed" and run["conclusion"] == "success"
    assert {j["id"] for j in jobs} == {BASE_JOB, SOURCE_JOB, REQUIRED_JOB}
    assert all(j["status"] == "completed" and j["conclusion"] == "success" for j in jobs)
    by_job = {j["id"]: j for j in jobs}
    for job_id in (BASE_JOB, SOURCE_JOB):
        assert any(s["name"] == "Verify unchanged reviewed source" and s["conclusion"] == "success" for s in by_job[job_id]["steps"])
        elapsed = datetime.fromisoformat(by_job[job_id]["completed_at"].replace("Z", "+00:00")) - datetime.fromisoformat(by_job[job_id]["started_at"].replace("Z", "+00:00"))
        assert elapsed.total_seconds() < 60 * 60
    artifacts = [common.verify_artifact(a) for a in (13873952864, 13877116867)]
    base = command_reader.receipts(13873952864, RUN, "base-merge", common.MERGE)
    source = command_reader.receipts(13877116867, RUN, "source-head", common.HEAD)
    assert len(base) == 4 and len(source) == 31
    assert all(r["status"] == "passed" and r["source_before_after_equal_clean"] for r in base + source)
    tree_raw = (HERE / "references/CANDIDATE_TREE.ls-tree").read_bytes()
    tree = listing(tree_raw)
    assert len(tree) == 14053 and tree_hash(tree) == common.TREE
    workflow_path = ".github/workflows/hepta-architecture-convergence.yml"
    workflow_raw = (HERE / "source" / workflow_path).read_bytes()
    assert tree[workflow_path]["git_blob"] == common.identity(workflow_raw)["git_blob"]
    workflow_commands = {}
    for line in workflow_raw.decode().splitlines():
        if "python3 scripts/hepta_ci_exec.py --output " not in line:
            continue
        parts = shlex.split(line.strip())
        boundary = parts.index("--")
        output_name = Path(parts[parts.index("--output") + 1]).name
        assert output_name not in workflow_commands
        workflow_commands[output_name] = parts[boundary + 1:]
    assert set(workflow_commands) == {r["receipt"] for r in source}
    assert all(workflow_commands[r["receipt"]] == r["command"] for r in source + base)
    lanes = []
    raw_jobs = {}
    all_python, native_passes = [], []
    for label, rows, job_id, tested, artifact_id in (
        ("base-merge", base, BASE_JOB, common.MERGE, 13873952864),
        ("source-head", source, SOURCE_JOB, common.HEAD, 13877116867),
    ):
        raw, text = cleaned_job(job_id)
        raw_jobs[str(job_id)] = common.identity(raw)
        python_rows = [r for r in rows if r["test_evidence"]["kind"] == "python-unittest"]
        receipt_ids = [c["case"] for r in python_rows for c in r["test_evidence"]["case_terminals"]]
        assert len(receipt_ids) == len(set(receipt_ids))
        expected_count = 136 if label == "base-merge" else 138
        assert len(receipt_ids) == expected_count
        preflight = audit_raw(HERE / "original" / f"job-{job_id}.log", common.HEAD, common.TREE, tested, label, job_id, set(receipt_ids))
        preflight["raw_file"] = f"original/job-{job_id}.log"
        raw_ids = re.findall(r"^test\S+ \(([^)]+)\)(?: \.\.\..*)?$", text, re.M)
        expected_ids = receipt_ids + preflight["raw_only_case_ids"]
        assert sorted(raw_ids) == sorted(expected_ids)
        summaries = [int(n) for n in re.findall(r"^Ran (\d+) tests? in [^\n]+$", text, re.M)]
        assert summaries == ([8, 18, 45, 73] if label == "base-merge" else [8, 18, 45, 73, 2])
        assert len(re.findall(r"^OK$", text, re.M)) == len(summaries)
        candidate = common.load(HERE / "artifacts" / str(artifact_id) / "files/candidate-tree.json")
        assert candidate["source_sha"] == common.HEAD and candidate["tested_sha"] == tested
        assert candidate["source_tree"] == candidate["tested_tree"] == common.TREE
        assert candidate["native_execution_required"] is (label == "source-head")
        assert candidate["requires_source_head_success"] is (label == "base-merge")
        transport = common.load(HERE / "artifacts" / str(artifact_id) / "files/candidate-transport.json")
        assert transport["advisory"] is True
        assert transport["activation_authorized"] is False
        assert transport["observation_status"] == "unknown"
        assert transport["write_transport_denied"] is None
        lane = {"lane": label, "tested_sha": tested, "tree": common.TREE,
                "command_receipts": len(rows), "python_receipted_pass": expected_count,
                "raw_only_candidate_preflight_pass": 8, "all_python_executions": len(expected_ids),
                "all_python_distinct_case_names": len(set(expected_ids)),
                "candidate": candidate, "candidate_transport_advisory": transport,
                "raw_preflight": preflight, "qualification_receipts": rows}
        lanes.append(lane)
        all_python.extend(expected_ids)
    native_rows = [r for r in source if r["test_evidence"]["kind"] in ("cargo-libtest", "nextest")]
    assert {r["receipt"]: r["test_evidence"]["passed"] for r in native_rows} == NATIVE_EXPECTED
    source_raw, source_text = cleaned_job(SOURCE_JOB)
    for row in native_rows:
        evidence = row["test_evidence"]
        assert evidence["failed"] == 0 and evidence["named_terminal_count_complete"] and evidence["terminal_ids_unique"]
        if evidence["kind"] == "nextest":
            assert evidence["selected_counts"] == [evidence["passed"]]
        cases = []
        for case in evidence["case_terminals"]:
            assert case["status"] in ("PASS", "SKIP")
            if case["status"] == "PASS":
                assert case["case"] in source_text
                key = (canonical_binary(row["command"], case["binary_id"]), case["case"])
                native_passes.append(key)
                cases.append({"canonical_binary": key[0], "case": key[1]})
        row["canonical_pass_ids"] = cases
    counts = Counter(native_passes)
    assert len(native_rows) == 26 and len(native_passes) == 526 and len(counts) == 521
    duplicates = [{"binary": key[0], "case": key[1], "executions": value} for key, value in sorted(counts.items()) if value > 1]
    assert len(duplicates) == 5 and all(row["executions"] == 2 for row in duplicates)
    source_files = HERE / "artifacts/13877116867/files"
    for row in native_rows:
        raw = (source_files / row["log_file"]).read_bytes()
        clean = command_reader.ANSI.sub("", raw.decode())
        assert not re.search(r"^\s*(?:TRY\s+[2-9]|RETRY|FAIL|TIMEOUT|EXECFAIL|LEAK)\b", clean, re.M)
    by_receipt = {row["receipt"]: row for row in source}
    assert "--ignored" in by_receipt["inference-scale.json"]["command"]
    assert by_receipt["inference-scale.json"]["test_evidence"]["passed"] == 1
    required_raw, required_text = cleaned_job(REQUIRED_JOB)
    raw_jobs[str(REQUIRED_JOB)] = common.identity(required_raw)
    assert 'Run test "$RESULT" = success' in required_text and "  RESULT: success" in required_text
    assert "All applicable exact-candidate lanes succeeded; identical-tree reuse includes source-head success." in required_text
    assert len(all_python) == 290 and len(set(all_python)) == 146
    result = {"schema": "mem8.d0f.Architecture.complete-original.v1", "status": "PASS_ORIGINAL_ARCHITECTURE_WORKFLOW",
              "run_id": RUN, "attempt": 1, "source_head": common.HEAD, "source_tree": common.TREE,
              "API_terminal": {"status": run["status"], "conclusion": run["conclusion"], "updated_at": run["updated_at"]},
              "original_jobs": [{"job_id": j["id"], "name": j["name"], "started_at": j["started_at"],
                                "completed_at": j["completed_at"], "conclusion": j["conclusion"]} for j in jobs],
              "artifacts": artifacts, "fulljobs": raw_jobs, "workflow": {"path": workflow_path, **common.identity(workflow_raw)},
              "all_31_command_arrays_match_exact_workflow": True, "lanes": lanes,
              "python_totals": {"executions": 290, "distinct_case_names": 146,
                                "base": {"receipted": 136, "raw_only": 8, "total": 144},
                                "source": {"receipted": 138, "raw_only": 8, "total": 146}},
              "native_totals": {"executions": 526, "distinct_package_target_case_ids": 521, "failed": 0,
                                "command_groups": 26, "cross_group_duplicate_ids": duplicates,
                                "one_explicit_ignored_scale_case_executed": True,
                                "base_native_execution": 0, "base_identical_tree_reuse_condition_source_head_success_met": True,
                                "binary_normalization": "Cargo crate underscores and nextest package names map to package::lib; integration targets retain their own target name."},
              "combined_test_executions": 816,
              "language_qualified_distinct_case_ids": 667,
              "all_receipts_known_exit_zero_and_source_before_after_clean": True,
              "derived_check": "passed with zero test count",
              "Architecture_required": "passed original aggregate after both applicable lanes",
              "candidate_transport_boundary": "Both observations remain advisory UNKNOWN/HTTP403; no activation, admin denial, credential separation or write-denial proof is inferred.",
              "historical_results_transferred": False, "new_scored_memory_actor_episodes": 0,
              "boundary": "Software architecture/runtime fixture scope. This is not all repository CI, original owner recovery, source-benefit evidence, or a real-provider smoke.",
              "archived_commands_executed_by_reader": 0}
    (HERE / "ARCH_COMPLETE_ORIGINAL_AUDIT.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: result[k] for k in ("status", "python_totals", "native_totals", "combined_test_executions", "language_qualified_distinct_case_ids")}, indent=2))


if __name__ == "__main__":
    main()
