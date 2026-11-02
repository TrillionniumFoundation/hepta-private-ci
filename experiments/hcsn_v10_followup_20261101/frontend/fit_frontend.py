"""Train ordinary historical AV heads; preserve selection and all predictions.

No raw waveform/vision encoder, original v6 reference, or fresh AV qualification.
Only causal accepted payloads enter features; actor/recording/target IDs do not.
"""

import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np
from scipy.fft import dct

from experiments.hcsn_v8_execution_20261101.frontend.replay import (
    DATA, episode_arrays, legacy_data,
)
from experiments.hcsn_v8_execution_20261101.frontend.legacy_v3 import LegacyV3Head
from experiments.hcsn_v8_execution_20261101.frontend.replay import populated_cache

ALPHAS = (.001, .01, .1, 1., 10., 100.)
KERNELS = ("linear", "rbf0.1", "rbf1", "rbf10")
FAMILIES = ("moments", "temporal", "cepstral", "spectral_shape")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")


def features(x, observed, times, modality, family, prefix=3.):
    """Fixed physical prefix; no future values inspected for finiteness."""
    parts = []
    for kind in ((0,) if modality == "audio" else (1,) if modality == "video" else (0, 1)):
        take = observed & ((x[:, 33] > x[:, 32]) == kind) & (times <= prefix)
        values, stamps = x[take, :16].astype(float), times[take]
        if not np.isfinite(values).all():
            raise ValueError("Nonfinite accepted prefix")
        if family == "spectral_shape" and kind == 0:
            values = values - values.mean(-1, keepdims=True)
        if family == "cepstral" and kind == 0:
            values = dct(values, type=2, axis=-1, norm="ortho")
        bins = (1,) if family == "moments" else (1, 2, 4)
        for count in bins:
            for index in range(count):
                local = values[(stamps > prefix * index / count) & (stamps <= prefix * (index + 1) / count)]
                if len(local):
                    parts.extend((local.mean(0), local.std(0), np.quantile(local, .25, axis=0),
                                  np.quantile(local, .75, axis=0)))
                else:
                    parts.extend([np.zeros(16)] * 4)
    return np.concatenate(parts)


def native_data(split):
    """Actual original-rate 16D features, before V3's 0.1s compression."""
    from experiments.hcsn_task_value_v1.async_av import event_inputs
    with np.load(DATA / (("validation" if split == "val" else split) + ".npz"), allow_pickle=False) as z:
        raw = {k: z[k].copy() for k in z.files}
    sequences, releases = [], []
    for i in range(len(raw["clip_ids"])):
        a,b = raw["offsets"][i:i+2]
        x,_ = event_inputs(raw["base"][a:b], raw["times"][a:b], raw["modality"][a:b],
                           raw["origins"][i], {"mean":raw["normalization_mean"], "scale":raw["normalization_scale"]})
        sequences.append(x)
        releases.append(raw["times"][a:b] - raw["origins"][i])
    width = max(map(len,sequences))
    n = len(sequences)
    result = {"x":np.zeros((n,width,40),np.float32), "observed":np.zeros((n,width),bool),
              "valid":np.zeros((n,width),bool), "relative_times":np.zeros((n,width)),
              "ids":raw["clip_ids"], "group_ids":raw["actors"], "y":np.full((n,width),-100,np.int64)}
    for i,x in enumerate(sequences):
        size = len(x)
        result["x"][i,:size],result["relative_times"][i,:size] = x,releases[i]
        result["observed"][i,:size] = True
        result["valid"][i,:size] = True
        result["y"][i,size-1] = raw["labels"][i]
    return result


def encoded(data, modality, family, prefix=3.):
    return np.stack([features(*episode_arrays(data, i), modality, family, prefix) for i in range(len(data["ids"]))])


def labels(data):
    ys = data["y"]
    return ys[np.arange(len(ys)), (ys >= 0).argmax(1)]


def kernel(x, z, name):
    dot = x @ z.T
    if name == "linear":
        return dot
    distance = np.maximum((x * x).sum(1)[:, None] + (z * z).sum(1)[None] - 2 * dot, 0)
    return np.exp(-float(name[3:]) * distance)


def fit(x, y, alpha, name):
    mean, scale = x.mean(0), np.maximum(x.std(0), 1e-4)
    z = (x - mean) / scale / np.sqrt(x.shape[1])
    targets = np.eye(6)[y]
    prior = targets.mean(0)
    dual = np.linalg.solve(kernel(z, z, name) + alpha * np.eye(len(x)), targets - prior)
    return {"mean": mean, "scale": scale, "training_features": z,
            "dual": dual, "prior": prior, "kernel": np.asarray(name), "alpha": np.asarray(alpha)}


def predict(model, x):
    z = (x - model["mean"]) / model["scale"] / np.sqrt(x.shape[1])
    logits = kernel(z, model["training_features"], str(model["kernel"])) @ model["dual"] + model["prior"]
    # The fixed scale is a declared score map, not empirical calibration.
    logit = logits - logits.max(1, keepdims=True)
    p = np.exp(logit)
    return p / p.sum(1, keepdims=True)


def metrics(p, y):
    return {"n": len(y), "correct": int(np.sum(p.argmax(1) == y)),
            "accuracy": float(np.mean(p.argmax(1) == y)),
            "nll": float(-np.log(p[np.arange(len(y)), y]).mean()),
            "brier": float(np.sum((p - np.eye(6)[y]) ** 2, axis=1).mean())}


def prediction_file(path, p, data):
    np.savez_compressed(path, probabilities=p, labels=labels(data),
                        recording_ids=data["ids"], actor_ids=data["group_ids"])
    return metrics(p, labels(data))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--input-policy", choices=("window", "native"), default="window")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    started, wall = time.process_time(), time.perf_counter()
    protocol = {"schema": "hcsn-v10-historical-frontend.v1", "source_sha256": sha(__file__),
                "train_sha256": sha(DATA / "train.npz"), "validation_sha256": sha(DATA / "validation.npz"),
                "task": "six-class historical V3 emotion; not v6 five-class emotion or semantic statement binding",
                "modalities": ["audio", "video", "av"], "families": list(FAMILIES),
                "kernels": list(KERNELS), "alphas": list(ALPHAS), "classes": 6,
                "selection": "minimum validation NLL; fixed declared enumeration order breaks ties",
                "input_policy": args.input_policy,
                "prior_attempt": "results002 ordinary cache heads did not improve accuracy; this version adds spectral-shape and native-rate development diagnoses",
                "input": "Native original-rate16D when native selected; extra information relative to same causal 0.1-second accepted V3 payloads; only first16 content coordinates and causal source time for physical bin membership",
                "state": "Temporal features computed from complete accepted cache; no 32-scalar memory claim",
                "prefix_seconds": 3., "future_input_forbidden": True,
                "test": "Previously exposed old test is diagnostic only, opened after all three selections; no independent validation or prospective freeze claim",
                "calibration": "No correctness calibrator fitted; fixed score softmax is not empirical correctness",
                "freeze_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "fresh_confirmation": False, "original_v6_assets_restored": False,
                "all_blockers_closed": False, "production_activation": False}
    save(args.out / "PROTOCOL.json", protocol)
    loader = native_data if args.input_policy == "native" else lambda s: legacy_data("async_av", s)
    data = {s: loader(s) for s in ("train", "val")}
    inventory = {s: {"recordings": d["ids"].tolist(), "actors": d["group_ids"].tolist()} for s,d in data.items()}
    if set(inventory["train"]["actors"]) & set(inventory["val"]["actors"]):
        raise ValueError("Training and validation actors overlap")
    save(args.out / "DEVELOPMENT_ROLES.json", inventory)
    selections, selected_models = {}, {}
    for modality in protocol["modalities"]:
        directory = args.out / modality
        directory.mkdir()
        candidates, best = [], None
        for family in FAMILIES:
            xt, xv = (encoded(data[s], modality, family) for s in ("train", "val"))
            for name in KERNELS:
                for alpha in ALPHAS:
                    identifier = f"{family}-{name}-a{alpha:g}"
                    model = fit(xt, labels(data["train"]), alpha, name)
                    model.update(family=np.asarray(family), modality=np.asarray(modality))
                    path = directory / (identifier + ".npz")
                    np.savez_compressed(path, **model)
                    pt, pv = predict(model, xt), predict(model, xv)
                    candidate = {"id": identifier, "features": xt.shape[1], "checkpoint_sha256": sha(path),
                                 "train": prediction_file(directory / (identifier + "-train.npz"), pt, data["train"]),
                                 "validation": prediction_file(directory / (identifier + "-val.npz"), pv, data["val"])}
                    candidates.append(candidate)
                    if best is None or candidate["validation"]["nll"] < best[0]["validation"]["nll"]:
                        best = candidate, model
        row, model = best
        np.savez_compressed(directory / "selected.npz", **model)
        save(directory / "CANDIDATES.json", candidates)
        selections[modality] = {**row, "selected_sha256": sha(directory / "selected.npz")}
        selected_models[modality] = model
    save(args.out / "SELECTION_COMPLETE.json", selections)
    data["test"] = loader("test")
    results = {}
    legacy = LegacyV3Head("async_av")
    for modality, model in selected_models.items():
        record = {"selected": selections[modality], "prefixes": {}}
        for prefix in (1., 2., 3.):
            bysplit = {}
            for split, values in data.items():
                p = predict(model, encoded(values, modality, str(model["family"]), prefix))
                entry = prediction_file(args.out / modality / f"selected-prefix{prefix:g}-{split}.npz", p, values)
                # Same original frozen head, same accepted contents; mode zero means no modality read.
                ap, vp = (int(prefix), 0) if modality == "audio" else (0, int(prefix)) if modality == "video" else (int(prefix), int(prefix))
                baseline = np.stack([legacy.classify(populated_cache(legacy_data("async_av", split), i, ap, vp)) for i in range(len(values["ids"]))])
                entry["original_v3_head"] = prediction_file(args.out / modality / f"legacy-prefix{prefix:g}-{split}.npz", baseline, values)
                bysplit[split] = entry
            record["prefixes"][str(int(prefix))] = bysplit
        results[modality] = record
    save(args.out / "RESULTS.json", {"results": results,
         "training_plus_scoring_process_cpu_seconds": time.process_time()-started,
         "training_plus_scoring_wall_seconds": time.perf_counter()-wall,
         "scope": "Historical development only; finite model search cannot establish globally strongest audio, quality gate, independent calibration or complete economics",
         "all_blockers_closed": False, "production_activation": False})
    print(json.dumps({m: {"selection":selections[m]["id"], "validation":selections[m]["validation"],
                         "old_test":results[m]["prefixes"]["3"]["test"]} for m in results}, indent=2))


if __name__ == "__main__":
    main()
