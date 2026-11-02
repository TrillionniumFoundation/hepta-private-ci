"""Fit ordinary audio references on the byte-verified, already exposed v3 cohort.

This is six-class emotion development, not the missing v6 strong-audio model.
"""

import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from experiments.hcsn_v8_execution_20261101.frontend.replay import (
    episode_arrays, legacy_data, populated_cache,
)
from experiments.hcsn_v8_execution_20261101.frontend.legacy_v3 import LegacyV3Head
from experiments.hcsn_causal_execution_v3.av_probe import labels_of

PREFIXES = (1, 2, 3)
ALPHAS = (.01, .1, 1., 10.)
TEMPERATURES = (.1, .25, .5, 1., 2.)
FAMILIES = ("linear", "rbf_0.25", "rbf_1", "rbf_4")
FEATURES = ("moments", "quantiles")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")


def audio_features(x, observed, times, prefix, feature_kind):
    # Source release is used for causal admission, never as a learned feature.
    use = observed & (x[:, 32] > x[:, 33]) & (x[:, 34] > 0) & (times <= prefix)
    values = np.asarray(x[use, :16], np.float64)
    if not np.isfinite(values).all():
        raise ValueError("Nonfinite accepted audio prefix")
    width = 48 if feature_kind == "moments" else 96
    if not len(values):
        return np.zeros(width)
    result = np.r_[values.mean(0), values.std(0), values[-1] - values[0]]
    return result if feature_kind == "moments" else np.r_[result, np.quantile(values, [.1, .5, .9], axis=0).ravel()]


def encode(data, feature_kind):
    rows = []
    for i in range(len(data["ids"])):
        x, observed, times = episode_arrays(data, i)
        rows.extend(audio_features(x, observed, times, p, feature_kind) for p in PREFIXES)
    return np.asarray(rows)


def softmax(scores, temperature):
    logits = scores / temperature
    logits -= logits.max(1, keepdims=True)
    probabilities = np.exp(logits)
    return probabilities / probabilities.sum(1, keepdims=True)


def score(probabilities, labels):
    return {"count": len(labels), "accuracy": float(np.mean(probabilities.argmax(1) == labels)),
            "nll": float(-np.log(np.maximum(probabilities[np.arange(len(labels)), labels], 1e-15)).mean())}


def distances(a, b):
    return np.maximum(0, (a * a).sum(1)[:, None] + (b * b).sum(1)[None] - 2 * a @ b.T)


def fit(x, labels, family, alpha):
    mean, scale = x.mean(0), np.maximum(x.std(0), 1e-6)
    z = (x - mean) / scale / np.sqrt(x.shape[1])
    if family == "linear":
        kernel, bandwidth = z @ z.T, 0.
    else:
        squared = distances(z, z)
        positive = squared[squared > 1e-12]
        bandwidth = float(np.median(positive) if len(positive) else 1.) * float(family.split("_")[1])
        kernel = np.exp(-squared / (2 * bandwidth))
    targets = np.eye(6)[labels]
    intercept = targets.mean(0)
    dual = np.linalg.solve(kernel + alpha * np.eye(len(z)), targets - intercept)
    return {"mean": mean, "scale": scale, "training_z": z, "dual": dual,
            "intercept": intercept, "bandwidth": np.asarray(bandwidth)}


def predict(model, features, temperature):
    z = (features - model["mean"]) / model["scale"] / np.sqrt(features.shape[1])
    bandwidth = float(model["bandwidth"])
    kernel = (z @ model["training_z"].T if bandwidth == 0 else
              np.exp(-distances(z, model["training_z"]) / (2 * bandwidth)))
    return softmax(kernel @ model["dual"] + model["intercept"], temperature)


def verify_input(data, expected):
    if (data["metadata"]["array_sha256"] != expected["array_sha256"] or
            data["ids"].astype(str).tolist() != expected["source_ids"] or
            hashlib.sha256(np.ascontiguousarray(data["x"]).tobytes()).hexdigest() != expected["content_sha256"]):
        raise ValueError("Historical data differs from recovered v9 input ledger")


def main(output, v9, stage):
    started_cpu, started_wall = time.process_time(), time.perf_counter()
    protocol = {
        "source_sha256": sha(Path(__file__)), "task": "v3 six-class emotion",
        "feature_kinds": FEATURES, "families": FAMILIES, "alphas": ALPHAS,
        "temperatures": TEMPERATURES, "prefixes_seconds": PREFIXES,
        "candidate_count": 160, "selection": "minimum historical-validation mean NLL over all three prefixes; first tie in declared order",
        "training": "train-only normalization and kernel fit; 24 recordings, 72 correlated prefix rows",
        "source_information": "Same causal 0.1-second emitted audio observations as original common head; no video/ID/actor/label/duration/count inputs",
        "test_role": "Previously exposed old test actors; descriptive replay only; labels were visible during earlier source investigation",
        "strong_audio_qualified": False, "original_v6_recovered": False, "fresh_confirmation": False,
        "cost_scope": "Separate preparation, fit and execution workers; imports/load/writes counted in each actual worker; original feature preparation/pretraining/decoding and development excluded"}
    if stage == "prepare":
        output.mkdir(parents=True, exist_ok=False)
        write(output / "PROTOCOL.json", protocol)
        return
    if json.loads((output / "PROTOCOL.json").read_text()) != json.loads(json.dumps(protocol)):
        raise ValueError("Protocol/source changed after preparation")
    ledger_path = v9 / "persistent_av/results002/async_av/INPUTS.json"
    ledger = json.loads(ledger_path.read_text())
    train, validation = legacy_data("async_av", "train"), legacy_data("async_av", "val")
    for data, key in ((train, "train"), (validation, "validation")):
        verify_input(data, ledger[key])
    labels = {"train": np.repeat(labels_of(train), 3), "validation": np.repeat(labels_of(validation), 3)}
    if stage == "train":
        candidates, best = [], None
        for kind in FEATURES:
            x, vx = encode(train, kind), encode(validation, kind)
            for family in FAMILIES:
                for alpha in ALPHAS:
                    model = fit(x, labels["train"], family, alpha)
                    for temperature in TEMPERATURES:
                        metrics = score(predict(model, vx, temperature), labels["validation"])
                        row = {"feature_kind": kind, "family": family, "alpha": alpha,
                               "temperature": temperature, "validation": metrics}
                        candidates.append(row)
                        if best is None or metrics["nll"] < best["validation"]["nll"]:
                            best, selected = row, {k: v.copy() for k, v in model.items()}
        write(output / "CANDIDATES.json", candidates)
        np.savez_compressed(output / "selected_audio_model.npz", **selected)
        write(output / "FREEZE.json", {"selected": best, "selected_model_sha256": sha(output / "selected_audio_model.npz"),
              "v9_input_ledger_sha256": sha(ledger_path), "train_input": train["metadata"],
              "validation_input": validation["metadata"], "frozen_before_this_test_execution": True,
              "independent_confirmation": False})
        return
    freeze = json.loads((output / "FREEZE.json").read_text())
    if freeze["selected_model_sha256"] != sha(output / "selected_audio_model.npz"):
        raise ValueError("Selected audio model changed after freeze")
    best = freeze["selected"]
    with np.load(output / "selected_audio_model.npz", allow_pickle=False) as z:
        selected = {k: z[k].copy() for k in z.files}
    # All model/recipe choices are fixed before this historical test execution.
    test = legacy_data("async_av", "test")
    test_identity = json.loads((v9 / "persistent_av/results002/async_av/HISTORICAL_TEST_INPUTS.json").read_text())
    verify_input(test, test_identity)
    head = LegacyV3Head("async_av")
    predictions, summaries = [], {}
    for split, data in (("train", train), ("validation", validation), ("test", test)):
        actual_labels = np.repeat(labels_of(data), 3)
        ordinary = predict(selected, encode(data, best["feature_kind"]), best["temperature"])
        original_audio, original_av = [], []
        for i in range(len(data["ids"])):
            for prefix in PREFIXES:
                original_audio.append(head.classify(populated_cache(data, i, prefix, 0)))
                original_av.append(head.classify(populated_cache(data, i, prefix, prefix)))
        summaries[split] = {}
        for name, values in (("selected_audio", ordinary), ("original_common_head_audio_only", np.asarray(original_audio)),
                             ("original_common_head_av", np.asarray(original_av))):
            summaries[split][name] = {str(p): score(values[np.arange(len(values)) % 3 == p - 1],
                                                   actual_labels[np.arange(len(values)) % 3 == p - 1]) for p in PREFIXES}
            for i, probability in enumerate(values):
                predictions.append({"split": split, "model": name, "recording": str(data["ids"][i // 3]),
                                    "actor": str(data["group_ids"][i // 3]), "prefix": PREFIXES[i % 3],
                                    "label": int(actual_labels[i]), "probabilities": probability.tolist()})
    # Inspect actual binding content, not filenames: identical audio inputs have opposing labels.
    binding = legacy_data("av_binding", "test")
    groups = {}
    for i, label in enumerate(labels_of(binding)):
        x, observed, times = episode_arrays(binding, i)
        audio = (observed & (x[:, 32] > x[:, 33]) & (x[:, 34] > 0) & (times <= 3))
        digest = hashlib.sha256(np.ascontiguousarray(x[audio, :16]).tobytes() +
                                np.ascontiguousarray(times[audio]).tobytes()).hexdigest()
        groups.setdefault(digest, []).append(int(label))
    balanced = all(row.count(0) == row.count(1) for row in groups.values())
    write(output / "BINDING_AUDIO_IDENTIFIABILITY.json", {
        "task": "Historical same-recording source binding, not v6 statement-relation binding",
        "objects": len(binding["ids"]), "distinct_actual_audio_prefix_sequences": len(groups),
        "labels_by_audio_sequence_sha256": groups, "all_groups_exactly_balanced": balanced,
        "audio_only_maximum_deterministic_empirical_accuracy":
            sum(max(row.count(0), row.count(1)) for row in groups.values()) / len(binding["ids"]),
        "scope": "Exact bound for this finite balanced set and this observed audio sequence; no population/information-theoretic generalization"})
    write(output / "PREDICTIONS.json", predictions)
    summary = {"selected": best, "by_split_model_prefix": summaries,
               "binding_audio_groups_balanced": balanced, "historical_test_recordings": len(test["ids"]),
               "historical_test_actors": sorted(set(test["group_ids"].astype(str))),
               "new_recordings": 0, "strong_audio_qualified": False, "frontend_gate_passed": False,
               "v6_recovered": False, "inner_cpu_seconds": time.process_time() - started_cpu,
               "inner_wall_seconds": time.perf_counter() - started_wall, "energy_joules": None}
    write(output / "SUMMARY.json", summary)
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--v9-evidence", type=Path, required=True)
    parser.add_argument("--stage", choices=("prepare", "train", "evaluate"), required=True)
    args = parser.parse_args()
    main(args.output, args.v9_evidence, args.stage)
