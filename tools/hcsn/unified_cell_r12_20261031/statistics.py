"""Preregistered paired-fit tests; episode counts are never pseudo-replicates."""

import argparse
import itertools
import json
from pathlib import Path

import numpy as np
from scipy.stats import t

from contract import PROTOCOL
from contract import ROOT


def paired_summary(values):
    values = np.asarray(values, dtype=float)
    n = len(values)
    se = values.std(ddof=1) / np.sqrt(n)
    mean = values.mean()
    signs = np.array(list(itertools.product([-1, 1], repeat=n)))
    randomized = (signs * values).mean(axis=1)
    pvalue = np.mean(np.abs(randomized) >= abs(mean) - 1e-14)
    half = t.ppf(0.975, n-1) * se
    return {"n_independent_fits": n, "paired_values": values.tolist(),
            "mean": float(mean), "ci95_student": [float(mean-half), float(mean+half)],
            "one_sided_simultaneous_lower": float(mean-t.ppf(0.975, n-1)*se),
            "exact_sign_flip_p": float(pvalue)}


def summarize(path):
    payload = json.loads(path.read_text())
    if payload["development"]:
        raise ValueError("Development data cannot count as confirmation")
    output = {"schema": "hcsn-r12-registered-analysis-v1", "domains": {},
              "scope": "Eight paired fits in a synthetic known-family finite CTMC task. No real-content or production claim."}
    for domain in ("iid", "ood"):
        rows = [r for r in payload["results"] if r["domain"] == domain]
        if len(rows) != len(PROTOCOL["seeds"]):
            raise ValueError("Missing independent fits")
        arms = {name: {metric: float(np.mean([r["arms"][name][metric] for r in rows]))
                       for metric in ["mean_utility", "mean_accuracy", "read_calls",
                                      "advance_calls", "recovery_read_calls",
                                      "amortized_cpu_per_episode",
                                      "equal_shared_charge_cpu_per_episode"]}
                for name in ["A", "B", "C", "D", "GRU", "SSM", "HMM", "ORACLE"]}
        contrasts = {}
        for name, lhs, rhs in [("B_minus_A", "B", "A"), ("D_minus_C", "D", "C"),
                               ("C_minus_A", "C", "A"), ("D_minus_B", "D", "B"),
                               ("D_minus_HMM", "D", "HMM")]:
            contrasts[name] = paired_summary([r["arms"][lhs]["mean_utility"]-
                                               r["arms"][rhs]["mean_utility"] for r in rows])
        contrasts["interaction"] = paired_summary([
            r["arms"]["D"]["mean_utility"]-r["arms"]["C"]["mean_utility"]-
            r["arms"]["B"]["mean_utility"]+r["arms"]["A"]["mean_utility"] for r in rows])
        accuracy = paired_summary([r["arms"]["D"]["mean_accuracy"]-
                                   r["arms"]["B"]["mean_accuracy"] for r in rows])
        sequence = {core: {metric: float(np.mean([r["sequence"][core][metric] for r in rows]))
                           for metric in ["mean_accuracy", "mean_posterior_ce",
                                          "mean_posterior_content_brier"]}
                    for core in [*PROTOCOL["cores"], "generic_hmm", "true_bayes"]}
        conservative_ratio = arms["D"]["equal_shared_charge_cpu_per_episode"] / arms["B"]["equal_shared_charge_cpu_per_episode"]
        actual_ratio = arms["D"]["amortized_cpu_per_episode"] / arms["B"]["amortized_cpu_per_episode"]
        noninferiority = contrasts["D_minus_B"]["one_sided_simultaneous_lower"] > -PROTOCOL["quality_noninferiority_margin"]
        output["domains"][domain] = {
            "arms": arms, "contrasts": contrasts, "accuracy_D_minus_B": accuracy,
            "sequence": sequence, "ordinary_choices": [r["ordinary_choice"] for r in rows],
            "generic_hmm_torch_parity_max": max(r["generic_hmm_torch_parity_max"] for r in rows),
            "conservative_cost_ratio_D_over_B": conservative_ratio,
            "unique_actual_cost_ratio_D_over_B": actual_ratio,
            "noninferiority_pass": bool(noninferiority),
            "cost_acceptance_pass": bool(noninferiority and conservative_ratio <= PROTOCOL["cost_ratio_maximum"]),
            "D_HMM_action_disagreements": sum(np.sum(np.asarray(r["arms"]["D"]["actions"]) !=
                                                        np.asarray(r["arms"]["HMM"]["actions"])) for r in rows),
        }
    ordered = sorted(output["domains"], key=lambda d: output["domains"][d]["contrasts"]["D_minus_B"]["exact_sign_flip_p"])
    largest = 0.0
    for rank, domain in enumerate(ordered):
        entry = output["domains"][domain]
        result = entry["contrasts"]["D_minus_B"]
        largest = max(largest, min(1.0, (len(ordered)-rank)*result["exact_sign_flip_p"]))
        result["holm_p"] = largest
        entry["quality_gain_acceptance_pass"] = bool(largest <= 0.05 and result["mean"] >= PROTOCOL["quality_effect"])
    output["all_scientific_blockers_closed"] = False
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=ROOT/"evidence/CONFIRMATION.json")
    args = parser.parse_args()
    summary = summarize(args.input)
    destination = args.input.parent / "SUMMARY.json"
    destination.write_text(json.dumps(summary, indent=2, default=lambda x: x.item()) + "\n")
    print(destination)
