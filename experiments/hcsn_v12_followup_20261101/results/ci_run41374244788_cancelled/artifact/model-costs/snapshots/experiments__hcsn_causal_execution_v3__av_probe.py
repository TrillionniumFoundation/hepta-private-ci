"""Ordinary causal AV feature sufficiency, selected before exploratory old test.

This probe uses the already published low-resolution CREMA-D features. It does
not create a foundation encoder or attribute shared content ability to HCSN.
Every predictor accepts an observed prefix; unavailable future rows are absent.
"""

import argparse
import hashlib
import json
from pathlib import Path
import resource
import time

import numpy as np


KINDS = ("moments", "bilinear", "synchrony", "combined")
ALPHAS = (.01, .1, 1., 10., 100., 1000.)
TEMPERATURES = (.1, .25, .5, 1., 2.)
ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, payload):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def prefix_features(x, observed, feature_kind):
    """Encode only accepted 40D rows; ignore absolute time, age, IDs and counts.

Each modality retains its own accepted observations. Synchrony uses causal
last-observation pairs at video arrivals; no interpolation or future pairing.
The means/stds use only the supplied prefix. Empty/one-modality prefixes work.
"""
    x = np.asarray(x, np.float64)
    observed = np.asarray(observed, bool)
    if x.ndim != 2 or x.shape[1] != 40 or observed.shape != (len(x),):
        raise ValueError("Expected a 40D accepted-prefix event sequence")
    if feature_kind not in KINDS or not np.isfinite(x).all():
        raise ValueError("Invalid feature family or nonfinite observed payload")
    history = [[], []]
    pairs = []
    latest = [None, None]
    for row, accepted in zip(x, observed, strict=True):
        if not accepted:
            continue
        kind = int(row[33] > row[32])
        if row[34 + kind] <= 0:
            continue
        value = row[:16].copy()
        history[kind].append(value)
        latest[kind] = value
        if kind == 1 and all(value is not None for value in latest):
            pairs.append(np.concatenate(latest))
    moments = []
    for rows in history:
        if not rows:
            moments.append(np.zeros(48))
            continue
        values = np.asarray(rows)
        moments.append(np.r_[values.mean(0), values.std(0), values[-1] - values[0]])
    additive = np.concatenate(moments)
    bilinear = np.outer(moments[0], moments[1]).ravel()
    correlations = []
    paired = np.asarray(pairs).reshape(-1, 32)
    for lag in (-2, -1, 0, 1, 2):
        if len(paired) <= abs(lag) + 1:
            correlations.append(np.zeros(256))
            continue
        a = paired[max(lag, 0):len(paired) + min(lag, 0), :16]
        v = paired[max(-lag, 0):len(paired) - max(lag, 0), 16:]
        a, v = a - a.mean(0), v - v.mean(0)
        denom = np.maximum(np.linalg.norm(a, axis=0)[:, None] *
                           np.linalg.norm(v, axis=0)[None, :], 1e-8)
        correlations.append(((a.T @ v) / denom).ravel())
    synchrony = np.concatenate(correlations)
    return dict(moments=additive, bilinear=bilinear, synchrony=synchrony,
                combined=np.r_[additive, bilinear, synchrony])[feature_kind]


def encode(values, kind):
    return np.stack([prefix_features(x[valid], obs[valid], kind)
        for x, obs, valid in zip(values["x"], values["observed"], values["valid"], strict=True)])


def probabilities(scores, temperature):
    logits = scores / temperature
    logits -= logits.max(-1, keepdims=True)
    exponent = np.exp(logits)
    return exponent / exponent.sum(-1, keepdims=True)


def score(probability, labels):
    return dict(accuracy=float((probability.argmax(-1) == labels).mean()),
        ce=float(-np.log(np.maximum(probability[np.arange(len(labels)), labels], 1e-15)).mean()),
        examples=len(labels))


def labels_of(values):
    labels = values["y"]
    if not np.all((labels >= 0).sum(1) == 1):
        raise ValueError("Expected exactly one final target per AV sample")
    return labels[np.arange(len(labels)), (labels >= 0).argmax(1)]


def fit(train, labels, classes, alpha):
    mean = train.mean(0)
    scale = np.maximum(train.std(0), 1e-6)
    x = (train - mean) / scale / np.sqrt(train.shape[1])
    targets = np.eye(classes)[labels]
    intercept = targets.mean(0)
    dual = np.linalg.solve(x @ x.T + alpha * np.eye(len(x)), targets - intercept)
    return dict(mean=mean, scale=scale, weights=x.T @ dual, intercept=intercept)


def predict_features(model, features):
    features = np.asarray(features)
    standardized = (features - model["mean"]) / model["scale"] / np.sqrt(len(model["mean"]))
    scores = standardized @ model["weights"] + model["intercept"]
    return probabilities(scores, float(model["temperature"]))


def load_encoder(path):
    with np.load(path, allow_pickle=False) as archive:
        return {key: archive[key].copy() for key in archive.files}


def predict_prefix(model, x, observed):
    """Public READ-before-encode interface: caller passes accepted rows only."""
    return predict_features(model, prefix_features(x, observed,
                            str(model["feature_kind"]))[None])[0]


def save_predictions(path, data, probability):
    labels = labels_of(data)
    np.savez_compressed(path, probabilities=probability, labels=labels,
        sample_ids=data["ids"], actor_ids=data["group_ids"],
        input_array_sha256=np.asarray(data["metadata"]["array_sha256"]))
    return score(probability, labels)


def actor_summary(data, probability):
    labels = labels_of(data)
    rows = []
    for actor in np.unique(data["group_ids"]):
        index = data["group_ids"] == actor
        rows.append(dict(actor=str(actor), **score(probability[index], labels[index])))
    accuracies = np.array([row["accuracy"] for row in rows])
    rng = np.random.default_rng(2026110143)
    bootstrap = np.mean(rng.choice(accuracies, (10000, len(accuracies))), axis=1)
    return dict(actors=rows, actor_macro_accuracy=float(accuracies.mean()),
        descriptive_actor_bootstrap_95=np.quantile(bootstrap, [.025, .975]).tolist(),
        independent_actors=len(rows),
        limitation="Only two reused test actors. This descriptive resampling interval is not reliable population confirmation.")


def run(output):
    from experiments.hcsn_mechanism_content_v2.data import load_data
    from experiments.hcsn_mechanism_content_v2.binding_data import verify_single_modality_marginals

    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    started_wall, started_cpu = time.perf_counter(), time.process_time()
    data_directory = ROOT / "experiments/hcsn_task_value_v1/results/async_frontend001/data"
    protocol = dict(schema="hcsn-v3.av-feature-probe", source_sha256=digest(__file__),
        tasks=["async_av", "av_binding"], families=list(KINDS), alphas=list(ALPHAS),
        temperatures=list(TEMPERATURES), selection="minimum validation CE; first tie in declared order",
        fitting="train-only feature mean/std and regularized least-squares one-hot targets",
        train_data_sha256=digest(data_directory / "train.npz"),
        validation_data_sha256=digest(data_directory / "validation.npz"),
        candidate_count_per_task=len(KINDS) * len(ALPHAS) * len(TEMPERATURES),
        test_access="selected checkpoint only; test and interventions opened after selection files",
        test_status="Exploratory reused old actors; baseline metadata inspected before this run; no fresh confirmation",
        features="No actor/clip/emotion labels, absolute timestamps, age, duration, or count input. Causal observed-prefix moments/interactions.",
        candidate_limits="Small validation set and finite grid selection can overfit validation; report all candidates",
        diagnostics=["missing_audio", "missing_video", "content_shuffle", "metadata_only"],
        qualification=dict(async_av_validation_accuracy=.5, av_binding_validation_accuracy=.75,
            meaning="Exploratory frontend screening threshold only, not inferential acceptance"),
        frozen_at_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    write_json(output / "protocol.json", protocol)
    records, selections = [], {}
    for task in protocol["tasks"]:
        task_out = output / task
        task_out.mkdir()
        job = dict(task=task, av_directory=str(data_directory), av_window_seconds=.1,
                   binding_deadline_seconds=1.5, binding_pair_seed=2026110173)
        train = load_data(job, "train")
        validation = load_data(job, "val")
        y_train, y_validation = labels_of(train), labels_of(validation)
        classes = 2 if task == "av_binding" else 6
        best, candidates, timing = None, [], []
        for kind in KINDS:
            wall, cpu = time.perf_counter(), time.process_time()
            features_train, features_validation = encode(train, kind), encode(validation, kind)
            timing.append(dict(feature_kind=kind, cpu_seconds=time.process_time() - cpu,
                               wall_seconds=time.perf_counter() - wall, scope="train+validation prefix encoding"))
            for alpha in ALPHAS:
                fitted = fit(features_train, y_train, classes, alpha)
                for temperature in TEMPERATURES:
                    identifier = f"{kind}_a{alpha:g}_t{temperature:g}"
                    candidate = dict(**fitted, temperature=np.asarray(temperature),
                        feature_kind=np.asarray(kind), alpha=np.asarray(alpha), task=np.asarray(task))
                    p_train = predict_features(candidate, features_train)
                    p_validation = predict_features(candidate, features_validation)
                    np.savez_compressed(task_out / (identifier + ".npz"), **candidate)
                    metrics_train = save_predictions(task_out / (identifier + "_train_predictions.npz"), train, p_train)
                    metrics_validation = save_predictions(task_out / (identifier + "_validation_predictions.npz"), validation, p_validation)
                    row = dict(id=identifier, family=kind, alpha=alpha, temperature=temperature,
                        features=features_train.shape[1], train=metrics_train, validation=metrics_validation)
                    candidates.append(row)
                    if best is None or metrics_validation["ce"] < best[0]["validation"]["ce"]:
                        best = row, candidate
        row, model = best
        np.savez_compressed(task_out / "selected_encoder.npz", **model)
        selection = dict(**row, checkpoint_sha256=digest(task_out / "selected_encoder.npz"),
            qualified_validation_screen=row["validation"]["accuracy"] >= protocol["qualification"][task + "_validation_accuracy"],
            selected_before_current_test_open=True, independent_training_actors=len(np.unique(train["group_ids"])),
            independent_validation_actors=len(np.unique(validation["group_ids"])))
        write_json(task_out / "selection.json", selection)
        write_json(task_out / "candidates.json", candidates)
        write_json(task_out / "feature_costs.json", timing)
        selections[task] = selection
        records.append((task, job, model, task_out))
    # Both tasks are selected before any test evaluation in this run.
    write_json(output / "SELECTION_COMPLETE.json", selections)
    results = {}
    for task, job, model, task_out in records:
        task_results = {}
        diagnostics = [None, "missing_audio", "missing_video", "content_shuffle"]
        if task == "av_binding":
            diagnostics.append("metadata_only")
        else:
            diagnostics.append("modality_mismatch")
        for diagnostic in diagnostics:
            wall, cpu = time.perf_counter(), time.process_time()
            data = load_data(job, "test", diagnostic=diagnostic, allow_heldout=True)
            probability = predict_features(model, encode(data, str(model["feature_kind"])))
            label = diagnostic or "normal"
            metrics = save_predictions(task_out / ("test_" + label + ".npz"), data, probability)
            task_results[label] = dict(**metrics, **actor_summary(data, probability),
                cpu_seconds=time.process_time() - cpu, wall_seconds=time.perf_counter() - wall,
                input_array_sha256=data["metadata"]["array_sha256"])
        if task == "av_binding":
            audio = load_data(job, "test", diagnostic="missing_video", allow_heldout=True)
            video = load_data(job, "test", diagnostic="missing_audio", allow_heldout=True)
            task_results["single_modality_balance"] = verify_single_modality_marginals(audio, video)
        results[task] = task_results
    summary = dict(protocol_sha256=digest(output / "protocol.json"), selections=selections,
        results=results, cpu_seconds=time.process_time() - started_cpu,
        wall_seconds=time.perf_counter() - started_wall,
        max_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        energy_joules=None, scope="prepared-feature dataset load, candidate fitting/selection, artifact I/O and inference; no original media decode or network",
        conclusion="Shared ordinary feature sufficiency only; no analytic-core attribution or fresh-actor confirmation")
    write_json(output / "summary.json", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.output)
    print(json.dumps(dict(selections=result["selections"], results=result["results"],
                          cpu_seconds=result["cpu_seconds"]), indent=2))
