"""Research only: pinned real Encoder -> train-only calibrated same-Encoder centroid.

Neither this producer nor its receipt sees any TEST target. Uncalibrated T=1
predictions are retained for comparison against the immutable V3 original run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "stem-optimal-v1"))
sys.path.insert(0, str(ROOT / "stem-optimal-v6"))
import stem_candidate_v1 as original
import calibrated_lexical_v6 as frozen

SCHEMA = "hepta.stem.same-encoder-trainonly-centroid.v7"
GRID = frozen.GRID
MODEL_NAMES = original.MODEL_NAMES
SOURCE_SHA = frozen.SOURCE_SHA


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      allow_nan=False, separators=(",", ":")).encode()


def _logits(train_features, labels, check_features):
    """Numerically stable class-mean cosine, no learned Head / test labels."""
    import torch
    need(train_features.ndim == check_features.ndim == 2 and
         train_features.shape[1] == check_features.shape[1] == 384 and
         train_features.shape[0] == len(labels) and len(labels) >= 4 and
         all(type(y) is int and 0 <= y < 4 for y in labels),
         "invalid original encoder/label geometry")
    need(bool(torch.isfinite(train_features).all()) and
         bool(torch.isfinite(check_features).all()), "nonfinite pretrained feature")
    label = torch.tensor(labels, dtype=torch.long)
    centroid = torch.stack([train_features[label == c].mean(0) for c in range(4)])
    need(bool(torch.isfinite(centroid).all()) and
         bool((centroid.norm(dim=-1) > 1e-8).all()), "empty centroid")
    centroid = torch.nn.functional.normalize(centroid, dim=-1)
    return (check_features @ centroid.T).float()


def _softmax(logits, temp):
    import torch
    need(temp in GRID, "temperature outside frozen candidate grid")
    return torch.softmax(logits * temp, dim=-1)


def calibrate(features, source):
    """One already-encoded 96x384 FP32 source; all fitting from 64 TRAIN only."""
    import torch
    frozen.validate_source(source)
    need(isinstance(features, torch.Tensor) and
         tuple(features.shape) == (96, 384) and features.dtype == torch.float32 and
         features.device.type == "cpu" and bool(torch.isfinite(features).all()),
         "incompatible original feature snapshot")
    labels = [row["label"] for row in source["train"]]
    folds = frozen.stratified_folds(source["train"])
    loss = [0.0 for _ in GRID]
    with torch.no_grad():
        for k in range(4):
            train_idx = [i for i, value in enumerate(folds) if value != k]
            check_idx = [i for i, value in enumerate(folds) if value == k]
            logits = _logits(features[train_idx], [labels[i] for i in train_idx],
                             features[check_idx])
            for j, t in enumerate(GRID):
                p = _softmax(logits, t).double().tolist()
                for prob, ix in zip(p, check_idx):
                    y = labels[ix]
                    loss[j] += sum((v - float(pos == y))**2 for pos, v in enumerate(prob)) / 64
        winner = min(range(len(GRID)), key=lambda j: (loss[j], GRID[j]))
        logits = _logits(features[:64], labels, features[64:])
        original_prob = _softmax(logits, 1.0).tolist()
        calibrated_prob = _softmax(logits, GRID[winner]).tolist()
    return {"grid": list(GRID), "fit_folds": folds,
            "cv_brier_by_temp": loss, "selected_temperature": GRID[winner],
            "t1": original_prob, "calibrated": calibrated_prob}


def physical_original(source, materials, model_name, feature_file):
    """Executes original pinned complete checkpoint and six genuine CPU batches."""
    import torch
    from safetensors.torch import load_file, save_file
    frozen.validate_source(source)
    need(model_name in MODEL_NAMES and
         materials == original.load_materials(Path(__file__).resolve().parents[1] /
                                              "stem-optimal-v1" / "MODEL_MATERIALS.json"),
         "model roster/material pin substitution")
    spec = materials["candidates"][model_name]
    torch.set_num_threads(2)
    started, cpu = time.perf_counter(), time.process_time()
    tokenizer, model = original._material_model(spec)
    loading = time.perf_counter() - started
    began = time.perf_counter()
    fit, n_fit = original._encode([r["text"] for r in source["train"]], tokenizer, model)
    test, n_test = original._encode([r["text"] for r in source["heldout"]], tokenizer, model)
    encoding = time.perf_counter() - began
    need(n_fit + n_test == 6 and fit.shape == (64, 384) and
         test.shape == (32, 384), "missing original pretrained forward work")
    features = torch.cat((fit, test)).contiguous().float().cpu()
    feature_file.parent.mkdir(parents=True, exist_ok=True)
    save_file({"features": features}, str(feature_file))
    need(torch.equal(load_file(str(feature_file))["features"], features),
         "feature tensor physical save/reopen drift")
    selected = calibrate(features, source)
    rows = [{"case_id": item["case_id"], "source_sha256": item["source_sha256"],
             "scores": {"original_centroid_t1": selected["t1"][i],
                        "train_calibrated_centroid": selected["calibrated"][i]}}
            for i, item in enumerate(source["heldout"])]
    return {"schema": SCHEMA, "source_plan_sha256": SOURCE_SHA,
            "candidate": model_name, "model_repo": spec["repo"],
            "model_revision": spec["revision"], "weight_sha256": spec["weight_sha256"],
            "model_material_sha256": sha(canonical(materials)),
            "features_sha256": sha(feature_file.read_bytes()),
            "feature_dtype": "float32", "feature_rows": 96, "feature_width": 384,
            "fit_ids": [x["case_id"] for x in source["train"]],
            "heldout_ids": [x["case_id"] for x in source["heldout"]],
            "fold_salt": frozen.FOLD_SALT, "grid": selected["grid"],
            "fit_folds": selected["fit_folds"],
            "cv_brier_by_temp": selected["cv_brier_by_temp"],
            "selected_temperature": selected["selected_temperature"], "rows": rows,
            "cost": {"encoder_forward_batches": n_fit + n_test,
                     "physical_encoder_sequences": 96,
                     "model_download_load_wall_seconds": loading,
                     "feature_encode_wall_seconds": encoding,
                     "elapsed_wall_seconds": time.perf_counter() - started,
                     "elapsed_cpu_seconds": time.process_time() - cpu,
                     "maxrss_bytes": original._peak_rss_bytes(),
                     "energy_joules": None, "p99_latency_ms": None},
            "publisher_heldout_label_access": False,
            "source_independent_families": 1, "future_windows": 0,
            "physical_claim_unattested": True,
            "production_authorized": False, "stem_winner_verified": False,
            "disposition": "HOLD_NO_GO", "authority": "DENY_ALL"}


def main():
    parser = argparse.ArgumentParser()
    for arg in ("source", "materials", "candidate", "feature-file", "output"):
        parser.add_argument("--" + arg, required=True)
    a = parser.parse_args()
    source = json.loads(Path(a.source).read_text())
    material = original.load_materials(Path(a.materials))
    output = Path(a.output)
    need(not output.exists() and not Path(a.feature_file).exists(),
         "original outputs are create-once")
    result = physical_original(source, material, a.candidate, Path(a.feature_file))
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as f:
        f.write(canonical(result) + b"\n")
        f.flush()
    print(json.dumps({"candidate": a.candidate, "sha256": sha(output.read_bytes()),
                      "physical_encoder_sequences": 96, "authority": "DENY_ALL"},
                     sort_keys=True))


if __name__ == "__main__":
    main()
