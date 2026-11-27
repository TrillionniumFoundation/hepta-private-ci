"""Frozen descriptive TRAIN contrasts; no model/data generation or selection."""

import argparse
import json
from pathlib import Path
import time


METRICS = ("ce", "raw_reward", "joint_success", "text_correct", "image_correct",
           "both_wrong", "wrong_agreement", "wrong_disagreement", "text_only_correct",
           "image_only_correct", "semantic_disagreement", "code_disagreement", "pixel_mse")
SEEDS = (11, 23, 47)


def extract(summary, recipe, seed, law):
    row = summary[f"{recipe}-{seed}"][law]
    return dict(row["means"], greedy_joint_success=row["greedy"]["joint_success"])


def contrast(left, right):
    keys = METRICS + ("greedy_joint_success",)
    seeds = {str(seed): {key: left(seed)[key] - right(seed)[key] for key in keys} for seed in SEEDS}
    means = {key: sum(seeds[str(seed)][key] for seed in SEEDS) / 3 for key in keys}
    return dict(per_seed=seeds, means=means,
                positive_mean_CE_and_joint=means["ce"] > 0 and means["joint_success"] > 0)


def summarize(quality, zero):
    result = dict(scope="same six-model portfolio, reused TRAIN inner rows; descriptive only",
                  formal_confirmation=False, best_full_budget_static_superiority=False,
                  coupling={}, native_training_over_zero={}, native_A_minus_H=None,
                  native_N_minus_A=None, native_A_minus_S=None,
                  independent_objective_contrasts={})
    for family in ("S", "H", "A", "N"):
        result["coupling"][family] = {
            law: contrast(lambda seed: extract(quality[family], "native", seed, "native"),
                          lambda seed: extract(quality[family], "independent", seed, law))
            for law in ("KEEP", "log2")}
        result["native_training_over_zero"][family] = contrast(
            lambda seed: extract(quality[family], "native", seed, "native"),
            lambda seed: dict(zero[str(seed)]["native"]["native"]["means"],
                greedy_joint_success=zero[str(seed)]["native"]["native"]["greedy"]["joint_success"]))
    for left, right, key in (("A", "H", "native_A_minus_H"),
                              ("N", "A", "native_N_minus_A"), ("A", "S", "native_A_minus_S")):
        result[key] = contrast(lambda seed: extract(quality[left], "native", seed, "native"),
                               lambda seed: extract(quality[right], "native", seed, "native"))
        result["independent_objective_contrasts"][left + "_minus_" + right] = {
            law: contrast(lambda seed: extract(quality[left], "independent", seed, law),
                          lambda seed: extract(quality[right], "independent", seed, law))
            for law in ("KEEP", "log2")}
    result["TRAIN_hypotheses"] = dict(
        coupling_vs_strong_S_H_log2=all(result["coupling"][f]["log2"]["positive_mean_CE_and_joint"] for f in ("S", "H")),
        native_additive_A_minus_H=result["native_A_minus_H"]["positive_mean_CE_and_joint"],
        native_entropic_N_minus_A=result["native_N_minus_A"]["positive_mean_CE_and_joint"])
    result["all_three_TRAIN_hypotheses"] = all(result["TRAIN_hypotheses"].values())
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run", type=Path)
    args = parser.parse_args()
    begin = time.process_time()
    quality = json.loads((args.run / "quality-summary.json").read_text())
    zero = json.loads((args.run / "zero-summary.json").read_text())
    result = summarize(quality, zero)
    result["saved_output_analysis_CPU_before_receipt"] = time.process_time() - begin
    (args.run / "analysis.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result["TRAIN_hypotheses"], sort_keys=True))
    raise SystemExit(0 if result["all_three_TRAIN_hypotheses"] else 2)


if __name__ == "__main__":
    main()
