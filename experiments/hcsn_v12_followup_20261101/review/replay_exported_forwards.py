"""Preselected V12 exports: actual NumPy forwards vs independent Torch formulas.

Loads all exact source/export tensors and replays index-0 value/expm episodes.
The Torch reference uses functional affine/gate equations; it does not import
the producer's Torch Model or exporter. Finite-path law audit is separate.
"""

import argparse
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np
import torch
from torch.nn import functional as functional

from experiments.hcsn_v12_followup_20261101.model_runtime import numpy_runtime as runtime


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(source, bundle, validation, output):
    output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1)
    runtime.write(output / "PLAN.json", {"selection": "index=0, policy=value, implementation=expm for every task x seed x family",
        "expected_cases": 16, "rtol": 1e-10, "atol": 1e-12, "torch": torch.__version__,
        "source_sha256": sha(__file__), "bundle_manifest_sha256": sha(bundle / "MANIFEST.json"),
        "scope": "Independent functional Torch gate/affine equations vs real NumPy inference, not retraining or Rust production"})
    manifest = runtime.verify(bundle)
    checks, failures, maximum, cases = 0, [], {}, []

    def check(ok, label):
        nonlocal checks
        checks += 1
        if not ok and len(failures) < 30:
            failures.append(label)

    def close(label, a, b):
        a, b = np.asarray(a), np.asarray(b)
        check(a.shape == b.shape and np.isfinite(a).all() and np.isfinite(b).all(), label + " shape/finite")
        difference = float(np.max(abs(a-b))) if a.size else 0.
        maximum[label] = max(maximum.get(label, 0.), difference)
        check(bool(np.all(abs(a-b) <= 1e-12 + 1e-10*abs(b))), label + " fixed tolerance")

    by_model = {}
    for item in manifest["models"]:
        path = source / item["source_pt_path"]
        check(sha(path) == item["source_pt_sha256"], "exact original source weights")
        original = torch.load(path, map_location="cpu", weights_only=True)
        with np.load(bundle / item["numpy_path"], allow_pickle=False) as arrays:
            exported = {key: arrays[key].copy() for key in arrays.files}
        check(set(original) == set(exported), "all parameter names exported")
        for name in original:
            check(np.array_equal(original[name].numpy(), exported[name]), "lossless exported tensor: " + name)
        by_model[item["task"], item["seed"], item["family"]] = (item, original)
    with gzip.open(validation / "TRACES.jsonl.gz", "rt") as stream:
        selected = [row for row in map(json.loads, stream) if row["index"] == 0 and row["policy"] == "value" and row["implementation"] == "expm"]
    check(len(selected) == 16, "all preselected cases")
    for record in selected:
        identity = record["model"]
        item, weights = by_model[identity["task"], identity["seed"], identity["family"]]
        model = runtime.Model(item["family"], bundle / item["numpy_path"])
        hp, hn = torch.zeros((1, 64), dtype=torch.float64), np.zeros((1, 64))
        history, logits_by_fingerprint = [], {}

        def linear(x, name):
            return functional.linear(x, weights[name + ".weight"], weights[name + ".bias"])

        for update in record["numpy_updates"]:
            row = torch.tensor(update["row"], dtype=torch.float64)[None]
            if item["family"] == "gru":
                xi = functional.linear(row, weights["update.weight_ih"], weights["update.bias_ih"])
                hh = functional.linear(hp, weights["update.weight_hh"], weights["update.bias_hh"])
                ir, iz, inn = xi.chunk(3, 1); hr, hz, hnn = hh.chunk(3, 1)
                reset, retain = torch.sigmoid(ir+hr), torch.sigmoid(iz+hz)
                proposal = torch.tanh(inn + reset*hnn)
                hp = (1-retain)*proposal + retain*hp
            elif item["family"] == "ssm":
                decay = torch.exp(-functional.softplus(linear(row, "rate"))*row[:, 40:41])
                gain = torch.sigmoid(linear(row, "gain"))
                hp = (1-gain)*decay*hp + gain*torch.tanh(linear(row, "drive"))
            hn = model.update_state(row.numpy(), hn)
            close("independent_hidden", hn, hp.numpy())
            close("saved_numpy_hidden", hn, update["hidden"])
            history.append(update["row"])
            slots = np.zeros((6, 58)); slots[:len(history)] = history
            full = np.r_[slots.ravel(), np.arange(6) < len(history)][None]
            belief = np.zeros((1, 256))
            if item["family"] == "filter":
                belief[0, :len(update["path_probability"]) ] = update["path_probability"]
            extra = torch.tensor(belief) if item["family"] == "filter" else hp if item["family"] in ("gru", "ssm") else None
            features = torch.tensor(full) if extra is None else torch.cat((torch.tensor(full), extra), 1)
            logits = linear(torch.tanh(linear(features, "reader.0")), "reader.2")
            actual = model.predict(full, hn, belief)
            close("independent_logits", actual, logits.numpy())
            probabilities = torch.sigmoid(logits).numpy()
            close("independent_probabilities", runtime.expit(actual), probabilities)
            logits_by_fingerprint[update["content_fingerprint"]] = (probabilities[0], update["row"])
        predicted = 0
        for decision in record["numpy"]["decisions"]:
            p, current = logits_by_fingerprint[decision["content_fingerprint"]]
            scored = []
            for candidate in decision["plans"]:
                levels = {"audio": round(current[38]*3), "video": round(current[39]*3)}
                for step in candidate["plan"].split("/"):
                    _, modality, endpoint = step.split(":")
                    levels[modality] = int(endpoint)
                value = float(p[runtime.LEVELS.index((levels["audio"], levels["video"]))])
                close("actual_candidate_prediction", value, candidate["correctness"])
                score = value - .02*candidate["expected_requested_reads"] - .005*candidate["expected_seconds"] - candidate["deadline_miss_probability"]
                scored.append((score, candidate["plan"]))
                predicted += 1
            best = max(scored, default=None)
            action = best[1] if best is not None and best[0] > decision["stop_score"] else None
            check(action == decision["selected"], "independent functional replay selects same actual action")
        cases.append({"task": item["task"], "seed": item["seed"], "family": item["family"],
                      "updates": len(history), "candidate_forecasts": predicted})
    result = {"schema": "hcsn-v12-independent-functional-forward-replay.v1", "checks": checks,
        "all_checks_passed": not failures, "failed_examples": failures, "largest_absolute_errors": maximum,
        "cases": cases, "rtol": 1e-10, "atol": 1e-12,
        "scope": "Lossless all-16 export tensors, real NumPy vs independent Torch functional neural equations on preselected causal traces"}
    runtime.write(output / "RESULT.json", result)
    print(json.dumps(result))
    return result["all_checks_passed"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--validation", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(0 if run(args.source, args.bundle, args.validation, args.out) else 1)
