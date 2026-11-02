"""Independent feature/statistics/value-calibration audit, TRAIN and VAL only.

The unrecorded first A1 class probability is replayed with the approved joint
core implementation. All history features, reader affine equations, normalizers,
minibatches and Laplace calibrators are reconstructed without the value fitter.
No TEST packet or label is loaded.
"""

import argparse
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.special import expit
import torch
from torch import nn

from experiments.hcsn_v13_followup_20261102.joint_core.model import Model


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def state_sha(state):
    result = hashlib.sha256()
    for name, value in sorted(state.items()):
        result.update(name.encode()+value.detach().numpy().tobytes())
    return result.hexdigest()


def path_key(path):
    return tuple((str(modality), int(endpoint)) for modality, endpoint in path)


def history_rows(packet, index, path, center, scale):
    valid = packet["valid"][index]
    values = np.asarray(packet["x"][index, valid], np.float64)
    times, observed = packet["relative_times"][index, valid], packet["observed"][index, valid]
    kinds = (values[:, 33] > values[:, 32]).astype(int)
    levels, previous, rows = [0, 0], 0, []
    for modality, endpoint in path:
        kind = int(modality == "video")
        if modality not in ("audio", "video") or endpoint != levels[kind]+1 or endpoint > 3:
            raise ValueError("Illegal accepted source path")
        levels[kind] = endpoint
        caches = []
        for k in (0, 1):
            mask = observed & (kinds == k) & (values[:, 34+k] > 0) & (times <= levels[k])
            caches.append(values[mask, :16].mean(0) if mask.any() and levels[k] else np.zeros(16))
        mask = observed & (kinds == kind) & (values[:, 34+kind] > 0) & (times <= endpoint)
        mask &= times >= 0 if endpoint == 1 else times > endpoint-1
        fresh = values[mask, :16].mean(0) if mask.any() else np.zeros(16)
        current = max(levels)
        row = np.r_[*caches, levels[0]/3, levels[1]/3, current-previous, fresh,
                    float(kind == 0), float(kind == 1), endpoint/3, float(mask.any())]
        rows.append((row-center)/scale)
        previous = current
    return rows


def feature(rows, probability, future):
    history = np.zeros((6, 55)); history[:len(rows)] = rows
    p = np.zeros(6); p[:len(probability)] = probability
    actions = np.zeros((2, 6))
    for i, (modality, endpoint) in enumerate(future):
        actions[i, (3 if modality == "video" else 0)+endpoint-1] = 1
    return np.r_[history.ravel(), np.arange(6) < len(rows), p, actions.ravel()]


def calibrator(prediction, correct):
    prediction, correct = np.asarray(prediction), np.asarray(correct)
    bins = np.minimum((prediction*5).astype(int), 4)
    count = [int((bins == i).sum()) for i in range(5)]
    global_rate = (correct.sum()+1)/(len(correct)+2)
    rates = [float((correct[bins == i].sum()+1)/(count[i]+2)) if count[i] else float(global_rate) for i in range(5)]
    return count, rates


def audit(root, run):
    torch.set_num_threads(1)
    checks, failed, maximum, results = 0, [], {}, []

    def check(ok, name):
        nonlocal checks
        checks += 1
        if not ok and len(failed) < 30:
            failed.append(name)

    def close(name, a, b):
        a, b = np.asarray(a), np.asarray(b)
        error = float(np.max(abs(a-b))) if a.size else 0.
        maximum[name] = max(maximum.get(name, 0.), error)
        check(a.shape == b.shape and bool(np.isfinite(a).all()) and bool(np.isfinite(b).all())
              and bool(np.all(abs(a-b) <= 1e-12+1e-10*abs(b))), name)

    plan = json.loads((run/"PLAN.json").read_text())
    frozen = json.loads((run/"CANDIDATES.json").read_text())
    for path, expected in plan["source_sha256"].items():
        check(sha(root/path) == expected, "frozen new-head control source")
    packets = {}
    for name, record in plan["packets"].items():
        check(sha(run/name) == record["sha256"], "frozen training/calibration packet")
        with np.load(run/name, allow_pickle=False) as data:
            packets[name[:-4]] = {k: data[k].copy() for k in data.files}
    source = root/plan["models_directory"]
    check(sha(source/"CANDIDATES.json") == plan["candidates_sha256"], "exact frozen new content roster")
    check(len(frozen["models"]) == 36, "all thirty-six value candidates")
    initial_groups, batches = {}, {}
    for item in frozen["models"]:
        directory = run/item["directory"]
        for name, expected in item["files"].items():
            check(sha(directory/name) == expected, "sealed actual value candidate artifact")
        meta = json.loads((directory/"CANDIDATE.json").read_text())
        task, family, seed = meta["task"], meta["family"], meta["seed"]
        core = root/meta["model_directory"]
        check(sha(core/"weights.pt") == meta["model_weights_sha256"] and sha(core/"NORMALIZATION.npz") == meta["model_normalization_sha256"], "new content head and normalizer binding")
        check(meta["head_id"] == f"joint-v13-{task}-{family}-{meta['model_weights_sha256'][:20]}", "new head identity, not legacy head")
        check(meta["plan_sha256"] == sha(run/"PLAN.json") and meta["test_opened"] is False, "untouched TEST candidate plan")
        classes = plan["protocol"]["tasks"][task]
        network = Model(family, classes)
        network.load_state_dict(torch.load(core/"weights.pt", map_location="cpu", weights_only=True)); network.eval()
        with np.load(core/"NORMALIZATION.npz", allow_pickle=False) as data:
            center, scale = data["center"].copy(), data["scale"].copy()
        by_split, node_probabilities, node_rows = {}, {}, {}
        prior = np.bincount(packets[task+"-train"]["labels"], minlength=classes)+1.
        prior /= prior.sum()
        close("train_class_prior", prior, meta["train_prior"])
        with gzip.open(directory/"FUTURE_TARGETS.jsonl.gz", "rt") as stream:
            records = list(map(json.loads, stream))
        for record in records:
            split, obj = record["split"], record["object"]
            check(split in ("train", "val"), "no TEST target source")
            current, future = path_key(record["current"]), path_key(record["future"])
            check(current and current[0] == ("audio", 1) and future[:len(current)] == current and 1 <= len(future)-len(current) <= 2, "exact one/two accepted-READ descendant target")
            check(record["label_for_training_only"] == int(packets[task+"-"+split]["labels"][obj]), "actual class target alignment")
            p = record["future_probabilities"]
            check(len(p) == classes and abs(sum(p)-1) <= 1e-12 and min(p) >= 0, "future actual class probability distribution")
            check(record["correct"] == int(np.argmax(p) == record["label_for_training_only"]), "future actual new-head correctness target")
            key = split, obj, future
            if key in node_probabilities:
                check(node_probabilities[key] == p, "reused node probabilities exactly consistent")
            node_probabilities[key] = p
        for split in ("train", "val"):
            packet = packets[task+"-"+split]
            for obj in range(len(packet["labels"])):
                node_probabilities[split, obj, ()] = prior.tolist()
                first = (("audio", 1),)
                first_rows = history_rows(packet, obj, first, center, scale)
                row = torch.as_tensor(np.asarray(first_rows[0])[None], dtype=torch.float64)
                with torch.no_grad():
                    state, _ = network.step(row, network.initial(row))
                    node_probabilities[split, obj, first] = torch.softmax(network.classify([row], state), -1)[0].tolist()
        for record in records:
            split, obj = record["split"], record["object"]
            current, future = path_key(record["current"]), path_key(record["future"])
            key = split, obj, current
            if key not in node_rows:
                node_rows[key] = history_rows(packets[task+"-"+split], obj, current, center, scale)
            values = feature(node_rows[key], node_probabilities[key], future[len(current):])
            check(hashlib.sha256(values.tobytes()).hexdigest() == record["feature_sha256"], "independently reconstructed causal value feature bytes")
            by_split.setdefault(split, []).append((values, record["correct"]))
        arrays = {split: (np.asarray([r[0] for r in records_]), np.asarray([r[1] for r in records_])) for split, records_ in by_split.items()}
        tx, ty = arrays["train"]; vx, vy = arrays["val"]
        check(len(tx) == meta["training_rows"] and len(vx) == meta["calibration_rows"], "all TRAIN/VAL target row counts")
        close("TRAIN_only_value_mean", tx.mean(0), meta["value_mean"])
        close("TRAIN_only_value_scale", np.maximum(tx.std(0), 1e-5), meta["value_scale"])
        parameters = torch.load(directory/"VALUE.pt", map_location="cpu", weights_only=True)
        z = (vx-np.asarray(meta["value_mean"]))/np.asarray(meta["value_scale"])
        hidden = np.tanh(z @ parameters["layers.0.weight"].numpy().T+parameters["layers.0.bias"].numpy())
        predicted = expit(hidden @ parameters["layers.2.weight"].numpy().T+parameters["layers.2.bias"].numpy()).ravel()
        counts, rates = calibrator(predicted, vy)
        check(counts == meta["future_calibration"]["counts"], "independent future five-bin calibration counts")
        close("future_Laplace_rates", rates, meta["future_calibration"]["rates"])
        probabilities, correct = [], []
        for (split, obj, path), p in node_probabilities.items():
            if split == "val":
                probabilities.append(max(p)); correct.append(int(np.argmax(p) == packets[task+"-val"]["labels"][obj]))
        counts, rates = calibrator(probabilities, correct)
        check(counts == meta["stop_calibration"]["counts"], "independent STOP node/empty-prior five-bin counts")
        close("STOP_Laplace_rates", rates, meta["stop_calibration"]["rates"])
        torch.manual_seed(seed+500000)
        initialized = nn.Sequential(nn.Linear(354, 32), nn.Tanh(), nn.Linear(32, 1)).double()
        initial = {"layers."+k: v for k, v in initialized.state_dict().items()}
        check(state_sha(initial) == meta["initial_reader_state_sha256"], "independent value-reader initialization")
        initial_groups.setdefault((task, seed), set()).add(meta["initial_reader_state_sha256"])
        generator, stream = torch.Generator().manual_seed(seed+600000), hashlib.sha256()
        for _ in range(128):
            stream.update(torch.randint(len(tx), (64,), generator=generator).numpy().tobytes())
        check(stream.hexdigest() == meta["minibatch_stream_sha256"], "independent value-reader batch stream")
        batches.setdefault((task, seed), set()).add(meta["minibatch_stream_sha256"])
        check(len(meta["losses"]) == 128 and np.isfinite(meta["losses"]).all(), "fixed finite 128 value-fit updates")
        results.append({"task": task, "family": family, "seed": seed, "train_rows": len(tx), "calibration_rows": len(vx)})
    check(all(len(v) == 1 for v in initial_groups.values()) and all(len(v) == 1 for v in batches.values()), "all content families share value-reader initialization and batches")
    return {"schema": "hcsn-v13-independent-value-feature-calibration-audit.v1", "checks": checks,
            "all_checks_passed": not failed, "failed_examples": failed, "largest_absolute_errors": maximum,
            "candidates": len(results), "rows": results, "TEST_loaded": False,
            "scope": "Independent feature/statistics/reader-affine/calibration reconstruction; A1 class probabilities use approved joint-core actual forward, not an independent HX numerical implementation"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    value = audit(args.root, args.run)
    with args.out.open("x") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")
    print(json.dumps({k: v for k, v in value.items() if k != "rows"}))
    raise SystemExit(0 if value["all_checks_passed"] else 1)
