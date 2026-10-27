"""Freeze and execute a full census of the actual owner/host continuation."""
import argparse
import json
from pathlib import Path
import shutil
import time

import numpy as np

from ...repair_20261026.risk_feedback.media import emit, readback
from .client import Native, continuation, digest, numerical_projection, sha, write
from .forecast import forecasts, plan
from .training import prefix, prepare, verify_domain


def permit_emit(run, directory, code, fault, native_ok, remaining, role):
    if not directory.resolve().is_relative_to(run.resolve()):
        raise ValueError("Research host media permit is out of scope")
    permit = {"authorization_source": "User instruction to execute this research study",
        "scope": str(run.resolve()), "destination": str(directory.resolve()), "role": role,
        "owner_signal_authority": "DENY_ALL", "native_nonabstention": bool(native_ok),
        "remaining_media_units_before": remaining, "host_permitted": True,
        "host_execution_admitted": bool(native_ok and remaining > 0),
        "production_authorization": False}
    if not permit["host_execution_admitted"]:
        return None, None, permit
    paths = emit(directory, code, fault)
    observed = readback(paths)
    permit["actual_media_files"] = len(paths)
    permit["delivered_monotonic_ns"] = time.monotonic_ns()
    return paths, observed, permit


def reference_table(native, run, model, calibration, protocol):
    table = {}
    directory = run / "reference-planning"
    directory.mkdir()
    for expires in protocol["expiry_contexts"]:
        native.open(directory / f"owner-{expires}", f"reference.{expires}", expires, model, calibration)
        first = prefix(native, 0)
        branches = forecasts(native, "risk_numeric", protocol)
        for cue in range(4):
            for budget in protocol["media_budget_contexts"]:
                result = plan(cue, budget, "risk_numeric", branches,
                              [not row["native_abstain"] for row in first], protocol)
                table[f"{cue}:{expires}:{budget}"] = result["selected"]["action"]
        native.close()
        write(directory / f"TRANSCRIPT-{expires}.json", native.transcript)
    write(run / "COMMON_ROOT_TABLE.json", table)
    return table


def episode(native, run, model, calibration, protocol, cue, expires, budget, arm, fault, root_table):
    name = f"cue{cue}-expiry{expires}-budget{budget}-{arm}-fault{fault}"
    directory = run / "evaluation" / name
    directory.mkdir(parents=True)
    began, cpu = time.monotonic_ns(), time.process_time_ns()
    native.open(directory / "owner", name, expires, model, calibration)
    first = prefix(native, cue)
    branches = forecasts(native, arm, protocol)
    forced = root_table[f"{cue}:{expires}:{budget}"] if arm == "risk_zero" else None
    prediction = plan(cue, budget, arm, branches, [not row["native_abstain"] for row in first], protocol, forced)
    action = prediction["selected"]["action"]
    write(directory / "PREDICTION_BEFORE_DELIVERY.json", prediction)
    paths, observed, permit = permit_emit(run, directory / "initial", action, fault,
        not first[action]["native_abstain"], budget, "initial")
    write(directory / "INITIAL_PERMIT.json", permit)
    if observed is None:
        raise ValueError("Selected initial action could not be delivered")
    write(directory / "PUBLIC_READBACK.json", observed)
    feedback = 0.0 if arm == "risk_zero" else protocol["numeric_feedback_by_fault"][observed["fault_class"]]
    feedback_at = time.monotonic_ns()
    write(directory / "PUBLIC_FEEDBACK.json", {"value": feedback, "readback_digest": digest(observed),
        "feedback_monotonic_ns": feedback_at, "private_target_supplied": False})
    ticks = continuation(native, feedback, observed)
    continuation_at = time.monotonic_ns()
    native_ok = not any(row["native_abstain"] for row in ticks)
    proposed = observed["fault_class"] != 0 if arm == "risk_history" else ticks[-1]["proposed_repair"]
    repair_paths = repair_observed = repair_permit = None
    if proposed:
        repair_paths, repair_observed, repair_permit = permit_emit(run, directory / "repair", action, 0,
            native_ok, budget - 1, "repair")
        write(directory / "REPAIR_PERMIT.json", repair_permit)
    executed = repair_observed is not None
    final_paths, final = (repair_paths, repair_observed) if executed else (paths, observed)
    closed = native.close()
    write(directory / "TRANSCRIPT.json", native.transcript)
    actual_ticks = sum(int(row["response"]["result"]["native_transition_executed"]) for row in native.transcript
        if row["request"]["command"] == "Tick" and row["response"]["ok"])
    actual_ticks += sum(len(row["response"]["result"]["ticks"]) for row in native.transcript
        if row["request"]["command"] == "Forecast" and row["response"]["ok"])
    if actual_ticks != 16:
        raise ValueError("Charged actual invocation count differs from declared model")
    validation_steps = sum(b["ledger_validation_kernel_steps"] for b in branches)
    journal_replays = sum(b["original_journal_replayed_prefix_steps"] for b in branches)
    if validation_steps + journal_replays != protocol["verification_replay_steps"]:
        raise ValueError("Actual restore work differs from declared fee contract")
    cost = protocol["initial_action_cost"][action] + protocol["channel_cost_by_fault"][observed["fault_class"]]
    cost += actual_ticks * protocol["native_tick_charge"]
    cost += (validation_steps + journal_replays) * protocol["verification_replay_step_charge"]
    cost += protocol["repair_cost"] * executed + protocol["denied_repair_attempt_cost"] * bool(proposed and not executed)
    observed_code = final["codes"]["text"]
    returns = np.array(protocol["semantic_utility_action_by_target"][observed_code], dtype=float)
    returns -= protocol["irreversible_first_delivery_damage"][observed["fault_class"]]
    returns -= protocol["terminal_mismatch_penalty"][final["fault_class"]] + cost
    strict = [int(final["fault_class"] == 0 and observed_code == target) for target in range(3)]
    row = {"name": name, "cue": cue, "expires": expires, "media_budget": budget, "arm": arm,
        "realized_transport_fault": fault, "action": action, "prediction": prediction["selected"],
        "initial_paths": paths, "initial_observed": observed, "final_paths": final_paths, "final_observed": final,
        "actual_native_ticks_including_planning": actual_ticks, "shadow_native_ticks": 9,
        "physical_receipt_processing_micros": sum(r["response"]["physical_receipt_processing_micros"] for r in native.transcript),
        "additional_ledger_validation_kernel_steps": validation_steps,
        "original_journal_replayed_prefix_steps": journal_replays,
        "total_original_sparse_kernel_executions": actual_ticks + validation_steps + journal_replays,
        "actual_continuation_ticks": ticks, "actual_root_ticks": first, "forecast_branches": branches,
        "proposed_repair": bool(proposed), "executed_repair": executed, "denied_attempt": bool(proposed and not executed),
        "native_nonabstention": native_ok, "remaining_media_units_before_repair": budget - 1,
        "host_initial_permit": permit, "host_repair_permit": repair_permit,
        "complete_task_charge": cost, "return_by_private_target": returns.tolist(), "strict_by_private_target": strict,
        "actual_final_state": closed, "actual_original_owner_executed": True,
        "production_authority": False, "native_owner_granted_action_authority": False,
        "realized_branch_numerical_state_matches": numerical_projection(ticks) == numerical_projection(branches[fault]["ticks"]),
        "chronology": {"delivered": permit["delivered_monotonic_ns"], "feedback": feedback_at,
                       "continuation": continuation_at, "private_scoring": time.monotonic_ns()},
        "wall_ns": time.monotonic_ns() - began, "python_cpu_ns": time.process_time_ns() - cpu}
    write(directory / "EPISODE.json", row)
    return row


def summarize(rows, protocol):
    groups = {}
    for row in rows:
        key = (row["cue"], row["expires"], row["media_budget"], row["arm"])
        groups.setdefault(key, []).append(row)
    summaries = []
    for key, values in sorted(groups.items()):
        if sorted(row["realized_transport_fault"] for row in values) != [0, 1, 2]:
            raise ValueError("Missing realized fault in complete census")
        if len({row["action"] for row in values}) != 1:
            raise ValueError("Initial policy anticipated an unobserved future fault")
        action = values[0]["action"]
        law = np.array(protocol["target_law_by_cue"][key[0]])
        actual_moment = actual_mean = actual_success = actual_cost = 0.0
        for row in values:
            mass = protocol["fault_law_by_action"][action][row["realized_transport_fault"]]
            returns = np.array(row["return_by_private_target"])
            actual_moment += mass * float(np.exp(-protocol["gamma"] * returns) @ law)
            actual_mean += mass * float(returns @ law)
            actual_success += mass * float(np.array(row["strict_by_private_target"]) @ law)
            actual_cost += mass * row["complete_task_charge"]
        predicted = values[0]["prediction"]
        summaries.append({"cue": key[0], "expires": key[1], "media_budget": key[2], "arm": key[3],
            "action": action, "actual_moment": actual_moment, "actual_mean": actual_mean,
            "actual_strict_success": actual_success, "actual_cost": actual_cost,
            "predicted_moment": predicted["moment"], "predicted_mean": predicted["mean"],
            "predicted_strict_success": predicted["strict_success_probability"],
            "moment_absolute_error": abs(actual_moment - predicted["moment"]),
            "mean_absolute_error": abs(actual_mean - predicted["mean"]),
            "success_absolute_error": abs(actual_success - predicted["strict_success_probability"]),
            "cost_absolute_error": abs(actual_cost - predicted["expected_task_charge"])})
    aware = [row for row in summaries if row["arm"] != "mean_blind_future"]
    blind = [row for row in summaries if row["arm"] == "mean_blind_future"]
    lookup = {(r["cue"], r["expires"], r["media_budget"], r["arm"]): r for r in summaries}
    numeric, zero, history, mean, naive = ([lookup[(c, e, b, arm)] for c in range(4)
        for e in protocol["expiry_contexts"] for b in protocol["media_budget_contexts"]]
        for arm in ("risk_numeric", "risk_zero", "risk_history", "mean_numeric", "mean_blind_future"))
    return {"schema": "hepta.continuation.actual-owner.result.v1", "actual_evaluation_episodes": len(rows),
        "all_census_states": len(summaries), "groups": summaries,
        "maximum_owner_aware_moment_error": max(r["moment_absolute_error"] for r in aware),
        "maximum_owner_aware_success_error": max(r["success_absolute_error"] for r in aware),
        "maximum_owner_aware_cost_error": max(r["cost_absolute_error"] for r in aware),
        "maximum_blind_future_moment_error": max(r["moment_absolute_error"] for r in blind),
        "mean_root_changes_from_future_blind_control": sum(a["action"] != b["action"] for a,b in zip(mean,naive)),
        "mean_control_return_gain_over_future_blind": float(np.mean([a["actual_mean"]-b["actual_mean"] for a,b in zip(mean,naive)])),
        "numeric_minus_zero_mean_return": float(np.mean([a["actual_mean"]-b["actual_mean"] for a,b in zip(numeric,zero)])),
        "numeric_minus_history_mean_return": float(np.mean([a["actual_mean"]-b["actual_mean"] for a,b in zip(numeric,history)])),
        "mean_risk_root_disagreements": sum(a["action"] != b["action"] for a,b in zip(mean,numeric)),
        "all_realized_native_branch_states_match": all(r["realized_branch_numerical_state_matches"] for r in rows),
        "actual_native_ticks_including_forecasts": sum(r["actual_native_ticks_including_planning"] for r in rows),
        "additional_event_ledger_sparse_validations": sum(r["additional_ledger_validation_kernel_steps"] for r in rows),
        "original_journal_sparse_prefix_replays": sum(r["original_journal_replayed_prefix_steps"] for r in rows),
        "total_original_sparse_kernel_executions": sum(r["total_original_sparse_kernel_executions"] for r in rows),
        "physical_receipt_processing_micros": sum(r["physical_receipt_processing_micros"] for r in rows),
        "actual_expired_native_decision_ticks": sum(r["actual_continuation_ticks"][-1]["native_abstain"] for r in rows),
        "host_denied_repair_attempts": sum(r["denied_attempt"] for r in rows),
        "owner_granted_generation_authority": False, "production_semantic_qualification": False,
        "old_native_qualification_reproduced": False, "scope": protocol["study"]}


def run(args):
    run = args.output.resolve()
    run.mkdir(parents=True, exist_ok=False)
    protocol_path = Path(__file__).with_name("PROTOCOL.json")
    protocol = json.loads(protocol_path.read_text())
    shutil.copyfile(protocol_path, run / "PROTOCOL.json")
    native = Native(args.binary)
    try:
        model, calibration = prepare(native, run, protocol)
        verify_domain(native, run, model, calibration)
        common = reference_table(native, run, model, calibration, protocol)
        sources = {p.name: sha(p) for p in Path(__file__).parent.iterdir() if p.suffix in (".py", ".rs", ".json")}
        write(run / "FROZEN.json", {"protocol_sha256": sha(protocol_path), "model_sha256": sha(model),
            "calibration_sha256": sha(calibration), "binary_sha256": sha(args.binary), "sources": sources,
            "common_root_table_sha256": sha(run / "COMMON_ROOT_TABLE.json"),
            "formal_census_started": False, "freeze_monotonic_ns": time.monotonic_ns()})
        executed = run / "executed-sources"
        executed.mkdir()
        for name in sources:
            shutil.copyfile(Path(__file__).with_name(name), executed / name)
        rows = []
        for cue in range(4):
            for expires in protocol["expiry_contexts"]:
                for budget in protocol["media_budget_contexts"]:
                    for arm in protocol["arms"]:
                        for fault in range(3):
                            rows.append(episode(native, run, model, calibration, protocol, cue, expires, budget, arm, fault, common))
        result = summarize(rows, protocol)
        write(run / "RESULT.json", result)
        write(run / "ROWS.json", rows)
        print(json.dumps({k:v for k,v in result.items() if k != "groups"}))
    except Exception as error:
        write(run / "FAILED.json", {"error": repr(error), "partial_evidence_retained": True})
        raise
    finally:
        native.finish()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--binary", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    run(p.parse_args())
