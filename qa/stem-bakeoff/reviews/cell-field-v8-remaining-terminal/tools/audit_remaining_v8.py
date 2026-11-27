"""Post-seal planning-only audit of all96 fixed remaining-terminal outputs."""

import argparse
from collections import Counter
from itertools import product
import json
import os
from pathlib import Path
import sys
import time

import numpy as np

from remaining_audit_case_v8 import inspect_case
from remaining_audit_core_v8 import (METHODS, bind_execution_identity, canonical, check_seal, digest, file_hash,
    panel_values, read, require, required_hash)


AXES = (["v5", "v6"], ["agnews", "dbpedia"], ["linear", "gated"], [7, 17, 29])
AUDITOR_FILES = ("audit_remaining_v8.py", "remaining_audit_core_v8.py", "remaining_audit_case_v8.py")


def validate_sources(workspace, run, pins):
    code = workspace/"hepta-repo-v8/qa/stem-bakeoff"
    sources = read(run/"executed_source.json")
    require(len(sources) == pins["source_files"] and len(sources) in (127, 129)
        and digest(sources) == pins["source_sha256"], "exact frozen source closure")
    if len(sources) == 129:
        require({"cell_field_remaining_run_compressed_v8.py", "test_cell_field_remaining_storage_v8.py"} <= set(sources), "registered compression-only revision")
    for name, identity in sources.items():
        require(Path(name).name == name and file_hash(code/name) == identity, "frozen source changed: "+name)
    return code, sources


def compare_pair(directory, records):
    full, field = (records[name] for name in ("full_adjoint_remaining", "terminal_field8_remaining"))
    complete = all(r.get("completed", False) for r in (full, field))
    row = {"complete": complete, "full_status": full["status"], "field_status": field["status"], "passed": False}
    if full["available"] and field["available"]:
        with np.load(directory/"full_adjoint_remaining/trajectory.npz", allow_pickle=False) as a, \
                np.load(directory/"terminal_field8_remaining/trajectory.npz", allow_pickle=False) as b:
            same = all(a[k].shape == b[k].shape for k in ("states", "actions", "old_losses"))
            row["same_available_prefix_length"] = same
            if same:
                row.update({"max_"+k+"_difference": float(np.max(np.abs(a[k]-b[k]), initial=0.))
                    for k in ("states", "actions", "old_losses")})
                row["same_available_prefix_within_1e_10"] = all(row["max_"+k+"_difference"] <= 1e-10
                    for k in ("states", "actions", "old_losses"))
                row["passed"] = complete and row["same_available_prefix_within_1e_10"]
    return row


def audit(workspace, run, grid, planning, pins, output):
    from threadpoolctl import threadpool_info
    workspace, run, grid, planning, pins_path, output = map(lambda p: Path(p).resolve(),
        (workspace, run, grid, planning, pins, output))
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    require(not output.exists() and run not in output.parents, "separate new audit directory")
    require(os.environ.get("OPENBLAS_NUM_THREADS") == os.environ.get("OMP_NUM_THREADS") == "1"
        and all(p["num_threads"] == 1 for p in threadpool_info()), "frozen single-thread numeric runtime")
    pins = read(pins_path)
    expected_seal = required_hash(pins, "control_seal_sha256")
    control_seal = file_hash(run/"control_seal.json")
    seal = check_seal(run, expected_seal)
    code, sources = validate_sources(workspace, run, pins)
    require(file_hash(run/"protocol.json") == pins["protocol_sha256"]
        and seal["source_sha256"] == pins["source_sha256"] and seal["protocol_sha256"] == pins["protocol_sha256"], "external source/protocol pins")
    protocol, report = read(run/"protocol.json"), read(run/"report.json")
    bind_execution_identity(report, pins)
    require(protocol["schema"] == "hepta.remaining-terminal-study.v8" and protocol["status"] == "FROZEN"
        and [protocol[k] for k in ("versions", "tasks", "head_modes", "seeds")] == list(AXES)
        and protocol["methods"] == list(METHODS) and protocol["registered_outputs"] == 96
        and report["source_commit"] == pins["source_commit"] and report["fits"] == 24
        and report["output_slots"] == 96 and len(report["rows"]) == 96
        and report["selection_labels_accessed"] is False and report["new_sources_accessed"] is False
        and report["scientific_acceptance"] is False, "complete frozen development-only control census")
    base_pins = protocol["base_inputs"]
    require(file_hash(grid/"protocol.json") == base_pins["protocol_sha256"]
        and file_hash(grid/"development_seal.json") == base_pins["seal_sha256"]
        and file_hash(planning/"index.json") == base_pins["planning_index_sha256"], "original planning-only input pins")
    sys.path.insert(0, str(code))
    from cell_field_common_run_v8 import load_planning, load_warmup
    index, base = read(planning/"index.json"), read(grid/"protocol.json")
    datasets = {(v, t): load_planning(planning, grid, index, v, t, base_pins["protocol_sha256"])
        for v, t in product(AXES[0], AXES[1])}
    combinations = list(product(*AXES))
    expected = {(f"{v}-{t}-seed{s}-{h}", m) for v, t, h, s in combinations for m in METHODS}
    recorded = {(r["fit"], r["method"]): r for r in report["rows"]}
    require(len(recorded) == 96 and set(recorded) == expected
        and {(p.parent.parent.name, p.parent.name) for p in run.glob("*/*/result.json")} == expected,
        "exact all96 output slots, without replacement or omission")
    auditor_sources = {name: file_hash(Path(__file__).with_name(name)) for name in AUDITOR_FILES}
    output.mkdir(parents=True, exist_ok=False)
    cases, parities, failures = [], [], []
    for ordinal, (v, t, h, s) in enumerate(combinations):
        fit = f"{v}-{t}-seed{s}-{h}"
        train, panels, manifest = datasets[v, t]
        origin, warm_pin = load_warmup(workspace, base, fit, v, train)
        require(origin.step_count == 64, "original warmed optimizer clock")
        inputs = read(run/fit/"inputs.json")
        rotation = ordinal % 4
        require(inputs["fit"] == fit and inputs["warmup"] == warm_pin
            and inputs["method_order"] == list(METHODS[rotation:]+METHODS[:rotation])
            and inputs["planning_manifest_canonical_sha256"] == digest(manifest)
            and inputs["original_old_anchors"] == panel_values(origin, panels[4:]).tolist(), "complete original input/rotation binding")
        local = {}
        for method in inputs["method_order"]:
            directory = run/fit/method
            require(file_hash(directory/"result.json") == recorded[fit, method]["result_sha256"], "original result commitment")
            try:
                result = inspect_case(directory, origin, train, panels, method, pins["protocol_sha256"], pins["source_sha256"],
                    compressed=len(sources) == 129)
                raw = result.pop("record")
                for key in ("status", "error", "completed_steps", "common_J32", "parameter_action_penalty",
                    "policy_call_cpu_ns", "policy_call_wall_ns", "terminal_state_sha256"):
                    require(recorded[fit, method].get(key) == raw.get(key), "report/result consistency: "+key)
                result.pop("actions", None)
                result.pop("states", None)
                result.update(audit_status="PASS", original_result_sha256=recorded[fit, method]["result_sha256"],
                    policy_call_cpu_ns=raw["policy_call_cpu_ns"], policy_call_wall_ns=raw["policy_call_wall_ns"])
                local[method] = result
            except Exception as error:
                result = {"audit_status": "FAIL", "error": {"type": type(error).__name__, "message": str(error)}}
                failures.append({"fit": fit, "method": method, **result})
            cases.append({"fit": fit, "version": v, "task": t, "head": h, "seed": s, "method": method, **result})
        if len(local) == 4:
            parities.append({"fit": fit, **compare_pair(run/fit, local)})
        print(json.dumps({"audited_fit": fit, "cases": len(cases), "audit_failures": len(failures)}), flush=True)
    if not failures:
        require(parities == report["full_field_parities"], "all24 complete/partial Full-field dispositions independently reproduced")
        require(dict(Counter(row["status"] for row in cases)) == report["status_counts"], "full original status census")
    check_seal(run, control_seal)
    validate_sources(workspace, run, pins)
    require({n: file_hash(Path(__file__).with_name(n)) for n in AUDITOR_FILES} == auditor_sources, "auditor source changed during checks")
    (output/"cases.json").write_bytes(canonical(cases)+b"\n")
    good = [r for r in cases if r["audit_status"] == "PASS"]
    summary = {"schema": "hepta.independent-remaining-terminal-audit.v8", "status": "FAIL" if failures else "PASS",
        "protocol_sha256": pins["protocol_sha256"], "source_sha256": pins["source_sha256"],
        "source_commit": pins["source_commit"], "control_seal_sha256": control_seal, "sealed_files": len(seal["files"]),
        "auditor_sources": auditor_sources, "pins_sha256": file_hash(pins_path), "output_slots": len(cases),
        "case_census_sha256": file_hash(output/"cases.json"), "audit_failures": failures,
        "unavailable_original_prefixes": sum(not r["available"] for r in good),
        "original_actual_error_slots": sum(bool(r["actual_errors"]) for r in good),
        "known_actual_updates_replayed": sum(r["known_replayed_steps"] for r in good),
        "complete32_policies": sum(r["completed"] for r in good), "saved_proposal_checks": sum(r["proposal_checks"] for r in good),
        "independent_zero_tail_updates": sum(r.get("audit_nominal_updates", 0) for r in good),
        "independent_jvp_steps": sum(r.get("audit_jvp_steps", 0) for r in good),
        "maximum_first_map_absolute_error": max((r.get("max_map_absolute_error", 0.) for r in good), default=0.),
        "maximum_initial_field_absolute_error": max((r.get("max_initial_field_absolute_error", 0.) for r in good), default=0.),
        "full_field_parities": parities, "selection_labels_accessed": False, "new_sources_accessed": False,
        "new_safety_searches": 0, "new_candidate_trajectories": 0, "scientific_acceptance": False,
        "scope": "Every available actual prefix and checkpoint, independent forward-JVP construction of every saved terminal map, all original portfolio ledgers, actual-action forecast and physical effort; no population-retention or future-adaptive-policy claim",
        "cpu_ns": time.process_time_ns()-cpu, "wall_ns": time.perf_counter_ns()-began}
    (output/"audit.json").write_bytes(canonical(summary)+b"\n")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("workspace", "run", "grid", "planning", "pins", "output"):
        parser.add_argument("--"+name, required=True)
    value = audit(**vars(parser.parse_args()))
    print(json.dumps({k: value[k] for k in ("status", "output_slots", "known_actual_updates_replayed", "complete32_policies")}))
