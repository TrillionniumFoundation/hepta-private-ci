"""Independent matrix-power reconstruction of jointly fitted renewal evidence."""

import gzip
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.special import log_ndtr, ndtr


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def close(a, b, tolerance=2e-10):
    assert np.allclose(a, b, atol=tolerance, rtol=tolerance)


def joint_probabilities(theta, packets, mode):
    cap = 24
    x, horizon, drift, volatility, reset, refractory = np.asarray(packets).T
    drift, volatility = drift*np.exp(theta[0]), volatility*np.exp(theta[1])
    n = np.arange(1, cap+1)
    t = horizon[:, None] - (n-1)*refractory[:, None]
    active = t > 0
    safe = np.where(active, t, 1.)
    gap = x[:, None] + (n-1)*reset[:, None]
    scale = volatility[:, None]*np.sqrt(safe)
    a = (-gap-drift[:, None]*safe)/scale
    b = (-gap+drift[:, None]*safe)/scale
    tail = np.where(active, ndtr(a) + np.exp(np.minimum(
        -2*drift[:, None]*gap/volatility[:, None]**2 + log_ndtr(b), 0)), 0.)
    assert np.max(tail[:, -1]) <= 1e-10
    counts = np.column_stack((np.ones(len(packets)), tail[:, :-1]))-tail
    assert counts.min() > -1e-10
    counts = np.maximum(counts, 0)
    close(counts.sum(1), 1)
    if mode == "single_transition":
        zero = counts[:, 0].copy()
        counts[:] = 0
        counts[:, 0], counts[:, 1] = zero, 1-zero
    elif mode == "mean_two_point":
        mean = counts @ np.arange(cap)
        lower = np.floor(mean).astype(int)
        assert (lower < cap-1).all()
        counts[:] = 0
        counts[np.arange(len(counts)), lower] = 1-(mean-lower)
        counts[np.arange(len(counts)), lower+1] = mean-lower
    else:
        assert mode == "original"
    if mode == "single_transition":
        assert not counts[:, 2:].any()
    logits = np.r_[0., theta[2:]]
    weights = np.exp(logits-logits.max()); weights /= weights.sum()
    transition = np.column_stack([np.roll(weights, c) for c in range(5)])
    vector, powers = np.eye(5)[0], []
    for _ in range(cap):
        powers.append(vector)
        vector = transition @ vector
    probability = counts @ np.asarray(powers)
    close(probability.sum(1), 1)
    return probability


def mlp_probabilities(flat, x):
    width = 16
    first = flat[:96].reshape(6, width)
    bias = flat[96:112]
    last = flat[112:192].reshape(width, 5)
    output_bias = flat[192:]
    scores = np.tanh(x@first+bias)@last+output_bias
    probability = np.exp(scores-scores.max(1, keepdims=True))
    return probability/probability.sum(1, keepdims=True)


def metrics(p, labels):
    return {"nll": float(-np.log(np.maximum(p[np.arange(len(labels)), labels], 1e-15)).mean()),
            "accuracy": float(np.mean(p.argmax(1) == labels)),
            "brier": float(np.square(p-np.eye(5)[labels]).sum(1).mean())}


def audit(base):
    base = Path(base)
    plan = json.loads((base/"PLAN.json").read_text())
    here = base.parents[1]
    for path, digest in plan["source_sha256"].items():
        assert sha(here/path) == digest
    data_ledger = json.loads((base/"DATA.json").read_text())
    for path, digest in data_ledger["files_sha256"].items():
        assert sha(base/path) == digest
    test = np.load(base/"test.npz")
    frozen = json.loads((base/"TRAINING_COMPLETE.json").read_text())
    summary = json.loads((base/"SUMMARY.json").read_text())
    assert sha(base/"TRAINING_COMPLETE.json") == summary["training_complete_sha256"]
    assert sha(base/"test.npz") == summary["test_sha256"]
    assert sha(base/"predictions.jsonl.gz") == summary["raw_sha256"]
    predictions, validations, changed, gradients = {}, [], [], []
    for fit in frozen["fits"]:
        seed = fit["seed"]
        path = base/f"fit_{seed}/weights.npz"
        assert sha(path) == fit["weights_sha256"]
        saved = np.load(path)
        valid = np.load(base/f"validation_{seed}.npz")
        training = np.load(base/f"train_{seed}.npz")
        for mode in plan["modes"]:
            report = fit["reports"][mode]
            candidate_scores = []
            for index, candidate in enumerate(report["candidates"]):
                theta = saved[f"candidate_{mode}_{index}"]
                close(theta, candidate["parameters"])
                assert (abs(theta[:2]) <= .5).all() and (abs(theta[2:]) <= 8).all()
                p = joint_probabilities(theta, valid["packets"], mode)
                score = metrics(p, valid["delta_labels"])
                for name, value in score.items():
                    close(value, candidate["validation"][name])
                candidate_scores.append(score["nll"])
            chosen = min(range(len(candidate_scores)), key=lambda i: (candidate_scores[i], report["candidates"][i]["l2"]))
            assert chosen == report["selected_index"]
            close(saved[mode], saved[f"candidate_{mode}_{chosen}"])
            dynamic_change = float(np.linalg.norm(saved[mode][:2]-saved["joint_initial"][:2]))
            content_change = float(np.linalg.norm(saved[mode][2:]-saved["joint_initial"][2:]))
            close(dynamic_change, report["selected"]["dynamics_parameter_change_norm"])
            close(content_change, report["selected"]["content_parameter_change_norm"])
            changed.append({"fit_seed": seed, "mode": mode,
                            "dynamics_parameter_change_norm": dynamic_change,
                            "content_parameter_change_norm": content_change})
            theta = saved[mode].copy()
            l2 = report["selected"]["l2"]
            def loss(parameters):
                p = joint_probabilities(parameters, training["packets"], mode)
                return metrics(p, training["delta_labels"])["nll"] + .5*l2*np.sum(parameters**2)
            numerical = []
            for dimension in range(6):
                direction = np.eye(6)[dimension]*1e-6
                numerical.append((loss(theta+direction)-loss(theta-direction))/2e-6)
            numerical_max = float(np.max(np.abs(numerical)))
            reported_max = report["selected"]["gradient_max_abs"]
            assert abs(numerical_max-reported_max) <= max(.002, .01*reported_max)
            corner_mass_errors = []
            for drift_corner in (-.5, .5):
                for sigma_corner in (-.5, .5):
                    corner = theta.copy(); corner[:2] = drift_corner, sigma_corner
                    p = joint_probabilities(corner, valid["packets"], mode)
                    corner_mass_errors.append(float(np.max(abs(p.sum(1)-1))))
            gradients.append({"fit_seed": seed, "mode": mode,
                "independent_finite_difference_gradient_max_abs": numerical_max,
                "reported_analytic_gradient_max_abs": reported_max,
                "physical_bound_corner_mass_error": max(corner_mass_errors),
                "scope": "Numerical likelihood gradient check, not an optimizer convergence or KKT certificate"})
            validations.append({"fit_seed": seed, "mode": mode, "chosen_index": chosen,
                                "optimizer_success": report["selected"]["optimizer_success"]})
        validation_x = (valid["packets"]-saved["ordinary_mean"])/saved["ordinary_scale"]
        report = fit["reports"]["ordinary_mlp"]
        scores = []
        for index, candidate in enumerate(report["candidates"]):
            p = mlp_probabilities(saved[f"candidate_ordinary_{index}"], validation_x)
            score = metrics(p, valid["delta_labels"])
            for name, value in score.items():
                close(value, candidate["validation"][name])
            scores.append(score["nll"])
        selected = min(range(len(scores)), key=lambda i: (scores[i], report["candidates"][i]["l2"]))
        assert selected == report["selected_index"]
        close(saved["ordinary_mlp"], saved[f"candidate_ordinary_{selected}"])
        predictions[seed] = {"joint_original": joint_probabilities(saved["original"], test["packets"], "original"),
            "ordinary_mlp": mlp_probabilities(saved["ordinary_mlp"], (test["packets"]-saved["ordinary_mean"])/saved["ordinary_scale"])}
        for mode in plan["modes"][1:]:
            predictions[seed]["same_weight_"+mode] = joint_probabilities(saved["original"], test["packets"], mode)
            predictions[seed]["joint_"+mode] = joint_probabilities(saved[mode], test["packets"], mode)
    seen, maximum_error = set(), 0.
    with gzip.open(base/"predictions.jsonl.gz", "rt") as stream:
        for line in stream:
            row = json.loads(line)
            seed, i, arm = row["fit_seed"], row["world"], row["arm"]
            key = seed, i, arm
            assert key not in seen; seen.add(key)
            assert row["truth"] == test["labels"][i] and row["initial_class"] == test["initials"][i]
            expected = np.roll(predictions[seed][arm][i], int(test["initials"][i]))
            maximum_error = max(maximum_error, float(np.max(abs(expected-row["probabilities"]))))
            close(expected, row["probabilities"])
    assert len(seen) == plan["test_size"]*len(plan["fit_seeds"])*len(plan["arms"])
    effects = {}
    for name,left,right in (("mean_retrained_minus_full", "joint_mean_two_point", "joint_original"),
            ("single_retrained_minus_full", "joint_single_transition", "joint_original"),
            ("mean_retrained_minus_same_weight", "joint_mean_two_point", "same_weight_mean_two_point"),
            ("single_retrained_minus_same_weight", "joint_single_transition", "same_weight_single_transition"),
            ("full_minus_ordinary", "joint_original", "ordinary_mlp")):
        delta = np.mean([metrics(p[left], test["delta_labels"])["nll"]-metrics(p[right], test["delta_labels"])["nll"]
                         for p in predictions.values()])
        close(delta, summary["contrasts"][name]["NLL_difference"])
        effects[name] = float(delta)
    return {"raw_predictions_reconstructed": len(seen), "maximum_probability_error": maximum_error,
            "validation_only_choices_reconstructed": validations, "joint_parameter_changes": changed,
            "finite_difference_and_bound_checks": gradients,
            "NLL_differences": effects, "candidate_implementations_imported": False,
            "scope": "Finite shared renewal family with joint dynamics/content refit; no raw AV or control benefit",
            "raw_sha256": sha(base/"predictions.jsonl.gz")}
