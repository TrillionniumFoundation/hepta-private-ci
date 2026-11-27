"""All24 warmups by four fixed commit-one controllers; planning data only.

A new externally pinned FROZEN protocol is mandatory. The control process
cannot read historical selection labels; a separately invoked DEV scorer may
read them only after the complete96-slot trace inventory is sealed.
"""

import argparse
from collections import Counter
from itertools import product
import json
import os
from pathlib import Path
import platform
import time

import numpy as np

from cell_field_common_run_v8 import (AXES, SOURCE_REQUIRED, file_hash, load_planning,
    load_warmup, read, require, sha, verify_sources, write)
from cell_field_terminal_v8 import METHODS


REQUIRED = SOURCE_REQUIRED | {"cell_field_terminal_v8.py", "cell_field_remaining_v8.py",
    "cell_field_remaining_run_v8.py", "cell_field_repair_v7.py", "cell_field_safety_v8.py",
    "cell_field_joint_search_v8.py", "cell_field_safety_portfolio_v8.py"}
MECHANISM = {"steps": 32, "commit_stride": 1, "dt": .02, "effort_price": .03,
    "action_bound": 4., "current_mean_weight": 1., "old_mean_weight": .25,
    "current_dispersion_weight": 0., "free_actions_per_proposal": 1,
    "nominal_continuation": "zero_control", "safety_filter": "fixed_old_first_portfolio"}


def frozen_plan(path, expected):
    require(file_hash(path) == expected, "protocol byte identity differs")
    plan = read(path)
    require(plan["status"] == "FROZEN" and plan["schema"] == "hepta.remaining-terminal-study.v8"
        and all(plan[k] == v for k, v in AXES.items()) and plan["methods"] == list(METHODS)
        and plan["mechanism"] == MECHANISM and plan["registered_fits"] == 24
        and plan["registered_outputs"] == 96 and plan["scientific_acceptance"] is False
        and plan["production_authority"] is False and plan["new_sources_accessed"] is False
        and plan["control_selection_labels_accessed"] is False
        and plan["post_seal_historical_development_scoring"] is True,
        "fixed planning-only control and separate historical DEV scoring must be frozen")
    return plan


def write_trace(directory, result):
    """Persist complete available prefixes, including terminal preimages at stops."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    record, states, plans = result["record"], result["states"], result["plans"]
    n, p = len(result["actions"]), result["state"].parameter_count
    require(len(states) == n+1 and record["completed_steps"] == n
        and states[-1].digest() == record["terminal_state_sha256"], "complete retained physical prefix required")
    np.savez_compressed(directory/"trajectory.npz", states=np.asarray([s.vector() for s in states]),
        actions=result["actions"], old_losses=result["old_losses"])
    np.savez_compressed(directory/"plans.npz",
        proposed_actions=np.asarray([v["action"] for v in plans]).reshape(-1, p),
        first_action_maps=np.asarray([v["first_action_map"] for v in plans]).reshape(-1, 8, p),
        reference_terminal_states=np.asarray([v["reference_terminal_state"] for v in plans]).reshape(-1, 3*p),
        reference_terminal_panels=np.asarray([v["reference_terminal_panels"] for v in plans]).reshape(-1, 8),
        initial_field_observations=np.asarray([v["initial_field_observation"] for v in plans
            if v["initial_field_observation"] is not None]).reshape(-1, 8, 3*p))
    cuts = sorted({k for k in (0, 16, 17, 32, n) if k <= n})
    for cut in cuts:
        states[cut].save(directory/"checkpoints"/str(cut))
    record.update(checkpoint_cuts=cuts, terminal_checkpoint="checkpoints/"+str(n),
        retained_prefix_available=True, saved_plan_count=len(plans))
    write(directory/"result.json", record)


def execute_one(directory, warmup, train, panels, anchors, method, protocol_sha, source_sha):
    from cell_field_remaining_v8 import execute_remaining
    began, wall = time.process_time_ns(), time.perf_counter_ns()
    try:
        result = execute_remaining(warmup, train, panels[:4], panels[4:], anchors, method,
            controller_protocol_sha256=protocol_sha, controller_source_sha256=source_sha)
    except Exception as error:
        record = {"schema": "hepta.remaining-terminal-policy-error.v8", "method": method,
            "status": "actual_error", "error": {"type": type(error).__name__, "message": str(error)},
            "completed_steps": None, "retained_prefix_available": False,
            "scientific_acceptance": False, "production_authority": False}
        result = None
    policy_cpu, policy_wall = time.process_time_ns()-began, time.perf_counter_ns()-wall
    if result is not None:
        record = result["record"]
    record.update(policy_call_cpu_ns=policy_cpu, policy_call_wall_ns=policy_wall)
    # Persistence failures abort without a completion seal. Do not convert disk
    # exhaustion into a scientific model failure or claim a lost prefix replay.
    if result is not None:
        write_trace(directory, result)
    else:
        directory.mkdir(parents=True, exist_ok=False)
        write(directory/"result.json", record)
    return record


def parity(directory, methods):
    full, field = (methods[name] for name in ("full_adjoint_remaining", "terminal_field8_remaining"))
    row = {"complete": all(r["status"] == "completed" and r["completed_steps"] == 32 for r in (full, field)),
        "full_status": full["status"], "field_status": field["status"], "passed": False}
    if all(r.get("retained_prefix_available") for r in (full, field)):
        with np.load(directory/"full_adjoint_remaining/trajectory.npz", allow_pickle=False) as a, \
                np.load(directory/"terminal_field8_remaining/trajectory.npz", allow_pickle=False) as b:
            same_shape = all(a[k].shape == b[k].shape for k in ("states", "actions", "old_losses"))
            row["same_available_prefix_length"] = same_shape
            if same_shape:
                row.update({"max_"+k+"_difference": float(np.max(np.abs(a[k]-b[k]), initial=0.))
                    for k in ("states", "actions", "old_losses")})
                row["same_available_prefix_within_1e_10"] = all(row["max_"+k+"_difference"] <= 1e-10
                    for k in ("states", "actions", "old_losses"))
                row["passed"] = row["complete"] and row["same_available_prefix_within_1e_10"]
    return row


def run(protocol, protocol_sha256, source_manifest, source_sha256, source_commit, workspace, grid, planning, output):
    import scipy
    from threadpoolctl import threadpool_info
    from cell_field_repair_v7 import panel_losses
    preparation_cpu, preparation_wall = time.process_time_ns(), time.perf_counter_ns()
    code = Path(__file__).resolve().parent
    protocol, source_manifest, workspace, grid, planning, output = map(lambda p: Path(p).resolve(),
        (protocol, source_manifest, workspace, grid, planning, output))
    plan, sources = frozen_plan(protocol, protocol_sha256), read(source_manifest)
    require(REQUIRED <= set(sources), "all actual proposal/safety/runtime dependencies must be frozen")
    verify_sources(code, sources, source_sha256)
    require(len(source_commit) == 40 and all(c in "0123456789abcdef" for c in source_commit), "host-pinned Git source required")
    require(not output.exists() and all(p != output and p not in output.parents for p in
        (grid, planning, code, workspace/"pft-run-v5", workspace/"pft-run-v6")), "fresh separate control output required")
    runtime = {"python": platform.python_version(), "numpy": np.__version__, "scipy": scipy.__version__,
        "threadpools": threadpool_info(), "platform": platform.platform(),
        "threads": {k: os.environ.get(k) for k in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS")}}
    require(runtime["threads"] == {"OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1"}
        and all(p["num_threads"] == 1 for p in runtime["threadpools"]), "actual single-thread numerical runtime required")
    pins = plan["base_inputs"]
    for path, key in ((grid/"protocol.json", "protocol_sha256"), (grid/"development_seal.json", "seal_sha256"),
                      (planning/"index.json", "planning_index_sha256")):
        require(file_hash(path) == pins[key], "base input identity changed")
    seal, base, index = read(grid/"development_seal.json"), read(grid/"protocol.json"), read(planning/"index.json")
    require(seal["protocol_sha256"] == index["protocol_sha256"] == pins["protocol_sha256"]
        and index["development_seal_sha256"] == pins["seal_sha256"]
        and sha(read(grid/"executed_source.json")) == seal["executed_source_sha256"]
        == index["executed_source_sha256"] == pins["executed_source_sha256"] and len(index["packages"]) == 4,
        "base source, planning packages and original seal differ")
    fits = [(v, t, h, s, f"{v}-{t}-seed{s}-{h}") for v, t, h, s
        in product(*(AXES[k] for k in ("versions", "tasks", "head_modes", "seeds")))]
    require(set(base["historical_warmups"]) == {f[-1] for f in fits}, "all24 original warmups required")
    inputs = {(v, t): load_planning(planning, grid, index, v, t, pins["protocol_sha256"])
        for v, t in product(AXES["versions"], AXES["tasks"])}
    warmups = {fit: load_warmup(workspace, base, fit, v, inputs[v, t][0]) for v, t, h, s, fit in fits}
    require(all(state.step_count == 64 for state, pin in warmups.values()), "original64-step warmups required")
    preparation = {"cpu_ns": time.process_time_ns()-preparation_cpu,
        "wall_ns": time.perf_counter_ns()-preparation_wall,
        "scope": "protocol/source/runtime checks, four planning packages and all24 pinned original warmups; outside per-policy costs"}
    started, wall, rows, parities = time.process_time_ns(), time.perf_counter_ns(), [], []
    output.mkdir(parents=True, exist_ok=False)
    (output/"protocol.json").write_bytes(protocol.read_bytes())
    write(output/"executed_source.json", sources)
    for ordinal, (v, t, h, s, fit) in enumerate(fits):
        train, panels, manifest = inputs[v, t]
        state, pin = warmups[fit]
        directory = output/fit
        directory.mkdir()
        anchors = panel_losses(state.head, panels[4:])
        methods, rotation = {}, ordinal % len(METHODS)
        order = METHODS[rotation:]+METHODS[:rotation]
        write(directory/"inputs.json", {"fit": fit, "warmup": pin, "method_order": order,
            "planning_manifest_canonical_sha256": sha(manifest), "original_old_anchors": anchors.tolist()})
        for method in order:
            methods[method] = execute_one(directory/method, state, train, panels, anchors,
                method, protocol_sha256, source_sha256)
            record = methods[method]
            rows.append({"fit": fit, "version": v, "task": t, "head": h, "seed": s, "method": method,
                **{key: record.get(key) for key in ("status", "error", "completed_steps", "common_J32",
                    "parameter_action_penalty", "policy_call_cpu_ns", "policy_call_wall_ns", "terminal_state_sha256")},
                "result_sha256": file_hash(directory/method/"result.json")})
        parities.append({"fit": fit, **parity(directory, methods)})
    require(len(rows) == 96 and len({(r["fit"], r["method"]) for r in rows}) == 96, "complete96 output census required")
    verify_sources(code, sources, source_sha256)
    require(file_hash(protocol) == protocol_sha256 and file_hash(grid/"development_seal.json") == pins["seal_sha256"]
        and file_hash(grid/"protocol.json") == pins["protocol_sha256"]
        and file_hash(planning/"index.json") == pins["planning_index_sha256"], "execution inputs changed")
    for v, t in product(AXES["versions"], AXES["tasks"]):
        load_planning(planning, grid, index, v, t, pins["protocol_sha256"])
    for v, t, h, s, fit in fits:
        load_warmup(workspace, base, fit, v, inputs[v, t][0])
    report = {"schema": "hepta.remaining-terminal-control-results.v8", "protocol_sha256": protocol_sha256,
        "source_sha256": source_sha256, "source_commit": source_commit, "runtime": runtime, "base_inputs": pins,
        "fits": 24, "output_slots": 96, "status_counts": dict(Counter(r["status"] for r in rows)),
        "rows": rows, "full_field_parities": parities, "common_input_preparation": preparation,
        "cpu_ns": time.process_time_ns()-started,
        "wall_ns": time.perf_counter_ns()-wall, "selection_labels_accessed": False,
        "new_sources_accessed": False, "scientific_acceptance": False, "production_authority": False,
        "cost_scope": "per-policy full caller interval excludes common input preparation and disk/DEV scoring; runner total includes loop IO/checks but ends before final report/seal write",
        "scope": "fixed development study, full96 census; shared empirical old filter; H1 proposal is explicitly myopic"}
    write(output/"report.json", report)
    inventory = {p.relative_to(output).as_posix(): {"sha256": file_hash(p), "bytes": p.stat().st_size}
        for p in sorted(output.rglob("*")) if p.is_file()}
    write(output/"control_seal.json", {"protocol_sha256": protocol_sha256, "source_sha256": source_sha256,
        "files": inventory, "scope": "local complete-control integrity commitment before historical DEV scoring"})
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("protocol", "protocol-sha256", "source-manifest", "source-sha256", "source-commit",
                "workspace", "grid", "planning", "output"):
        parser.add_argument("--"+key, required=True)
    result = run(**vars(parser.parse_args()))
    print(json.dumps({k: result[k] for k in ("fits", "output_slots", "status_counts")}, sort_keys=True))
