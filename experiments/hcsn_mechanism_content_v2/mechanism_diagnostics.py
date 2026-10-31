"""Predeclared grid diagnostics for renewal content, with independent labels.

Numerical work is density-integrand evaluations, never network updates.
Point collapse and reset/refractory removals are named model ablations, not
substitutes for the strong ordinary gated baseline. No natural-AV claim follows.
"""

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import resource
import time

import numpy as np
import torch

from .mechanism import transition_matrix, write_json, write_jsonl
from .renewal import (GatedPropagator, LearnedCore, Physics, RenewalCore,
                      content_from_counts, sample_counts, shared_calibration)


VARIANTS = ("analytic_full_distribution", "ordinary_gated", "matched_numerical_integral",
            "mean_count_point_collapse", "absorbing_no_repeat", "future_refractory_removed")


def grid_case(index, seed, samples, classes=5):
    """Fixed factor grid; first two cases isolate equal-mean/variance posteriors."""
    nu = -[.25, .5, .85, 1.15][index % 4]
    sigma = [.18, .35, .55, .72][(index // 4) % 4]
    reset = [.4, .6, .9, 1.2][(index * 7 // 3) % 4]
    delay = [.13, .18, .24, .3][(index * 11 // 5) % 4]
    horizon = [.08, .2, .4, .7, 1.1, 1.6, 2.3, 3.0][(index // 16) % 8]
    x = [.08, .25, .55, .9, 1.5, 2.5][(index * 5 // 7) % 6]
    remaining = delay / 2 if index % 5 == 4 else 0.
    gaps, weights = ([reset], [1.]) if remaining else ([x], [1.])
    if index % 4 == 1 and remaining == 0:
        gaps, weights = [x / 2, x, 1.5 * x], [.25, .5, .25]
    if index in (0, 1):
        nu, sigma, reset, delay, horizon, remaining = -.4, .35, .6, .2, .6, 0.
        gaps, weights = ([.5, 1.5], [.5, .5]) if index == 0 else (
            [.1, 1., 1.9], [.154320987654321, .691358024691358, .154320987654321])
    truth = Physics(nu, sigma, reset, delay)
    calibration_rng = np.random.default_rng(np.random.SeedSequence([seed, 0 if index < 2 else index, 71]))
    started = time.perf_counter()
    estimates, calibration = shared_calibration(calibration_rng, truth)
    calibration["wall_seconds"] = time.perf_counter() - started
    rng = np.random.default_rng(np.random.SeedSequence([seed, index, 83]))
    components = rng.choice(len(gaps), size=samples, p=weights)
    counts = np.empty(samples, dtype=int)
    for j, gap in enumerate(gaps):
        chosen = components == j
        counts[chosen] = sample_counts(rng, truth, gap, horizon, int(chosen.sum()), remaining)
    initial_class = 0 if index < 2 else index % classes
    content = np.full(samples, initial_class, dtype=int)
    matrix = transition_matrix(classes)
    cumulative = matrix.cumsum(axis=0)
    for n in range(1, int(counts.max()) + 1):
        active = counts >= n
        random = rng.uniform(size=int(active.sum()))
        content[active] = (random[:, None] > cumulative[:, content[active]].T).sum(axis=1)
    return {"case": index, "seed": seed, "horizon": horizon,
            "gaps": gaps, "weights": weights, "refractory_remaining": remaining,
            "posterior_mean": float(np.dot(gaps, weights)),
            "posterior_variance": float(np.dot(np.square(gaps), weights) - np.dot(gaps, weights)**2),
            "shared_calibration": calibration, "initial_class": initial_class,
            "label_source": "independent_IG_and_sampled_Markov_content_transitions",
            "sample_counts": counts.tolist(), "sample_content": content.tolist(),
            "alias_pair": "same_first_two_moments" if index < 2 else None}


def evaluate_variant(name, case, model, cap, repeats):
    if name == "ordinary_gated":
        core = LearnedCore(model, cap)
    else:
        core = RenewalCore(numerical=name == "matched_numerical_integral", cap=cap,
                           reset_enabled=name != "absorbing_no_repeat",
                           refractory_enabled=name != "future_refractory_removed")
    physics = Physics(**case["shared_calibration"]["estimated"])
    wall_start = time.perf_counter()
    cpu_start = time.process_time()
    for _ in range(repeats):
        probabilities = sum(weight * core.counts(gap, case["horizon"], physics,
                                                case["refractory_remaining"])
                            for gap, weight in zip(case["gaps"], case["weights"]))
        if name == "mean_count_point_collapse":
            point = int(np.floor(probabilities @ np.arange(cap) + .5))
            probabilities = np.eye(cap)[point]
        initial = np.eye(5)[case["initial_class"]]
        content = content_from_counts(probabilities, initial, transition_matrix(5))
    cpu_seconds = (time.process_time() - cpu_start) / repeats
    wall_seconds = (time.perf_counter() - wall_start) / repeats
    counts, labels = np.array(case["sample_counts"]), np.array(case["sample_content"])
    expected_count = float(probabilities @ np.arange(cap))
    result = {"case": case["case"], "variant": name,
              "count_probabilities": probabilities.tolist(), "content_probabilities": content.tolist(),
              "expected_count": expected_count, "predicted_event_probability": float(1 - probabilities[0]),
              "count_nll": float(-np.log(np.maximum(probabilities[counts], 1e-12)).mean()),
              "content_nll": float(-np.log(np.maximum(content[labels], 1e-12)).mean()),
              "content_brier": float(np.square(content[None, :] - np.eye(5)[labels]).sum(axis=1).mean()),
              "content_accuracy": float(np.mean(labels == content.argmax())),
              "count_mean_squared_error": float(np.square(expected_count - counts).mean()),
              "event_brier": float(np.square(1 - probabilities[0] - (counts > 0)).mean()),
              "wall_seconds_per_query": wall_seconds, "cpu_seconds_per_query": cpu_seconds,
              "repeats": repeats, "core_calls_per_query": core.calls / repeats,
              "cdf_terms_per_query": core.cdf_terms / repeats,
              "density_integrand_evaluations_per_query": core.work / repeats,
              "max_omitted_tail_mass": getattr(core, "max_tail_mass", 0.),
              "max_mass_normalization_correction": getattr(core, "max_normalization_correction", 0.),
              "shared_observation_packet": True,
              "scope": "model_ablation" if name in VARIANTS[3:] else "matched_information_propagator"}
    if name == "mean_count_point_collapse":
        result["cost_includes_full_distribution_before_collapse"] = True
    if name == "future_refractory_removed":
        result["current_observed_remaining_preserved"] = True
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True); parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--seed", type=int, default=6101); parser.add_argument("--cases", type=int, default=128)
    parser.add_argument("--samples-per-case", type=int, default=256); parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args(); torch.set_num_threads(1)
    if not 2 <= args.cases <= 128 or args.samples_per_case < 2 or args.repeats < 1:
        raise ValueError("require 2..128 grid cases, >=2 samples, and >=1 repeats")
    started = time.perf_counter(); cpu_before = resource.getrusage(resource.RUSAGE_SELF)
    output = Path(args.output); output.mkdir(parents=True, exist_ok=False)
    checkpoint_path = Path(args.checkpoint)
    checkpoint_sha = hashlib.sha256(checkpoint_path.read_bytes()).hexdigest()
    job = {**vars(args), "schema": "hcsn_mechanism_diagnostics_v2.1", "checkpoint_sha256": checkpoint_sha}
    write_json(output / "job.json", job)
    write_json(output / "selection.json", {**job, "variants": VARIANTS,
               "written_before_case_generation": True, "grid_is_predeclared": True,
               "samples_are_not_analytic_probability_labels": True})
    checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
    report = checkpoint["report"]; model = GatedPropagator(report["width"], report["cap"])
    model.load_state_dict(checkpoint["state_dict"]); model.eval()
    # Public warm-up is paid in total process cost, not charged to one variant.
    warmup_start = time.perf_counter()
    for warm in (LearnedCore(model, report["cap"]), RenewalCore(), RenewalCore(numerical=True),
                 RenewalCore(reset_enabled=False), RenewalCore(refractory_enabled=False)):
        warm.counts(.7, .8, Physics(-.6, .4, .6, .2))
    warmup_seconds = time.perf_counter() - warmup_start
    cases, predictions, comparisons = [], [], []
    for index in range(args.cases):
        case = grid_case(index, args.seed, args.samples_per_case); cases.append(case)
        order = list(VARIANTS); np.random.default_rng(args.seed + index + 37).shuffle(order)
        case["predetermined_variant_order"] = order
        rows = {name: evaluate_variant(name, case, model, report["cap"], args.repeats) for name in order}
        predictions.extend(rows.values())
        analytic, numeric = rows[VARIANTS[0]], rows[VARIANTS[2]]
        err = float(np.max(np.abs(np.array(analytic["count_probabilities"]) - numeric["count_probabilities"])))
        comparisons.append({"case": index, "same_estimates_numeric_max_absolute_error": err,
                            "target_absolute_error": 1e-8, "matched_precision_pass": err <= 1e-8,
                            "analytic_wall_seconds": analytic["wall_seconds_per_query"],
                            "numeric_wall_seconds": numeric["wall_seconds_per_query"],
                            "analytic_cdf_terms": analytic["cdf_terms_per_query"],
                            "numeric_density_evaluations": numeric["density_integrand_evaluations_per_query"]})
    cpu_after = resource.getrusage(resource.RUSAGE_SELF)
    metrics = ("content_nll", "content_brier", "content_accuracy", "event_brier", "count_nll",
               "wall_seconds_per_query", "cpu_seconds_per_query", "density_integrand_evaluations_per_query")
    aggregate = {name: {key: float(np.mean([row[key] for row in predictions if row["variant"] == name]))
                        for key in metrics} for name in VARIANTS}
    summary = {"scope": "independent_labels_controlled_renewal_mechanism_not_general_network_superiority",
               "cases": args.cases, "samples_per_case": args.samples_per_case,
               "aggregate": aggregate, "matched_precision": comparisons,
               "wall_seconds": time.perf_counter() - started,
               "public_warmup_wall_seconds": warmup_seconds,
               "cpu_seconds": cpu_after.ru_utime + cpu_after.ru_stime - cpu_before.ru_utime - cpu_before.ru_stime,
               "training_cost_once": report, "checkpoint_sha256": checkpoint_sha,
               "calibration_wall_seconds": sum(c["shared_calibration"]["wall_seconds"] for c in cases),
               "accounting_note": "kernel per-query costs exclude label generation; total process costs include it",
               "point_ablation_has_analytic_mean_information": True,
               "no_reset_and_no_refractory_are_model_mismatch_ablations": True}
    write_jsonl(output / "cases.jsonl", cases); write_jsonl(output / "predictions.jsonl", predictions)
    write_json(output / "summary.json", summary)
    print(json.dumps({"output": str(output), "cases": args.cases, "wall_seconds": summary["wall_seconds"]}))


if __name__ == "__main__":
    main()
