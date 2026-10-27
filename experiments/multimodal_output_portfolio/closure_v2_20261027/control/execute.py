"""A real delivery, a cold owner restore, and a later neural generation action."""

import resource
import time

from ...continuation_20261027.control.client import Native, Q, numerical_projection
from ...continuation_20261027.control.training import prefix
from .adapter import scalar_feedback, score
from .binding import BoundCritic
from .critic import proposal, task_cost
from .protocol import PROTOCOL as P, digest, sha, write


def episode(task, arm, reference, donor, generator, audit, binary, development, output, fit, heads, shrinkage, *, forecast_model):
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    if not isinstance(forecast_model, BoundCritic):
        raise TypeError("A runtime-bound continuation critic is required")
    forecast_model.verify_inputs(fit, heads, shrinkage)
    name = f"pair-{task['index']:03}-{arm}"
    directory = output / "episodes" / name
    directory.mkdir(parents=True)
    model, calibration = development / "MODEL.json", development / "ENCODER_DOMAIN_PROOF.json"
    children_before = resource.getrusage(resource.RUSAGE_CHILDREN)
    native = Native(binary)
    native.open(directory / "owner", name, task["expires"], model, calibration)
    first = prefix(native, 0)
    if any(row["native_abstain"] for row in first):
        raise ValueError("Registered initial delivery was refused")
    branches = {str(symbol): native.call({"command": "Forecast", "feedback_q24": symbol * Q,
        "branch": f"scalar-{symbol + 1}"}) for symbol in (-1, 0, 1)}
    before = forecast_model.predict(task["condition"], arm, task["expires"], task["budget"])
    write(directory / "PREDICTION_BEFORE_DELIVERY.json", before)
    initial, pixels = generator.deliver(task["public"], 0, directory / "initial")
    if initial["sha256"] != reference["delivery"]["sha256"]:
        raise ValueError("Matched initial generator output differs across interventions")
    real_feedback = scalar_feedback(initial["caption"], task["private"].labels[0].tolist())
    feedback = 0 if arm == "native_zero" else donor["feedback"] if arm == "native_permuted" else real_feedback
    evidence = {"actual_initial_sha256": initial["sha256"], "scalar": feedback,
        "scalar_source": f"other-delivered-pair:{donor['index']}" if arm == "native_permuted" else "current-delivery"}
    feedback_at = time.monotonic_ns()
    feedback_tick = native.tick(1, feedback, evidence)
    before_close = native.close()
    initial_transcript = native.transcript
    native.finish()
    restart_at = time.monotonic_ns()
    resumed = Native(binary)
    resumed.case = name
    restored = resumed.call({"command": "Resume", "directory": str(directory / "owner"), "case": name,
        "expires": task["expires"], "model": str(model), "model_sha256": sha(model),
        "calibration": str(calibration), "calibration_sha256": sha(calibration)})
    if restored != before_close or restored["durable_event_count"] != 5:
        raise ValueError("Actual cold process did not recover the feedback state")
    hold = resumed.tick(2, 0, evidence)
    decision = resumed.tick(3, 0, evidence)
    ticks = [feedback_tick, hold, decision]
    chosen = proposal(arm, feedback, heads) if arm in ("history", "linear_memory") else decision["proposed_repair"]
    admitted = bool(chosen and not any(t["native_abstain"] for t in ticks) and task["budget"] >= 2)
    after = forecast_model.predict(task["condition"], arm, task["expires"], task["budget"], feedback)
    write(directory / "PREDICTION_AFTER_FEEDBACK.json", after)
    permit = {"scope": str(output.resolve()), "destination": str((directory / "correction").resolve()),
        "authorization_source": "User-authorized bounded research execution", "native_authority": "DENY_ALL",
        "native_nonabstention": not any(t["native_abstain"] for t in ticks),
        "media_units_remaining": task["budget"] - 1, "proposed": bool(chosen),
        "execution_admitted": admitted, "production_authorization": False}
    write(directory / "CORRECTION_PERMIT.json", permit)
    decision_at = time.monotonic_ns()
    correction = None
    if admitted:
        correction, final_pixels = generator.deliver(task["public"], 1, directory / "correction")
        final = correction
    else:
        final, final_pixels = initial, pixels
    end = resumed.close()
    transcript = initial_transcript + resumed.transcript
    resumed.finish()
    children_after = resource.getrusage(resource.RUSAGE_CHILDREN)
    scored_at = time.monotonic_ns()
    initial_score = score(audit, initial, pixels, task["private"])
    final_score = score(audit, final, final_pixels, task["private"])
    invocation_ticks = sum(int(r["response"]["result"].get("native_transition_executed", False))
        for r in transcript if r["request"]["command"] == "Tick")
    invocation_ticks += sum(len(b["ticks"]) for b in branches.values())
    forecast_replays = sum(b["ledger_validation_kernel_steps"] + b["original_journal_replayed_prefix_steps"]
                           for b in branches.values())
    cold_replays = 2 * restored["durable_event_count"]
    kernels = invocation_ticks + forecast_replays + cold_replays
    if (invocation_ticks, forecast_replays, cold_replays, kernels) != (16, 24, 10, 50):
        raise ValueError("Actual kernel/recovery work disagrees with the declared charge")
    matches = numerical_projection(ticks) == numerical_projection(branches[str(feedback)]["ticks"])
    if not matches or admitted != bool(chosen and task["expires"] >= 7 and task["budget"] >= 2):
        raise ValueError("Future state or admission differs from actual execution")
    charge = task_cost(bool(chosen), admitted, kernels)
    record = {"name": name, "index": task["index"], "arm": arm, "condition": task["condition"],
        "expires": task["expires"], "budget": task["budget"], "source_ids": task["source_ids"],
        "preference": task["preference"], "true_feedback": real_feedback, "delivered_feedback": feedback,
        "feedback_evidence": evidence, "initial": initial, "correction": correction, "final": final,
        "initial_score": initial_score, "final_score": final_score, "proposed": bool(chosen),
        "admitted": admitted, "denied": bool(chosen and not admitted), "permit": permit,
        "forecast_branches": branches, "actual_ticks": ticks, "before_cold_close": before_close,
        "cold_restored_state": restored, "final_owner_state": end, "future_state_matches": matches,
        "prediction_before": before, "prediction_after": after, "task_charge": charge,
        "net_utility": final_score["utility"] - charge,
        "actual_original_kernel_executions": kernels, "actual_owner_api_ticks": invocation_ticks,
        "forecast_verification_kernel_steps": forecast_replays, "cold_recovery_kernel_steps": cold_replays,
        "actual_generator_calls": 1 + int(admitted), "actual_delivered_files": 2 + 2 * int(admitted),
        "wall_ns": time.perf_counter_ns() - wall, "python_cpu_ns": time.process_time_ns() - cpu,
        "native_child_user_cpu_seconds": children_after.ru_utime - children_before.ru_utime,
        "native_child_system_cpu_seconds": children_after.ru_stime - children_before.ru_stime,
        "chronology": {"initial_delivery": initial["delivered_monotonic_ns"], "feedback": feedback_at,
            "process_restart": restart_at, "late_decision": decision_at,
            "correction_delivery": correction["delivered_monotonic_ns"] if correction else None,
            "private_final_scoring": scored_at},
        "downstream_private_truth_access": False, "native_authority": "DENY_ALL", "production_authorization": False}
    write(directory / "TRANSCRIPT.json", transcript)
    write(directory / "EPISODE.json", record)
    return record
