"""Independent exact original model/feature reader and label reviewer for V7.

Does not import the V7 producer, load/download pretrained weights, train Heads,
or assign production authority. Compares new T=1 to original V3 artifact before
scoring train-calibrated same-Encoder centroids against immutable learned Heads.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import sys

import numpy as np
from safetensors.numpy import load_file

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "stem-optimal-v3"))
sys.path.insert(0, str(ROOT / "stem-optimal-v1"))
import stem_hard_charge_review_v3 as source_review
import stem_review_v1 as v1review

SCHEMA = "hepta.stem.same-encoder-trainonly-centroid.v7"
ARMS = ("original_centroid_t1", "train_calibrated_centroid")
MODELS = ("granite47", "granite97", "mmbert140")
GRID = (0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0)
FOLD_SALT = "hepta-hard-charge-v6-fixed-four-stratified-folds\\0"
SOURCE_SHA = "3e79b3449f3b63d1f261ae4ad9632ae4cff07262a82c5259a17d040e61929900"
MODEL_FIELDS = {"schema", "source_plan_sha256", "candidate", "model_repo", "model_revision",
                "weight_sha256", "model_material_sha256", "features_sha256", "feature_dtype",
                "feature_rows", "feature_width", "fit_ids", "heldout_ids", "fold_salt", "grid",
                "fit_folds", "cv_brier_by_temp", "selected_temperature", "rows", "cost",
                "publisher_heldout_label_access", "source_independent_families", "future_windows",
                "physical_claim_unattested", "production_authorized", "stem_winner_verified",
                "disposition", "authority"}


def need(condition, reason):
    if not condition:
        raise ValueError(reason)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(obj):
    return json.dumps(obj, sort_keys=True, ensure_ascii=False,
                      allow_nan=False, separators=(",", ":")).encode()


def _scores(fit, labels, check):
    need(fit.shape[1:] == check.shape[1:] == (384,) and
         len(fit) == len(labels) and all(labels.count(k) > 0 for k in range(4)),
         "independent original features/class geometry mismatch")
    centers = []
    for k in range(4):
        subset = fit[np.asarray(labels) == k]
        c = np.mean(subset, axis=0, dtype=np.float32)
        norm = float(np.linalg.norm(c))
        need(math.isfinite(norm) and norm > 1e-8, "independent class center missing")
        centers.append(c / norm)
    return np.asarray(check @ np.stack(centers).T, dtype=np.float64)


def _prob(x, temperature):
    y = x * temperature
    y -= np.max(y, axis=-1, keepdims=True)
    p = np.exp(y)
    return p / np.sum(p, axis=-1, keepdims=True)


def _original_replay(source, receipt, material, original_v3, feature_file):
    need(type(receipt) is dict and set(receipt) == MODEL_FIELDS and
         receipt["schema"] == SCHEMA and receipt["source_plan_sha256"] == SOURCE_SHA and
         receipt["candidate"] in MODELS and
         receipt["source_independent_families"] == 1 and receipt["future_windows"] == 0 and
         receipt["authority"] == "DENY_ALL" and receipt["disposition"] == "HOLD_NO_GO" and
         receipt["production_authorized"] is False and receipt["stem_winner_verified"] is False and
         receipt["publisher_heldout_label_access"] is False and
         receipt["physical_claim_unattested"] is True,
         "unqualified V7 producer identity/authority")
    name = receipt["candidate"]
    spec = material["candidates"][name]
    need((receipt["model_repo"], receipt["model_revision"], receipt["weight_sha256"]) ==
         (spec["repo"], spec["revision"], spec["weight_sha256"]) and
         receipt["model_material_sha256"] == sha(canonical(material)),
         "V7 model manifest/weight mismatch")
    need(receipt["feature_dtype"] == "float32" and receipt["feature_rows"] == 96 and
         receipt["feature_width"] == 384 and
         receipt["fit_ids"] == [r["case_id"] for r in source["train"]] and
         receipt["heldout_ids"] == [r["case_id"] for r in source["heldout"]] and
         receipt["fold_salt"] == FOLD_SALT and receipt["grid"] == list(GRID),
         "V7 tensor/fold/input identity changed")
    c = receipt["cost"]
    need(type(c) is dict and set(c) == {"encoder_forward_batches", "physical_encoder_sequences",
         "model_download_load_wall_seconds", "feature_encode_wall_seconds",
         "elapsed_wall_seconds", "elapsed_cpu_seconds", "maxrss_bytes", "energy_joules", "p99_latency_ms"}
         and c["physical_encoder_sequences"] == 96 and c["encoder_forward_batches"] == 6 and
         c["energy_joules"] is None and c["p99_latency_ms"] is None and
         type(c["maxrss_bytes"]) is int and c["maxrss_bytes"] > 0 and
         all(type(c[k]) in (float, int) and math.isfinite(c[k]) and c[k] >= 0
             for k in ("model_download_load_wall_seconds", "feature_encode_wall_seconds",
                       "elapsed_wall_seconds", "elapsed_cpu_seconds")),
         "V7 self-reported cost omitted or falsified")
    path = Path(feature_file)
    need(path.is_file() and not path.is_symlink() and
         0 < path.stat().st_size <= 300_000 and
         sha(path.read_bytes()) == receipt["features_sha256"],
         "V7 actual original feature artifact byte mismatch")
    data = load_file(str(path))
    need(set(data) == {"features"} and data["features"].shape == (96, 384) and
         data["features"].dtype == np.float32 and np.isfinite(data["features"]).all(),
         "V7 source feature tensor corrupt/nonfloat")
    features = data["features"]
    need(np.linalg.norm(features, axis=1).min() >= 0.9999 and
         np.linalg.norm(features, axis=1).max() <= 1.0001,
         "real pretrained pooled feature norm drift")
    fit = source["train"]
    labels = [r["label"] for r in fit]
    folds = [-1]*64
    for category in range(4):
        indices = sorted([i for i, row in enumerate(fit) if row["label"] == category],
                         key=lambda i: sha((FOLD_SALT + fit[i]["case_id"]).encode()))
        need(len(indices) == 16, "original V7 training class coverage")
        for index, ix in enumerate(indices):
            folds[ix] = index % 4
    need(receipt["fit_folds"] == folds and all(folds.count(k) == 16 for k in range(4)),
         "altered original fold assignment")
    cvloss = [0.0]*len(GRID)
    for k in range(4):
        tr = [i for i, j in enumerate(folds) if j != k]
        va = [i for i, j in enumerate(folds) if j == k]
        cos = _scores(features[tr], [labels[i] for i in tr], features[va])
        for j, temperature in enumerate(GRID):
            pred = _prob(cos.copy(), temperature)
            for row, original_ix in zip(pred, va):
                y = labels[original_ix]
                cvloss[j] += sum((float(value)-float(i == y))**2
                                 for i,value in enumerate(row)) / 64
    choice = min(range(len(GRID)), key=lambda j: (cvloss[j], GRID[j]))
    need(receipt["selected_temperature"] == GRID[choice] and
         len(receipt["cv_brier_by_temp"]) == len(GRID) and
         all(type(y) in (float,int) and math.isfinite(y) and abs(x-y) <= 1e-5
             for x,y in zip(cvloss, receipt["cv_brier_by_temp"])),
         "V7 train-only temperature/CV loss cannot independently replay")
    logits = _scores(features[:64], labels, features[64:])
    original1 = _prob(logits.copy(), 1.0)
    calibrated = _prob(logits.copy(), GRID[choice])
    old_rows = {r["case_id"]: r for r in original_v3["rows"]}
    need(original_v3["candidate"] == name and
         original_v3["source_plan_sha256"] == SOURCE_SHA and
         len(old_rows) == 32 and len(receipt["rows"]) == 32,
         "cannot compare with pinned original V3 pretrained control")
    for i, case in enumerate(source["heldout"]):
        row = receipt["rows"][i]
        need(type(row) is dict and set(row) == {"case_id", "source_sha256", "scores"} and
             row["case_id"] == case["case_id"] and
             row["source_sha256"] == case["source_sha256"] and
             type(row["scores"]) is dict and set(row["scores"]) == set(ARMS),
             "V7 heldout label, source or score missing")
        orig, new = row["scores"][ARMS[0]], row["scores"][ARMS[1]]
        for expected, actual in ((original1[i],orig), (calibrated[i],new)):
            need(type(actual) is list and len(actual) == 4 and
                 all(type(x) in (float, int) and math.isfinite(x) and 0 <= x <= 1 for x in actual)
                 and abs(sum(actual) - 1) <= 1e-5 and
                 all(abs(float(a)-float(b)) <= 5e-5 for a,b in zip(expected,actual)),
                 "original V7 feature replay numerical mismatch")
        old = old_rows[case["case_id"]]["scores"]["centroid"]
        need(all(abs(a-b) <= 5e-4 for a,b in zip(orig,old)),
             "independent V3 pretrained T1 drift; cross-run model parity HOLD")
    return {"temperature": GRID[choice], "cv_brier": cvloss[choice],
            "original_t1_replays_v3": True,
            "original_forward_calls": c["physical_encoder_sequences"]}


def review_original(train_raw, test_raw, source, material, originals, v7_runs):
    v1review._validate_model_spec(material)
    expected, gold = source_review.reconstruct(train_raw, test_raw, v1review.FIXED_SHA)
    need(source["schema"] == source_review.SOURCE_SCHEMA and
         source["source_plan_sha256"] == SOURCE_SHA and
         source["train"] == expected["train"] and
         source["heldout"] == expected["heldout"] and
         source["heldout_labels_excluded"] is True,
         "V7 original publisher source/heldout label mismatch")
    need(set(originals) == set(v7_runs) == set(MODELS), "not all original Encoder arms")
    scores={}
    for name in MODELS:
        receipt, feature_file = v7_runs[name]
        replay = _original_replay(source, receipt, material, originals[name], feature_file)
        original_rows={r["case_id"]:r for r in originals[name]["rows"]}
        tally = {a:{"correct":0,"mean_multiclass_brier":0.0} for a in ARMS}
        same = {"calibrated_only":0, "original_learned_only":0}
        original_learned_brier = 0.0
        for row in receipt["rows"]:
            y=gold[row["case_id"]]
            for arm in ARMS:
                p=row["scores"][arm]
                tally[arm]["correct"]+= int(max(range(4), key=lambda j:p[j]) == y)
                tally[arm]["mean_multiclass_brier"] += sum(
                    (x-float(j==y))**2 for j,x in enumerate(p))/32
            learned=original_rows[row["case_id"]]["scores"]["learned"]
            original_learned_brier += sum((float(p)-float(k==y))**2
                                          for k,p in enumerate(learned))/32
            a=max(range(4), key=lambda j:row["scores"][ARMS[1]][j]) == y
            b=max(range(4), key=lambda j:learned[j]) == y
            same["calibrated_only"] += int(a and not b)
            same["original_learned_only"] += int(b and not a)
        need(tally[ARMS[0]]["correct"] ==
             sum(max(range(4),key=lambda k:original_rows[r["case_id"]]["scores"]["centroid"][k])==gold[r["case_id"]]
                 for r in receipt["rows"]), "original V3 centroid classes do not match")
        discordant = same["calibrated_only"] + same["original_learned_only"]
        if discordant:
            exact_p = min(1.0, 2 * sum(math.comb(discordant, i) for i in
                    range(min(same.values()) + 1)) / (2 ** discordant))
        else:
            exact_p = 1.0
        scores[name] = {"train_only": replay, "centroids": tally,
                        "calibrated_vs_original_learned": same,
                        "exploratory_exact_mcnemar_p": exact_p,
                        "original_learned_multiclass_brier": original_learned_brier,
                        "delta_brier_calibrated_minus_learned":
                            tally["train_calibrated_centroid"]["mean_multiclass_brier"] - original_learned_brier,
                        "original_learned_n32": sum(max(range(4), key=lambda k:r["scores"]["learned"][k])==gold[r["case_id"]]
                                                    for r in originals[name]["rows"])}
    return {"schema":"hepta.stem.same-encoder-independent-review.v7",
            "case_count":32,"original_pub_bytes_verified":True,
            "training_only_calibration_replayed":True,"original_v3_t1_matched":True,
            "models":scores,"source_independent_families":1,"future_windows":0,
            "original_labels_previously_exposed":True,
            "stem_winner_verified":False,"ndu_benefit_verified":False,
            "production_authorized":False,"cell_split_authorized":False,
            "disposition":"HOLD_NO_GO","authority":"DENY_ALL"}


def main():
    parser=argparse.ArgumentParser()
    for arg in ("train","test","source","materials","output"):
        parser.add_argument("--"+arg,required=True)
    for name in MODELS:
        parser.add_argument("--v3-"+name,required=True)
        parser.add_argument("--v7-"+name,required=True)
        parser.add_argument("--features-"+name,required=True)
    args=parser.parse_args()
    source=json.loads(Path(args.source).read_text())
    material=json.loads(Path(args.materials).read_text())
    old={name:json.loads(Path(getattr(args,"v3_"+name)).read_text()) for name in MODELS}
    recent={name:(json.loads(Path(getattr(args,"v7_"+name)).read_text()),
                  Path(getattr(args,"features_"+name))) for name in MODELS}
    outcome=review_original(Path(args.train).read_bytes(),Path(args.test).read_bytes(),
                            source,material,old,recent)
    path=Path(args.output)
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("xb") as f:
        f.write(canonical(outcome)+b"\n")
    print(json.dumps({"sha256":sha(path.read_bytes()),"authority":"DENY_ALL",
                      "disposition":"HOLD_NO_GO"},sort_keys=True))


if __name__=="__main__":
    main()
