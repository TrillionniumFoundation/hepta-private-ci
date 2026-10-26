"""Continue all actual native-decoded V7 step17 checkpoints under frozen policy.

Uses only pinned fitting/planning arrays. The original grid, scientific metrics,
costs, stopped outcomes and owner state are never changed. New verification,
planning, repair and continuation CPU/wall costs are recorded separately.
"""

import argparse
import gzip
import io
import json
import os
from pathlib import Path
import sys
import time
from contextlib import redirect_stdout

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from handoff_v7 import canonical, require, restore_native_dump, sha, verified_modules


INPUT_SHA = "14e2293f83878d70e76754f3de6f5c5b7e4b689fbec1aed728b5f955a0a159b4"
NATIVE_SHA = "de4d4249b8e6e83fbe0b1c0b4f162fd6d6c4a1a98b7b75660eb23050af98367d"
PLANNING_SHA = "d902e815601c963199ac9f8a3f6ca54864884d42a021b3466f573fdcab0d0b7d"
RECOVERY_SHA = "8038e1f0a480f4fcfa065995d983a985c7ba74c3a467fa5934e3b8fabdecd090"


def read_gzip(path):
    return json.loads(gzip.decompress(path.read_bytes()))


def run(manifest, native_root, planning, planning_loader, recovery, grid, code, output):
    manifest, native_root, planning, planning_loader, recovery, grid, code, output = map(
        Path, (manifest, native_root, planning, planning_loader, recovery, grid, code, output))
    start_cpu, start_wall = time.process_time_ns(), time.perf_counter_ns()
    require(sha(manifest.read_bytes()) == INPUT_SHA
        and sha((native_root/"qualification.json").read_bytes()) == NATIVE_SHA
        and sha((planning/"index.json").read_bytes()) == PLANNING_SHA
        and sha((recovery/"recovery.json").read_bytes()) == RECOVERY_SHA,
        "independently pinned input/native/planning/recovery evidence changed")
    plan = json.loads(manifest.read_bytes())
    native = json.loads((native_root/"qualification.json").read_bytes())
    seal = grid/"development_seal.json"
    require(sha(seal.read_bytes()) == plan["grid_seal_sha256"], "sealed grid changed")
    source = (grid/"executed_source.json").read_bytes()
    verified_modules(code, {}, source, plan["executed_source_sha256"])
    from cell_field_policy_v7 import resume_policy

    loader_names = ("recover_v7_terminal_controllers.py", "v7_recover_controller.py",
        "audit_v7_development.py", "v7_audit_records.py", "v7_audit_statistics.py")
    loader_source = {name: sha((planning_loader/name).read_bytes()) for name in loader_names}
    sys.path.insert(0, str(planning_loader.resolve()))
    from recover_v7_terminal_controllers import load_planning

    packages = json.loads((planning/"index.json").read_bytes())["packages"]
    for package in packages:
        path = planning/Path(package["directory"]).name/"manifest.json"
        require(sha(path.read_bytes()) == package["manifest_sha256"], "planning-only package changed")
    inputs = {(version, task): load_planning(planning, version, task, grid)
        for version in ("v5", "v6") for task in ("agnews", "dbpedia")}
    midpoints = [r for r in plan["rows"] if r["step"] == 17 and r["available"]]
    require(len(midpoints) == 23 and all(r["run_status"] == "active" for r in midpoints),
        "fixed23 available active native midpoints required")
    output.mkdir(parents=True, exist_ok=False)
    runtime = io.StringIO()
    with redirect_stdout(runtime):
        np.show_runtime()
    rows = []
    for row in midpoints:
        fit = row["fit_id"]
        destination = output/fit
        destination.mkdir()
        group = native_root/row["version"]/"step17"
        pin = next(b for b in native["bundles"] if b["version"] == row["version"] and b["step"] == 17)
        require(sha((group/"native.json").read_bytes()) == pin["native_receipt_sha256"], "native decode receipt changed")
        decoded = json.loads((group/"native.json").read_bytes())
        cell = f"{row['task']}-{row['head']}-seed{row['seed']}"
        record = next(c for c in decoded["checkpoints"] if c["cell_id"] == cell)
        contract = plan["contracts"][fit]
        state, controller = restore_native_dump(record, code, source, contract, destination/"restored17")
        controller_bytes = canonical(controller)
        require(state.digest() == row["state_sha256"] and sha(controller_bytes) == row["controller_sha256"]
            and controller["action_cursor"] == 1 and controller["plan_horizon"] == 8,
            "actual native midpoint or its seven pending actions changed")
        original = grid/"config00"/fit/"future_field_h8"
        trace = read_gzip(original/"trace.json.gz")
        policy = read_gzip(original/"policy-record.json.gz")
        with np.load(original/"compact.npz", allow_pickle=False) as archive:
            original_actions, original_terminal = archive["actions"], archive["terminal_vector"]
        completed = len(original_actions)
        checkpoints = read_gzip(original/"controller-checkpoints.json.gz")
        if str(completed) in checkpoints:
            terminal_bytes = canonical(checkpoints[str(completed)])
        else:
            terminal_bytes = (recovery/"config00"/fit/"future_field_h8/controller.json").read_bytes()
        require(sha(terminal_bytes) == trace["controller_sha256"][-1],
            "exact original terminal controller preimage changed")
        terminal = json.loads(terminal_bytes)
        data = inputs[row["version"], row["task"]]
        before_cpu, before_wall = time.process_time_ns(), time.perf_counter_ns()
        resumed = resume_policy(state, controller_bytes, contract, data["split"]["current_train"],
            data["current_panels"], data["old_panels"], expected_controller_sha256=row["controller_sha256"])
        extra_cpu, extra_wall = time.process_time_ns()-before_cpu, time.perf_counter_ns()-before_wall
        observed = resumed["record"]
        checks = {"actions_equal": np.array_equal(resumed["actions"], original_actions[17:]),
            "receipts_equal": resumed["receipts"] == trace["receipts"][17:],
            "all_state_digests_equal": [s.digest() for s in resumed["states"]] == trace["state_sha256"][17:],
            "terminal_vector_equal": np.array_equal(resumed["state"].vector(), original_terminal),
            "terminal_state_digest_equal": resumed["state"].digest() == trace["state_sha256"][-1],
            "receipt_chain_equal": resumed["controllers"][-1]["receipt_chain"] == terminal["receipt_chain"],
            "original_stop_or_completion_preserved": observed["status"] == policy["status"]
                and observed["completed_steps"] == policy["completed_steps"] == completed,
            "first_seven_pending_reverified": observed["steps"][0].get("resume_verified_steps") == 7,
            "native_start_state_unchanged": state.digest() == row["state_sha256"]}
        receipt = {"fit_id": fit, "starting_step": 17, "original_status": policy["status"],
            "original_completed_steps": completed, "newly_committed_steps": len(resumed["actions"]),
            "checks": checks, "passed": all(checks.values()),
            "native_midpoint_sha256": row["state_sha256"], "original_controller17_sha256": row["controller_sha256"],
            "original_terminal_controller_sha256": sha(terminal_bytes),
            "terminal_state_sha256": resumed["state"].digest(),
            "new_policy_cpu_ns": observed["cpu_ns"], "new_policy_wall_ns": observed["wall_ns"],
            "total_continuation_cpu_ns": extra_cpu, "total_continuation_wall_ns": extra_wall,
            "resumed_policy_record": observed, "new_receipt_chain": resumed["controllers"][-1]["receipt_chain"],
            "original_stop_ledger_sha256": sha(canonical(terminal["failure_ledger"])),
            "new_stop_ledger_sha256": sha(canonical(resumed["controllers"][-1]["failure_ledger"])),
            "timing_and_resume_verification_counters_compared_as_identical": False,
            "scientific_acceptance": False, "candidate_published": False}
        resumed["state"].save(destination/"terminal")
        (destination/"new-controller.json").write_bytes(canonical(resumed["controllers"][-1]))
        (destination/"receipt.json").write_bytes(canonical(receipt)+b"\n")
        rows.append(receipt)
        print(json.dumps({"fit_id": fit, "passed": receipt["passed"], "status": observed["status"],
            "completed_steps": observed["completed_steps"], "additional_cpu_seconds": extra_cpu/1e9}), flush=True)
    require(sha(seal.read_bytes()) == plan["grid_seal_sha256"]
        and sha(manifest.read_bytes()) == INPUT_SHA
        and {name: sha((planning_loader/name).read_bytes()) for name in loader_names} == loader_source,
        "original sealed evidence or loader source changed")
    result = {"schema": "hepta.actual-native-midpoint-continuation.v7", "status": "PASS" if all(r["passed"] for r in rows) else "FAIL",
        "input_manifest_sha256": INPUT_SHA, "native_roundtrip_receipt_sha256": NATIVE_SHA,
        "planning_index_sha256": PLANNING_SHA, "exact_terminal_recovery_receipt_sha256": RECOVERY_SHA,
        "protocol_sha256": plan["protocol_sha256"], "controller_source_sha256": plan["executed_source_sha256"],
        "grid_seal_sha256": plan["grid_seal_sha256"], "continuation_source_sha256": sha(Path(__file__).read_bytes()),
        "planning_loader_sources": loader_source, "registered_midpoints": 23,
        "passed_midpoints": sum(r["passed"] for r in rows),
        "completed_at32": sum(r["original_status"] == "completed" for r in rows),
        "original_stop_preserved": sum(r["original_status"] != "completed" and r["passed"] for r in rows),
        "newly_committed_steps": sum(r["newly_committed_steps"] for r in rows),
        "additional_policy_cpu_ns": sum(r["new_policy_cpu_ns"] for r in rows),
        "additional_policy_wall_ns": sum(r["new_policy_wall_ns"] for r in rows),
        "total_cpu_ns": time.process_time_ns()-start_cpu, "total_wall_ns": time.perf_counter_ns()-start_wall,
        "runtime": {"numpy_runtime": runtime.getvalue(), "thread_environment": {name: os.environ.get(name)
            for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")}},
        "rows": rows, "selection_labels_used": False, "scientific_costs_replaced": False,
        "primary_selection_changed": False, "candidate_published": False, "scientific_acceptance": False,
        "production_authority": False}
    (output/"qualification.json").write_bytes(canonical(result)+b"\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("manifest", "native-root", "planning", "planning-loader", "recovery", "grid", "code", "output"):
        parser.add_argument("--"+name, required=True)
    result = run(**vars(parser.parse_args()))
    print(json.dumps({k: result[k] for k in ("status", "registered_midpoints", "passed_midpoints",
        "newly_committed_steps", "additional_policy_cpu_ns", "additional_policy_wall_ns")}))
