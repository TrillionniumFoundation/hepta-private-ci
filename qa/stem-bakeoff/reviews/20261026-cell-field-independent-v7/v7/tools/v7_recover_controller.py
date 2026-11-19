"""Recover missing stopped-controller bytes only against their original SHA256.

This is separate post-run engineering work. Historical records and paid timings
are never regenerated. At most one intended-plan reconstruction is permitted,
at the last actually committed block origin, and its cost is charged here.
"""

import copy
from pathlib import Path
import time

import numpy as np

from v7_audit_records import (array_hash, canonical, check_snapshot, digest,
    expected_contract, file_hash, panel_losses, read, require)


METHODS = {"myopic_h1": ("full", 1), "loss2_h8": ("loss2", 8),
    "future_field_h8": ("future_field", 8), "full_h8": ("full", 8)}


def reconstruct(template, intended, actions, trace, record):
    """Use original raw certificates, counters, receipts and final paid ledger."""
    n = len(actions)
    installed = [row for row in record["steps"] if row.get("committed_steps", 0)]
    require(installed and sum(row["committed_steps"] for row in installed) == n,
        "complete original installed block census")
    at = 0
    for row in installed:
        require(row["at_step"] == at and row["status"] == "committed_certified",
            "primary installed blocks must form the exact committed prefix")
        at += row["committed_steps"]
    origin, horizon = installed[-1]["at_step"], installed[-1]["committed_steps"]
    intended = np.asarray(intended, dtype=np.float64)
    resolved = actions[origin:n]
    require(intended.shape == resolved.shape == (horizon, actions.shape[1]), "exact final plan shape")
    result = copy.deepcopy(template)
    chain = digest([])
    for receipt in trace["receipts"]:
        chain = digest([chain, digest(receipt)])
    certificates = [{"origin_step": row["at_step"],
        "origin_state_sha256": trace["state_sha256"][row["at_step"]],
        "plan_sha256": digest(row["plan"]), "repair_sha256": digest(row["repair"]),
        "resolved_plan_sha256": array_hash(actions[row["at_step"]:row["at_step"]+row["committed_steps"]])}
        for row in installed]
    result.update(full_state_sha256=trace["state_sha256"][-1], absolute_step=n,
        plan_origin_step=origin, plan_origin_state_sha256=trace["state_sha256"][origin],
        plan_horizon=horizon, action_cursor=horizon, intended_actions=intended.tolist(),
        resolved_actions=resolved.tolist(), intended_plan_sha256=array_hash(intended),
        resolved_plan_sha256=array_hash(resolved), plan_state_sha256=trace["state_sha256"][origin:n+1],
        plan_receipt_sha256=[digest(row) for row in trace["receipts"][origin:n]],
        certificate_chain=certificates, receipt_chain={"count": n, "sha256": chain}, run_status="stopped",
        failure_ledger=[{"origin_absolute_step": 0, "stopped_absolute_step": n, "status": record["status"],
            "paid_cpu_ns": record["cpu_ns"], "paid_wall_ns": record["wall_ns"],
            "execution_record_sha256": digest(record["steps"]), "error": record["error"]}],
        counters={"plans": len(installed), "qp_calls": sum(len(row["plan"]["rounds"]) for row in installed),
            "actual_merit_rollout_steps": sum(row["committed_steps"]*sum(len(q["trials"]) for q in row["plan"]["rounds"])
                for row in installed),
            "repair_optimizer_updates": sum(row["repair"]["verified_optimizer_steps"] for row in installed),
            "repair_panel_evaluations": sum(row["repair"]["panel_head_evaluations"] for row in installed),
            "resume_verification_updates": 0, "committed_steps": n, "controller_cpu_ns": record["cpu_ns"]})
    return result


def recover_case(directory, warmup, inputs, configuration, policy, protocol_sha, source_sha,
                 output, *, planner=None):
    """Return explicit available/recovered/unresolved status; never alter a run."""
    cpu, wall = time.process_time_ns(), time.perf_counter_ns()
    directory, output = Path(directory), Path(output)
    row = {"status": "unresolved", "method": None, "planner_calls": 0,
        "planner_cpu_ns": 0, "planner_wall_ns": 0, "attempts": [],
        "primary_evidence_changed": False, "primary_costs_replaced": False,
        "resumption_authorized": False, "scientific_acceptance": False}
    try:
        header = read(directory/"result.json")
        require(header["status"] != "unavailable_execution_error", "no missing slot may be imputed")
        record, trace, cuts = [read(directory/name, True) for name in
            ("policy-record.json.gz", "trace.json.gz", "controller-checkpoints.json.gz")]
        with np.load(directory/"compact.npz", allow_pickle=False) as data:
            actions, terminal = data["actions"], data["terminal_vector"]
        count = len(actions)
        row.update(completed_steps=count, original_status=record["status"],
            expected_controller_sha256=trace["controller_sha256"][-1],
            original_record_cpu_ns=record["cpu_ns"], original_record_wall_ns=record["wall_ns"],
            original_policy_record_file_sha256=file_hash(directory/"policy-record.json.gz"),
            original_trace_file_sha256=file_hash(directory/"trace.json.gz"))
        if str(count) in cuts:
            require(digest(cuts[str(count)]) == row["expected_controller_sha256"], "existing preimage commitment")
            row.update(status="original_preimage_available", method="original_retained_bytes")
        else:
            require(record["status"] != "completed" and 0 < count < 32
                and record["completed_steps"] == count and len(trace["receipts"]) == count,
                "only a missing stopped terminal preimage is recoverable")
            anchors = panel_losses(warmup, inputs["old_panels"])
            contract = expected_contract(warmup, inputs, anchors, policy, configuration, protocol_sha, source_sha)
            require(cuts["0"]["contract"] == contract and digest(cuts["0"]) == trace["controller_sha256"][0],
                "original initial controller and admitted immutable contract")
            installed = [r for r in record["steps"] if r.get("committed_steps", 0)]
            origin, horizon = installed[-1]["at_step"], installed[-1]["committed_steps"]
            current, origin_state = warmup.clone(), None
            for step in range(count+1):
                if step == origin:
                    origin_state = current.clone()
                require(current.digest() == trace["state_sha256"][step], "original complete physical prefix")
                if step < count:
                    receipt = current.advance(*inputs["split"]["current_train"],
                        intervention=configuration["dt"]*actions[step])
                    require(receipt == trace["receipts"][step], "original physical receipt prefix")
                    require(np.all(panel_losses(current, inputs["old_panels"]) <= anchors), "original actual planning-panel retention")
            require(np.array_equal(current.vector(), terminal), "original exact terminal optimizer state")
            retained = [value for value in cuts.values() if value["plan_origin_step"] == origin
                and value["plan_horizon"] == horizon]
            intended = np.asarray(retained[0]["intended_actions"]) if retained else actions[origin:count]
            method = "retained_same_plan_intended_bytes" if retained else "resolved_equals_intended_hash_proof"

            def attempt(value, source):
                candidate = reconstruct(cuts["0"], value, actions, trace, record)
                actual = digest(candidate)
                matched = actual == row["expected_controller_sha256"]
                row["attempts"].append({"method": source, "candidate_sha256": actual, "matched": matched})
                return candidate if matched else None

            candidate = attempt(intended, method)
            if candidate is None and not retained:
                if planner is None:
                    from cell_field_planner_v7 import make_plan
                    planner = make_plan
                planner_cpu, planner_wall = time.process_time_ns(), time.perf_counter_ns()
                row["planner_calls"] = 1
                try:
                    planned = planner(origin_state, inputs["split"]["current_train"],
                        inputs["current_panels"]+inputs["old_panels"], anchors,
                        method=METHODS[policy][0], horizon=horizon,
                        **{key: configuration[key] for key in ("dt", "effort_price", "action_bound",
                            "old_weight", "current_dispersion", "relinearizations")})
                finally:
                    row["planner_cpu_ns"] = time.process_time_ns()-planner_cpu
                    row["planner_wall_ns"] = time.perf_counter_ns()-planner_wall
                require(planned["record"]["status"] == "qualified", "original committed-origin intended plan must reconstruct")
                method = "one_frozen_plan_at_last_committed_origin"
                candidate = attempt(planned["actions"], method)
            if candidate is None:
                row["reason"] = "canonical reconstruction differs from original terminal commitment; no controller bytes saved"
            else:
                check_snapshot(candidate, current, count, contract, trace, record, actions)
                output.mkdir(parents=True, exist_ok=False)
                (output/"controller.json").write_bytes(canonical(candidate))
                current.save(output/"state")
                require(file_hash(output/"controller.json") == row["expected_controller_sha256"], "saved exact preimage")
                row.update(status="recovered_exact_original_preimage", method=method,
                    controller_file=str(output/"controller.json"), state_directory=str(output/"state"),
                    terminal_state_sha256=current.digest(), stopped_for_rejection=True)
    except Exception as error:
        row.update(status="unresolved", error={"type": type(error).__name__, "message": str(error)})
    row.update(cpu_ns=time.process_time_ns()-cpu, wall_ns=time.perf_counter_ns()-wall,
        cost_scope="separate post-run prefix replay, byte recovery and optional one frozen intended-plan reconstruction")
    return row
