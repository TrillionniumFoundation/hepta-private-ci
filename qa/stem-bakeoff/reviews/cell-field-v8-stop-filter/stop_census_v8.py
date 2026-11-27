"""Read-only census of every sealed V7b stopped policy and prior witnesses.

No optimizer, predictor, solver, source CSV, or evaluation labels are loaded.
This is a diagnostic input specification, not a new policy evaluation.
"""

import argparse
from collections import Counter
import gzip
import hashlib
from itertools import product
import json
from pathlib import Path

import numpy as np


PROTOCOL = "e1827b6a0a4de9a083fca5c9401751b6063e63b447617a90719e64a089b4da7d"
SEAL = "e3ad867157e293e0c80eee6a2985583688e851fee9ff98c68323f6fa83af6131"
AUDIT = "84919528742d5645eae8d5903887dd813dc7d27cd6befb484c584e83249425f9"
DIAGNOSTIC_REPORT = "935bf50502ebb85cf400b8c8d30de3639c0e8f1920662c0ee44ac00948b2900e"
SOURCE = "1a112e348eeaa06645896f1121c2ceab3f73e36caa967d1abda72bc462c7f110"
STATUSES = {"completed", "not_executed_rejected", "not_executed_tangent_infeasible", "not_executed_unresolved"}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else canonical(value)).hexdigest()


def sha(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            value.update(block)
    return value.hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), "ordinary file: " + str(path))
    return json.loads(gzip.decompress(path.read_bytes()) if path.suffix == ".gz" else path.read_bytes())


def sealed(grid, seal, relative):
    path = grid / relative
    pin = seal["files"][relative]
    require(path.stat().st_size == pin["bytes"] and sha(path) == pin["sha256"], "sealed bytes: " + relative)
    return path


def matched_witness(diagnostic, snapshot, configuration, horizon):
    """A prior trajectory is reusable only at the exact complete physical state."""
    contract = snapshot["contract"]
    if (diagnostic["initial_state_sha256"] != snapshot["full_state_sha256"]
            or diagnostic["configuration"] != configuration
            or diagnostic["original_old_anchors"] != contract["original_old_anchors"]):
        return False
    for name in ("full", "future_field"):
        branch = diagnostic["branches"][name]
        if not branch.get("certified"):
            continue
        repair = branch["repair"]
        require(branch["initial_state_sha256"] == diagnostic["initial_state_sha256"], "prior witness origin")
        require(repair["old_panel_sha256"] == contract["old_panel_sha256"]
            and repair["original_old_anchors"] == contract["original_old_anchors"]
            and repair["action_bound"] == configuration["action_bound"] and repair["dt"] == configuration["dt"]
            and repair["horizon"] >= horizon and branch["prospective_steps"] >= horizon
            and all(r["dataset_sha256"] == contract["training_sha256"] for r in branch["receipts"]),
            "same physical task, old thresholds and original box in reused trajectory")
    return True


def summarize_repair(repair):
    failed = repair["step_records"][-1]
    anchors = np.asarray(repair["original_old_anchors"])
    values = np.asarray([row["old_losses"] for row in failed["trials"]])
    require(values.ndim == 2 and values.shape[1] == 4 and np.isfinite(values).all(), "four finite actual panel values")
    excess = values - anchors
    maxima = excess.max(axis=1)
    best = int(np.argmin(maxima))
    require(failed["status"] == "rejected" and not np.any(np.all(excess <= 0., axis=1))
        and repair["committed_optimizer_steps"] == 0 and repair["certified_optimizer_steps"] == 0,
        "failed finite search cannot contain an accepted feasible action")
    return {"failed_local_step": repair["failed_at_step"],
        "failed_prospective_state_sha256": failed["initial_state_sha256"],
        "prospective_safe_steps_not_committed": repair["prospective_safe_steps"],
        "initial_within_threshold": repair["initial_within_threshold"],
        "initial_maximum_old_excess": float(np.max(np.asarray(repair["initial_old_losses"])-anchors)),
        "parameter_hold_within_original_box_at_failed_step": failed.get("parameter_hold_within_box"),
        "trial_count": len(values), "trial_kinds": dict(Counter(t["kind"] for t in failed["trials"])),
        "feasible_actual_trial_count": 0, "best_trial_index": best,
        "best_trial_maximum_old_excess": float(maxima[best]),
        "best_trial_panel_excesses": excess[best].tolist(),
        "violated_panel_count_at_best_trial": int(np.sum(excess[best] > 0)),
        "violated_panel_count_at_intended_trial": int(np.sum(excess[0] > 0)),
        "maximum_violated_panel_count_across_trials": int(np.sum(excess > 0, axis=1).max()),
        "panel_gradient_conflict_computed": False,
        "global_nonlinear_feasibility": "unknown; only this finite single-ray search was exhausted"}


def count_rows(rows, keys):
    counts = Counter(tuple(row[key] for key in keys) for row in rows)
    return [{**dict(zip(keys, key)), "count": count} for key, count in sorted(counts.items())]


def census(workspace, output):
    workspace, output = Path(workspace), Path(output)
    grid = workspace / "pft-development-v7b/grid"
    report_path = workspace / "pft-audit-v7b-development/result/audit.json"
    diagnostic_root = workspace / "pft-v7-stop-diagnostics"
    require(sha(grid/"protocol.json") == PROTOCOL and sha(grid/"development_seal.json") == SEAL
        and sha(report_path) == AUDIT and sha(diagnostic_root/"report.json") == DIAGNOSTIC_REPORT,
        "pinned complete V7b audit and original diagnostic report")
    plan, seal, audit = read(grid/"protocol.json"), read(grid/"development_seal.json"), read(report_path)
    require(audit["status"] == "PASS" and audit["primary_records"] == 864 and audit["actual_error_records"] == 0,
        "complete previously verified source execution")
    combinations = list(product(plan["versions"], plan["tasks"], plan["head_modes"], plan["seeds"]))
    expected = {f"config{index:02d}/{version}-{task}-seed{seed}-{head}/{policy}/result.json"
        for index in range(12) for version, task, head, seed in combinations for policy in plan["primary_policies"]}
    require({p.relative_to(grid).as_posix() for p in grid.glob("config*/*/*/result.json")} == expected,
        "all864 and only864 registered policy results")
    previous = [(p, read(p)) for p in sorted(diagnostic_root.glob("config*/*/diagnostic.json"))]
    require(len(previous) == 71, "complete original71 stopped Loss2 diagnostics")
    slots, rows = [], []
    for name in sorted(expected):
        path = sealed(grid, seal, name)
        header = read(path)
        require(header["status"] in STATUSES and header["error"] is None, "typed status and no actual exception")
        slot = name.removesuffix("/result.json")
        index = int(slot.split("/")[0][-2:])
        configuration = plan["configurations"][index]["configuration"]
        slots.append({"slot": slot, "status": header["status"], "completed_steps": header["completed_steps"],
            "result_sha256": sha(path), "terminal_state_sha256": header["terminal_state_sha256"]})
        if header["status"] == "completed":
            require(header["completed_steps"] == 32, "complete means all32 real updates")
            continue
        records = {key: read(sealed(grid, seal, slot+"/"+filename)) for key, filename in
            (("raw", "policy-record.json.gz"), ("trace", "trace.json.gz"), ("cuts", "controller-checkpoints.json.gz"))}
        raw, trace, cuts = [records[k] for k in ("raw", "trace", "cuts")]
        count = header["completed_steps"]
        snapshot, final = cuts[str(count)], raw["steps"][-1]
        require(digest(snapshot) == trace["controller_sha256"][-1] and snapshot["run_status"] == "stopped"
            and snapshot["full_state_sha256"] == header["terminal_state_sha256"] == trace["state_sha256"][-1]
            and final["at_step"] == count and final.get("committed_steps", 0) == 0
            and raw["status"] == final["status"] == header["status"] and raw["error"] is None,
            "exact stopped original controller and complete physical origin")
        horizon = final["plan"]["horizon"]
        qps = final["plan"]["rounds"]
        qp = qps[-1]["qp"]
        qp_fields = {key: qp.get(key) for key in ("status", "reason", "stationarity", "maximum_constraint_violation",
            "complementary_slackness", "verified_box_infeasibility_lower_bound", "separating_mixture", "attempts")}
        row = {"slot": slot, "configuration_index": index, "configuration": configuration,
            **{key: header[key] for key in ("fit_id", "version", "task", "head", "seed", "policy", "status")},
            "committed_steps": count, "original_method": final["plan"]["method"], "attempted_horizon": horizon,
            "origin_state_sha256": snapshot["full_state_sha256"], "controller_sha256": digest(snapshot),
            "contract_sha256": digest(snapshot["contract"]), "original_old_anchors": snapshot["contract"]["original_old_anchors"],
            "training_sha256": snapshot["contract"]["training_sha256"],
            "old_panel_sha256": snapshot["contract"]["old_panel_sha256"],
            "current_panel_sha256": snapshot["contract"]["current_panel_sha256"],
            "result_sha256": sha(path), "policy_record_sha256": sha(path.with_name("policy-record.json.gz")),
            "last_attempt": {"plan_status": final["plan"]["status"], "round_statuses": [v["qp"]["status"] for v in qps],
                "selected_proposal_iteration": final["plan"].get("selected_proposal_iteration"),
                "selected_fraction": final["plan"].get("selected_fraction"), "last_qp": qp_fields},
            "repair_invoked": "repair" in final, "physical_box_feasibility": "not_established",
            "shared_fallback_already_executed": False, "original_intended_actions_retained": False,
            "source_metrics_used": False, "matched_prior_diagnostics": []}
        if "repair" in final:
            row["repair"] = summarize_repair(final["repair"])
        else:
            require(final["plan"]["status"] in ("tangent_infeasible", "unresolved"), "only QP certificate stops bypass repair")
        for prior_path, diagnostic in previous:
            if not matched_witness(diagnostic, snapshot, configuration, horizon):
                continue
            branches = {key: value["status"] for key, value in diagnostic["branches"].items()}
            witness = {"path": str(prior_path.relative_to(workspace)), "sha256": sha(prior_path),
                "same_origin_configuration_thresholds_context": True, "branch_statuses": branches,
                "full_safe_h8": diagnostic["full_actual_safe_witness"],
                "field_safe_h8": diagnostic["branches"]["future_field"].get("certified", False),
                "parameter_hold_status": diagnostic["branches"]["parameter_hold"]["status"]}
            row["matched_prior_diagnostics"].append(witness)
            if witness["full_safe_h8"] or witness["field_safe_h8"]:
                row["physical_box_feasibility"] = "established_by_existing_exact_origin_actual_h8_witness"
        rows.append(row)
    counts = dict(Counter(r["status"] for r in slots))
    require(counts == {"completed": 766, "not_executed_rejected": 54,
        "not_executed_tangent_infeasible": 37, "not_executed_unresolved": 7}, "all original status counts retained")
    repairs = [r for r in rows if r["repair_invoked"]]
    witnesses = [r for r in rows if r["physical_box_feasibility"].startswith("established")]
    result = {"schema": "hepta.cell-field-stop-census.v8-preparation", "status": "PASS",
        "source_v7b_protocol_sha256": PROTOCOL, "source_v7b_seal_sha256": SEAL, "source_closure_sha256": SOURCE,
        "source_execution_commit": "147a67868afb68511a5152f7f944fb26df34843b", "independent_audit_sha256": AUDIT,
        "prior_diagnostic_report_sha256": DIAGNOSTIC_REPORT, "census_code_sha256": sha(__file__),
        "registered_policy_slots": 864, "completed_policy_slots": 766, "stopped_policy_slots": 98,
        "actual_errors": 0, "status_counts": counts, "by_policy_status": count_rows(rows, ("policy", "status")),
        "by_configuration_policy_status": count_rows(rows, ("configuration_index", "policy", "status")),
        "by_step_status": count_rows(rows, ("committed_steps", "status")),
        "by_task_head_version_status": count_rows(rows, ("version", "task", "head", "status")),
        "qp_stops_without_any_nonlinear_repair": 44, "repair_rejections": len(repairs),
        "repair_hold_outside_box_at_failed_prospective_step": sum(r["repair"]["parameter_hold_within_original_box_at_failed_step"] is False for r in repairs),
        "repair_safe_prefix_discarded_atomically": sum(r["repair"]["prospective_safe_steps_not_committed"] > 0 for r in repairs),
        "repair_best_trial_excess_range": [min(r["repair"]["best_trial_maximum_old_excess"] for r in repairs),
            max(r["repair"]["best_trial_maximum_old_excess"] for r in repairs)],
        "prior_exact_origin_diagnostic_matches": sum(bool(r["matched_prior_diagnostics"]) for r in rows),
        "prior_actual_h8_safe_witnesses": len(witnesses),
        "prior_actual_h8_safe_witnesses_by_stop": dict(Counter(r["status"] for r in witnesses)),
        "physical_nonlinear_box_feasibility_unresolved": len(rows)-len(witnesses),
        "new_optimizer_calls": 0, "new_solver_calls": 0, "new_confirmation_sources_selected": False,
        "selection_labels_used": False, "scientific_acceptance": False,
        "limits": ["a tangent separation certifies only that particular linear predictor",
            "the last proposed actions are absent for stopped attempts; do not substitute the prior installed plan",
            "54 parameter-hold checks are at failed prospective steps, not all original stopped origins",
            "a safe H8 witness establishes local feasibility only, not a shared fallback policy or32-step completion",
            "no zero-action or parameter-hold safety assumption; no threshold slack or wider action box"],
        "all864_slots": slots, "all98_stops": rows}
    output.parent.mkdir(parents=True, exist_ok=True)
    require(not output.exists(), "new census output required")
    output.write_bytes(canonical(result)+b"\n")
    require(sha(grid/"development_seal.json") == SEAL, "original development seal unchanged")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--output", required=True)
    result = census(**vars(parser.parse_args()))
    print(json.dumps({key: result[key] for key in ("status", "status_counts", "prior_actual_h8_safe_witnesses",
        "physical_nonlinear_box_feasibility_unresolved", "new_solver_calls")}))
