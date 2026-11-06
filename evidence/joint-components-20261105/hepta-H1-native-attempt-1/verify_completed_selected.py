#!/usr/bin/env python3
"""Verify received H1 selected-gate records; this never executes native tests."""
import collections
import datetime
import hashlib
import json
import pathlib
import re
import shutil
import sys

source = pathlib.Path(sys.argv[1])
plan_path = pathlib.Path(sys.argv[2])
out = pathlib.Path(sys.argv[3])
out.mkdir(parents=True, exist_ok=True)
sha = lambda b: hashlib.sha256(b).hexdigest()
read = lambda name: json.loads((source / name).read_bytes())
commit = "9f785cb201ba12ab0ae0f0d341c0f7912cc65efc"
tree = "24804b21d0306b617e12fa3f5b9454a12ed4ad41"
plan = json.loads(plan_path.read_bytes())
pipeline = read("pipeline-status.final.json")
image_map = read("post-terminal-gates-and-image-map.json")
environment_hash = sha((source / "native-environment.json").read_bytes())
assert pipeline["status"] == "failed"
assert pipeline["error"] == "AssertionError('effect-pq-owner original gate did not pass')"
assert pipeline["budget_semantics"]["outer_seconds"] == 5400
assert pipeline["timed_coordinator_elapsed_seconds"] < 5400
assert pipeline["configuration_unchanged"] is True
assert (source / "full-source-before.json").read_bytes() == (source / "full-source-after.json").read_bytes()
gates = ["dispatcher", "product", "recovery-owner", "recovery-signed", "recovery-product", "qualification-growth", "effect-pq-owner"]
plans = {v["name"]: v for v in plan["steps"]}
rows, images, all_missing = [], {}, []
files = {"pipeline-status.final.json", "post-terminal-gates-and-image-map.json", "full-source-before.json", "full-source-after.json", "native-environment.json", "configuration-after.json", "terminal.raw.json", "post-sparse-readback-1.json", "post-sparse-readback-2.json", "post-sparse-readback-3.json"}
for gate in gates:
    receipt_name, captures_name = gate + ".json", gate + ".executed-binaries.json"
    receipt, captures, expected = read(receipt_name), read(captures_name), plans[gate]
    record = pipeline["gates"][gate]
    raw = (source / receipt["log_file"]).read_bytes()
    assert sha(raw) == receipt["log_sha256"] and len(raw) == receipt["log_bytes"]
    assert sha((source / receipt_name).read_bytes()) == record["receipt_sha256"]
    assert receipt["command"] == expected["command"]
    assert record["command_budget_seconds"] == expected["timeout_seconds"]
    assert receipt["elapsed_seconds"] < expected["timeout_seconds"]
    assert receipt["before"] == receipt["after"]
    assert receipt["before"]["commit"] == commit and receipt["before"]["tree"] == tree
    assert receipt["before"]["dirty"] is False
    assert receipt["timed_out"] is False and receipt["output_limit_exceeded"] is False
    assert receipt["source_sha"] == receipt["tested_sha"] == commit
    cases = re.findall(r"^test (\S+) \.\.\. (ok|FAILED)$", raw.decode(), re.M)
    assert collections.Counter(name for name, _ in cases) == collections.Counter(expected["expected_names"])
    count = collections.Counter(status for _, status in cases)
    assert count["ok"] == receipt["observed_passed_tests"] == record["passed"]
    assert count["FAILED"] == receipt["observed_failed_tests"] == record["failed"]
    if gate == "effect-pq-owner":
        assert (count["ok"], count["FAILED"], receipt["status"], receipt["exit_code"]) == (9, 2, "failed", 100)
    else:
        assert count["FAILED"] == 0 and receipt["exit_code"] == 0 and receipt["status"] == "passed"
    observed = set()
    assert captures["errors"] == []
    started = datetime.datetime.fromisoformat(receipt["started_at"]).timestamp()
    finished = datetime.datetime.fromisoformat(receipt["finished_at"]).timestamp()
    for capture in captures["records"]:
        assert capture["source"]["commit"] == commit and capture["source"]["tree"] == tree
        assert capture["source"]["environment_sha256"] == environment_hash
        assert capture["wrapper_descendant_verified"] is True and capture["post_open_task_and_exe_verified"] is True
        assert capture["pid"] > 0 and capture["wrapper_pid"] > 0
        assert int(capture["start_ticks"]) > 0 and int(capture["wrapper_start_ticks"]) > 0
        assert started <= capture["captured_unix"] <= finished
        names = set(capture["observed_selected_tests"])
        assert names and names <= set(expected["expected_names"])
        observed.update(names)
        key = capture["sha256"]
        image = images.setdefault(key, {"sha256": key, "bytes": capture["bytes"], "records": 0, "gates": set(), "retained_paths": set()})
        assert image["bytes"] == capture["bytes"]
        image["records"] += 1
        image["gates"].add(gate)
        image["retained_paths"].add(capture["retained_copy"])
    assert observed == set(captures["observed_selected_tests"])
    assert set(captures["unique_actual_elf_sha256"]) == {c["sha256"] for c in captures["records"]}
    missing = sorted(set(expected["expected_names"]) - observed)
    all_missing.extend(missing)
    rows.append({"gate": gate, "passed": count["ok"], "failed": count["FAILED"], "exact_selected_names_verified": True, "original_budget_seconds": expected["timeout_seconds"], "wrapper_seconds": receipt["elapsed_seconds"], "process_capture_records": len(captures["records"]), "missing_individual_process_captures": missing, "raw_log_bytes": len(raw), "raw_log_sha256": sha(raw), "receipt_sha256": sha((source / receipt_name).read_bytes()), "capture_sha256": sha((source / captures_name).read_bytes())})
    files.update((receipt_name, captures_name, receipt["log_file"]))
assert sum(r["passed"] for r in rows) == 65
assert sum(r["failed"] for r in rows) == 2
assert sum(r["process_capture_records"] for r in rows) == 64
assert len(all_missing) == 3 and len(images) == 4
assert sum(x["bytes"] for x in images.values()) == 774620584
assert set(all_missing) == {"recovery_invocation_schema_tests::recovery_invocation_schema_refuses_non_rowid_or_composite_sequences", "evidence_frontier::tests::recovery_frontier_cannot_be_omitted_at_the_ordinary_agentd_run_entry", "evidence_frontier::tests::recovery_frontier_enforces_root_scope_epoch_revocation_and_generation_floor"}
for image in images.values():
    image["gates"] = sorted(image["gates"])
    image["retained_paths"] = sorted(image["retained_paths"])
for original in image_map["unique_actual_images"]:
    item = images[original["sha256"]]
    assert item["bytes"] == original["bytes"] and item["records"] == original["captured_records"]
    assert item["gates"] == sorted(original["gates"])
    assert item["retained_paths"] == sorted(original["retained_paths"])
inventory = []
for name in sorted(files):
    b = (source / name).read_bytes()
    (out / name).write_bytes(b)
    assert (out / name).read_bytes() == b
    inventory.append({"path": name, "bytes": len(b), "sha256": sha(b)})
shutil.copyfile(plan_path, out / "h1-native-plan.json")
review = {"schema": "root-H1-completed-selected-raw-review-v1", "commit": commit, "tree": tree, "result": "FAILED", "source_guard_before_after_byte_identical": True, "configuration_unchanged": True, "actual_selected_run": 67, "actual_passed": 65, "actual_failed": 2, "process_capture_records": 64, "missing_individual_process_captures": all_missing, "gates": rows, "unique_images": sorted(images.values(), key=lambda i: i["sha256"]), "actual_raw_ELF_bytes_rehashed_locally": False, "missing_captures_retroactively_assigned": False, "whole_runtime_interpreter_closure_qualified": False, "original_selected_not_run": ["effect-pq-contract", "effect-pq-product"], "followup_not_run": image_map["not_run_followup_gates"], "original_full_sequence_passed": False, "H2_credit": False, "inventory": inventory}
(out / "root-review.json").write_text(json.dumps(review, indent=2) + "\n")
print(json.dumps({"result": review["result"], "selected_run": 67, "passed": 65, "failed": 2, "captures": 64, "missing_captures": all_missing, "unique_images": 4, "unique_image_bytes": 774620584, "copied_files": len(inventory) + 1, "review_sha256": sha((out / "root-review.json").read_bytes())}))
