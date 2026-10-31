"""Descriptive aggregation of all registered full-joint fits and evaluations.

This post-freeze reporter never trains or evaluates a policy. It reads the
completed records and retains all five seeds; no hypothesis, threshold,
candidate selection, or confidence claim is added here.
"""

import argparse
import gzip
import json
from pathlib import Path

import numpy as np

from .full_joint import HERE, MODES, SEEDS, sha, verify_registration, write


def mean(values):
    return float(np.asarray(values, dtype=np.float64).mean())


def summarize(evidence):
    verify_registration(evidence / "REGISTRATION.json")
    manifest = json.loads((evidence / "CANDIDATES.json").read_text())
    cases = {}
    for entry in manifest["cases"]:
        key = f"{entry['mode']}_{entry['seed']}"
        folder = evidence / "cases" / key
        for label, filename in (("initial", "initial.json"), ("final", "final.json"), ("training", "TRAINING.json")):
            if sha(folder / filename) != entry[f"{label}_sha256"]:
                raise ValueError(f"Frozen {label} changed: {key}")
        training = json.loads((folder / "TRAINING.json").read_text())
        evaluation = json.loads((folder / "EVALUATION.json").read_text())
        gradients = np.load(folder / "gradients.npz")["before_clip"]
        if training["updates_applied"] != 30 or len(training["curves"]) != 31 or gradients.shape[0] != 30:
            raise ValueError(f"Incomplete training: {key}")
        if training["failure"] is not None or not np.isfinite(gradients).all():
            raise ValueError(f"Failed training: {key}")
        with gzip.open(folder / "paired_rollouts.jsonl.gz", "rt") as stream:
            paths = [json.loads(line) for line in stream]
        if len(paths) != 64 or any(set(path["runs"]) != {"initial", "final"} for path in paths):
            raise ValueError(f"Incomplete paired rollouts: {key}")
        cases[key] = {"training": training, "evaluation": evaluation, "paths": paths}

    exact = {}
    for regime in ("nominal", "heldout"):
        exact[regime] = {}
        for policy in ("soft", "greedy"):
            exact[regime][policy] = {}
            for mode in MODES:
                per_fit = []
                for seed in SEEDS:
                    record = cases[f"{mode}_{seed}"]["evaluation"]["exact"]
                    initial = record["initial"][regime][policy]["mean"]
                    final = record["final"][regime][policy]["mean"]
                    per_fit.append({"fit_seed": seed, "initial": initial, "final": final,
                                    "change": (np.asarray(final)-np.asarray(initial)).tolist()})
                exact[regime][policy][mode] = {"per_fit": per_fit,
                    "mean_initial": np.mean([x["initial"] for x in per_fit], axis=0).tolist(),
                    "mean_final": np.mean([x["final"] for x in per_fit], axis=0).tolist(),
                    "mean_change": np.mean([x["change"] for x in per_fit], axis=0).tolist()}

    comparisons = {}
    for other in ("clocked", "direct"):
        comparisons[f"first_passage_minus_{other}"] = {}
        for regime in exact:
            comparisons[f"first_passage_minus_{other}"][regime] = {}
            for policy in exact[regime]:
                per_fit = [{"fit_seed": seed,
                    "metrics_difference": (np.asarray(exact[regime][policy]["first_passage"]["per_fit"][i]["final"])
                                           -np.asarray(exact[regime][policy][other]["per_fit"][i]["final"])).tolist()}
                           for i, seed in enumerate(SEEDS)]
                comparisons[f"first_passage_minus_{other}"][regime][policy] = {
                    "per_fit": per_fit,
                    "mean_difference": np.mean([x["metrics_difference"] for x in per_fit], axis=0).tolist()}

    rollout = {}
    for regime in exact:
        rollout[regime] = {}
        for mode in MODES:
            fits = [cases[f"{mode}_{seed}"]["evaluation"]["actual_hard_soft_rollouts"][regime] for seed in SEEDS]
            rollout[regime][mode] = {"per_fit": [{"fit_seed": seed, **fit} for seed, fit in zip(SEEDS, fits)],
                "mean_initial": mean([fit["initial"]["mean"] for fit in fits]),
                "mean_final": mean([fit["final"]["mean"] for fit in fits]),
                "mean_paired_change": mean([fit["paired_change"]["mean"] for fit in fits]),
                "mean_initial_sample_minus_exact": mean([fit["initial"]["sample_minus_exact_soft"] for fit in fits]),
                "mean_final_sample_minus_exact": mean([fit["final"]["sample_minus_exact_soft"] for fit in fits])}
    pair_keys = ("regime", "world_seed", "latent_seed", "configuration_index")
    pairing = all(
        [[path[key] for key in pair_keys] for path in cases[f"{mode}_{seed}"]["paths"]]
        == [[path[key] for key in pair_keys] for path in cases[f"direct_{seed}"]["paths"]]
        for mode in MODES for seed in SEEDS)

    training_summary = {}
    for mode in MODES:
        reports = [cases[f"{mode}_{seed}"]["training"] for seed in SEEDS]
        training_summary[mode] = {
            "fits": len(reports), "updates": sum(r["updates_applied"] for r in reports),
            "max_gradient_norm": max(row["unclipped_gradient_norm"] for r in reports for row in r["curves"][:-1]),
            "decreasing_updates": sum(b["exact_soft_utility"] < a["exact_soft_utility"]
                                      for r in reports for a, b in zip(r["curves"], r["curves"][1:])),
            "inactive_max_parameter_change": max(change["max_absolute_change"] for r in reports
                for change in r["parameter_changes"].values() if not change["requires_grad"]),
            "per_fit_parameter_changes": [{"fit_seed": r["fit_seed"], "changes": r["parameter_changes"]} for r in reports],
            "max_process_peak_rss_kib": max(r["peak_process_rss_kib"] for r in reports),
            "train_full_process": json.loads((evidence / f"launch_{mode}.json").read_text()),
            "evaluation_full_process": json.loads((evidence / f"evaluate_launch_{mode}.json").read_text())}

    return {"schema": "hepta.full-joint.descriptive-summary.v1", "reporter_sha256": sha(__file__),
        "registration_sha256": sha(evidence / "REGISTRATION.json"),
        "candidate_manifest_sha256": sha(evidence / "CANDIDATES.json"),
        "metric_order": ["registered utility", "decisions", "events"],
        "training": training_summary, "exact": exact, "comparisons": comparisons,
        "actual_hard_soft_rollouts": rollout, "trajectory_count": sum(2*len(c["paths"]) for c in cases.values()),
        "cross_family_world_latent_config_pairing": pairing,
        "scope": "All registered update-30 fits, exact finite-DAG values and small paired deployment diagnostics. Descriptive appendix after primary confirmation; no significance, superiority or noninferiority claim. Equal fit/configuration weights.",
        "resource_correction": "Use SELF/CHILDREN RUSAGE and step wall timings only. Original launch /proc namespace-PID VmRSS/VmHWM observations are invalid; resource_replay.json preserves the diagnosis and independent first-step replay."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, default=HERE / "evidence/full_joint_v1")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = summarize(args.evidence)
    write(args.output or args.evidence / "SUMMARY.json", report)
    print(json.dumps({"trajectories": report["trajectory_count"],
                      "pairing": report["cross_family_world_latent_config_pairing"]}))


if __name__ == "__main__":
    main()
