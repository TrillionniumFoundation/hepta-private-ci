"""Predeclared six-emotion TRAIN-only actor-OOF ridge development reference."""

import argparse
import hashlib
import json
from pathlib import Path
import re

import numpy as np
from .strong_audio import sha, write

HERE = Path(__file__).resolve().parent
INPUT = HERE / "reused_train001/inputs/train001"
CLASSES = ("ANG", "DIS", "FEA", "HAP", "NEU", "SAD")


def freeze():
    files = [HERE / name for name in ("strong_audio.py", "cache_contract.py", "emotion_readout.py", "PROTOCOL.json",
              "FORWARD_PLAN.json", "CACHE_PLAN.json", "forward001/RESULT.json", "cache_contract001/RESULT.json")]
    files += [INPUT / name for name in ("features.npz", "COHORT.json", "IDENTITY.json")]
    files += [HERE / "reused_train001" / name for name in ("CHECKPOINT.json", "SOURCE_PUBLICATION.json", "encoder.py")]
    write(HERE / "SOURCE_FREEZE.json", {"schema": "hcsn-v13-audio-readout-source-freeze.v1",
        "files_sha256": {str(path.relative_to(HERE)): sha(path) for path in files},
        "formal_OOF_fits_started": False, "validation_or_test_opened": False})


def source_guard():
    publication = json.loads((HERE / "SOURCE_PUBLICATION.json").read_text())
    if (not re.fullmatch(r"[0-9a-f]{40}", publication["source_commit"])
            or publication["source_freeze_sha256"] != sha(HERE / "SOURCE_FREEZE.json")):
        raise ValueError("Published exact source freeze is required before actor OOF")
    frozen = json.loads((HERE / "SOURCE_FREEZE.json").read_text())
    for path, expected in frozen["files_sha256"].items():
        if sha(HERE / path) != expected:
            raise ValueError("Frozen source/input changed: " + path)
    contract = json.loads((HERE / "cache_contract001/RESULT.json").read_text())
    if contract["status"] != "PASS" or contract["descriptor_bitwise_equal"] is not True:
        raise ValueError("Actual pretrained cache contract did not pass")
    return publication


def digest(array):
    return hashlib.sha256(np.ascontiguousarray(array).tobytes()).hexdigest()


def fit(x, y):
    mean, scale = x.mean(0), x.std(0)
    scale[scale < 1e-12] = 1.
    z = (x - mean) / scale
    targets = np.eye(6, dtype=np.float64)[y]
    bias = targets.mean(0)
    alpha = np.linalg.solve(z @ z.T + 10. * np.eye(len(z)), targets - bias)
    weight = z.T @ alpha
    return mean, scale, weight, bias


def probabilities(x, parameters):
    mean, scale, weight, bias = parameters
    scores = ((x - mean) / scale) @ weight + bias
    shifted = scores - scores.max(1, keepdims=True)
    exp = np.exp(shifted)
    return scores, exp / exp.sum(1, keepdims=True)


def save_parameters(path, parameters):
    with path.open("xb") as stream:
        np.savez_compressed(stream, mean=parameters[0], scale=parameters[1],
                            weight=parameters[2], bias=parameters[3], ridge=np.asarray(10.))


def metrics(probability, y):
    predicted = probability.argmax(1)
    truth = np.eye(6)[y]
    return {"correct": int((predicted == y).sum()), "examples": len(y),
            "accuracy": float((predicted == y).mean()),
            "uncalibrated_nll": float(-np.log(probability[np.arange(len(y)), y]).mean()),
            "uncalibrated_brier": float(np.square(probability - truth).sum(1).mean())}


def run(out):
    publication = source_guard()
    out.mkdir(parents=True, exist_ok=False)
    records = sorted(json.loads((INPUT / "COHORT.json").read_text())["records"], key=lambda r: r["clip"])
    if len(records) != 288 or any(row["split"] != "train" for row in records):
        raise ValueError("Only the frozen 288 TRAIN records are admissible")
    actors = np.asarray([str(row["actor"]) for row in records])
    y = np.asarray([CLASSES.index(row["emotion"]) for row in records])
    with np.load(INPUT / "features.npz", allow_pickle=False) as arrays:
        x = arrays["features"][:, :1536].astype(np.float64)
        if arrays["clip"].tolist() != [row["clip"] for row in records]:
            raise ValueError("Frozen feature rows no longer match TRAIN target metadata")
    if x.shape != (288, 1536) or not np.isfinite(x).all() or len(set(actors)) != 24:
        raise ValueError("Fixed actor/descriptor contract differs")
    oof, scores, folds = np.zeros((288, 6)), np.zeros((288, 6)), []
    for actor in sorted(set(actors)):
        held = np.flatnonzero(actors == actor)
        train = np.flatnonzero(actors != actor)
        if len(held) != 12 or not np.array_equal(np.bincount(y[held], minlength=6), np.full(6, 2)):
            raise ValueError("Each held actor must contain both sentences and six emotions")
        parameters = fit(x[train], y[train])
        local_scores, probability = probabilities(x[held], parameters)
        oof[held], scores[held] = probability, local_scores
        path = out / ("held_actor_" + actor + ".npz")
        save_parameters(path, parameters)
        folds.append({"held_actor": actor, "train_indices": train.tolist(), "held_indices": held.tolist(),
                      "train_actors": sorted(set(actors[train])), "train_x_sha256": digest(x[train]),
                      "train_y_sha256": digest(y[train]), "held_x_sha256": digest(x[held]),
                      "weights_sha256": sha(path), "normalization_fitted_only_on_train": True,
                      **metrics(probability, y[held])})
    save_parameters(out / "full_train.npz", fit(x, y))
    with (out / "OOF_PREDICTIONS.npz").open("xb") as stream:
        np.savez_compressed(stream, probability=oof, scores=scores, emotion_target=y, actor=actors,
                            clip=np.asarray([row["clip"] for row in records]))
    confusion = np.zeros((6, 6), dtype=np.int64)
    np.add.at(confusion, (y, oof.argmax(1)), 1)
    write(out / "RESULT.json", {"schema": "hcsn-v13-pretrained-emotion-development-reference.v1",
        "status": "COMPLETED", "source_publication": publication, "source_freeze_sha256": sha(HERE / "SOURCE_FREEZE.json"),
        "protocol_sha256": sha(HERE / "PROTOCOL.json"), "input_sha256": sha(INPUT / "features.npz"),
        "descriptor_width": 1536, "classes": list(CLASSES), "fixed_ridge": 10., "fits": 25,
        "held_actor_folds": folds, "oof": metrics(oof, y), "confusion_counts": confusion.tolist(),
        "oof_prediction_sha256": sha(out / "OOF_PREDICTIONS.npz"), "full_train_weights_sha256": sha(out / "full_train.npz"),
        "validation_or_test_loaded": False, "independent_confirmation": False,
        "emotion_readout_calibrated": False, "strong_audio_reference_qualified": False,
        "original_v6_head_recovered": False, "full_process_family_memory_bytes": None, "device_energy_joules": None,
        "scope": "Actor-OOF development on historical TRAIN; frozen ASR encoder, new six-emotion ridge head. No original v6 five-class/binding equivalence or new-group admission."})
    print(json.dumps({"fits": 25, "actor_folds": 24, "oof": metrics(oof, y)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("freeze", "run"))
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    freeze() if args.mode == "freeze" else run(args.out)
