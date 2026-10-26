"""Execute the separately frozen posthoc census after the complete V7 seal."""

import argparse
from collections import Counter
import gzip
import hashlib
from itertools import product
import json
from pathlib import Path
import sys
import time

import numpy as np


PROTOCOL_SHA = "75def1fe5a2610f76f5fe02db082bb4f0d01d02f683da0ee500a9af1f7e5e0e6"
BRANCHES = ("full", "loss2", "future_field", "parameter_hold")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else canonical(value)).hexdigest()


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def require(value, message):
    if not value:
        raise ValueError(message)


def read(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), "ordinary input file required")
    with (gzip.open if path.suffix == ".gz" else open)(path, "rb") as stream:
        data = stream.read((32 << 20)+1)
    require(len(data) <= 32 << 20, "bounded JSON input required")
    return json.loads(data)


def write(path, value):
    Path(path).write_bytes(canonical(value)+b"\n")


def verify_seal(grid, expected):
    require(file_hash(grid/"development_seal.json") == expected, "independently pinned development seal required")
    seal = read(grid/"development_seal.json")
    actual = {p.relative_to(grid).as_posix(): p for p in grid.rglob("*") if p.is_file() and p.name != "development_seal.json"}
    require(set(actual) == set(seal["files"]) and seal["protocol_sha256"] == PROTOCOL_SHA, "complete sealed grid census")
    for name, path in actual.items():
        pin = seal["files"][name]
        require(not path.is_symlink() and path.stat().st_size == pin["bytes"] and file_hash(path) == pin["sha256"], "changed sealed file: "+name)
    return seal


def planning_package(workspace, grid, root, pin, version, task, plan):
    from cell_field_state import dataset_digest
    directory = root/f"{version}-{task}"
    require(str(directory) == pin["directory"] and file_hash(directory/"manifest.json") == pin["manifest_sha256"], "planning package manifest")
    manifest, sources = read(directory/"manifest.json"), read(directory/"sources.json")["rows"]
    provenance_path = grid/"inputs"/f"{version}-{task}.json"
    provenance = read(provenance_path)
    require(manifest["version"] == version and manifest["task"] == task
        and manifest["protocol_sha256"] == PROTOCOL_SHA and manifest["selection_labels_included"] is False
        and manifest["frozen_grid_input_provenance_sha256"] == file_hash(provenance_path), "planning-only provenance binding")
    for name, identity in manifest["files"].items():
        require(Path(name).name == name and file_hash(directory/name) == identity["sha256"]
            and (directory/name).stat().st_size == identity["bytes"], "planning payload identity")
    by_index = {row["index"]: row for row in sources}
    require(len(by_index) == len(sources) == len({row["component_id"] for row in sources}) == 1024,
        "exact disjoint planning source census")
    require(all(row["role"] in {"current_train", "current_probe", "current_validation", "old_probe", "old_validation"}
        for row in sources), "selection source entered diagnostic package")
    old_root = workspace/f"pft-run-{version}"
    historical = read(old_root/"pre_evaluation_seal.json")
    require(file_hash(old_root/"pre_evaluation_seal.json") == plan["historical_run_seal_sha256"][version], "historical seal")
    projected_path = f"{task}/projected.npz"
    require(file_hash(old_root/projected_path) == historical["files"][projected_path]["sha256"], "original projected features")
    with np.load(old_root/projected_path, allow_pickle=False) as archive:
        projected = archive["features"]
    names = ["current_train"]+[f"{domain}_panel_{k}" for domain in ("current", "old") for k in range(4)]
    require(set(manifest["contexts"]) == set(names), "nine planning contexts required")
    pairs = {}
    with np.load(directory/"arrays.npz", allow_pickle=False) as archive:
        require(set(archive.files) == {name+"_"+suffix for name in names for suffix in ("x", "y")}, "selection arrays forbidden")
        for name in names:
            x, y = archive[name+"_x"], archive[name+"_y"]
            metadata = manifest["contexts"][name]
            indices = metadata["indices"]
            count = 256 if name == "current_train" else 96
            require(x.shape == (count, 8) and y.shape == (count,) and np.isfinite(x).all()
                and len(indices) == count and dataset_digest(x, y) == metadata["dataset_sha256"]
                and np.array_equal(x, projected[indices]), "exact planning features/labels")
            identity = {"indices": indices, "labels": y.tolist(),
                "source_ids": [by_index[i]["source_id"] for i in indices],
                "component_ids": [by_index[i]["component_id"] for i in indices]}
            expected = (provenance["roles"][name] if name == "current_train" else
                provenance["panels"][name.split("_")[0]][int(name[-1])])
            require(sha(identity) == expected["identity_sha256"], "planning labels/source order differs from frozen grid")
            pairs[name] = x, y
    return pairs["current_train"], [pairs[f"current_panel_{k}"] for k in range(4)], [pairs[f"old_panel_{k}"] for k in range(4)]


def warmup(workspace, plan, fit, version, train):
    from cell_field_state import CellTrainingState, dataset_digest
    pin = plan["historical_warmups"][fit]
    directory = workspace/f"pft-run-{version}"/pin["relative_directory"]
    for name, identity in pin["files"].items():
        require(file_hash(directory/name) == identity["sha256"] and (directory/name).stat().st_size == identity["bytes"], "original warmup changed")
    metadata = read(directory/"manifest.json")
    state = CellTrainingState.load(directory, metadata["bindings"], metadata["protocol"], metadata["contexts"], pin["state_sha256"])
    require(state.contexts[state.active_context] == dataset_digest(*train), "warmup training context differs")
    return state


def reconstruct_origin(directory, warm, train, old, anchors, configuration):
    from cell_field_repair_v7 import panel_losses
    row, trace, record = read(directory/"result.json"), read(directory/"trace.json.gz"), read(directory/"policy-record.json.gz")
    with np.load(directory/"compact.npz", allow_pickle=False) as values:
        actions, terminal = values["actions"], values["terminal_vector"]
    n, p = len(actions), warm.parameter_count
    require(actions.shape == (n, p) and np.isfinite(actions).all() and n < 32
        and n == row["completed_steps"] == record["completed_steps"] and n % 8 == 0
        and len(trace["receipts"]) == n and len(trace["state_sha256"]) == n+1
        and trace["state_sha256"][0] == warm.digest() == record["initial_state_sha256"], "stopped prefix census")
    require(np.all(np.abs(actions) <= configuration["action_bound"]/np.sqrt(p)), "original committed action box")
    state = warm.clone()
    for k, action in enumerate(actions):
        receipt = state.advance(*train, intervention=configuration["dt"]*action)
        require(receipt == trace["receipts"][k] and state.digest() == trace["state_sha256"][k+1], "exact original complete-state prefix replay")
        losses = panel_losses(state.head, old)
        require(np.isfinite(losses).all() and np.all(losses <= anchors), "original committed prefix panel safety")
    require(state.digest() == row["terminal_state_sha256"] == record["terminal_state_sha256"]
        and np.array_equal(state.vector(), terminal), "exact original stopped terminal state")
    return state, {"original_policy_record_sha256": file_hash(directory/"policy-record.json.gz"),
        "original_terminal_controller_sha256": trace["controller_sha256"][-1],
        "original_last_attempt": record["steps"][-1], "original_error": record["error"], "prefix_replayed_updates": n}


def run(workspace, grid, packages, code, output, expected_development_seal_sha256):
    workspace, grid, packages, code, output = map(lambda p: Path(p).resolve(), (workspace, grid, packages, code, output))
    require(output != grid and grid not in output.parents, "diagnostic output must be outside sealed grid")
    freeze = read(Path(__file__).with_name("diagnostic-source-freeze.json"))
    require(freeze["development_seal_sha256"] == expected_development_seal_sha256, "diagnostic names a different sealed grid")
    for name, identity in freeze["sources"].items():
        require(file_hash(Path(__file__).with_name(name)) == identity, "posthoc source/plan changed")
    require(file_hash(packages/"index.json") == freeze["planning_index_sha256"], "planning package index changed")
    seal = verify_seal(grid, expected_development_seal_sha256)
    sources, plan = read(grid/"executed_source.json"), read(grid/"protocol.json")
    require(len(sources) == 103 and sha(sources) == seal["executed_source_sha256"]
        and file_hash(grid/"protocol.json") == PROTOCOL_SHA, "frozen source/protocol closure")
    for name, identity in sources.items():
        require(Path(name).name == name and file_hash(code/name) == identity, "executed source changed")
    sys.path.insert(0, str(code))
    from cell_field_repair_v7 import panel_losses
    from loss2_stop_diagnostic import diagnose_origin
    output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    index = read(packages/"index.json")
    pins = {Path(pin["directory"]).name: pin for pin in index["packages"]}
    data, warms = {}, {}
    for version, task in product(plan["versions"], plan["tasks"]):
        data[version, task] = planning_package(workspace, grid, packages, pins[f"{version}-{task}"], version, task, plan)
        for head, seed in product(plan["head_modes"], plan["seeds"]):
            fit = f"{version}-{task}-seed{seed}-{head}"
            warms[fit] = warmup(workspace, plan, fit, version, data[version, task][0])
    table = []
    for item in plan["configurations"]:
        configuration, number = item["configuration"], item["index"]
        for version, task, head, seed in product(plan["versions"], plan["tasks"], plan["head_modes"], plan["seeds"]):
            fit = f"{version}-{task}-seed{seed}-{head}"
            directory = grid/f"config{number:02d}"/fit/"loss2_h8"
            original = read(directory/"result.json")
            require(all(original[k] == v for k, v in {"version": version, "task": task, "head": head,
                "seed": seed, "fit_id": fit, "policy": "loss2_h8"}.items()), "original slot identity differs")
            row = {"configuration_index": number, "fit_id": fit, "original_status": original["status"],
                "original_completed_steps": original["completed_steps"], "original_errors": original["error"],
                "original_result_sha256": file_hash(directory/"result.json"), "diagnostic_status": "not_stopped"}
            if original["status"] == "completed":
                require(original["completed_steps"] == 32, "completed slot has wrong clock")
                table.append(row); continue
            destination = output/f"config{number:02d}"/fit
            destination.mkdir(parents=True)
            try:
                train, current, old = data[version, task]
                warm = warms[fit]
                anchors = panel_losses(warm.head, old)
                origin, binding = reconstruct_origin(directory, warm, train, old, anchors, configuration)
                result = diagnose_origin(origin, train, current, old, anchors, configuration)
                result["record"].update(binding, original_slot=row)
                np.savez_compressed(destination/"arrays.npz", **result["arrays"])
                write(destination/"diagnostic.json", result["record"])
                row.update(diagnostic_status="executed", initial_state_sha256=origin.digest(),
                    branches={name: result["record"]["branches"][name]["status"] for name in BRANCHES},
                    full_actual_safe_witness=result["record"]["full_actual_safe_witness"],
                    hold_actual_safe_witness=result["record"]["hold_actual_safe_witness"])
            except Exception as error:
                row.update(diagnostic_status="unavailable_origin_or_diagnostic", error={"type": type(error).__name__, "message": str(error)},
                    branches={name: "unavailable" for name in BRANCHES})
                write(destination/"unavailable.json", row)
            table.append(row)
        print(json.dumps({"configuration": number, "slots_checked": len(table), "diagnosed": sum(r["diagnostic_status"] == "executed" for r in table)}), flush=True)
    require(len(table) == 288, "all288 original Loss2 slots must remain in the census")
    verify_seal(grid, expected_development_seal_sha256)
    require(all(file_hash(code/name) == identity for name, identity in sources.items()), "executed source changed during diagnostic")
    write(output/"case-table.json", table)
    report = {"schema": "hepta.loss2-stop-diagnostic-census.v7", "registered_loss2_slots": 288,
        "original_statuses": dict(Counter(row["original_status"] for row in table)),
        "diagnostic_statuses": dict(Counter(row["diagnostic_status"] for row in table)),
        "stopped_slots": sum(row["diagnostic_status"] != "not_stopped" for row in table),
        "full_actual_safe_witnesses": sum(row.get("full_actual_safe_witness", False) for row in table),
        "hold_actual_safe_witnesses": sum(row.get("hold_actual_safe_witness", False) for row in table),
        "branch_statuses": {name: dict(Counter(row["branches"][name] for row in table if "branches" in row)) for name in BRANCHES},
        "case_table_sha256": file_hash(output/"case-table.json"), "source_freeze_sha256": file_hash(Path(__file__).with_name("diagnostic-source-freeze.json")),
        "development_seal_sha256": expected_development_seal_sha256, "development_source_sha256": sha(sources),
        "cpu_ns": time.process_time_ns()-cpu, "wall_ns": time.perf_counter_ns()-started,
        "selection_labels_used": False, "primary_selection_changed": False, "scientific_acceptance": False,
        "global_nonlinear_infeasibility_claimed": False}
    write(output/"report.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("workspace", "grid", "packages", "code", "output", "expected-development-seal-sha256"):
        parser.add_argument("--"+name, required=True)
    print(json.dumps(run(**vars(parser.parse_args()))))
