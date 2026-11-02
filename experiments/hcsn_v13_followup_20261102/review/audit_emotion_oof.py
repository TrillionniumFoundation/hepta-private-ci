"""Independent TRAIN-only actor-OOF reconstruction using a spectral ridge solve.

Does not import the author's reader, feature extractor or fit routine, and has
no validation/test data path. The only labels read are the frozen TRAIN cohort.
"""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.linalg import eigh


CLASSES = ("ANG", "DIS", "FEA", "HAP", "NEU", "SAD")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def digest(array):
    return hashlib.sha256(np.ascontiguousarray(array).tobytes()).hexdigest()


def spectral_fit(x, y):
    center, scale = np.mean(x, axis=0), np.std(x, axis=0)
    scale = np.where(scale < 1e-12, 1., scale)
    z = (x-center)/scale
    targets = np.eye(6)[y]
    bias = np.mean(targets, axis=0)
    eigenvalues, vectors = eigh(z @ z.T, check_finite=True)
    coefficients = vectors @ ((vectors.T @ (targets-bias))/(eigenvalues[:, None]+10.))
    return center, scale, z.T @ coefficients, bias


def predict(x, p):
    center, scale, weight, bias = p
    scores = ((x-center)/scale) @ weight + bias
    exp = np.exp(scores-np.max(scores, axis=1, keepdims=True))
    return scores, exp/np.sum(exp, axis=1, keepdims=True)


def audit(frontend, run):
    checks, failures, maxima = 0, [], {}

    def check(ok, name):
        nonlocal checks
        checks += 1
        if not ok and len(failures) < 25:
            failures.append(name)

    def close(name, actual, expected):
        actual, expected = np.asarray(actual), np.asarray(expected)
        difference = float(np.max(abs(actual-expected)))
        maxima[name] = max(maxima.get(name, 0.), difference)
        check(actual.shape == expected.shape and bool(np.isfinite(actual).all()) and
              bool(np.isfinite(expected).all()) and bool(np.all(abs(actual-expected) <= 1e-10+1e-9*abs(expected))), name)

    frozen = json.loads((frontend/"SOURCE_FREEZE.json").read_text())
    for path, expected in frozen["files_sha256"].items():
        check(sha(frontend/path) == expected, "frozen source/input identity")
    publication = json.loads((frontend/"SOURCE_PUBLICATION.json").read_text())
    check(publication["source_freeze_sha256"] == sha(frontend/"SOURCE_FREEZE.json"), "published pre-fit source freeze identity")
    inputs = frontend/"reused_train001/inputs/train001"
    records = sorted(json.loads((inputs/"COHORT.json").read_text())["records"], key=lambda r: r["clip"])
    check(len(records) == 288 and all(r["split"] == "train" for r in records), "only historical TRAIN cohort")
    actors = np.array([str(r["actor"]) for r in records])
    y = np.array([CLASSES.index(r["emotion"]) for r in records], dtype=np.int64)
    with np.load(inputs/"features.npz", allow_pickle=False) as data:
        x = data["features"][:, :1536].astype(np.float64)
        check(data["clip"].tolist() == [r["clip"] for r in records], "exact feature-to-recording order")
    check(x.shape == (288, 1536) and len(set(actors)) == 24, "fixed ASR descriptor/actor count")
    result = json.loads((run/"RESULT.json").read_text())
    check(result["fits"] == 25 and result["fixed_ridge"] == 10., "predeclared 24 folds plus full fit, one lambda")
    check(result["source_freeze_sha256"] == sha(frontend/"SOURCE_FREEZE.json") and result["input_sha256"] == sha(inputs/"features.npz"), "actual result source/data binding")
    check(result["validation_or_test_loaded"] is False and result["emotion_readout_calibrated"] is False and result["strong_audio_reference_qualified"] is False, "development and uncalibrated scope retained")
    check(sha(run/"OOF_PREDICTIONS.npz") == result["oof_prediction_sha256"], "recorded OOF bytes")
    with np.load(run/"OOF_PREDICTIONS.npz", allow_pickle=False) as data:
        scores, probability = data["scores"].copy(), data["probability"].copy()
        check(np.array_equal(data["emotion_target"], y) and np.array_equal(data["actor"], actors), "correct emotion labels and actor identities")
    covered, held_actors = [], set()
    for fold in result["held_actor_folds"]:
        actor = fold["held_actor"]
        check(actor not in held_actors, "unique held actor")
        held_actors.add(actor)
        held, train = np.flatnonzero(actors == actor), np.flatnonzero(actors != actor)
        check(fold["held_indices"] == held.tolist() and fold["train_indices"] == train.tolist(), "actor-disjoint fold and exact complement")
        check(len(held) == 12 and np.array_equal(np.bincount(y[held], minlength=6), [2]*6), "balanced six-emotion held actor")
        check(fold["train_actors"] == sorted(set(actors[train])) and len(set(actors[train])) == 23, "exact 23 training actors")
        check(fold["train_x_sha256"] == digest(x[train]) and fold["held_x_sha256"] == digest(x[held]) and fold["train_y_sha256"] == digest(y[train]), "fold input hashes")
        path = run/("held_actor_"+actor+".npz")
        check(sha(path) == fold["weights_sha256"], "fold checkpoint byte identity")
        expected = spectral_fit(x[train], y[train])
        with np.load(path, allow_pickle=False) as p:
            check(np.array_equal(p["mean"], expected[0]) and np.array_equal(p["scale"], expected[1]), "normalization fitted solely on 23-actor train set")
            close("ridge_weight", p["weight"], expected[2])
            close("ridge_bias", p["bias"], expected[3])
            check(float(p["ridge"]) == 10., "fixed lambda in actual checkpoint")
        actual_scores, actual_p = predict(x[held], expected)
        close("oof_scores", scores[held], actual_scores)
        close("oof_probabilities", probability[held], actual_p)
        covered.extend(held.tolist())
    check(sorted(covered) == list(range(288)) and len(held_actors) == 24, "every recording held out exactly once")
    expected_full = spectral_fit(x, y)
    check(sha(run/"full_train.npz") == result["full_train_weights_sha256"], "separate full TRAIN fit bytes")
    with np.load(run/"full_train.npz", allow_pickle=False) as p:
        for name, value in zip(("mean", "scale", "weight", "bias"), expected_full):
            close("full_train_"+name, p[name], value)
    predictions = probability.argmax(axis=1)
    nll = float(-np.log(probability[np.arange(288), y]).mean())
    brier = float(((probability-np.eye(6)[y])**2).sum(axis=1).mean())
    confusion = np.zeros((6, 6), dtype=int)
    np.add.at(confusion, (y, predictions), 1)
    check(result["oof"]["correct"] == int((predictions == y).sum()) and result["confusion_counts"] == confusion.tolist(), "actual OOF counts and confusion")
    close("nll", result["oof"]["uncalibrated_nll"], nll)
    close("brier", result["oof"]["uncalibrated_brier"], brier)
    return {"schema": "hcsn-v13-independent-TRAIN-OOF-audit.v1", "checks": checks,
            "all_checks_passed": not failures, "failed_examples": failures, "largest_absolute_errors": maxima,
            "folds": len(held_actors), "recordings": len(records), "correct": int((predictions == y).sum()),
            "uncalibrated_nll": nll, "uncalibrated_brier": brier, "validation_or_test_loaded": False,
            "scope": "Spectral reconstruction of fixed-lambda TRAIN actor-OOF; no new cohort, calibrated reliability, original-v6 equivalence or strong-reference admission"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frontend", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    value = audit(args.frontend, args.run)
    with args.out.open("x") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")
    print(json.dumps(value))
    raise SystemExit(0 if value["all_checks_passed"] else 1)
