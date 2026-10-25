"""Frozen complete-census analysis; only aggregate evidence is published."""

import argparse
from collections import Counter
import json
from pathlib import Path

import numpy as np

from ...abc_recovery.statistics import crossed_bootstrap, loss_tails, paired_comparison, summarize_utility
from .facts import ACTIONS, GENERATOR_ACTIONS, PublicFrame, observed_metrics
from .policy import MODES, SEEDS, PolicyBundle, predict
from .audit import write_json
from .registration import verify_final_freeze
from .speech import sha256
from .stream import verify_output


METRICS = ("net_utility", "utility", "loss", "joint_task_success", "required_semantic_completion",
           "text_fact_accuracy", "audio_fact_accuracy", "fact_agreement")
FIXED = tuple("fixed/" + action for action in GENERATOR_ACTIONS) + (
    "fixed/best_fit", "public/assumed_prior_reference", "mechanism/clamped_fuse", "oracle_offline")
CONDITIONS = MODES + FIXED


def distribution(values, divisor=1.0):
    array = np.asarray(values) / divisor
    return {"mean": float(array.mean()), "p50": float(np.quantile(array, .5)),
            "p95": float(np.quantile(array, .95)), "sum": float(array.sum()), "n_rows": array.size}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("freeze", "final-protocol", "policies", "qualification", "evaluation-run", "fit-run", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--timing-report", type=Path)
    args = parser.parse_args()
    protocol = verify_final_freeze(args.final_protocol, args.freeze, args.policies, args.qualification)
    policies = PolicyBundle.load(args.policies)
    sources = json.loads((args.freeze / "sources.json").read_text())["roles"]["evaluation"]
    source_index = {source["source_id"]: index for index, source in enumerate(sources)}
    shape = (len(SEEDS), len(sources), 1, 4)
    cubes = {observer: {condition: {metric: np.full(shape, np.nan) for metric in METRICS}
                        for condition in CONDITIONS} for observer in ("external", "online")}
    costs = {condition: {clock: np.full(shape, np.nan) for clock in ("wall_ns", "cpu_ns")}
             for condition in CONDITIONS}
    audio_durations = {condition: np.full(shape, np.nan) for condition in CONDITIONS}
    choices = {condition: Counter() for condition in CONDITIONS}
    seen, mismatch_rows, errors, wave_hashes = set(), [], [], set()
    total_terminal = {observer: {clock: 0 for clock in ("wall_ns", "cpu_ns")} for observer in ("external", "online")}
    model_calls, physical_paths, case_costs, probe_confidence = 0, 0, [], []
    value_errors = {observer: {mode: [] for mode in MODES} for observer in ("external", "online")}
    for line in (args.evaluation_run / "cases.jsonl").read_text().splitlines():
        entry = json.loads(line)
        if sha256(entry["case_path"]) != entry["case_sha256"]:
            raise ValueError("Frozen candidate evidence changed")
        case_path = Path(entry["case_path"])
        case = json.loads(case_path.read_text())
        key = case["source_id"], case["scenario"]
        if key in seen or key[0] not in source_index or key[1] not in range(4):
            raise ValueError("Duplicate or out-of-census case")
        seen.add(key)
        index, scenario = source_index[key[0]], key[1]
        if set(case["outcomes"]) != set(ACTIONS):
            raise ValueError("A real candidate path is absent")
        frame = PublicFrame(**case["public_frame"])
        if case["choices"] != policies.feedback_decisions(frame, policies.initial_decisions(frame)):
            raise ValueError("Recorded decision differs from frozen public policy")
        decision = json.loads((case_path.parent / "decision.json").read_text())
        if not decision["prefix_committed_ns"] < decision["fresh_released_ns"] <= decision["decision_done_ns"]:
            raise ValueError("Decision/prefix causal ordering is invalid")
        if case["decision_sha256"] != sha256(case_path.parent / "decision.json"):
            raise ValueError("A previously committed policy decision changed")
        model_calls += 2
        probe_confidence.append(frame.probe_confidence)
        case_costs.append(case["entire_candidate_matrix_cost"])
        for action, outcome in case["outcomes"].items():
            directory = case_path.parent / action / "committed-output"
            verified = verify_output(directory)
            if verified != outcome["output"] or not outcome["physical_complete"]:
                raise ValueError("Actual candidate output differs or is incomplete")
            physical_paths += 1
            model_calls += len(outcome["tts_calls"])
            wave_hashes.add(verified["wave_sha256"])
            for observer in ("external", "online"):
                observation = outcome[observer + "_terminal_observation"]
                if observation["input_sha256"] != verified["wave_sha256"]:
                    raise ValueError("Independent content observer did not read the actual committed WAV")
                expected = observed_metrics(sources[index]["fact"], (directory / "output.txt").read_text(),
                                            observation["transcript"], outcome["physical_complete"])
                for metric in METRICS:
                    if metric != "net_utility" and expected[metric] != outcome[observer + "_metrics"][metric]:
                        raise ValueError("Stored content score differs from independent transcript")
                for clock in ("wall_ns", "cpu_ns"):
                    total_terminal[observer][clock] += observation[clock]
            external_metrics, online_metrics = outcome["external_metrics"], outcome["online_metrics"]
            if external_metrics["audio_fact"] != online_metrics["audio_fact"]:
                mismatch_rows.append({"source_id": key[0], "scenario": scenario, "action": action,
                                      "external": outcome["external_terminal_observation"]["transcript"],
                                      "online": outcome["online_terminal_observation"]["transcript"]})
            if external_metrics["audio_fact"] != external_metrics["text_fact"] and len(errors) < 12:
                errors.append({"source_id": key[0], "scenario": scenario, "action": action,
                               "committed_text": outcome["actual_text"],
                               "external_transcript": outcome["external_terminal_observation"]["transcript"],
                               "metrics": external_metrics})
        for observer in ("external", "online"):
            actual_z = np.exp(-2 * np.asarray([case["outcomes"][action][observer + "_metrics"]["net_utility"]
                                               for action in GENERATOR_ACTIONS]))
            for mode in MODES:
                for model in policies.payload["models"][mode]:
                    value_errors[observer][mode].extend((predict(model, frame, mode) - actual_z).tolist())
            oracle = max(GENERATOR_ACTIONS, key=lambda action: case["outcomes"][action][observer + "_metrics"]["net_utility"])
            for condition in CONDITIONS:
                for seed_index, seed in enumerate(SEEDS):
                    action = oracle if condition == "oracle_offline" else case["choices"].get(condition if condition in FIXED else f"{condition}/{seed}")
                    outcome = case["outcomes"][action]
                    for metric in METRICS:
                        cubes[observer][condition][metric][seed_index, index, 0, scenario] = outcome[observer + "_metrics"][metric]
                    if observer == "external":
                        choices[condition][action] += 1
                        charged = case["entire_candidate_matrix_cost"] if condition == "oracle_offline" else outcome["online_component_cost"]
                        for clock in ("wall_ns", "cpu_ns"):
                            costs[condition][clock][seed_index, index, 0, scenario] = charged[clock]
                        audio_durations[condition][seed_index, index, 0, scenario] = outcome["output"]["duration_seconds"]
    if len(seen) != 64 * 4 or any(not np.isfinite(array).all() for rows in cubes.values()
                                  for row in rows.values() for array in row.values()):
        raise ValueError("Incomplete frozen source/seed/scenario census")
    bootstrap = crossed_bootstrap(5, 64, replicates=4000, seed=2026102503)
    summaries, contrasts = {}, {}
    for observer, conditions in cubes.items():
        summaries[observer] = {}
        for condition, metric in conditions.items():
            summaries[observer][condition] = {"net_utility": summarize_utility(metric["net_utility"]),
                "metrics": {name: float(values.mean()) for name, values in metric.items()},
                "loss_tails": loss_tails(metric["loss"]),
                "selected_action_rows": dict(choices[condition]),
                "generated_audio_duration_seconds": distribution(audio_durations[condition]),
                "component_cost_ms": {clock: distribution(costs[condition][clock], 1e6) for clock in costs[condition]}}
        comparisons = list(protocol["primary_comparisons"]) + [
            {"name": "initial_gate_increment", "candidate": "feedback", "reference": "initial_only"},
            {"name": "probe_increment", "candidate": "feedback", "reference": "feedback_no_probe"},
            {"name": "declared_prior_reference", "candidate": "feedback", "reference": "public/assumed_prior_reference"},
            {"name": "oracle_vs_fixed", "candidate": "oracle_offline", "reference": "fixed/best_fit"},
            {"name": "oracle_vs_feedback", "candidate": "oracle_offline", "reference": "feedback"}]
        contrasts[observer] = {}
        for position, contrast in enumerate(comparisons):
            candidate, reference = conditions[contrast["candidate"]], conditions[contrast["reference"]]
            confidence = .975 if observer == "external" and position < 2 else .95
            ce = paired_comparison(candidate["net_utility"], reference["net_utility"], confidence=confidence, bootstrap=bootstrap)
            success = paired_comparison(candidate["joint_task_success"], reference["joint_task_success"],
                                        estimand="success_rate", confidence=.95, bootstrap=bootstrap)
            contrasts[observer][contrast["name"]] = {**contrast, "net_ce": ce, "success": success,
                                                     "primary_positive_gate_passed": bool(observer == "external" and position < 2 and ce["interval"][0] > 0)}
    qualification = json.loads(args.qualification.read_text())
    compact_qual = {key: qualification[key] for key in ("passed", "checks", "summary", "loads", "wall_ns_before_report", "cpu_ns_before_report")}
    summary = {"schema": "hepta.abc3.text-speech-summary.v1", "final_protocol_sha256": sha256(args.final_protocol),
               "policies_sha256": sha256(args.policies), "qualification": compact_qual,
               "census": {"fact_groups": 64, "cases": len(seen), "actual_paths": physical_paths,
                          "actual_tts_api_calls": model_calls, "distinct_final_wave_hashes": len(wave_hashes),
                          "api_calls_are_not_sentence_level_acoustic_forward_passes": True,
                          "template_families": 1, "voices": 1, "policy_seeds": SEEDS},
               "bootstrap_unit": "64 held-out fact combinations; same template/voice fixed; no general template/source inference",
               "summaries": summaries, "contrasts": contrasts,
               "observer_disagreement": {"paths": len(mismatch_rows), "fraction": len(mismatch_rows) / physical_paths,
                                         "first_12_examples": mismatch_rows[:12]},
               "external_text_audio_disagreement_examples": errors, "probe_confidence": distribution(probe_confidence),
               "positive_value_prediction_diagnostics": {observer: {mode: {
                   "realized_target_mse": float(np.mean(np.asarray(values) ** 2)),
                   "mean_prediction_minus_realized_target": float(np.mean(values)),
                   "scope": "one realized exponential-utility target per candidate; this is not a conditional-expectation oracle or a proved calibration bound"}
                   for mode, values in modes.items()} for observer, modes in value_errors.items()},
               "offline_terminal_asr_total_cost": total_terminal,
               "matrix_total_case_cost": {clock: sum(row[clock] for row in case_costs) for clock in ("wall_ns", "cpu_ns")},
               "fit_run": json.loads((args.fit_run / "run_complete.json").read_text()),
               "evaluation_run": json.loads((args.evaluation_run / "run_complete.json").read_text()),
               "value_fit_cost": {key: policies.payload[key] for key in ("wall_ns_before_report", "cpu_ns_before_report")},
               "fit_selected_fixed_action": policies.payload["best_fixed_action"],
               "timing": None if not args.timing_report else {key: value for key, value in json.loads(args.timing_report.read_text()).items() if key != "rows"},
               "checks": {"complete_census": True, "immutable_prefix_and_spans": True,
                          "independent_asr_reads_actual_output": True, "decisions_match_frozen_public_models": True,
                          "decisions_precede_future_outputs": True, "external_evaluator_never_enters_fitting_or_policy": True},
               "economic_cost_dominance_claimed": False, "end_to_end_acoustic_training_claimed": False,
               "video_or_av_sync_claimed": False}
    write_json(args.output, summary)
    print(json.dumps({"summary_sha256": sha256(args.output), "primary": contrasts["external"],
                      "held_out_fact_groups": 64, "fixed_template_families": 1}))


if __name__ == "__main__":
    main()
