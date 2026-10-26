"""Materialize all98 exact sealed V7b stop origins for a frozen V8 diagnostic.

Only original stored actions are replayed. This never replans, loads selection
arrays, or runs a proposed repair. Original stopped controllers remain stopped.
"""

import argparse
import json
from pathlib import Path
import sys
import time

import numpy as np

from stop_census_v8 import PROTOCOL, SEAL, SOURCE, canonical, digest, read, require, sealed, sha


PLANNING_INDEX = "fee97efebd8b20ef2a996cecc3ccc97e901b1272fceecde8e4671749000a0b26"


def export(workspace, census_file, output):
    workspace, census_file, output = map(Path, (workspace, census_file, output))
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    grid = workspace/"pft-development-v7b/grid"
    packages = workspace/"pft-development-v7b/planning-only"
    source = workspace/"hepta-repo-v7b/qa/stem-bakeoff"
    source_map = read(grid/"executed_source.json")
    require(digest(source_map) == SOURCE and len(source_map) == 103, "exact original103-source closure")
    for name, value in source_map.items():
        require(sha(source/name) == value, "original source unchanged: "+name)
    require(sha(grid/"protocol.json") == PROTOCOL and sha(grid/"development_seal.json") == SEAL
        and sha(packages/"index.json") == PLANNING_INDEX, "frozen original run and planning-only data")
    sys.path[:0] = [str(source), str(workspace/"pft-audit-v7b-development")]
    from cell_field_state import CellTrainingState, dataset_digest
    from export_v7b_planning_only import load_planning
    from cell_field_repair_v7 import panel_losses
    from threadpoolctl import threadpool_info

    plan, seal = read(grid/"protocol.json"), read(grid/"development_seal.json")
    census = read(census_file)
    require(census["status"] == "PASS" and census["stopped_policy_slots"] == 98
        and len(census["all98_stops"]) == 98 and census["source_v7b_seal_sha256"] == SEAL,
        "exact complete stop census required")
    require(not output.exists(), "new independent diagnostic input directory required")
    output.mkdir(parents=True)
    datasets, warmups, rows, updates = {}, {}, [], 0
    for row in census["all98_stops"]:
        case_cpu, case_wall = time.process_time_ns(), time.perf_counter_ns()
        slot, fit = row["slot"], row["fit_id"]
        version, task = row["version"], row["task"]
        if (version, task) not in datasets:
            datasets[version, task] = load_planning(packages, version, task, grid)
        data = datasets[version, task]
        train = data["split"]["current_train"]
        if fit not in warmups:
            pin = plan["historical_warmups"][fit]
            directory = workspace/f"pft-run-{version}"/pin["relative_directory"]
            for name, value in pin["files"].items():
                require(sha(directory/name) == value["sha256"] and (directory/name).stat().st_size == value["bytes"],
                    "exact historical complete warmup")
            metadata = read(directory/"manifest.json")
            initial = CellTrainingState.load(directory, metadata["bindings"], metadata["protocol"],
                metadata["contexts"], pin["state_sha256"])
            require(initial.contexts["current_train"] == dataset_digest(*train), "bound original training data")
            warmups[fit] = initial
        initial = warmups[fit]
        current = initial.clone()
        trace = read(sealed(grid, seal, slot+"/trace.json.gz"))
        raw = read(sealed(grid, seal, slot+"/policy-record.json.gz"))
        cuts = read(sealed(grid, seal, slot+"/controller-checkpoints.json.gz"))
        count = row["committed_steps"]
        controller = cuts[str(count)]
        require(controller["contract"]["current_panel_sha256"] == [dataset_digest(*v) for v in data["current_panels"]]
            and controller["contract"]["old_panel_sha256"] == [dataset_digest(*v) for v in data["old_panels"]],
            "all8 exact planning panel identities")
        anchors = panel_losses(initial.head, data["old_panels"])
        require(anchors.tolist() == row["original_old_anchors"], "four original warmup thresholds")
        with np.load(sealed(grid, seal, slot+"/compact.npz"), allow_pickle=False) as arrays:
            actions, terminal = arrays["actions"], arrays["terminal_vector"]
        require(actions.shape == (count, initial.parameter_count)
            and np.all(np.abs(actions) <= row["configuration"]["action_bound"]/np.sqrt(initial.parameter_count)),
            "complete original action prefix within unchanged box")
        require(current.digest() == trace["state_sha256"][0], "exact original warmup")
        for step, action in enumerate(actions):
            receipt = current.advance(*train, intervention=row["configuration"]["dt"]*action)
            require(receipt == trace["receipts"][step] and current.digest() == trace["state_sha256"][step+1],
                "every original receipt and complete optimizer checkpoint replay exactly")
            updates += 1
        require(current.digest() == row["origin_state_sha256"] == raw["terminal_state_sha256"]
            and np.array_equal(current.vector(), terminal) and digest(controller) == row["controller_sha256"],
            "full stopped state and canonical controller preimage")
        losses = panel_losses(current.head, data["old_panels"])
        require(np.all(losses <= anchors), "committed origin still satisfies all original old-panel anchors")
        target = output/slot
        current.save(target/"state")
        (target/"original-stopped-controller.json").write_bytes(canonical(controller))
        (target/"original-last-attempt.json").write_bytes(canonical(raw["steps"][-1])+b"\n")
        restored = CellTrainingState.load(target/"state", initial.bindings, initial.protocol,
            initial.contexts, row["origin_state_sha256"])
        require(np.array_equal(restored.vector(), current.vector()), "all theta/m/v and identity preserved by saved snapshot")
        names = ("state/manifest.json", "state/state.npz", "original-stopped-controller.json", "original-last-attempt.json")
        pins = {name: {"bytes": (target/name).stat().st_size, "sha256": sha(target/name)} for name in names}
        rows.append({key: row[key] for key in ("slot", "fit_id", "version", "task", "head", "seed", "policy",
            "configuration_index", "configuration", "committed_steps", "original_method", "attempted_horizon", "status",
            "origin_state_sha256", "controller_sha256", "contract_sha256", "original_old_anchors",
            "current_panel_sha256", "old_panel_sha256", "training_sha256")})
        rows[-1].update(directory=str(target), files=pins, original_warmup_state_sha256=initial.digest(),
            optimizer_step_count=current.step_count, original_old_panel_losses=losses.tolist(),
            original_maximum_old_panel_excess=float((losses-anchors).max()),
            planning_package=str(packages/f"{version}-{task}"),
            planning_manifest_sha256=sha(packages/f"{version}-{task}"/"manifest.json"),
            original_intended_actions_retained=False,
            original_terminal_controller_status=controller["run_status"],
            replayed_original_updates=count, new_optimizer_actions=0, new_solver_calls=0,
            export_cpu_ns=time.process_time_ns()-case_cpu, export_wall_ns=time.perf_counter_ns()-case_wall)
    require(len(rows) == len({r["slot"] for r in rows}) == 98, "all98 exact distinct origins exported")
    require(sha(grid/"development_seal.json") == SEAL, "original development seal unchanged")
    result = {"schema": "hepta.cell-field-stop-origins.v8-preparation", "status": "PASS",
        "registered_origins": 98, "exported_origins": len(rows), "rows": rows,
        "source_v7b_protocol_sha256": PROTOCOL, "source_v7b_seal_sha256": SEAL,
        "source_v7b_closure_sha256": SOURCE, "source_commit": "147a67868afb68511a5152f7f944fb26df34843b",
        "census_sha256": sha(census_file), "planning_only_index_sha256": PLANNING_INDEX,
        "exporter_sha256": sha(__file__), "census_code_sha256": sha(Path(__file__).with_name("stop_census_v8.py")),
        "planning_loader_sha256": sha(workspace/"pft-audit-v7b-development/export_v7b_planning_only.py"),
        "replayed_original_optimizer_updates": updates, "new_solver_calls": 0, "new_optimizer_actions": 0,
        "selection_label_arrays_loaded": False, "new_confirmation_sources_selected": False,
        "source_selection_changed": False, "scientific_acceptance": False,
        "old_controller_resumable": False, "authority": "DENY_ALL",
        "scope": "exact original stopped physical states for separately frozen diagnostic; no retry of original controllers",
        "original_failed_intended_plan_scope": "raw records retained; actions absent; any deterministic reconstruction is a separately charged diagnostic planner call",
        "environment": {"numpy": np.__version__, "threadpools": threadpool_info()},
        "cpu_ns": time.process_time_ns()-cpu, "wall_ns": time.perf_counter_ns()-began}
    (output/"manifest.json").write_bytes(canonical(result)+b"\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("workspace", "census-file", "output"):
        parser.add_argument("--"+name, required=True)
    result = export(**vars(parser.parse_args()))
    print(json.dumps({key: result[key] for key in ("status", "exported_origins", "replayed_original_optimizer_updates", "new_solver_calls", "cpu_ns", "wall_ns")}))
