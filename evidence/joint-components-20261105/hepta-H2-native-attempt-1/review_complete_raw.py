#!/usr/bin/env python3
"""Check actual H2 raw outcomes and descriptor records, without executing tests."""
from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sys

SOURCE = "620cb63ae9b58904483005bcb2c4e1507df99539"
TREE = "f2cebe6d99deca596c170922b8e60d66648d7393"
RUNNER = "903c622365c9cf863f1ae4b5eca2d4a0501c9f86862538c48f94f126a82ba62b"
ENVIRONMENT = "42a7e79bf271684caccb12c864449b57bf72755a10a367b67d985f277e91a5c2"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read_json(path):
    return json.loads(path.read_bytes())


def main():
    base, output = map(Path, sys.argv[1:])
    delivery_raw = (base / "h2-native-attempt1-delivery.json").read_bytes()
    assert sha(delivery_raw) == "886577e8de8d59ab85e5f86b7c63a59b3a5ec82d806329d90267f314e2671f97"
    delivery = json.loads(delivery_raw)
    assert delivery["source_commit"] == SOURCE and delivery["source_tree"] == TREE
    assert delivery["authoritative_terminal"] == "FAILED" and delivery["exit_code"] == 1
    for entry in delivery["files"]:
        raw = (base / entry["path"]).read_bytes()
        assert len(raw) == entry["bytes"] and sha(raw) == entry["sha256"]
    assert len(delivery["files"]) == delivery["file_count"] == 96
    assert sum(x["bytes"] for x in delivery["files"]) == delivery["total_bytes"] == 2320504
    run = base / "joint-h2-native-attempt-1"
    pipeline = read_json(run / "pipeline-status.final.json")
    plan = read_json(base / "h2-native-plan.json")
    steps = {row["name"]: row for row in plan["steps"]}
    assert plan["selected_total"] == 71 and plan["original_job_timeout_seconds"] == 5400
    assert pipeline["source_before"] == pipeline["source_after"]
    assert pipeline["source_before"]["tracked_count"] == 11839
    assert pipeline["source_before"]["tracked_bytes"] == 183391637
    config = read_json(run / "configuration-after.json")
    assert config["before"] == config["after"] == pipeline["configuration_before"]
    assert len(config["before"]) == 4 and config["unchanged"]
    assert sha((run / "native-environment.json").read_bytes()) == ENVIRONMENT
    runtime_before = read_json(run / "runtime-inputs-before.json")
    runtime_after = read_json(run / "runtime-inputs-after.json")
    assert runtime_before["external_configuration_sha256"] == runtime_after["external_configuration_sha256"]
    assert len(runtime_after["external_configuration_sha256"]) == 9
    for name, expected in runtime_after["external_configuration_sha256"].items():
        assert sha((base / name).read_bytes()) == expected
    bytecode = runtime_after["bytecode"]
    assert len(bytecode) == 1 and bytecode[0]["bytes"] == 6094
    assert bytecode[0]["mtime_ns"] == bytecode[0]["ctime_ns"] == 1793910320715604066
    assert sha((run / "observed-bytecode-after" / (bytecode[0]["sha256"] + ".pyc")).read_bytes()) == bytecode[0]["sha256"]
    outcomes, gate_results, identities = [], [], set()
    for entry in delivery["gates"]:
        name = entry["gate"]
        raw = (base / entry["raw"]).read_bytes()
        receipt_raw = (base / entry["receipt"]).read_bytes()
        receipt = json.loads(receipt_raw)
        gate = pipeline["gates"][name]
        assert sha(receipt_raw) == gate["receipt_sha256"]
        assert sha(raw) == receipt["log_sha256"] == entry["raw_sha256"]
        assert len(raw) == receipt["log_bytes"] == entry["raw_bytes"]
        assert receipt["before"] == receipt["after"]
        assert receipt["before"]["commit"] == SOURCE and receipt["before"]["tree"] == TREE
        assert not receipt["before"]["dirty"] and not receipt["timed_out"]
        text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", raw.decode())
        if name in ("dependencies", "execution-source-controls", "diverse-source-controls"):
            assert receipt["command_exit_code"] == 0 and receipt["status"] == "passed"
            if name != "dependencies":
                expected = 135 if name == "execution-source-controls" else 32
                assert re.search(r"Ran " + str(expected) + r" tests? in ", text)
                assert receipt["observed_passed_tests"] == expected
            continue
        step = steps[name]
        assert receipt["command"] == step["command"]
        assert receipt["elapsed_seconds"] <= step["timeout_seconds"]
        cases = re.findall(r"^test (\S+) \.\.\. (ok|FAILED|ignored)\s*$", text, re.M)
        evidence = read_json(run / (name + ".fd-executed-binaries.json"))
        assert evidence == gate["actual_binary_evidence"]
        records = evidence["records"]
        assert evidence["runner_sha256"] == RUNNER
        assert len(records) == len(step["expected_names"])
        assert Counter(r["exact_test"] for r in records) == Counter(step["expected_names"])
        for record in records:
            assert record["phase"] == "run" and record["status"] == "pre_exec_fd_bound"
            assert record["source"]["commit"] == SOURCE and record["source"]["tree"] == TREE
            assert record["source"]["environment_sha256"] == ENVIRONMENT
            assert record["capture_config_sha256"] == evidence["config_sha256"]
            assert record["runner_sha256"] == RUNNER and record["gate"] == name
            assert record["coordinator"] == {"pid": 823760, "start_ticks": "98793384"}
            assert record["coordinator_descendant_verified"] and record["pre_exec_fd_identity_verified"]
            assert record["observed_selected_tests"] == [record["exact_test"]]
            assert record["argv"][0] == record["actual_executable"]
            assert record["argv"][record["argv"].index("--exact") + 1] == record["exact_test"]
            identity = (record["pid"], record["start_ticks"])
            assert identity not in identities
            identities.add(identity)
            assert datetime.fromisoformat(receipt["started_at"]).timestamp() <= record["captured_unix"] <= datetime.fromisoformat(receipt["finished_at"]).timestamp()
        if name == "effect-pq-product":
            assert not cases and not evidence["per_case_bijection_verified"]
            assert evidence["errors"] and receipt["command_exit_code"] == 100
            assert "TIMEOUT [  60.007s]" in text
            assert "1 test run: 0 passed, 1 timed out, 0 skipped" in text
            result = "TIMEOUT; no completed outcome; pre-exec capture gives no pass"
        else:
            assert Counter(cases) == Counter((n, "ok") for n in step["expected_names"])
            assert [list(x) for x in cases] == evidence["actual_cases"] == gate["observed_cases"]
            assert evidence["per_case_bijection_verified"] and not evidence["errors"]
            assert receipt["command_exit_code"] == 0 and receipt["status"] == "passed"
            outcomes.extend({"gate": name, "name": case, "result": result} for case, result in cases)
            result = "PASS; exact raw outcome / descriptor-record bijection"
        gate_results.append({"gate": name, "result": result, "raw_sha256": sha(raw),
                             "raw_bytes": len(raw), "descriptor_records": len(records),
                             "config_sha256": evidence["config_sha256"]})
    assert outcomes == delivery["exact_passed_selection"] and len(outcomes) == 70
    assert len(identities) == 71 and len(gate_results) == 10
    review = {"schema": "root-H2-complete-raw-review-v1", "source_commit": SOURCE,
              "source_tree": TREE, "delivery_sha256": sha(delivery_raw),
              "all_96_original_file_hashes_match": True, "original_gates_with_raw": 13,
              "selected_completed_passes": 70, "selected_timeouts": 1,
              "actual_preexec_process_identities": len(identities), "gate_reviews": gate_results,
              "all_exact_passed_selection": outcomes, "tracked_source_and_4_git_configs_unchanged": True,
              "9_external_execution_configs_actual_bytes_match": True,
              "per_gate_fd_capture_config_bytes": "Dispatcher retained; nine remaining original files requested separately. Record/config digests are checked here, not substituted for those missing original bytes.",
              "actual_bytecode_bytes_retained": 6094,
              "runtime_input_limit": "Post-run bytecode observation and ignored-path inventory are not an import trace or full interpreter/runtime closure.",
              "not_executed": delivery["not_executed"], "native_result": "FAILED",
              "actual_ELF_archive": "Separate retained-byte export; this review does not rebuild or substitute binaries.",
              "all_joint_gates": "HOLD"}
    output.write_text(json.dumps(review, indent=2) + "\n")
    print(json.dumps({"output": str(output), "sha256": sha(output.read_bytes()),
                      "verified_files": 96, "selected_passes": 70, "timeouts": 1}))


if __name__ == "__main__":
    main()
