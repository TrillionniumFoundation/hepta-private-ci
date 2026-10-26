"""Independent sealed V7 replay/statistics audit and separate native input export."""

import argparse
from collections import Counter
from datetime import datetime, timezone
from itertools import product
import json
from pathlib import Path
import subprocess
import sys
import time

import numpy as np

from v7_audit_records import canonical, digest, file_hash, inspect_case, pair_hash, read, require
from v7_audit_statistics import compare, recompute


PROTOCOL = "e1827b6a0a4de9a083fca5c9401751b6063e63b447617a90719e64a089b4da7d"
SOURCE_COMMIT = "147a67868afb68511a5152f7f944fb26df34843b"


def validate_seal(grid):
    seal = read(grid/"development_seal.json")
    require(seal["protocol_sha256"] == PROTOCOL and seal["historical_development_labels_used"] is True
        and seal["new_confirmation_labels_accessed"] is False, "complete development-only seal")
    paths = {p.relative_to(grid).as_posix(): p for p in grid.rglob("*") if p.is_file() and p.name != "development_seal.json"}
    require(set(paths) == set(seal["files"]), "sealed complete file census")
    for name, path in paths.items():
        pin = seal["files"][name]
        require(not path.is_symlink() and path.stat().st_size == pin["bytes"] and file_hash(path) == pin["sha256"], "sealed file: "+name)
    return seal


def validate_sources(workspace, grid):
    source = read(grid/"executed_source.json")
    require(len(source) == 103, "registered103 executed source files")
    for name, expected in source.items():
        path = workspace/"hepta-repo-v7b/qa/stem-bakeoff"/name
        require(path.name == name and not path.is_symlink() and file_hash(path) == expected, "current source closure: "+name)
        published = subprocess.run(["git", "show", SOURCE_COMMIT+":qa/stem-bakeoff/"+name],
            cwd=workspace/"hepta-repo-v7b", stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True).stdout
        require(digest(published) == expected, "published pre-outcome source blob: "+name)
    return digest(source)


def warmup(workspace, plan, version, task, head, seed, inputs):
    from cell_field_state import CellTrainingState
    identity = f"{version}-{task}-seed{seed}-{head}"
    pin = plan["historical_warmups"][identity]
    expected = f"{task}/seed{seed}-{head}/warmup/checkpoint"
    require(pin["relative_directory"] == expected and set(pin["files"]) == {"manifest.json", "state.npz"}, "historical checkpoint path")
    directory = workspace/f"pft-run-{version}"/expected
    for name, value in pin["files"].items():
        require(file_hash(directory/name) == value["sha256"] and (directory/name).stat().st_size == value["bytes"], "historical complete checkpoint")
    metadata = read(directory/"manifest.json")
    expected_contexts = {name: pair_hash(inputs["split"][name]) for name in ("old_train", "current_train")}
    return CellTrainingState.load(directory, metadata["bindings"], inputs["plan"]["optimizer"], expected_contexts, pin["state_sha256"])


def audit(workspace, grid, output, native_output):
    workspace, grid, output, native_output = map(Path, (workspace, grid, output, native_output))
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    auditor_files = [Path(__file__), Path(__file__).with_name("v7_audit_records.py"),
        Path(__file__).with_name("v7_audit_statistics.py"), Path(__file__).with_name("test_v7_postrun_audit.py")]
    auditor_sources = {path.name: file_hash(path) for path in auditor_files}
    seal = validate_seal(grid)
    source_sha = validate_sources(workspace, grid)
    seal_sha = file_hash(grid/"development_seal.json")
    require(file_hash(grid/"protocol.json") == PROTOCOL and seal["executed_source_sha256"] == source_sha, "protocol/closure bindings")
    plan, recorded_run, recorded_selection = read(grid/"protocol.json"), read(grid/"run.json"), read(grid/"selection.json")
    sys.path.insert(0, str(workspace/"hepta-repo-v7b/qa/stem-bakeoff"))
    from cell_field_development_data_v7 import load_development
    output.mkdir(parents=True, exist_ok=True)
    selected = recorded_selection["selected_index"]
    engineering_index = 0 if selected is None else selected
    fallback = selected is None
    native_output.mkdir(parents=True, exist_ok=True)
    datasets, warms = {}, {}
    for version, task in product(plan["versions"], plan["tasks"]):
        data = load_development(version, task, workspace/f"pft-data-{version}/cohorts",
            workspace/f"pft-features-{version}", workspace/"pft-data-v5/inputs")
        prior, actual = read(grid/"inputs"/f"{version}-{task}.json"), json.loads(json.dumps(data["provenance"]))
        for key in prior:
            if key not in {"cpu_ns", "wall_ns"}:
                require(prior[key] == actual[key], "frozen data/panel provenance: "+key)
        datasets[version, task] = data
        for head, seed in product(plan["head_modes"], plan["seeds"]):
            warms[version, task, head, seed] = warmup(workspace, plan, version, task, head, seed, data)
    cases, case_rows, native_rows, snapshot_count, replay_steps = {}, [], [], 0, 0
    native_contracts = {}
    expected_order = []
    combinations = list(product(plan["versions"], plan["tasks"], plan["head_modes"], plan["seeds"]))
    expected_paths = {f"config{index:02d}/{version}-{task}-seed{seed}-{head}/{policy}/result.json"
        for index in range(12) for version, task, head, seed in combinations for policy in plan["primary_policies"]}
    if selected is not None:
        expected_paths.update(f"config{selected:02d}/{version}-{task}-seed{seed}-{head}/full_h8/result.json"
            for version, task, head, seed in combinations)
    actual_paths = {path.relative_to(grid).as_posix() for path in grid.glob("config*/*/*/result.json")}
    require(actual_paths == expected_paths, "exact primary and conditional Full policy artifact census")
    for index in range(12):
        configuration = plan["configurations"][index]["configuration"]
        for ordinal, (version, task, head, seed) in enumerate(combinations):
            identity = f"{version}-{task}-seed{seed}-{head}"
            inputs, initial = datasets[version, task], warms[version, task, head, seed]
            shift = (index+ordinal) % 3
            policies = plan["primary_policies"]
            order = policies[shift:]+policies[:shift]
            expected_order.append({"index": index, "fit_id": identity, "policies": order})
            sources_sha = digest({name: inputs["role_metadata"][role] for name, role in (("old", "old_test"), ("future", "future_test"))})
            for policy in order:
                directory = grid/f"config{index:02d}"/identity/policy
                header = read(directory/"result.json")
                for key, value in {"version": version, "task": task, "head": head, "seed": seed,
                    "fit_id": identity, "policy": policy, "selection_sources_sha256": sources_sha}.items():
                    require(header[key] == value, "registered policy slot/source identity: "+key)
                engineering = index == engineering_index and policy == "future_field_h8"
                restore = directory/"selected-checkpoints" if index == selected else None
                destination = native_output/identity if engineering and fallback else None
                case = inspect_case(directory, initial, inputs, configuration, policy, PROTOCOL, source_sha,
                    restore_directory=restore, native_directory=destination,
                    keep_vectors=index == selected and policy == "future_field_h8")
                cases[index, version, task, head, seed, policy] = case
                cuts = case["registered_checkpoint_rows"]
                snapshot_count += len(cuts)
                replay_steps += header["completed_steps"] or 0
                case_rows.append({"index": index, "fit_id": identity, "policy": policy, "status": header["status"],
                    "completed_steps": header["completed_steps"], "cpu_ns": header["cpu_ns"], "wall_ns": header["wall_ns"],
                    "future_mean_nll": header["future_mean_nll"], "old_mean_difference": header["old_mean_difference"],
                    "actual_errors": case["actual_errors"], "controller_cut_points_checked": [r["step"] for r in cuts],
                    "terminal_controller_preimage_available": case["terminal_controller_preimage_available"],
                    "maximum_empirical_old_panel_excess": case.get("maximum_panel_excess")})
                if engineering:
                    if cuts:
                        native_contracts[identity] = read(Path(cuts[0]["directory"])/"controller.json")["contract"]
                    for step in (0, 16, 17, 32):
                        found = next((r for r in cuts if r["step"] == step), None)
                        native_rows.append({"fit_id": identity, "version": version, "task": task, "head": head, "seed": seed,
                            "policy": policy, "configuration_index": engineering_index, "step": step,
                            "available": found is not None, "policy_status": header["status"],
                            **(found if found else {"reason": "checkpoint not committed or result unavailable; no state synthesized"})})
        print(json.dumps({"audited_configuration": index, "primary_records": len(case_rows), "actual_updates_replayed": replay_steps}), flush=True)
    require(read(grid/"execution-order.json") == expected_order, "all288 prescribed policy order rotations")
    summaries, selection, compact = recompute(plan, cases)
    numeric_error = compare(summaries, read(grid/"configuration-summaries.json"))
    numeric_error = max(numeric_error, compare(selection, recorded_selection))
    parity = []
    if selected is not None:
        for version, task, head, seed in combinations:
            identity = f"{version}-{task}-seed{seed}-{head}"
            directory = grid/f"config{selected:02d}"/identity/"full_h8"
            full = inspect_case(directory, warms[version, task, head, seed], datasets[version, task],
                plan["configurations"][selected]["configuration"], "full_h8", PROTOCOL, source_sha,
                restore_directory=directory/"selected-checkpoints", keep_vectors=True)
            field = cases[selected, version, task, head, seed, "future_field_h8"]
            if not full["available"] or full["actions"].shape != field["actions"].shape:
                row = {"fit_id": identity, "passed": False, "reason": "different committed trace lengths", "absolute_tolerance": 1e-9}
            else:
                action_error = float(np.max(np.abs(full["actions"]-field["actions"])))
                state_error = float(np.max(np.abs(full["state_vectors"]-field["state_vectors"])))
                row = {"fit_id": identity, "passed": full["header"]["status"] == "completed" and full["header"]["audit_passed"]
                    and action_error <= 1e-9 and state_error <= 1e-9, "maximum_action_absolute_error": action_error,
                    "maximum_full_state_absolute_error": state_error, "absolute_tolerance": 1e-9}
            parity.append(row)
        numeric_error = max(numeric_error, compare(parity, recorded_run["full_reference_parity"]))
    else:
        require(recorded_run["full_reference_parity"] == [], "Full reference remains conditional on an eligible configuration")
    require(recorded_run["primary_outputs"] == recorded_run["registered_primary_outputs"] == 864
        and recorded_run["new_confirmation_selected"] is False and recorded_run["scientific_acceptance"] is False,
        "complete primary census and no new science claim")
    parity_passed = len(parity) == 24 and all(r["passed"] for r in parity)
    require(recorded_run["full_reference_parity_passed"] == parity_passed
        and recorded_run["development_conditions_met"] == (selection["confirmation_plausibility_passed"] and parity_passed), "conditional development disposition")
    fallback_plan = Path(__file__).with_name("engineering-fallback-plan.json")
    native = {"schema": "hepta.cell-field-native-development-inputs.v7b", "protocol_sha256": PROTOCOL,
        "executed_source_sha256": source_sha, "executed_source_commit": SOURCE_COMMIT,
        "grid_seal_sha256": seal_sha, "unchanged_selection_sha256": file_hash(grid/"selection.json"),
        "engineering_plan_sha256": file_hash(fallback_plan), "fallback": fallback,
        "configuration_index": engineering_index, "selected_index": selected, "registered_fits": 24,
        "registered_checkpoints": 96, "available_checkpoints": sum(r["available"] for r in native_rows),
        "missing_checkpoints": sum(not r["available"] for r in native_rows), "rows": native_rows,
        "contracts": native_contracts,
        "resumable_active_checkpoints": sum(r.get("run_status") == "active" for r in native_rows),
        "completed_terminal_checkpoints": sum(r.get("run_status") == "completed" for r in native_rows),
        "stopped_for_rejection_checkpoints": sum(r.get("run_status") == "stopped" for r in native_rows),
        "optimization_calls": 0, "primary_selection_changed": False, "scientific_acceptance": False,
        "scope": "separate engineering coverage only; exact original controller bytes and stored-action physical restore"}
    (native_output/"manifest.json").write_bytes(canonical(native)+b"\n")
    require(file_hash(grid/"development_seal.json") == seal_sha, "original seal unchanged during audit")
    validate_seal(grid)
    require(validate_sources(workspace, grid) == source_sha, "source closure unchanged during audit")
    require({path.name: file_hash(path) for path in auditor_files} == auditor_sources, "separate post-run auditor source unchanged")
    report = {"schema": "hepta.cell-field-independent-development-audit.v7b", "status": "PASS",
        "protocol_sha256": PROTOCOL, "executed_source_sha256": source_sha, "executed_source_commit": SOURCE_COMMIT,
        "development_seal_sha256": seal_sha, "sealed_files": len(seal["files"]), "executed_source_files": 103,
        "post_run_auditor_sources": auditor_sources,
        "post_run_auditor_source_scope": "independent post-run verification; absent from the 103-file pre-execution closure",
        "primary_records": len(case_rows), "actual_updates_replayed": replay_steps,
        "canonical_controller_snapshots_checked": snapshot_count, "cost_order_groups": len(expected_order),
        "source_metric_and_selection_maximum_absolute_error": numeric_error,
        "policy_statuses": dict(Counter(row["status"] for row in case_rows)),
        "actual_error_records": sum(bool(row["actual_errors"]) for row in case_rows),
        "terminal_controller_preimages_available": sum(row["terminal_controller_preimage_available"] for row in case_rows),
        "terminal_controller_preimages_unavailable": sum(not row["terminal_controller_preimage_available"] for row in case_rows),
        "configuration_table": compact, "group_rows": [{"index": row["index"], **g} for row in summaries for g in row["groups"]],
        "selection": selection, "full_reference_parity": parity,
        "native_manifest_sha256": file_hash(native_output/"manifest.json"),
        "native_available_checkpoints": native["available_checkpoints"], "native_missing_checkpoints": native["missing_checkpoints"],
        "native_checkpoint_statuses": {key: native[key] for key in ("resumable_active_checkpoints",
            "completed_terminal_checkpoints", "stopped_for_rejection_checkpoints")},
        "no_new_optimization": True, "new_confirmation_selected": False, "scientific_acceptance": False,
        "scope": "independent recorded arithmetic and actual-engine replay; every actual physical state/receipt/old-panel step; all retained canonical0/16/17/32 and actual terminal cuts; stored-action suffix restoration, not future optimizer replanning; each actual terminal preimage is required and includes its full original paid stop ledger; unavailable execution-error slots remain explicit",
        "cpu_ns": time.process_time_ns()-cpu, "wall_ns": time.perf_counter_ns()-began,
        "completed_at": datetime.now(timezone.utc).isoformat()}
    (output/"case-census.json").write_bytes(canonical(case_rows)+b"\n")
    report["case_census_sha256"] = file_hash(output/"case-census.json")
    (output/"audit.json").write_bytes(canonical(report)+b"\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("workspace", "grid", "output", "native-output"):
        parser.add_argument("--"+name, required=True)
    result = audit(**vars(parser.parse_args()))
    print(json.dumps({key: result[key] for key in ("status", "primary_records", "actual_updates_replayed",
        "source_metric_and_selection_maximum_absolute_error", "selection", "native_available_checkpoints", "native_missing_checkpoints")}))
