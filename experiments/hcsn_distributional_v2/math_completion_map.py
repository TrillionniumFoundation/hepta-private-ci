"""Export immutable evidence links, independent generators and raw MC replay.

The original failed and successful audit files are never overwritten. Monte
Carlo samples are replayed with the saved seeds through the unchanged audit
function; a return-frame observer captures its existing trial outcomes without
changing the simulation. Replayed counts must match the original saved means.
"""

import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np
import torch

from . import risk_independent_audit as risk_audit


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def main():
    start = time.perf_counter()
    directory = Path(__file__).resolve().parent
    repo = directory.parent.parent
    root = directory / "results"
    failed_dir = root / "sixstage_20261030_math"
    stable_dir = root / "sixstage_20261030_stable_probability"
    risk_dir = root / "sixstage_20261030_risk_independent"
    output = failed_dir / "completion_export"
    output.mkdir(exist_ok=False)
    failed, stable, risk = [read(p / "RESULTS.json") for p in (failed_dir, stable_dir, risk_dir)]
    replay = read(failed_dir / "kernel_replay" / "RESULTS.json")
    registration = read(risk_dir / "REGISTRATION.json")
    source_path = Path(risk_audit.__file__)
    source_hash = risk["source_sha256"][str(source_path)]
    if digest(source_path) != source_hash:
        raise ValueError("Monte Carlo source changed since the saved independent audit")
    registered = dict(schema="hcsn-math-evidence-export-registration.v1",
                      source_sha256=digest(Path(__file__)), source_risk_audit_sha256=source_hash,
                      action="Replay original five 30000-trial seeds and capture existing per-trial outcomes",
                      original_results_overwritten=False, replay_counts_must_match=True)
    (output / "REGISTRATION.json").write_text(json.dumps(registered, indent=2) + "\n")
    arrays, mc_records = {}, []
    for case in registration["cases"]:
        grid = risk_audit.make_grid(case["phases"])
        for dtype, name in ((np.float32, "float32"), (np.float64, "float64")):
            parameters = [float(dtype(v)) for v in case["parameters"]]
            old, dt = float(dtype(case["old_boundary"])), float(dtype(case["duration"]))
            killed, full, event, destination = risk_audit.independent_killed(parameters, grid)
            prefix = case["name"] + "_" + name
            arrays[prefix + "_parameters"] = np.r_[parameters, old, dt]
            arrays[prefix + "_full_column_generator"] = full
            arrays[prefix + "_killed_column_generator"] = killed
            arrays[prefix + "_marked_event_intensity"] = event
            arrays[prefix + "_marked_reset_destination"] = destination
            arrays[prefix + "_survival_remap_row"] = risk_audit.independent_survival_remap(old, parameters, grid)
            arrays[prefix + "_dense_survival_transition_row"] = risk_audit.dense_operator(parameters, grid, old, dt)
    for row in risk["records"]["dense_and_monte_carlo"]:
        if "monte_carlo" not in row:
            continue
        index = next(i for i, case in enumerate(registration["cases"]) if case["name"] == row["case"])
        case = registration["cases"][index]
        grid = risk_audit.make_grid(case["phases"])
        p = np.random.default_rng(registration["monte_carlo_seed"] + index).dirichlet(np.ones(8 + case["phases"]))
        if case["name"] == "self_reset":
            p = np.eye(8)[-1]
        capture = {}

        def observer(frame, event, argument):
            if event == "return" and frame.f_code is risk_audit.monte_carlo_first_event.__code__:
                capture["first"] = frame.f_locals["first"].copy()
                capture["times"] = frame.f_locals["times"].copy()

        previous = sys.getprofile()
        try:
            sys.setprofile(observer)
            replayed = risk_audit.monte_carlo_first_event(case["parameters"], grid,
                case["old_boundary"], case["duration"], p, row["monte_carlo"]["seed"])
        finally:
            sys.setprofile(previous)
        first = capture["first"]
        successes = int(np.count_nonzero(first))
        original_successes = int(round(row["monte_carlo"]["risk"] * row["monte_carlo"]["samples"]))
        if successes != original_successes or replayed["risk"] != row["monte_carlo"]["risk"]:
            raise ValueError("Raw Monte Carlo replay differs from saved evidence: " + case["name"])
        arrays[case["name"] + "_mc_first_event_indicator"] = first
        arrays[case["name"] + "_mc_event_time_or_censoring_time"] = np.where(first, capture["times"], case["duration"])
        arrays[case["name"] + "_mc_initial_probability"] = p
        mc_records.append(dict(case=case["name"], seed=row["monte_carlo"]["seed"],
            trials=len(first), first_event_count=successes, no_event_count=len(first) - successes,
            saved_probability=row["monte_carlo"]["risk"], replayed_probability=replayed["risk"],
            exact_saved_count_reproduced=True, simulated_physical_transitions=replayed["simulated_physical_transitions"],
            raw_indicator_key=case["name"] + "_mc_first_event_indicator",
            event_or_censoring_time_key=case["name"] + "_mc_event_time_or_censoring_time"))
    raw_path = output / "independent_generators_and_raw_mc.npz"
    np.savez_compressed(raw_path, **arrays)
    (output / "MONTE_CARLO_COUNTS.json").write_text(json.dumps(dict(schema="hcsn-raw-mc-counts.v1", records=mc_records), indent=2) + "\n")
    long_rows = [row for row in stable["records"].values() if "snapshots" in row]
    float32_rows = [row["snapshots"][-1] for row in long_rows if row["dtype"] == "float32"]
    float64_rows = [row["snapshots"][-1] for row in long_rows if row["dtype"] == "float64"]
    inventory = []
    for result_dir in (failed_dir, stable_dir, risk_dir):
        for path in sorted(result_dir.rglob("*")):
            if path.is_file():
                inventory.append(dict(path=str(path.relative_to(repo)), bytes=path.stat().st_size, sha256=digest(path)))
    source_inventory = []
    for filename in ("long_horizon_audit.py", "stable_probability.py", "stable_probability_tests.py",
                     "risk_independent_audit.py", "math_completion_map.py", "distribution_kernel.py", "kernel_tests.py", "MATH.md"):
        path = directory / filename
        source_inventory.append(dict(path=str(path.relative_to(repo)), sha256=digest(path)))
    completion = dict(schema="hcsn-sixstage-math-completion-map.v1",
        stage_scope=[1, 4], task_labels_read=False, frozen_protocol_or_sources_modified=False,
        old_results_deleted_or_overwritten=False, gpu_or_energy_claim=False,
        entries=[
            dict(id="frozen_kernel_replay", status="passed", tests=replay["tests_run"], result=str((failed_dir / "kernel_replay" / "RESULTS.json").relative_to(repo))),
            dict(id="renewal_and_stationary_occupation", status="passed", cases=8,
                 reference="Independent mean first-passage and occupation linear solves versus stationary generator equations"),
            dict(id="uncorrected_long_horizon_probability", status="failed_preserved", observations=4096,
                 all_mass_contracts=failed["all_prepared_rollouts_within_checked_mass_contract"],
                 implication="Frozen short-horizon success does not establish long-horizon unit-mass stability",
                 result=str((failed_dir / "RESULTS.json").relative_to(repo))),
            dict(id="bounded_probability_profile", status="passed", cases=8, observations=4096,
                 float32_maximum_post_projection_mass_error=max(row["maximum_post_projection_mass_defect"] for row in float32_rows),
                 float32_maximum_final_state_l1_error=max(row["state_l1_error"] for row in float32_rows),
                 float64_maximum_final_state_l1_error=max(row["state_l1_error"] for row in float64_rows),
                 result=str((stable_dir / "RESULTS.json").relative_to(repo))),
            dict(id="moving_boundary_long_gradient", status="passed", steps=128, parameters=8,
                 maximum_scaled_gradient_error=max(row["scaled_error"] for row in stable["records"]["moving_and_gradients"]["gradients"])),
            dict(id="first_event_probability_and_survival", status="passed", dense_cases=10, mc_cases=5,
                 monte_carlo_trials=150000, gradient_parameters=6,
                 includes=["m0_marked_self_reset", "zero_duration_boundary_shrink", "zero_duration_boundary_expand", "existing_refractory_phase_release", "repeated_event_window"],
                 result=str((risk_dir / "RESULTS.json").relative_to(repo))),
            dict(id="raw_monte_carlo_replay", status="passed", all_saved_integer_counts_reproduced=True,
                 npz=str(raw_path.relative_to(repo)), npz_sha256=digest(raw_path)),
        ],
        limitations=[
            "The validated propagator is a finite reflecting-domain CTMC, not an exact unbounded Brownian process",
            "The refractory law is Erlang; two phases have nonzero duration variance",
            "Closed-form continuous boundary optimality does not imply finite-grid/task-optimal boundary selection",
            "Boundary overlaps and upwind drift have piecewise derivatives; successful local gradients are not global smoothness",
            "The probability correction is a separate numerical profile and cannot be applied to killed survival",
            "Per-step roundoff guards are not complete global IEEE forward-error certificates",
            "Float32 accumulation of many event increments retains additional error; double accumulation is separately recorded",
            "A tiny negative risk at zero duration (about -1.38e-16) is retained as reported floating-point roundoff",
            "No content accuracy, full multimodal scaling, energy or same-quality speed conclusion is established by these audits"
        ],
        source_inventory=source_inventory, artifact_inventory=inventory,
        frozen_kernel_sha256=digest(directory / "distribution_kernel.py"),
        export_wall_seconds=time.perf_counter() - start)
    (output / "COMPLETION_MAP.json").write_text(json.dumps(completion, indent=2, allow_nan=False) + "\n")
    print(json.dumps(dict(completion_map=str(output / "COMPLETION_MAP.json"), monte_carlo_counts=mc_records)))


if __name__ == "__main__":
    torch.set_num_threads(1); torch.set_num_interop_threads(1)
    main()
