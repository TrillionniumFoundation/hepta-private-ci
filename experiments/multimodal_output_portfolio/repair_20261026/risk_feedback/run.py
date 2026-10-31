"""Run the frozen finite study, retaining every generated bundle and readback."""
import argparse
import json
from pathlib import Path
import resource
import time

import numpy as np

from .media import emit, file_sha, readback
from .model import (PublicTask, certainty_equivalent, choose_continuation, choose_initial,
                    digest, exact_diagnostic, fit_feedback, fit_posterior, softmax)


def save(path, value):
    Path(path).write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def feedback_training(spec, output):
    rng = np.random.default_rng(spec["feedback_seed"])
    feedback, labels, rows = [], [], []
    for i in range(spec["feedback_training_rows"]):
        action = int(rng.integers(4))
        fault = int(rng.choice(3, p=spec["fault_probabilities"]))
        root = output / "training-media" / str(i)
        paths = emit(root / "first", action, fault)
        before = readback(paths)
        repaired_paths = emit(root / "repair", action)
        after = readback(repaired_paths)
        gain = (spec["terminal_mismatch_penalty"][before["fault_class"]]
                - spec["terminal_mismatch_penalty"][after["fault_class"]] - spec["repair_cost"])
        feedback.append(spec["numeric_feedback_by_fault"][before["fault_class"]])
        labels.append(int(gain > 0))
        rows.append({"row": i, "before": before, "after": after,
                     "target_free_paired_repair_gain": gain, "hidden_target_supplied": False})
    save(output / "FEEDBACK_TRAINING.json", rows)
    parameters, training = fit_feedback(np.asarray(feedback), np.asarray(labels), spec)
    training["training_receipts_sha256"] = file_sha(output / "FEEDBACK_TRAINING.json")
    training["actual_output_bundles"] = 2 * len(rows)
    return parameters, training


def episode(public, *, arm, environment_fault, shuffled_feedback, posterior, policy, spec, directory):
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    action, law, values = choose_initial(public, posterior, "mean" if arm == "mean_numeric" else "risk", spec)
    chosen_ns = time.perf_counter_ns()
    first_paths = emit(directory / "first", action, environment_fault)
    first = readback(first_paths)
    readback_ns = time.perf_counter_ns()
    scalar = spec["numeric_feedback_by_fault"][first["fault_class"]]
    receipt = {"public_observation": first, "numeric_feedback": scalar,
               "public_observation_sha256": digest(first), "readback_ns": readback_ns,
               "hidden_target_supplied": False, "already_delivered_output_is_immutable": True}
    save(directory / "FEEDBACK_COMMITTED.json", receipt)
    committed_ns = time.perf_counter_ns()
    effective = 0.0 if arm == "risk_zero" else shuffled_feedback if arm == "risk_shuffled" else scalar
    next_action = choose_continuation(arm, first, effective, policy, spec)
    continuation_ns = time.perf_counter_ns()
    if next_action == "repair":
        final_paths = emit(directory / "repair", action)
        final = readback(final_paths)
    else:
        final = first
    end = time.perf_counter_ns()
    ledger = {"arm": arm, "public_cue": public.cue, "initial_action": action,
        "posterior": law, "initial_values": values, "continuation": next_action,
        "first_observation": first, "final_observation": final,
        "observed_feedback": scalar, "effective_scalar_for_numeric_path": effective,
        "initial_choice_ns": chosen_ns, "first_readback_ns": readback_ns,
        "feedback_committed_ns": committed_ns, "continuation_choice_ns": continuation_ns,
        "completed_ns": end, "wall_ns": end - began, "cpu_ns": time.process_time_ns() - cpu,
        "target_supplied_to_online": False, "actual_output_bundles": 1 + int(next_action == "repair"),
        "same_public_observation_available_to_all_control_paths": True}
    save(directory / "EPISODE.json", ledger)
    return ledger


def private_score(ledger, target, spec):
    # This function is invoked only after the final episode receipt is saved.
    semantic_code = ledger["final_observation"]["codes"]["text"]
    first_fault = ledger["first_observation"]["fault_class"]
    final_fault = ledger["final_observation"]["fault_class"]
    semantic = spec["semantic_utility_action_by_target"][semantic_code][target]
    costs = {"initial_action": spec["initial_action_cost"][ledger["initial_action"]],
        "stochastic_channel_charge": spec["channel_cost_by_fault"][first_fault],
        "irreversible_first_delivery_damage": spec["irreversible_first_delivery_damage"][first_fault],
        "repair": spec["repair_cost"] * (ledger["continuation"] == "repair")}
    return {"private_target": int(target), "semantic_utility": semantic, "declared_charges": costs,
        "terminal_mismatch_penalty": spec["terminal_mismatch_penalty"][final_fault],
        "net_return": semantic - sum(costs.values()) - spec["terminal_mismatch_penalty"][final_fault],
        "private_score_started_ns": time.perf_counter_ns()}


def summarize(rows, spec):
    grouped = {arm: sorted((r for r in rows if r["arm"] == arm), key=lambda r: r["case"])
               for arm in spec["arms"]}
    arrays = {arm: np.array([r["net_return"] for r in records]) for arm, records in grouped.items()}
    statistics = {}
    for arm, values in arrays.items():
        records = grouped[arm]
        statistics[arm] = {"rows": len(records), "mean_net_return": float(values.mean()),
            "certainty_equivalent": float(certainty_equivalent(values, spec["gamma"])),
            "p05_net_return": float(np.quantile(values, .05)), "worst_net_return": float(values.min()),
            "severe_loss_count": int((values < -3).sum()),
            "repair_count": sum(r["continuation"] == "repair" for r in records),
            "actual_output_bundles": sum(r["actual_output_bundles"] for r in records),
            "wall_ns": sum(r["wall_ns"] for r in records), "cpu_ns": sum(r["cpu_ns"] for r in records)}
    rng = np.random.default_rng(spec["bootstrap_seed"])
    indices = rng.integers(len(grouped["risk_numeric"]), size=(spec["bootstrap_replicates"], len(grouped["risk_numeric"])))
    intervals = {}
    for reference, metric in (("mean_numeric", "ce"), ("risk_zero", "mean"),
                              ("risk_shuffled", "mean"), ("risk_history", "mean")):
        candidate, baseline = arrays["risk_numeric"], arrays[reference]
        samples = ((candidate - baseline)[indices].mean(1) if metric == "mean" else
                   certainty_equivalent(candidate[indices], spec["gamma"])
                   - certainty_equivalent(baseline[indices], spec["gamma"]))
        tail = (1 - spec["paired_interval"]) / 2
        estimate = (float((candidate - baseline).mean()) if metric == "mean" else
                    float(certainty_equivalent(candidate, spec["gamma"]) - certainty_equivalent(baseline, spec["gamma"])))
        intervals[reference] = {"metric": metric, "difference": estimate,
            "interval": np.quantile(samples, [tail, 1 - tail]).tolist(),
            "prespecified_primary": reference in ("mean_numeric", "risk_zero"),
            "positive_lower_bound": bool(np.quantile(samples, tail) > 0)}
    disagreements = {arm: sum(a["continuation"] != b["continuation"]
        for a, b in zip(grouped["risk_numeric"], grouped[arm])) for arm in spec["arms"] if arm != "mean_numeric"}
    return statistics, intervals, disagreements


def run(output):
    source = Path(__file__).parent
    spec_path = source / "PROTOCOL.json"
    spec = json.loads(spec_path.read_text())
    output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    pins = {str(p.relative_to(source)): file_sha(p) for p in source.glob("*.py")}
    pins["PROTOCOL.json"] = file_sha(spec_path)
    bellman = source.parents[1] / "advance_20261026/control/bellman.py"
    pins["upstream_bellman.py"] = file_sha(bellman)
    save(output / "FROZEN_REGISTRATION.json", {"registered_ns": time.time_ns(), "protocol": spec,
        "source_pins": pins, "run_count": 1, "evaluation_has_not_started": True})
    posterior, posterior_training = fit_posterior(spec)
    policy, policy_training = feedback_training(spec, output)
    save(output / "PARAMETERS.json", {"posterior": posterior.tolist(), "feedback_policy": policy.tolist()})
    saved = json.loads((output / "PARAMETERS.json").read_text())
    posterior, policy = np.array(saved["posterior"]), np.array(saved["feedback_policy"])
    if digest(posterior.tolist()) != posterior_training["final_parameter_sha256"] or digest(policy.tolist()) != policy_training["final_parameter_sha256"]:
        raise ValueError("Saved learned parameter reload mismatch")
    rng = np.random.default_rng(spec["evaluation_seed"])
    cues = rng.choice(4, spec["evaluation_rows"], p=spec["cue_probabilities"])
    targets = [int(rng.choice(3, p=spec["target_law_by_cue"][c])) for c in cues]
    faults = rng.choice(3, len(cues), p=spec["fault_probabilities"])
    raw_feedback = np.array(spec["numeric_feedback_by_fault"])[faults]
    shuffled = np.random.default_rng(spec["shuffle_seed"]).permutation(raw_feedback)
    rows = []
    for i, cue in enumerate(cues):
        for arm in spec["arms"]:
            directory = output / "evaluation" / f"case-{i:04d}" / arm
            record = episode(PublicTask(int(cue)), arm=arm, environment_fault=int(faults[i]),
                shuffled_feedback=float(shuffled[i]), posterior=posterior, policy=policy, spec=spec, directory=directory)
            score = private_score(record, targets[i], spec)
            score["episode_sha256"] = file_sha(directory / "EPISODE.json")
            save(directory / "PRIVATE_SCORE.json", score)
            rows.append({"case": i, **record, **score})
        if (i + 1) % 64 == 0:
            print(json.dumps({"completed_cases": i + 1, "episodes": len(rows)}), flush=True)
    save(output / "ROWS.json", rows)
    statistics, comparisons, disagreements = summarize(rows, spec)
    diagnostics = [exact_diagnostic(spec, law) for law in spec["target_law_by_cue"]]
    decisions = {profile: [choose_initial(PublicTask(c), posterior, profile, spec)[0] for c in range(4)] for profile in ("mean", "risk")}
    binary_checks = []
    for p in np.linspace(0, 1, 101):
        binary_checks.append(int(np.argmax([p, 1-p])) == int(np.argmin([1-p+p*np.exp(-spec["gamma"]), p+(1-p)*np.exp(-spec["gamma"])])))
    chronology = all(r["initial_choice_ns"] < r["first_readback_ns"] < r["feedback_committed_ns"] < r["continuation_choice_ns"] < r["completed_ns"] < r["private_score_started_ns"] for r in rows)
    unchanged = all(file_sha(source / p) == h for p, h in pins.items() if p != "upstream_bellman.py") and file_sha(bellman) == pins["upstream_bellman.py"]
    result = {"schema": "hepta.repair.risk-feedback.result.v1", "status": "completed",
        "protocol_sha256": pins["PROTOCOL.json"], "registration_sha256": file_sha(output / "FROZEN_REGISTRATION.json"),
        "training": {"posterior": posterior_training, "feedback": policy_training}, "source_unchanged": unchanged,
        "learned_decisions_by_cue": decisions, "risk_action_ranking_identified": decisions["mean"] != decisions["risk"],
        "binary_equal_cost_negative_control_agrees": all(binary_checks), "finite_bellman_enumeration": diagnostics,
        "actual_evaluation_episodes": len(rows), "actual_media_files": 4 * (sum(r["actual_output_bundles"] for r in rows) + policy_training["actual_output_bundles"]),
        "post_delivery_continuation_chronology_passed": chronology, "statistics": statistics,
        "comparisons": comparisons, "continuation_disagreements_with_numeric": disagreements,
        "numeric_unique_benefit_over_same_information_history_control": comparisons["risk_history"]["positive_lower_bound"],
        "real_parameter_updates": True, "real_file_generation_and_readback": True, "learned_media_generation": False,
        "synthetic_task_and_fault_law": True, "old_v6_reproduced": False, "native_owner_integration": False,
        "natural_multimodal_generalization_proven": False, "all_blockers_closed": False,
        "rows_sha256": file_sha(output / "ROWS.json"), "wall_ns": time.perf_counter_ns() - started,
        "cpu_ns": time.process_time_ns() - cpu, "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024}
    save(output / "RESULT.json", result)
    if not unchanged or not chronology or not all(binary_checks) or any(d["absolute_error"] > 1e-8 for d in diagnostics):
        raise ValueError("Execution or mathematical verification failed; retained results must not be promoted")
    print(json.dumps({k: result[k] for k in ("status", "actual_evaluation_episodes", "actual_media_files", "risk_action_ranking_identified", "numeric_unique_benefit_over_same_information_history_control")}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        run(args.output)
    except Exception as error:
        if args.output.exists():
            save(args.output / "FAILED.json", {"error": f"{type(error).__name__}: {error}", "raw_evidence_retained": True})
        raise
