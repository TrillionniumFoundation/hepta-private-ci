"""Descriptive common-price contrasts and a saved-data H1 baseline comparison.

No optimization, forward optimizer update or prediction is executed here.
Scores at terminal32 are kept separate from zero-tail conditional forecasts.
"""

import argparse
from itertools import product
import gzip
import json
from pathlib import Path

import numpy as np

from remaining_audit_core_v8 import METHODS, canonical, check_seal, file_hash, load_policy_record, read, require
from remaining_dev_statistics_v8 import AXES, CANDIDATE


GRID_SEAL = "77f138160f96ddddde862d5e07cd241038409a4a8aba353f6d575b74e800a363"


def distribution(values):
    values = np.asarray(values, dtype=np.float64)
    require(values.ndim == 1 and len(values) > 0 and np.isfinite(values).all(), "complete finite descriptive differences")
    return {"count": len(values), "mean": float(values.mean()), "minimum": float(values.min()),
        "maximum": float(values.max()), "better_below_minus1e_12": int(np.sum(values < -1e-12)),
        "equal_within1e_12": int(np.sum(np.abs(values) <= 1e-12)), "worse_above1e_12": int(np.sum(values > 1e-12))}


def baseline_pair(grid, run, records):
    require(file_hash(grid/"development_seal.json") == GRID_SEAL, "independently audited original1152 grid seal")
    seal, rows = read(grid/"development_seal.json"), []
    for v, t, h, s in product(*AXES):
        fit = f"{v}-{t}-seed{s}-{h}"
        old = grid/"config04"/fit/"myopic_h1"
        for name in ("compact.npz", "trace.json.gz", "policy-record.json.gz"):
            path = old/name
            require(file_hash(path) == seal["files"][path.relative_to(grid).as_posix()]["sha256"], "original saved baseline member")
        with gzip.open(old/"trace.json.gz", "rt") as f:
            trace = json.load(f)
        with gzip.open(old/"policy-record.json.gz", "rt") as f:
            original = json.load(f)
        current = records[fit, "myopic_h1"]
        require(original["initial_state_sha256"] == current["initial_state_sha256"], "identical complete historical warmup")
        with np.load(old/"compact.npz", allow_pickle=False) as a, \
                np.load(run/fit/"myopic_h1/trajectory.npz", allow_pickle=False) as b:
            # Deliberately never access compact.npz future_losses/old_differences.
            old_actions, old_terminal = a["actions"], a["terminal_vector"]
            new_actions, new_states = b["actions"], b["states"]
            common = min(len(old_actions), len(new_actions))
            same = len(old_actions) == len(new_actions)
            hashes = [a == b for a, b in zip(trace["state_sha256"], current["state_sha256"])]
            rows.append({"fit": fit, "grid_configuration_index": 4, "old_weight": .25, "commit_stride": 1,
                "grid_status": original["status"], "remaining_status": current["status"],
                "grid_steps": len(old_actions), "remaining_steps": len(new_actions), "common_action_prefix": common,
                "maximum_common_action_absolute_difference": float(np.max(np.abs(old_actions[:common]-new_actions[:common]), initial=0.)),
                "exact_common_action_prefix": bool(np.array_equal(old_actions[:common], new_actions[:common])),
                "same_terminal_step": same,
                "maximum_terminal_theta_m_v_absolute_difference": float(np.max(np.abs(old_terminal-new_states[-1]))) if same else None,
                "complete_state_digest_matches": sum(hashes), "complete_state_digests_compared": len(hashes),
                "all_recorded_full_states_exact": same and all(hashes),
                "intermediate_numeric_state_arrays_available_in_grid": False})
    return {"rows": rows, "fits": 24, "all24_full_state_paths_exact": all(r["all_recorded_full_states_exact"] for r in rows),
        "maximum_action_absolute_difference": max(r["maximum_common_action_absolute_difference"] for r in rows),
        "maximum_same_step_terminal_absolute_difference": max((r["maximum_terminal_theta_m_v_absolute_difference"]
            for r in rows if r["same_terminal_step"]), default=None),
        "new_optimizer_updates": 0, "new_planner_calls": 0,
        "scope": "stored actions, complete-state digests and terminal theta/m/v only; unequal intermediate hashes do not measure their numerical distance. Different tracing/forecast construction costs are not a CPU causal contrast."}


def summarize(run, audit, evaluation, grid, output):
    run, audit, evaluation, grid, output = map(Path, (run, audit, evaluation, grid, output))
    require(not output.exists() and run not in output.parents, "new descriptive output outside control")
    qualification, external = read(audit), read(evaluation)
    require(qualification["status"] == "PASS" and external["independent_audit_sha256"] == file_hash(audit), "same independently audited and scored study")
    seal = qualification["control_seal_sha256"]
    check_seal(run, seal)
    rows, records = [], {}
    for v, t, h, s in product(*AXES):
        fit = f"{v}-{t}-seed{s}-{h}"
        for method in METHODS:
            record = load_policy_record(run/fit/method, True)
            records[fit, method] = record
            require(record["status"] == "completed" and record["completed_steps"] == 32,
                "descriptive common32 table requires this actual complete96 census")
            panels = np.asarray(record["terminal_planning_panels"])
            rows.append({"fit": fit, "version": v, "task": t, "head": h, "seed": s, "method": method,
                "planning_current_mean": float(panels[:4].mean()), "planning_old_mean": float(panels[4:].mean()),
                "parameter_effort": record["parameter_action_penalty"], "J32": record["common_J32"],
                "policy_call_cpu_ns": record["policy_call_cpu_ns"]})
    by_key = {(r["fit"], r["method"]): r for r in rows}
    contrasts = []
    for baseline in ("myopic_h1", "loss2_remaining", "full_adjoint_remaining"):
        paired = []
        for v, t, h, s in product(*AXES):
            fit = f"{v}-{t}-seed{s}-{h}"
            a, b = by_key[fit, CANDIDATE], by_key[fit, baseline]
            paired.append({"fit": fit, **{key: a[key]-b[key] for key in
                ("J32", "planning_current_mean", "planning_old_mean", "parameter_effort")}})
        contrasts.append({"candidate": CANDIDATE, "baseline": baseline, "paired_rows": paired,
            "differences": {key: distribution([r[key] for r in paired]) for key in
                ("J32", "planning_current_mean", "planning_old_mean", "parameter_effort")}})
    groups = [{"version": g["version"], "task": g["task"], "head": g["head"],
        "candidate_h1_cpu_ratio": g["candidate_h1_cpu_ratio"], "candidate_full_cpu_ratio": g["candidate_full_cpu_ratio"],
        "historical_DEV_future": g["future"], "historical_DEV_old_vs_warmup": g["old_vs_original_warmup"]} for g in external["groups"]]
    baseline = baseline_pair(grid, run, records)
    check_seal(run, seal)
    result = {"schema": "hepta.remaining-terminal-descriptive-contrasts.v8", "source_sha256": file_hash(__file__),
        "control_seal_sha256": seal, "independent_audit_sha256": file_hash(audit),
        "historical_dev_evaluation_sha256": file_hash(evaluation), "entry_disposition": external["disposition"],
        "all96_planning_rows": rows, "paired_common32_contrasts": contrasts, "all8_cpu_and_historical_dev_groups": groups,
        "h1_vs_grid_config04_saved_data_comparison": baseline, "scientific_acceptance": False,
        "scope": "actual32 terminal planning risk and total physical effort are separate from disclosed historical DEV outcomes; no zero-tail forecast is compared with a subsequent adaptive-policy tail as a model error"}
    output.write_bytes(canonical(result)+b"\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("run", "audit", "evaluation", "grid", "output"):
        parser.add_argument("--"+key, required=True)
    value = summarize(**vars(parser.parse_args()))
    print(json.dumps({"entry_disposition": value["entry_disposition"],
        "contrasts": [{"baseline": r["baseline"], "J32": r["differences"]["J32"]} for r in value["paired_common32_contrasts"]]}))
