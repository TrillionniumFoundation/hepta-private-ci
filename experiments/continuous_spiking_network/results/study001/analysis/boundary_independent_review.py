"""Independent read-only boundary audit; no training and no repository writes.

Analysis contrasts were specified after study launch but before inspecting any
boundary outcome values: value-direct and value-fixed, ID and OOD; paired seeds.
The supplemental Gaussian Bellman reference uses NumPy/Gauss-Hermite, not the
implementation's Torch analytic interpolation-weight integration.
"""

import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np
from scipy.special import expit
from scipy.stats import t as student_t


SEEDS = (4401, 4402, 4403, 4404, 4405)
ARMS = ("fixed", "direct", "value", "oracle")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_split(directory, receipt, split):
    shards = []
    for entry in receipt["episode_files"]:
        if entry["split"] != split:
            continue
        path = directory / entry["file"]
        assert sha(path) == entry["sha256"]
        with np.load(path, allow_pickle=False) as data:
            shards.append({key: data[key].copy() for key in data.files})
    assert len(shards) == 4
    return {key: np.concatenate([chunk[key] for chunk in shards]) for key in shards[0]}


def audit_split(data, receipt, split):
    ids = data["episode_id"]
    assert len(ids) == 512 and len(set(ids.tolist())) == len(ids)
    assert np.isfinite(data["actor_log_odds"]).all()
    exact = (2 * data["snr"].astype(float)[:, None] * data["observations"]).cumsum(1)
    llr_error = float(np.abs(exact - data["bayes_log_odds"]).max())
    assert np.allclose(exact, data["bayes_log_odds"], atol=3e-5, rtol=1e-6)
    result = {"bayes_llr_max_error": llr_error, "arms": {}}
    for arm in ARMS:
        mask = data[f"{arm}_stop_mask"]
        assert mask[:, -1].all()
        index = mask.argmax(1)
        assert np.array_equal(index, data[f"{arm}_stop_index"])
        odds = data["bayes_log_odds" if arm == "oracle" else "actor_log_odds"]
        action = (odds[np.arange(len(index)), index] >= 0).astype(int)
        correct = action == data["label"]
        count = index + 1
        cost = count * data["cost"].astype(float)
        utility = correct.astype(float) - cost
        for key, value in (("action", action), ("correct", correct), ("observations", count)):
            assert np.array_equal(value, data[f"{arm}_{key}"])
        for key, value in (("total_cost", cost), ("net_utility", utility)):
            assert np.allclose(value, data[f"{arm}_{key}"], atol=1e-12, rtol=0)
        metrics = {"accuracy": float(correct.mean()), "mean_observations": float(count.mean()),
                   "mean_total_cost": float(cost.mean()), "net_utility": float(utility.mean())}
        for key, value in metrics.items():
            assert abs(value - receipt["metrics"][split][arm][key]) < 1e-6
        result["arms"][arm] = metrics
    confidence = expit(np.abs(data["actor_log_odds"].astype(float)))
    for arm in ("fixed", "direct"):
        threshold = receipt["fixed"]["threshold"]
        if arm == "direct":
            parameters = receipt["direct"]["parameters"]
            features = np.stack((np.log1p(data["remaining_steps"]),
                                 np.broadcast_to(np.log(data["snr"])[:, None], confidence.shape),
                                 np.broadcast_to(np.log(data["cost"])[:, None], confidence.shape)), axis=-1)
            threshold = .5 + .4999 * expit(parameters["direct_bias"] + features @ parameters["direct_context"])
        expected = confidence >= threshold
        expected[:, -1] = True
        disagreement = expected != data[f"{arm}_stop_mask"]
        stable_disagreement = disagreement & (np.abs(confidence - threshold) > 1e-6)
        assert not stable_disagreement.any()
        result[f"{arm}_roundoff_boundary_differences"] = int(disagreement.sum())
    truth = data["label"][:, None]
    odds = data["actor_log_odds"].astype(float)
    learned_p, bayes_p = expit(odds), expit(data["bayes_log_odds"].astype(float))
    result["calibration_descriptive"] = {
        "all_prefix_binary_brier": float(np.mean((learned_p - truth)**2)),
        "all_prefix_log_loss": float(np.mean(np.logaddexp(0, odds) - truth * odds)),
        "probability_rmse_vs_true_bayes": float(np.sqrt(np.mean((learned_p - bayes_p)**2))),
        "final_accuracy": float(np.mean((odds[:, -1] >= 0) == data["label"])),
        "prefixes_are_correlated": True,
    }
    return result


def reference_bellman(snr, cost, horizon, size=1025, quadrature=201):
    """Independent Gaussian quadrature of piecewise-linear Bellman functions."""
    grid = np.linspace(-12., 12., size)
    nodes, weights = np.polynomial.hermite.hermgauss(quadrature)
    weights = weights / np.sqrt(np.pi)
    noise = 2 * snr * np.sqrt(2.) * nodes
    plus = grid[:, None] + 2 * snr**2 + noise
    minus = grid[:, None] - 2 * snr**2 + noise
    prior, stop = expit(grid), expit(np.abs(grid))
    value, waits = stop.copy(), [np.full_like(stop, -np.inf)]
    for _ in range(horizon):
        expectation = prior * (np.interp(plus, grid, value) @ weights)
        expectation += (1 - prior) * (np.interp(minus, grid, value) @ weights)
        wait = expectation - cost
        waits.append(wait)
        value = np.maximum(stop, wait)
    return grid, np.stack(waits)


def sample_dp(data, cache):
    contexts = np.stack((data["snr"], data["cost"]), axis=1)
    total, near, far, largest = 0, 0, 0, 0.
    ex_ante = np.empty(len(contexts))
    for context in np.unique(contexts, axis=0):
        rows = np.flatnonzero((contexts == context).all(1))
        horizon = int(data["horizon"][rows[0]])
        key = (float(context[0]), float(context[1]), horizon)
        if key not in cache:
            cache[key] = reference_bellman(*key)
        grid, waits = cache[key]
        # First observation is compulsory, so use continuation at the prior.
        ex_ante[rows] = np.interp(0., grid, waits[horizon])
        for arm in ("value", "oracle"):
            odds = data["bayes_log_odds" if arm == "oracle" else "actor_log_odds"]
            for row in rows[:2]:
                for position in range(horizon - 1):
                    remaining = horizon - position - 1
                    gap = expit(abs(float(odds[row, position]))) - np.interp(odds[row, position], grid, waits[remaining])
                    agrees = bool(gap >= 0) == bool(data[f"{arm}_stop_mask"][row, position])
                    total += 1
                    if not agrees:
                        largest = max(largest, abs(gap))
                        if abs(gap) > .001:
                            far += 1
                        else:
                            near += 1
    return {"sampled_decisions": total, "near_boundary_differences": near,
            "differences_with_reference_advantage_over_0_001": far,
            "largest_disagreement_advantage": largest,
            "oracle_expected_utility_independent_model": float(ex_ante.mean())}


def mean_interval(values, confidence=.95):
    values = np.asarray(values, dtype=float)
    mean, sd = float(values.mean()), float(values.std(ddof=1))
    half = float(student_t.ppf((1 + confidence) / 2, len(values) - 1)) * sd / np.sqrt(len(values))
    return {"mean": mean, "seed_sd": sd, "interval": [mean - half, mean + half],
            "confidence": confidence, "seed_values": values.tolist(), "independent_units": len(values)}


def write_markdown(report, path):
    lines = ["# Independent boundary study review", "",
             "This is a read-only analysis of study001. No training, tuning, policy selection or sealed source was changed.", "",
             f"Completed planned seeds: {report['complete_seeds']}.", ""]
    if len(report["complete_seeds"]) != 5:
        lines += ["The five-seed analysis remains pending. Available artifacts were checked without redefining the planned contrasts.", ""]
    else:
        lines += ["## Four-arm outcomes", "",
                  "Each entry is the mean of five seed means. Seed-to-seed SD and unadjusted descriptive 95% t intervals are retained in the JSON. The trained actor and trajectories are shared within each seed.", "",
                  "| Split | Arm | Accuracy | Observations | Observation cost | Net utility |",
                  "| --- | --- | ---: | ---: | ---: | ---: |"]
        for split in ("id", "ood"):
            for arm in ARMS:
                item = report["aggregate"][split][arm]
                values = [item[key]["mean"] for key in ("accuracy", "mean_observations", "mean_total_cost", "net_utility")]
                lines.append(f"| {split.upper()} | {arm} | {values[0]:.6f} | {values[1]:.4f} | {values[2]:.6f} | {values[3]:.6f} |")
        lines += ["", "## Paired utility contrasts", "",
                  "The four contrasts were specified after study launch, before inspecting boundary outcome values. They are analysis choices, not a new preregistered pass/fail gate. The 98.75% t intervals apply a Bonferroni adjustment across these four contrasts; five seeds provide limited precision.", "",
                  "| Split | Contrast | Mean difference | Seed SD | 98.75% t interval | Positive seeds |",
                  "| --- | --- | ---: | ---: | --- | ---: |"]
        for item in report["paired_utility_contrasts"]:
            low, high = item["bonferroni_98_75_percent_t_interval"]
            lines.append(f"| {item['split'].upper()} | {item['contrast']} | {item['mean']:.6f} | {item['seed_sd']:.6f} | [{low:.6f}, {high:.6f}] | {item['positive_seeds']}/5 |")
        lines += ["", "## All seed-level contrasts", "",
                  "| Seed | ID value−direct | ID value−fixed | OOD value−direct | OOD value−fixed |",
                  "| --- | ---: | ---: | ---: | ---: |"]
        for position, seed in enumerate(SEEDS):
            row = [item["seed_differences"][position] for item in report["paired_utility_contrasts"]]
            lines.append(f"| {seed} | " + " | ".join(f"{number:.6f}" for number in row) + " |")
    lines += ["", "## Execution and mathematical checks", "",
              "Shard hashes, unique episode IDs, raw Bayesian LLR arithmetic, the first True stop mask entry, class decisions, correctness, paid observation counts and total costs, and reported utility means are independently recomputed. Fixed/direct threshold decisions are reconstructed, with a 1e-6 margin tolerance for float32 roundoff. Actor manifest hashes and recorded exact reload checks are verified.", ""]
    samples = [entry["splits"][split].get("independent_dp_sample") for entry in report["reports"].values() for split in ("id", "ood")]
    samples = [item for item in samples if item]
    if samples:
        lines += [f"Independent NumPy/Gauss-Hermite Bellman reference: {sum(x['sampled_decisions'] for x in samples)} sampled prefix decisions, {sum(x['near_boundary_differences'] for x in samples)} differences within a .001 reference advantage, and {sum(x['differences_with_reference_advantage_over_0_001'] for x in samples)} differences beyond that margin. This is a numerical cross-check, not a proof of exact continuum optimality.", ""]
    lines += ["## Interpretation limits", ""]
    lines += [f"- {item}" for item in report["interpretation"]]
    lines += ["", "## Calibration and timing", "",
              "The JSON retains all-prefix binary Brier score, log loss and probability RMSE against the exact Bayesian posterior. These are descriptive diagnostics; prefixes within an episode are correlated. It also retains each run's actor and policy timing receipts. Timing subtotals are nested and must not all be summed. No test-driven calibration was fitted.", ""]
    Path(path).write_text("\n".join(lines))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--study", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--sample-dp", action="store_true")
    args = parser.parse_args()
    study = Path(args.study)
    complete, reports, frames, cache, global_ids = [], {}, {}, {}, set()
    for seed in SEEDS:
        directory = study / "boundary" / f"seed{seed}"
        if not (directory / "RESULT.json").exists():
            continue
        receipt = json.loads((directory / "RESULT.json").read_text())
        assert receipt["kind"] == "boundary_study" and receipt["seed"] == seed
        assert receipt["first_observation_charged"] and not receipt["bayes_teacher"]
        assert sha(directory / "actor_checkpoint/manifest.json") == receipt["actor"]["checkpoint_manifest_sha256"]
        assert receipt["actor"]["checkpoint_reload_max_error"] == 0
        assert all(item["finite"] for item in receipt["actor"]["gradient_groups"].values())
        complete.append(seed)
        reports[str(seed)] = {"splits": {}, "selected_actor_step": receipt["actor"]["selected_step"],
                              "fixed_threshold": receipt["fixed"]["threshold"],
                              "total_cpu_seconds": receipt["total_cpu_seconds"],
                              "direct_parameters": receipt["direct"]["parameters"],
                              "timing": receipt["timing"],
                              "actor_training_cpu_seconds": receipt["actor"]["training_cpu_seconds"],
                              "actor_validation_cpu_seconds": receipt["actor"]["validation_cpu_seconds"]}
        for split in ("id", "ood"):
            data = load_split(directory, receipt, split)
            ids = set(data["episode_id"].tolist())
            assert not ids.intersection(global_ids)
            global_ids.update(ids)
            report = audit_split(data, receipt, split)
            if args.sample_dp:
                report["independent_dp_sample"] = sample_dp(data, cache)
            reports[str(seed)]["splits"][split] = report
            frames[(seed, split)] = data
    contrasts, aggregate = [], {}
    if len(complete) == len(SEEDS):
        for split in ("id", "ood"):
            aggregate[split] = {}
            for arm in ARMS:
                aggregate[split][arm] = {
                    key: mean_interval([reports[str(seed)]["splits"][split]["arms"][arm][key] for seed in SEEDS])
                    for key in ("accuracy", "mean_observations", "mean_total_cost", "net_utility")
                }
        critical = float(student_t.ppf(1 - .05 / (2 * 4), len(SEEDS) - 1))
        for split in ("id", "ood"):
            for comparator in ("direct", "fixed"):
                differences = np.array([np.mean(frames[(seed, split)]["value_net_utility"] -
                                               frames[(seed, split)][f"{comparator}_net_utility"]) for seed in SEEDS])
                mean, sd = float(differences.mean()), float(differences.std(ddof=1))
                half = critical * sd / np.sqrt(len(SEEDS))
                contrasts.append({"split": split, "contrast": f"value_minus_{comparator}",
                                  "seed_differences": differences.tolist(), "mean": mean, "seed_sd": sd,
                                  "bonferroni_98_75_percent_t_interval": [mean - half, mean + half],
                                  "positive_seeds": int((differences > 0).sum()), "independent_units": 5})
    report = {"script_sha256": sha(__file__), "created_unix": time.time(), "planned_seeds": SEEDS,
              "complete_seeds": complete, "reports": reports, "aggregate": aggregate,
              "paired_utility_contrasts": contrasts,
              "interpretation": ["Fixed/direct/value share the same selected actor and causal observation/context inputs. Value is model-informed plug-in stopping on learned logits; the actor's future score dynamics need not match Bayesian LLR transitions, so this is not a proved Bellman optimum for that actor.",
                                 "Value embeds the known Gaussian generative model. Direct is a four-parameter context threshold trained for 100 updates, and fixed is a single validation-selected threshold. Their structural priors, function classes and optimization/computation budgets differ.",
                                 "The separate raw Bayesian DP arm uses exact raw-evidence log odds and has an expected model-based optimality interpretation, subject to grid/quadrature approximation, not per-episode dominance or a pure boundary improvement.",
                                 "Every arm must purchase at least one observation. The oracle is constrained accordingly; it is not an upper bound over policies allowed to guess without purchasing any observation.",
                                 "Five independent training/data seeds; episodes and prefixes are not independent model replicates.",
                                 "The four t intervals are approximate and multiplicity-adjusted; no new success gate is imposed.",
                                 "The boundary actor uses AdamW weight decay 1e-4 on all parameters, as specified in its own implementation/documentation; this differs from the classification pipeline's vector/no-weight-decay exclusion. All three learned-score policy arms still share exactly that actor.",
                                 "Saved observation costs are task utility, not energy or measured early-cancellation time. The actor is evaluated on all prefixes offline, and shared actor fitting costs must not be repeatedly charged as if the arms had separately trained actors.",
                                 "This boundary experiment evaluates stopping on an HCSN actor, not HCSN superiority over other backbones or a solved endogenous natural spiking threshold."]}
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    write_markdown(report, output.with_suffix(".md"))
    print(json.dumps({"complete_seeds": complete, "output": str(output), "contrasts": contrasts}, indent=2))


if __name__ == "__main__":
    main()
