"""Bounded, separately costed recovery of all missing sealed V7 terminal bytes."""

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

import numpy as np

from audit_v7_development import PROTOCOL, SOURCE_COMMIT, validate_seal, validate_sources
from v7_audit_records import canonical, digest, file_hash, pair_hash, read, require
from v7_recover_controller import recover_case


PLANNING_INDEX_SHA = "d902e815601c963199ac9f8a3f6ca54864884d42a021b3466f573fdcab0d0b7d"


def load_planning(packages, version, task, grid):
    path = packages/f"{version}-{task}"
    manifest = read(path/"manifest.json")
    require(manifest["protocol_sha256"] == PROTOCOL and manifest["selection_labels_included"] is False
        and manifest["version"] == version and manifest["task"] == task
        and file_hash(grid/"inputs"/f"{version}-{task}.json") == manifest["frozen_grid_input_provenance_sha256"],
        "planning-only inputs bound to frozen execution provenance")
    for name, pin in manifest["files"].items():
        require((path/name).stat().st_size == pin["bytes"] and file_hash(path/name) == pin["sha256"], "planning package bytes")
    names = ["current_train"]+[f"{role}_panel_{index}" for role in ("current", "old") for index in range(4)]
    with np.load(path/"arrays.npz", allow_pickle=False) as data:
        require(set(data.files) == {name+suffix for name in names for suffix in ("_x", "_y")}, "no selection arrays in recovery inputs")
        pairs = {name: (data[name+"_x"], data[name+"_y"]) for name in names}
    indices = []
    for name, pair in pairs.items():
        rows = 256 if name == "current_train" else 96
        pin = manifest["contexts"][name]
        require(pair[0].shape == (rows, 8) and pair[1].shape == (rows,)
            and pair_hash(pair) == pin["dataset_sha256"] and pin["rows"] == rows,
            "exact declared fitting/planning context")
        indices.extend(pin["indices"])
    require(len(indices) == len(set(indices)) == 1024, "all fitting and planning rows disjoint")
    return {"split": {"current_train": pairs["current_train"]},
        "current_panels": [pairs[f"current_panel_{index}"] for index in range(4)],
        "old_panels": [pairs[f"old_panel_{index}"] for index in range(4)]}


def recover(workspace, grid, audit_report, packages, output):
    workspace, grid, audit_report, packages, output = map(Path, (workspace, grid, audit_report, packages, output))
    cpu, wall = time.process_time_ns(), time.perf_counter_ns()
    code_paths = [Path(__file__), Path(__file__).with_name("v7_recover_controller.py"),
        Path(__file__).with_name("test_v7_recover_controller.py")]
    code = {path.name: file_hash(path) for path in code_paths}
    seal, source_sha = validate_seal(grid), validate_sources(workspace, grid)
    seal_sha = file_hash(grid/"development_seal.json")
    audit = read(audit_report)
    require(audit["status"] == "PASS" and audit["development_seal_sha256"] == seal_sha
        and audit["executed_source_sha256"] == source_sha and audit["primary_records"] == 864,
        "completed original recorded-action audit required before preimage recovery")
    census_path = audit_report.with_name("case-census.json")
    require(file_hash(census_path) == audit["case_census_sha256"], "independent complete case census")
    census = read(census_path)
    require(len(census) == 864, "all primary slots retained")
    missing = [row for row in census if not row["terminal_controller_preimage_available"]]
    require(len(missing) == audit["terminal_controller_preimages_unavailable"], "registered recovery scope")
    require(file_hash(packages/"index.json") == PLANNING_INDEX_SHA, "prior planning-only package index")
    index = read(packages/"index.json")
    for package in index["packages"]:
        path = packages/Path(package["directory"]).name/"manifest.json"
        require(file_hash(path) == package["manifest_sha256"], "original planning-only manifest")
    sys.path.insert(0, str(workspace/"hepta-repo/qa/stem-bakeoff"))
    from cell_field_state import CellTrainingState
    plan = read(grid/"protocol.json")
    inputs, states, rows = {}, {}, []
    output.mkdir(parents=True, exist_ok=False)
    for number, item in enumerate(missing):
        identity, policy, config_index = item["fit_id"], item["policy"], item["index"]
        header_path = grid/f"config{config_index:02d}"/identity/policy/"result.json"
        header = read(header_path)
        version, task = header["version"], header["task"]
        if (version, task) not in inputs:
            inputs[version, task] = load_planning(packages, version, task, grid)
        if identity not in states:
            pin = plan["historical_warmups"][identity]
            path = workspace/f"pft-run-{version}"/pin["relative_directory"]
            for name, value in pin["files"].items():
                require(file_hash(path/name) == value["sha256"] and (path/name).stat().st_size == value["bytes"], "original pinned warmup bytes")
            metadata = read(path/"manifest.json")
            require(metadata["contexts"]["current_train"] == pair_hash(inputs[version, task]["split"]["current_train"]), "original current Adam context")
            states[identity] = CellTrainingState.load(path, metadata["bindings"], metadata["protocol"],
                metadata["contexts"], pin["state_sha256"])
        configuration = plan["configurations"][config_index]["configuration"]
        row = recover_case(header_path.parent, states[identity], inputs[version, task], configuration,
            policy, PROTOCOL, source_sha, output/f"config{config_index:02d}"/identity/policy)
        rows.append({"configuration_index": config_index, "fit_id": identity, "policy": policy, **row})
        if (number+1) % 12 == 0:
            print(json.dumps({"attempted": number+1, "registered": len(missing),
                "recovered": sum(r["status"] == "recovered_exact_original_preimage" for r in rows)}), flush=True)
    require(file_hash(grid/"development_seal.json") == seal_sha, "original grid seal unchanged")
    validate_seal(grid)
    require(validate_sources(workspace, grid) == source_sha, "all103 original sources unchanged")
    require({path.name: file_hash(path) for path in code_paths} == code, "post-run recovery source unchanged")
    recovered = sum(row["status"] == "recovered_exact_original_preimage" for row in rows)
    report = {"schema": "hepta.cell-field-exact-terminal-preimage-recovery.v7",
        "status": "PASS" if recovered == len(missing) else "PARTIAL_UNRESOLVED",
        "protocol_sha256": PROTOCOL, "executed_source_commit": SOURCE_COMMIT,
        "executed_source_sha256": source_sha, "development_seal_sha256": seal_sha,
        "recorded_action_audit_sha256": file_hash(audit_report), "planning_only_index_sha256": PLANNING_INDEX_SHA,
        "post_run_recovery_sources": code, "original_preimages_available": 864-len(missing),
        "missing_preimages_registered": len(missing), "exact_preimages_recovered": recovered,
        "unresolved_preimages": len(missing)-recovered,
        "methods": dict(Counter(row["method"] for row in rows if row["status"] == "recovered_exact_original_preimage")),
        "extra_planner_calls": sum(row["planner_calls"] for row in rows),
        "extra_planner_cpu_ns": sum(row["planner_cpu_ns"] for row in rows),
        "extra_planner_wall_ns": sum(row["planner_wall_ns"] for row in rows),
        "cpu_ns": time.process_time_ns()-cpu, "wall_ns": time.perf_counter_ns()-wall,
        "rows": rows, "selection_labels_used": False, "primary_selection_changed": False,
        "primary_costs_replaced": False, "scientific_acceptance": False,
        "scope": "exact stopped-controller preimage recovery only; regenerated intended plans at committed origins are never new policy outcomes; stopped snapshots remain inadmissible for continuation",
        "completed_at": datetime.now(timezone.utc).isoformat()}
    (output/"recovery.json").write_bytes(canonical(report)+b"\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("workspace", "grid", "audit-report", "packages", "output"):
        parser.add_argument("--"+name, required=True)
    result = recover(**vars(parser.parse_args()))
    print(json.dumps({key: result[key] for key in ("status", "missing_preimages_registered",
        "exact_preimages_recovered", "unresolved_preimages", "methods", "extra_planner_calls", "cpu_ns", "wall_ns")}))
