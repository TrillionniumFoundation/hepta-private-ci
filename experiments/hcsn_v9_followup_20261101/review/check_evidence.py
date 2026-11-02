"""Independent raw-record reconstruction for the v9 development assays.

This script imports no candidate model, controller, or aggregator implementation.
It validates finite evidence; it cannot certify natural AV or archive completeness.
"""

import argparse
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(Path(path).read_text())


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def records(path):
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rt") as stream:
        return [json.loads(line) for line in stream]


def close(a, b, atol=1e-10):
    if not np.allclose(a, b, atol=atol, rtol=1e-10):
        raise AssertionError(f"Numerical mismatch: {a!r}, {b!r}")


def logistic(x):
    return 1 / (1 + np.exp(-np.clip(x, -40, 40)))


def learned_step(weights, family, previous, delta, modality=None, symbol=0):
    packet = np.array([delta, modality == "A", modality == "V",
                       symbol if modality == "A" else 0,
                       symbol if modality == "V" else 0], float)
    if family == "gru":
        update = logistic(packet @ weights["Wz"] + previous @ weights["Uz"] + weights["bz"])
        reset = logistic(packet @ weights["Wr"] + previous @ weights["Ur"] + weights["br"])
        proposal = np.tanh(packet @ weights["Wn"] + (reset * previous) @ weights["Un"] + weights["bn"])
        current = previous + (np.abs(packet).sum() > 0) * update * (proposal - previous)
    else:
        decay = np.exp(-delta * np.logaddexp(0, weights["rate"])
                       - (modality is not None) * np.logaddexp(0, weights["event_rate"]))
        drive = np.tanh(packet @ weights["W"] + weights["b"])
        current = decay * previous + (1 - decay) * drive
    probability = float(logistic(current @ weights["out"] + weights["bout"])[0])
    return current, probability


def analytic_step(previous, delta, plan, modality=None, symbol=0):
    current = .5 + (previous - .5) * np.exp(-2 * plan["rate"] * delta)
    if modality:
        accuracy = plan["sensor_accuracy"][modality]
        likelihood_one = accuracy if symbol == 1 else 1 - accuracy
        current = current * likelihood_one / (current * likelihood_one + (1-current) * (1-likelihood_one))
    return float(current), float(current)


def persistent():
    base = ROOT / "persistent_core/results/development001"
    plan, summary = read(base / "PLAN.json"), read(base / "SUMMARY.json")
    for name, expected in plan["source_sha256"].items():
        assert digest(ROOT / "persistent_core" / name) == expected
    frozen = read(base / "FROZEN_MODELS.json")
    assert digest(base / "PLAN.json") == frozen["plan_sha256"]
    assert digest(base / "FIT.json") == frozen["fit_sha256"]
    for name, expected in frozen["checkpoints"].items():
        assert digest(base / name) == expected
    for name, expected in summary["raw_sha256"].items():
        assert digest(base / name) == expected
    worlds = {r["index"]: r for r in records(base / "evaluation/worlds.jsonl.gz")}
    runs = records(base / "evaluation/runs.jsonl.gz")
    fits = read(base / "FIT.json")
    checkpoints = {(seed, family): dict(np.load(base / "fits" / f"{family}_{seed}.npz"))
                   for seed in plan["fit_seeds"] for family in plan["families"]}
    keys, reconstructed = set(), {}
    max_state_error = 0.
    for run in runs:
        key = (run["world"], run["fit_seed"], run["family"], run["control"])
        assert key not in keys
        keys.add(key)
        w, family = worlds[run["world"]], run["family"]
        if family in plan["families"]:
            weights = checkpoints[run["fit_seed"], family]
            state = np.zeros(plan["width"])
            step = lambda s, dt, m=None, v=0: learned_step(weights, family, s, dt, m, v)
        else:
            state = .5
            step = lambda s, dt, m=None, v=0: analytic_step(s, dt, plan, m, v)
        rewards = []
        for tick, row in enumerate(run["trace"]):
            delta = w["dt"][tick]
            state, prior = step(state, delta)
            close(prior, row["prior_probability"])
            scores = {"SKIP": max(prior, 1-prior)}
            for modality in ("A", "V"):
                acc = plan["sensor_accuracy"][modality]
                chance_one = prior * acc + (1-prior) * (1-acc)
                gain = 0.
                for symbol, chance in ((1, chance_one), (-1, 1-chance_one)):
                    _, p = step(state, 0, modality, symbol)
                    gain += chance * max(p, 1-p)
                scores[modality] = gain - plan["read_cost"][modality]
            for action in scores:
                close(scores[action], row["scores"][action])
            if run["control"] == "light":
                action = ("A" if (tick // 3) % 2 == 0 else "V") if tick % 3 == 0 else "SKIP"
            else:
                action = max(("SKIP", "A", "V"), key=lambda a: (scores[a], a == "SKIP"))
            assert row["action"] == action
            probability, fee = prior, 0.
            if action != "SKIP":
                assert row["accepted_event"] == w[action][tick]
                state, probability = step(state, 0, action, w[action][tick])
                fee = plan["read_cost"][action]
            else:
                assert row["accepted_event"] is None
            close(probability, row["probability"])
            close(fee, row["fee"])
            state_error = float(np.max(np.abs(np.asarray(state).ravel() - row["state"])))
            max_state_error = max(max_state_error, state_error)
            assert state_error < 1e-9
            reward = int(int(probability > .5) == w["latent"][tick]) - fee
            close(reward, row["net_reward"])
            close((probability - w["latent"][tick])**2, row["brier"])
            rewards.append(reward)
        reconstructed[key] = float(np.mean(rewards))
        close(reconstructed[key], run["summary"]["net_reward"])
    assert len(runs) == len(worlds) * (4 + 4 * len(plan["fit_seeds"]))
    differences, history_difference = [], []
    for seed in plan["fit_seeds"]:
        family = fits[str(seed)]["selected_family"]
        differences.append([reconstructed[i, None, "analytic", "value"] - reconstructed[i, seed, family, "value"]
                            for i in range(len(worlds))])
        history_difference.extend(reconstructed[i, None, "analytic", "value"] - reconstructed[i, None, "direct_history", "value"]
                                  for i in range(len(worlds)))
    close(np.mean(differences), summary["D_minus_B_mean"])
    close(history_difference, 0)
    close(differences, np.load(base / "evaluation/paired_D_minus_B.npz")["paired"])
    return {"runs_replayed": len(runs), "outputs_replayed": sum(len(r["trace"]) for r in runs),
            "D_minus_B": float(np.mean(differences)), "D_minus_exact_history": float(np.mean(history_difference)),
            "maximum_state_replay_error": max_state_error, "raw_sha256": digest(base / "evaluation/runs.jsonl.gz"),
            "scientific_scope": "Synthetic known-law CTMC; finite-budget ordinary fit, no AV/renewal-core adoption claim"}


def refit_run(base):
    plan, summary = read(base / "PLAN.json"), read(base / "SUMMARY.json")
    frozen_source = base / "source_snapshot"
    if not frozen_source.is_dir():
        frozen_source = ROOT / "refit_ablation"
    for name, expected in plan["source_sha256"].items():
        assert digest(frozen_source / name) == expected
    assert digest(base / "test_data.npz") == summary["test_data_sha256"]
    assert digest(base / "predictions.jsonl.gz") == summary["raw_sha256"]
    for report in summary["fits"]:
        directory = base / f"fit_{report['seed']}"
        assert digest(directory / "data.npz") == report["data_sha256"]
        assert digest(directory / "weights.npz") == report["weights_sha256"]
    data = np.load(base / "test_data.npz")
    rows = records(base / "predictions.jsonl.gz")
    weights = {seed: dict(np.load(base / f"fit_{seed}/weights.npz")) for seed in plan["fit_seeds"]}
    indexed, nll = {}, {}
    for row in rows:
        seed, world, arm = row["fit_seed"], row["world"], row["arm"]
        assert row["truth"] == int(data["labels"][world])
        key = seed, world, arm
        assert key not in indexed
        indexed[key] = row
        if arm == "unfitted_analytic":
            expected = data["oracle"][world]
        else:
            mode = arm.removeprefix("same_weight_").removeprefix("refit_")
            parameter_mode = "original" if arm.startswith("same_weight_") else mode
            logits = data["X_" + mode][world] @ weights[seed][parameter_mode].reshape(6, 5)
            expected = np.exp(logits - logits.max()); expected /= expected.sum()
        close(expected, row["probabilities"])
        nll[key] = float(-np.log(max(row["probabilities"][row["truth"]], 1e-300)))
    assert len(rows) == plan["test_size"] * len(plan["fit_seeds"]) * 6
    effects = {}
    for mode in plan["modes"][1:]:
        for name, right in (("refit_minus_original", "refit_original"),
                            ("refit_minus_same_weight", "same_weight_" + mode)):
            effect = np.mean([nll[s, i, "refit_"+mode] - nll[s, i, right]
                              for s in plan["fit_seeds"] for i in range(plan["test_size"])])
            label = mode + "_" + name
            close(effect, summary["contrasts"][label]["nll_difference"])
            effects[label] = float(effect)
    candidates = [candidate for fit in summary["fits"] for report in fit["modes"].values()
                  for candidate in report["all_candidates"]]
    return {"run": base.name, "prediction_rows_replayed": len(rows), "nll_contrasts": effects,
            "source_directory": str(frozen_source.relative_to(ROOT)),
            "optimizer_success_candidates": sum(x["optimizer_success"] for x in candidates),
            "optimizer_candidates": len(candidates),
            "maximum_terminal_gradient": max(x["gradient_max_abs"] for x in candidates),
            "scope": "Frozen analytic-kernel readout refitting only; full analytic network not retrained",
            "raw_sha256": digest(base / "predictions.jsonl.gz")}


def refit():
    return {"runs": [refit_run(p.parent) for p in sorted((ROOT / "refit_ablation/results").glob("*/SUMMARY.json"))]}


def risk():
    base = ROOT / "risk/results/development001"
    plan, summary = read(base / "PLAN.json"), read(base / "SUMMARY.json")
    assert digest(base / "PLAN.json") == summary["plan_sha256"]
    assert digest(base / "runs.jsonl") == summary["raw_sha256"]
    for name, expected in plan["source_sha256"].items():
        assert digest(ROOT.parent / name) == expected
    rows = records(base / "runs.jsonl")
    worlds = {w["id"]: w for w in plan["logical_worlds"]}
    by_key = {}
    for row in rows:
        receipt, world = row["receipt"], worlds[row["world_id"]]
        assert row["scored_deadline_penalty"] == receipt["deadline_penalty"]
        correct = int(receipt["output"]["predicted_class"] == world["target"])
        utility = correct - receipt["observation_fee"] - receipt["latency_fee"] - receipt["deadline_penalty"]
        close(utility, row["net_utility"])
        keys = receipt["output"]["accepted_event_ids"]
        likelihood = np.ones(2)
        for name, accuracy in (("audio", .7), ("video", .95)):
            if "READ:" + name + ":1" in keys:
                symbol = world[name]
                likelihood *= np.array([accuracy if symbol == target else 1-accuracy for target in (0, 1)])
        probability = likelihood / likelihood.sum()
        close(probability, receipt["output"]["probabilities"])
        if any(e["status"] == "timed_out" for e in receipt["events"]):
            assert "READ:video:1" not in keys
        by_key[row["clock_mode"], row["world_id"], row["arm"]] = row
    effects, no_penalty_effects = {}, {}
    for mode, published in summary["modes"].items():
        ids = [k for k in worlds if (mode, k, "full") in by_key]
        means = {}
        for arm in plan["arms"]:
            means[arm] = sum((worlds[k]["weight"] if mode == "logical" else 1/len(ids)) *
                             by_key[mode, k, arm]["net_utility"] for k in ids)
            close(means[arm], published["mean_net_utility"][arm])
        effects[mode] = means["full"] - means["zero"]
        close(effects[mode], published["full_minus_zero"])
        no_penalty_effects[mode] = sum((worlds[k]["weight"] if mode == "logical" else 1/len(ids)) *
            (by_key[mode,k,"full"]["net_utility"] + by_key[mode,k,"full"]["receipt"]["deadline_penalty"]
             - by_key[mode,k,"zero"]["net_utility"] - by_key[mode,k,"zero"]["receipt"]["deadline_penalty"])
             for k in ids)
        for k in ids:
            assert by_key[mode,k,"full_on_zero"]["receipt"]["output"]["probabilities"] == by_key[mode,k,"zero"]["receipt"]["output"]["probabilities"]
            assert by_key[mode,k,"zero_on_full"]["receipt"]["output"]["probabilities"] == by_key[mode,k,"full"]["receipt"]["output"]["probabilities"]
    return {"rows_recomputed": len(rows), "full_minus_zero_net_utility": effects,
            "retained_actions_without_deadline_penalty_full_minus_zero": no_penalty_effects,
            "scope": "Controlled synthetic service-risk fixture, real subset descriptive, no Put-necessity claim",
            "raw_sha256": digest(base / "runs.jsonl")}


def economics():
    reports = []
    for path in sorted((ROOT / "economics/results").glob("*/RECEIPT.json")):
        receipt = read(path)
        samples_path = path.with_name("MEMORY_SAMPLES.jsonl")
        assert digest(samples_path) == receipt["sample_sha256"]
        sample_count, rss_peak, pss_peak = 0, 0, 0
        with samples_path.open() as stream:
            for line in stream:
                sample = json.loads(line)
                rss = sum(m.get("rss_bytes") or 0 for m in sample["members"])
                pss = sum(m.get("pss_bytes") or 0 for m in sample["members"])
                assert rss == sample["observed_rss_sum_bytes"]
                assert pss == sample["observed_pss_sum_bytes"]
                rss_peak, pss_peak = max(rss_peak, rss), max(pss_peak, pss)
                sample_count += 1
        close(sum(w["cpu_seconds"] for w in receipt["wait4_subtrees"]), receipt["task_cpu_seconds"])
        close(receipt["task_cpu_seconds"] + receipt["measurement_cpu_seconds"], receipt["enclosing_observed_cpu_seconds"])
        assert sample_count == receipt["memory"]["samples"]
        assert rss_peak == receipt["memory"]["observed_peak_nonatomic_rss_sum_bytes"]
        assert pss_peak == receipt["memory"]["observed_peak_nonatomic_pss_sum_bytes"]
        assert receipt["memory"]["complete"] is False
        assert receipt["memory"]["continuous_complete_family_peak_bytes"] is None
        assert receipt["capabilities"]["energy"]["joules"] is None
        reports.append({"directory": path.parent.name, "task_success": receipt["task_success"],
                        "cpu_seconds": receipt["task_cpu_seconds"], "memory_samples_recomputed": sample_count,
                        "sampled_rss_sum_peak_bytes": rss_peak, "sampled_pss_sum_peak_bytes": pss_peak})
    return {"receipts_recomputed": len(reports), "reports": reports,
            "scope": "Non-atomic sampled family memory; continuous complete peak and attributable energy unavailable"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", choices=("persistent_core", "refit_ablation", "risk", "economics"))
    args = parser.parse_args()
    result = {"schema": "hcsn-v9-independent-reconstruction.v1", "candidate_implementations_imported": False}
    for name, operation in (("persistent_core", persistent), ("refit_ablation", refit), ("risk", risk), ("economics", economics)):
        if args.only and name != args.only:
            continue
        result[name] = operation()
        Path(__file__).with_name(name.upper() + "_RECONSTRUCTION.json").write_text(
            json.dumps(result[name], indent=2, allow_nan=False) + "\n")
    front = read(ROOT / "frontend/OBSERVED_RESULT.json")
    assert front["status"] == "FAIL"
    result["frontend_observed_status"] = front["status"]
    result["all_reconstructions_pass"] = True
    target = Path(__file__).with_name("RECONSTRUCTION.json" if not args.only else args.only.upper()+"_REVIEW_RUN.json")
    target.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
