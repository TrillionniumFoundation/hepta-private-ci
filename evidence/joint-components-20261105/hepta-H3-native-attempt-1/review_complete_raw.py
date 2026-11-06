#!/usr/bin/env python3
"""Read original H3 outcomes and execution records; never execute native tests."""
from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

SOURCE = "6db78eca53a5acdda0d96873d3f4cd65863426f0"
TREE = "e91f5994017fc5d2cfe58d405a20ee6ad9376772"
ENVIRONMENT = "3ca2ffadd3c6439f1401f04929b5ee4e8747a813de6d2647f139f8efb3b311f6"
RUNNER = "9679cc6e11762c29b4c0ee92dd7715d3fce0555a6f8e0e10ed9d0b007951381a"
DELIVERY = "101c8f7a356cfe702565502eeeb3417e047492f19ee7599492f8f08292e7e1d5"
COORDINATOR = {"pid": 989453, "start_ticks": "99250221"}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    return json.loads(path.read_bytes())


def main():
    native, output = map(Path, sys.argv[1:])
    run = native / "joint-h3-native-attempt-1"
    manifest_raw = (native / "h3-native-attempt1-delivery.json").read_bytes()
    assert digest(manifest_raw) == DELIVERY
    manifest = json.loads(manifest_raw)
    assert manifest["source_commit"] == SOURCE and manifest["source_tree"] == TREE
    terminal = manifest["authoritative_status"]
    assert terminal["job_id"] == "1a1ada80dcc-fc05-5a8b"
    assert terminal["state"] == "failed" and terminal["exit_code"] == 1
    assert terminal["at_unix_ms"] == 1793916036769 and not terminal["timed_out"]
    assert terminal["output_complete"] and terminal["output_durable"]
    assert not terminal["automatic_retry"] and not terminal["cancelled"]
    assert len(manifest["files"]) == manifest["file_count"] == 107
    assert sum(f["bytes"] for f in manifest["files"]) == manifest["total_bytes"] == 2100909
    for entry in manifest["files"]:
        relative = Path(entry["relative_path"])
        assert not relative.is_absolute() and ".." not in relative.parts
        assert Path(entry["path"]).resolve() == (run / relative).resolve()
        raw = (run / relative).read_bytes()
        assert len(raw) == entry["bytes"] and digest(raw) == entry["sha256"], str(relative)

    pipeline = read(run / "pipeline-status.json")
    assert pipeline["error"] == "AssertionError('final-use-profile-controls lacks an exact per-case test-image binding')"
    before = read(run / "full-source-before.json")
    assert before == read(run / "full-source-after.json") == pipeline["source_before"] == pipeline["source_after"]
    assert before["identity"]["commit"] == SOURCE and before["identity"]["tree"] == TREE
    assert not before["identity"]["dirty"] and before["raw_git_blob_bytes_match"]
    assert before["tracked_count"] == before["index_count"] == 11840
    assert before["tracked_bytes"] == 183410043 and not before["missing"] and not before["hidden"]
    configuration = read(run / "configuration-after.json")
    assert configuration["before"] == configuration["after"] == pipeline["configuration_before"]
    assert len(configuration["before"]) == 5 and configuration["unchanged"] and pipeline["configuration_unchanged"]
    assert digest((run / "native-environment.json").read_bytes()) == ENVIRONMENT
    runtime_before, runtime_after = (read(run / n) for n in ("runtime-inputs-before.json", "runtime-inputs-after.json"))
    external = runtime_after["external_configuration_sha256"]
    assert external == runtime_before["external_configuration_sha256"] and len(external) == 10
    for name, sha in external.items():
        assert digest((native / name).read_bytes()) == sha, name
    bytecode = runtime_after["bytecode"]
    assert len(bytecode) == 1 and bytecode[0]["bytes"] == 6094
    assert bytecode[0]["mtime_ns"] == bytecode[0]["ctime_ns"] == 1793914887932050494
    assert digest((run / "observed-bytecode-after" / (bytecode[0]["sha256"] + ".pyc")).read_bytes()) == bytecode[0]["sha256"]
    plan = read(native / "h3-native-plan.json")
    assert plan["selected_total"] == 74 and plan["original_job_timeout_seconds"] == 5400
    steps = {x["name"]: x for x in plan["steps"]}
    extra = read(native / "h3-extra-controls.json")
    selected_count, identities, reviews = 0, set(), []
    all_cases = []
    for name, gate in pipeline["gates"].items():
        receipt_raw = (run / gate["receipt"]).read_bytes()
        receipt = json.loads(receipt_raw)
        raw = (run / receipt["log_file"]).read_bytes()
        assert digest(receipt_raw) == gate["receipt_sha256"]
        assert digest(raw) == receipt["log_sha256"] and len(raw) == receipt["log_bytes"]
        assert receipt["before"] == receipt["after"]
        assert receipt["before"]["commit"] == SOURCE and receipt["before"]["tree"] == TREE
        assert not receipt["before"]["dirty"] and not receipt["timed_out"]
        assert receipt["status"] == "passed" and receipt["command_exit_code"] == receipt["exit_code"] == gate["wrapper_exit"] == 0
        assert receipt["elapsed_seconds"] <= gate["command_budget_seconds"]
        text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", raw.decode())
        if name in ("dependencies", "execution-source-controls", "diverse-source-controls"):
            if name != "dependencies":
                count = 135 if name == "execution-source-controls" else 32
                assert re.search(r"Ran " + str(count) + r" tests? in ", text)
                assert receipt["observed_passed_tests"] == count
            continue
        cases = re.findall(r"^test (\S+) \.\.\. (ok|FAILED|ignored)\s*$", text, re.M)
        assert cases and all(outcome == "ok" for _, outcome in cases)
        assert len(cases) == receipt["observed_passed_tests"] and receipt["observed_failed_tests"] == 0
        if name in steps:
            step = steps[name]
            assert receipt["command"] == step["command"] and gate["command_budget_seconds"] == step["timeout_seconds"]
            assert Counter(cases) == Counter((n, "ok") for n in step["expected_names"])
            selected_count += len(cases)
        elif name == "original-six-effect-controls":
            assert Counter(cases) == Counter((n, "ok") for n in extra["original_six_effect_controls"])
            assert gate["command_budget_seconds"] == 600
        elif name == "provider-effect-existing-and-pq":
            assert len(cases) == 10 and all(n.startswith("provider_effect::") for n, _ in cases)
            assert gate["command_budget_seconds"] == 600
        else:
            assert name == "final-use-profile-controls" and len(cases) == 50
            assert all("final_use" in n and "::" in n for n, _ in cases)
            assert gate["command_budget_seconds"] == 600
        evidence = read(run / (name + ".fd-executed-binaries.json"))
        config_path = run / (name + ".fd-capture-config.json")
        config = read(config_path)
        assert evidence == gate["actual_binary_evidence"]
        assert [list(x) for x in cases] == evidence["actual_cases"] == gate["observed_cases"]
        assert evidence["per_case_bijection_verified"] and evidence["runner_sha256"] == RUNNER
        assert evidence["config_sha256"] == digest(config_path.read_bytes())
        records = evidence["records"]
        assert Counter(r["exact_test"] for r in records) == Counter(n for n, _ in cases)
        assert len(records) == len(cases) == len({n for n, _ in cases})
        expected_images = 2 if name == "neural-runtime-input" else 1
        assert evidence["runner_declared_binary_counts"] == [expected_images]
        assert len(evidence["unique_actual_elf_sha256"]) == expected_images
        for record in records:
            assert record["source"] == config["source"] == gate["source"]
            assert record["source"]["commit"] == SOURCE and record["source"]["tree"] == TREE
            assert record["source"]["environment_sha256"] == ENVIRONMENT
            assert record["coordinator"] == config["coordinator"] == COORDINATOR
            assert record["phase"] == "run" and record["status"] == "pre_exec_fd_bound"
            assert record["coordinator_descendant_verified"] and record["pre_exec_fd_identity_verified"]
            assert record["gate"] == name and record["runner_sha256"] == RUNNER
            assert record["capture_config_sha256"] == evidence["config_sha256"]
            assert record["observed_selected_tests"] == [record["exact_test"]]
            assert record["argv"][0] == record["actual_executable"]
            assert record["argv"].count("--exact") == 1 and "--list" not in record["argv"]
            assert record["argv"][record["argv"].index("--exact") + 1] == record["exact_test"]
            assert record["sha256"] in evidence["unique_actual_elf_sha256"]
            identity = record["pid"], record["start_ticks"]
            assert identity not in identities
            identities.add(identity)
            assert datetime.fromisoformat(receipt["started_at"]).timestamp() <= record["captured_unix"] <= datetime.fromisoformat(receipt["finished_at"]).timestamp()
        live_raw = (run / (name + ".live-polled-binaries.json")).read_bytes()
        live = json.loads(live_raw)
        assert digest(live_raw) == evidence["live_polling_corroboration"]["sha256"] and not live["errors"]
        by_id = {(r["pid"], r["start_ticks"]): r for r in records}
        unmatched = [r for r in live["records"] if (r["pid"], r["start_ticks"]) not in by_id or by_id[r["pid"], r["start_ticks"]]["sha256"] != r["sha256"]]
        if name == "final-use-profile-controls":
            assert evidence["errors"] == ["live process capture differs from exact fd-exec record"]
            assert len(unmatched) == 1 and (unmatched[0]["pid"], unmatched[0]["start_ticks"]) == (1038111, "99368575")
            binding = "REJECTED: one unmatched live PID; no retrospective helper-parent binding"
        else:
            assert not evidence["errors"] and not unmatched
            binding = "exact completed-case / FD-image binding; observed live PIDs agree"
        all_cases.extend({"gate": name, "test": n, "outcome": o} for n, o in cases)
        reviews.append({"gate": name, "passed_outcomes": len(cases), "raw_sha256": digest(raw), "raw_bytes": len(raw), "fd_config_sha256": evidence["config_sha256"], "fd_records": len(records), "binding_result": binding})
    assert selected_count == 74 and len(reviews) == 14 and len(identities) == len(all_cases) == 140
    assert set(manifest["unexecuted"]) == {"full-evidence-library", "full-evidence-ignored-list", "fix", "format"}
    assert not set(manifest["unexecuted"]).intersection(pipeline["gates"])
    assert manifest["coordinator_elapsed_seconds"] == pipeline["timed_coordinator_elapsed_seconds"] < 5400
    proof_path = run / "effect-pq-product-process/1032265-1793915885381498081/completed.json"
    proof_raw = proof_path.read_bytes()
    assert digest(proof_raw) == "f70ff1df3fd8a4b38b9c984400c1fa5101a882cae38720638bed6ee77310c50f"
    proof = json.loads(proof_raw)
    assert (proof["post_count"], proof["physical_apply_count"], proof["lookup_count"], proof["used_nonces"]) == (1, 1, 2, 1)
    assert proof["provider_ack"]["provider_operation_id_sha256"] == proof["provider_record"]["provider_operation_id_sha256"]
    assert proof["provider_ack"]["payload_sha256"] == proof["provider_record"]["payload_sha256"]
    assert proof["provider_ack"]["key"] == proof["provider_record"]["effect_key"]
    assert proof["terminal"]["observation"] == "succeeded"
    first, second = proof["first_process"], proof["second_process"]
    for key in ("sha256", "bytes", "device", "inode", "retained_copy", "source"):
        assert first[key] == second[key]
    assert first["source"]["commit"] == SOURCE and first["source"]["tree"] == TREE
    assert first["full_hash_and_copy_this_capture"] and not second["full_hash_and_copy_this_capture"]
    assert second["same_held_file_object_verified"] and second["capture_method"] == "same-held-file-object-reuse"
    assert first["pid"] != second["pid"] and first["spawn_generation"] == 1 and second["spawn_generation"] == 5

    output.mkdir(parents=True, exist_ok=True)
    copied = output / "complete-raw"
    for entry in manifest["files"]:
        target = copied / entry["relative_path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(run / entry["relative_path"], target)
    shutil.copyfile(native / "h3-native-attempt1-delivery.json", copied / "h3-native-attempt1-delivery.json")
    for name in external:
        shutil.copyfile(native / name, copied / name)
    report = {"schema": "root-H3-complete-raw-review-v1", "source_commit": SOURCE, "source_tree": TREE,
              "delivery_sha256": DELIVERY, "verified_delivered_files": 107, "delivered_bytes": 2100909,
              "delivery_scope": "Original small artifacts plus one explicitly derived retained-image inventory; no archive bytes are substituted for missing execution bindings.",
              "original_gate_logs_checked": len(pipeline["gates"]), "selected_passed_outcomes": selected_count,
              "additional_passed_outcomes": {"compatibility": 6, "provider": 10, "final_use": 50},
              "top_level_actual_fd_identities": len(identities), "gate_reviews": reviews,
              "actual_case_executions": all_cases, "tracked_source_and_5_git_configurations_unchanged": True,
              "10_external_configuration_bytes_match_before_and_after": True, "all_14_per_gate_fd_config_files_verified": True,
              "retained_postrun_bytecode_bytes": 6094, "runtime_scope": "Post-run bytecode and ignored-path inventory, not an import trace or complete runtime closure.",
              "controlled_process_proof_sha256": digest(proof_raw), "process_counts": {"post": 1, "physical_apply": 1, "lookup": 2, "nonce": 1},
              "process_scope": "Original controlled composition with supervisor pre-fencing before SIGKILL; no whole-host restore, hostile privileged-writer or independent custody qualification.",
              "native_result": "FAILED exit1; FinalUse live/FD reconciliation refused; no outer timeout",
              "unexecuted": manifest["unexecuted"], "actual_ELF_bytes": "Separate postrun archive/readback required; no rebuild or image reassignment.", "all_joint_gates": "HOLD"}
    target = output / "root-complete-raw-review.json"
    target.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"output": str(target), "sha256": digest(target.read_bytes()), "files_verified": 107,
                      "selected_passed": 74, "additional_outcomes": [6, 10, 50], "overall": "FAILED"}))


if __name__ == "__main__":
    main()
