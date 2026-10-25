"""Descriptive presentation of the registered fixed-history diagnostic.

No action is reselected. Interval arithmetic uses only the already-registered
simultaneous action intervals. The eight histories remain a fixed finite set.
"""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


def mixture_ce(conditional_ce, gamma):
    return float(-np.log(np.exp(-gamma * np.asarray(conditional_ce)).mean()) / gamma)


def summarize(report):
    gamma = report["settings"]["gamma"]
    observers = {}
    for observer, histories in report["observer_results"].items():
        policies = {}
        for name in histories[0]["policies"]:
            values = np.array([history["policies"][name]["evaluation_CE"] for history in histories])
            bounds = np.array([history["policies"][name]["simultaneous_CE_interval"] for history in histories])
            policies[name] = {"mean_conditional_CE": float(values.mean()),
                "mean_conditional_CE_simultaneous_interval": bounds.mean(axis=0).tolist(),
                "uniform_fixed_history_mixture_CE": mixture_ce(values, gamma),
                "uniform_fixed_history_mixture_CE_simultaneous_interval": [mixture_ce(bounds[:, j], gamma) for j in (0, 1)],
                "actions": [history["policies"][name]["action"] for history in histories]}
        comparisons = {}
        for candidate, reference in (("fit_only_public_lookup", "legacy_feedback_q1"),
                                     ("fit_only_public_lookup", "fixed_h1_stop"),
                                     ("fit_only_public_lookup", "fixed_h1_couple"),
                                     ("legacy_feedback_q1", "fixed_h1_stop")):
            intervals = []
            for history in histories:
                left, right = history["policies"][candidate], history["policies"][reference]
                if left["action_index"] == right["action_index"]:
                    intervals.append([0., 0.])
                else:
                    a, b = left["simultaneous_CE_interval"], right["simultaneous_CE_interval"]
                    intervals.append([a[0] - b[1], a[1] - b[0]])
            left, right = policies[candidate], policies[reference]
            a, b = left["uniform_fixed_history_mixture_CE_simultaneous_interval"], right["uniform_fixed_history_mixture_CE_simultaneous_interval"]
            comparisons[candidate + " minus " + reference] = {
                "mean_conditional_CE_difference": left["mean_conditional_CE"] - right["mean_conditional_CE"],
                "mean_conditional_CE_simultaneous_difference_interval": np.mean(intervals, axis=0).tolist(),
                "uniform_fixed_history_mixture_CE_difference": left["uniform_fixed_history_mixture_CE"] - right["uniform_fixed_history_mixture_CE"],
                "uniform_fixed_history_mixture_CE_simultaneous_difference_interval": [a[0] - b[1], a[1] - b[0]]}
        lattice = {}
        for name in histories[0]["empirical_information_lattice"]["CE"]:
            values = [h["empirical_information_lattice"]["CE"][name] for h in histories]
            lattice[name] = {"mean_conditional_CE": float(np.mean(values)),
                             "uniform_fixed_history_mixture_CE": mixture_ce(values, gamma)}
        best_bounds = np.array([h["causal_best_action_CE_interval"] for h in histories])
        observers[observer] = {"frozen_policies": policies, "descriptive_comparisons": comparisons,
            "empirical_information_lattice": lattice,
            "causal_optimum_mean_conditional_CE_simultaneous_interval": best_bounds.mean(0).tolist(),
            "causal_optimum_uniform_fixed_history_mixture_CE_simultaneous_interval": [mixture_ce(best_bounds[:, j], gamma) for j in (0, 1)],
            "fit_lookup_regret_mean_conditional_CE_simultaneous_interval": np.mean(
                [h["policies"]["fit_only_public_lookup"]["finite_history_regret_interval"] for h in histories], axis=0).tolist()}
    mse = [h["critic_predictions"]["legacy_q1"]["conditional_mean_target_MSE_estimate"] for h in report["observer_results"]["primary"]]
    return {"schema": "hepta.abc-next.common-history-descriptive-summary.v1",
        "protocol_sha256": report["protocol_sha256"], "fit_selection_seal_sha256": report["fit_selection_seal_sha256"],
        "interpretation": "Post-run presentation only; no new policy selection, no independent task confidence claim, no change to registered simultaneous bounds",
        "observers": observers, "legacy_Q1_mean_conditional_Z_MSE_estimate": float(np.mean(mse)),
        "legacy_Q1_maximum_history_conditional_Z_MSE_estimate": float(np.max(mse)),
        "legacy_structurally_dominated_H1_semantic_histories": [h["history_index"] for h in report["histories"] if h["selected_actions"]["legacy_feedback_q1"] == 1],
        "generation_draw_examples": report["actual_generator_work"]["pixel_decoder_panel_examples"] // 2,
        "complete_terminal_media_rows": sum(report[name]["complete_required_media_rows"] for name in ("fit_receipt", "evaluation_receipt")),
        "offline_target_scoring_rows_both_observers": 2 * sum(report[name]["target_scoring_rows_per_observer"] for name in ("fit_receipt", "evaluation_receipt")),
        "total_wall_seconds": report["total_wall_ns"] / 1e9, "total_cpu_seconds": report["total_cpu_ns"] / 1e9}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    raw = args.report.read_bytes()
    summary = summarize(json.loads(raw))
    summary["input_report_file_sha256"] = hashlib.sha256(raw).hexdigest()
    summary["presentation_source_file_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    with args.output.open("x") as stream:
        json.dump(summary, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


if __name__ == "__main__":
    main()
