"""Reproduce the original29 box-validation errors without modifying that run."""

from pathlib import Path
import sys
import time
from unittest.mock import patch

import numpy as np

from run_loss2_stop_diagnostic import file_hash, planning_package, read, require, sha, verify_seal, warmup, write


def execute(workspace, output):
    workspace, output = Path(workspace), Path(output)
    grid, packages = workspace/"pft-development-v7/grid", workspace/"pft-development-v7/planning-only"
    code = workspace/"hepta-repo/qa/stem-bakeoff"
    seal_sha = "c590a7487d1a6f229d7d03f14f03f3141e23b529a531cdd37978ef568818082d"
    verify_seal(grid, seal_sha)
    sources, plan = read(grid/"executed_source.json"), read(grid/"protocol.json")
    require(len(sources) == 103 and all(file_hash(code/name) == value for name, value in sources.items()), "original103 sources required")
    sys.path.insert(0, str(code))
    import cell_field_planner_v7 as planner
    from cell_field_controller_v7 import POLICIES
    from cell_field_repair_v7 import panel_losses, repair_sequence
    pins = {Path(row["directory"]).name: row for row in read(packages/"index.json")["packages"]}
    cases = []
    for path in sorted(grid.glob("config*/*/*/result.json")):
        header = read(path)
        if "finite intended H-by-p actions already inside the declared box required" in str(header.get("error")):
            cases.append((path.parent, header))
    require(len(cases) == 29, "all29 original box-validation error slots required")
    cpu, wall = time.process_time_ns(), time.perf_counter_ns()
    data, rows = {}, []
    for directory, header in cases:
        version, task, fit = header["version"], header["task"], header["fit_id"]
        key = version, task
        if key not in data:
            data[key] = planning_package(workspace, grid, packages, pins[f"{version}-{task}"], version, task, plan)
        train, current, old = data[key]
        state = warmup(workspace, plan, fit, version, train)
        anchors = panel_losses(state.head, old)
        configuration_index = int(directory.parents[1].name.removeprefix("config"))
        config = plan["configurations"][configuration_index]["configuration"]
        trace = read(directory/"trace.json.gz")
        with np.load(directory/"compact.npz", allow_pickle=False) as saved:
            actions, terminal = saved["actions"], saved["terminal_vector"]
        require(state.digest() == trace["state_sha256"][0], "original warmup identity")
        for k, action in enumerate(actions):
            require(state.advance(*train, intervention=config["dt"]*action) == trace["receipts"][k]
                and state.digest() == trace["state_sha256"][k+1], "original full-state prefix")
        require(state.digest() == header["terminal_state_sha256"] and np.array_equal(state.vector(), terminal), "original failure origin")
        original_solver, calls = planner.solve_terminal, []
        def capture(*args, **kwargs):
            solved = original_solver(*args, **kwargs)
            calls.append({"nominal": np.asarray(args[3]).copy(),
                "proposal": None if solved["actions"] is None else solved["actions"].copy(),
                "status": solved["record"]["status"]})
            return solved
        method, horizon = POLICIES[header["policy"]]
        with patch.object(planner, "solve_terminal", side_effect=capture):
            result = planner.make_plan(state, train, current+old, anchors, method=method, horizon=horizon,
                **{k: config[k] for k in ("dt", "effort_price", "action_bound", "old_weight", "current_dispersion", "relinearizations")})
        require(result["record"]["status"] == "qualified", "failed physical plan no longer reproduces qualified proposal")
        selected = calls[result["record"]["selected_proposal_iteration"]]
        fraction = result["record"]["selected_fraction"]
        nominal, proposal = selected["nominal"], selected["proposal"]
        interpolated = nominal+fraction*(proposal-nominal)
        require(np.array_equal(interpolated, result["actions"]), "selected floating interpolation differs")
        bound = config["action_bound"]/np.sqrt(state.parameter_count)
        offending = np.argwhere(np.abs(interpolated) > bound)
        require(len(offending) > 0 and np.all(np.abs(proposal) <= bound), "original clipped proposal versus interpolation spill not reproduced")
        caught = None
        try:
            repair_sequence(state, train, old, result["actions"], anchors, horizon=horizon,
                dt=config["dt"], action_bound=config["action_bound"])
        except ValueError as error:
            caught = str(error)
        require(caught == "finite intended H-by-p actions already inside the declared box required", "original validation error not reproduced")
        coordinates = []
        for k, j in offending:
            value = float(interpolated[k, j])
            coordinates.append({"step": int(k), "parameter": int(j), "bound_hex": float(bound).hex(),
                "nominal_hex": float(nominal[k, j]).hex(), "qp_proposal_hex": float(proposal[k, j]).hex(),
                "selected_hex": value.hex(), "absolute_excess": abs(value)-float(bound),
                "ulp_distance_outside": int(np.float64(abs(value)).view(np.int64)-np.float64(bound).view(np.int64))})
        bounded = proposal.copy() if fraction == 1. else np.clip(interpolated, -bound, bound)
        rows.append({"original_result": directory.relative_to(grid).as_posix()+"/result.json",
            "original_result_sha256": file_hash(directory/"result.json"), "origin_state_sha256": state.digest(),
            "configuration_index": configuration_index, "fit_id": fit, "policy": header["policy"],
            "original_completed_steps": len(actions), "selected_fraction": fraction,
            "qp_proposal_within_box": True, "original_error_reproduced": caught,
            "offending_coordinates": coordinates, "endpoint_copy_or_bounded_interpolation_within_box": bool(np.all(np.abs(bounded) <= bound)),
            "maximum_rounding_correction": float(np.max(np.abs(bounded-interpolated)))})
    require(file_hash(grid/"development_seal.json") == seal_sha
        and all(file_hash(code/name) == value for name, value in sources.items()), "original source/seal changed")
    report = {"schema": "hepta.original-v7-action-rounding-reproduction", "cases": rows,
        "original_cases": 29, "reproduced": len(rows), "script_sha256": file_hash(__file__),
        "development_seal_sha256": seal_sha, "source_closure_sha256": sha(sources),
        "cpu_ns": time.process_time_ns()-cpu, "wall_ns": time.perf_counter_ns()-wall,
        "scope": "same-state frozen planner reproduction; bounded arithmetic correction demonstrated only, no primary policy or outcome changed",
        "selection_labels_used": False, "primary_run_modified": False, "scientific_acceptance": False}
    require(not output.exists(), "reproduction output must be new")
    write(output, report)
    return report


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--output", required=True)
    result = execute(**vars(parser.parse_args()))
    print({"reproduced": result["reproduced"], "cpu_ns": result["cpu_ns"]})
