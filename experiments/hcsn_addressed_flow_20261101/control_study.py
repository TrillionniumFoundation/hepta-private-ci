"""Matched 2x2 experiment with an executed optional delayed READ.

One common value controller is fit on paired training continuations pooled
equally across both addressed cores and all seeds. Its inputs contain only the
first query prediction, observed clock and the quoted READ price. The lightweight
control is the best fixed price threshold on a separate development stream.
Both actions are executed for an offline counterfactual ledger; evaluation then
selects the frozen policy's actual action and charges the quoted READ cost.
CPU cost of constructing that ledger is recorded, never called deployment cost.
"""

import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np
import torch

from . import data


HERE = Path(__file__).resolve().parent
SEEDS = (17, 29, 43)
ARMS = ("addressed_diagonal", "addressed_flow")
POLICY_SEED = 77101
CONFIRM_SEED = 88101


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def features(logits, stop):
    query_mask = (stop["x"][..., 13] > 0) & stop["observed"]
    if not query_mask.any(-1).all():
        raise ValueError("An observed query token is required")
    query = query_mask.argmax(1)
    first = logits[np.arange(len(query)), query].astype(np.float64)
    probability = np.exp(first - np.logaddexp.reduce(first, axis=-1, keepdims=True))
    ordered = np.sort(probability, axis=-1)
    entropy = -(probability * np.log(np.maximum(probability, 1e-30))).sum(-1)
    prefix = np.arange(stop["x"].shape[1])[None] <= query[:, None]
    return np.stack((np.ones(len(query)), ordered[:, -1], ordered[:, -2],
        entropy / np.log(8), (stop["dt"] * prefix).sum(-1) / 16,
        ((~stop["observed"]) & prefix).sum(-1) / prefix.sum(-1)), axis=1)


def query_quality(logits, sample):
    valid = sample["y"] >= 0
    correct = logits.argmax(-1) == sample["y"]
    return (correct & valid).sum(-1) / valid.sum(-1), (correct | ~valid).all(-1)


def load_model(run, task, arm, seed):
    from .study import new_model
    manifest = json.loads((Path(run) / "ALL_CHECKPOINTS.json").read_text())
    row = next(r for r in manifest["fits"]
               if (r["task"], r["arm"], r["seed"]) == (task, arm, seed))
    checkpoint = Path(run) / row["checkpoint"]
    if row["status"] != "completed" or digest(checkpoint) != row["checkpoint_sha256"]:
        raise ValueError("Content checkpoint differs from the candidate manifest")
    saved = torch.load(checkpoint, map_location="cpu", weights_only=True)
    model = new_model(task, arm, seed)
    model.load_state_dict(saved, strict=True)
    model.eval()
    return model, digest(checkpoint)


def paired(model, task, split, count, seed):
    from .study import predict
    stop, read, price, removed = data.read_opportunity(task, count, seed, split)
    start_cpu, start_wall = time.process_time(), time.perf_counter()
    stop_logits = predict(model, stop)
    read_logits = predict(model, read)
    q0, a0 = query_quality(stop_logits, stop)
    q1, a1 = query_quality(read_logits, read)
    feature_start = time.process_time()
    feature_values = features(stop_logits, stop)
    feature_cpu = time.process_time() - feature_start
    return dict(features=feature_values, feature_cpu_seconds=np.asarray(feature_cpu), stop_quality=q0,
        read_quality=q1, stop_all4=a0, read_all4=a1, price=price,
        stop_logits=stop_logits[stop["y"] >= 0].reshape(count, 4, 8),
        read_logits=read_logits[read["y"] >= 0].reshape(count, 4, 8),
        labels=stop["y"][stop["y"] >= 0].reshape(count, 4), removed_step=removed,
        counterfactual_cpu_seconds=np.asarray(time.process_time() - start_cpu),
        counterfactual_wall_seconds=np.asarray(time.perf_counter() - start_wall))


def train(run, out, candidate_hash):
    from .study import source_hashes
    if digest(Path(run) / "ALL_CHECKPOINTS.json") != candidate_hash:
        raise ValueError("Content candidate freeze hash mismatch")
    protocol = json.loads((Path(run) / "PROTOCOL.json").read_text())
    if source_hashes() != protocol["source_hashes"]:
        raise ValueError("Scientific source changed after training freeze")
    start_cpu, start_wall = time.process_time(), time.perf_counter()
    out = Path(out)
    policies, checkpoints = {}, {}
    for task in data.CONTENT_TASKS:
        training, development = [], []
        for arm in ARMS:
            for seed in SEEDS:
                model, sha = load_model(run, task, arm, seed)
                key = f"{task}__{arm}__{seed}"
                checkpoints[key] = sha
                rows = []
                for split, count, dest in (("train", 384, training), ("dev", 512, development)):
                    record = paired(model, task, split, count, POLICY_SEED)
                    path = out / "calibration" / f"{key}__{split}.npz"
                    path.parent.mkdir(parents=True, exist_ok=True)
                    np.savez_compressed(path, **record)
                    dest.append(record)
                    rows.append(dict(split=split, sha256=digest(path), path=str(path.relative_to(out))))
                write(out / "calibration" / f"{key}.json", dict(checkpoint_sha256=sha, records=rows))
        x = np.concatenate([row["features"] for row in training])
        gain = np.concatenate([row["read_quality"] - row["stop_quality"] for row in training])
        penalty = np.eye(x.shape[1]) * .01
        penalty[0, 0] = 0
        coef = np.linalg.solve(x.T @ x + penalty, x.T @ gain)
        thresholds = [-1., .02, .08, .16, .24, .32, 1.]
        fixed = []
        for threshold in thresholds:
            scores = [np.mean(row["stop_quality"] + (row["price"] < threshold)
                * (row["read_quality"] - row["stop_quality"] - row["price"])) for row in development]
            fixed.append(float(np.mean(scores)))
        selected = int(np.argmax(fixed))
        policies[task] = dict(value_coefficients=coef.tolist(),
            lightweight_threshold=thresholds[selected], thresholds=thresholds,
            development_utilities=fixed, ridge_penalty=.01,
            common_controller="One coefficient vector shared across both cores and all seeds",
            training_rows=len(x), independent_training_episodes=384,
            calibration_note="Repeated trajectories across six frozen models are paired, not independent episodes")
    write(out / "POLICY_FREEZE.json", dict(schema="hcsn.addressed.control.v1",
        source_sha256=digest(__file__), data_sha256=digest(HERE / "data.py"),
        source_hashes=source_hashes(), candidate_freeze_sha256=candidate_hash,
        checkpoint_sha256=checkpoints, policies=policies, confirm_seed=CONFIRM_SEED,
        confirmation_episodes=1024, training_seed=POLICY_SEED,
        action="First query is observed without answering; READ spends 0.1 time for one missing final raw write, then answers a zero-time repeated query",
        objective="Mean of four query correctness indicators minus explicit read price",
        prices=[.02, .08, .16, .24, .32],
        features="First-query top two probabilities, entropy, elapsed time and missing fraction; no future query logits",
        fixed_selection="Best fixed price threshold by pooled development utility, deterministic first tie",
        value_selection="Predicted paired gain > current price; gain clipped to [-1,1]",
        limits=["Restricted one-opportunity READ/STOP controller, not general WAIT/RESET",
                "Physical wall/CPU and symbolic read price are separate ledgers; no joule conversion",
                "Missing-final-write intervention is structured and announced by missing observations"],
        cpu_seconds=time.process_time() - start_cpu, wall_seconds=time.perf_counter() - start_wall))


def evaluate(run, out, frozen_sha):
    from .study import source_hashes
    out = Path(out)
    path = out / "POLICY_FREEZE.json"
    if digest(path) != frozen_sha:
        raise ValueError("Policy freeze hash mismatch")
    freeze = json.loads(path.read_text())
    if freeze["source_sha256"] != digest(__file__) or freeze["data_sha256"] != digest(HERE / "data.py"):
        raise ValueError("Controller or environment changed after freeze")
    if (freeze["source_hashes"] != source_hashes()
            or freeze["candidate_freeze_sha256"] != digest(Path(run) / "ALL_CHECKPOINTS.json")):
        raise ValueError("Scientific source or candidate manifest changed after control freeze")
    start_cpu, start_wall = time.process_time(), time.perf_counter()
    records = []
    for task in data.CONTENT_TASKS:
        policy = freeze["policies"][task]
        for arm in ARMS:
            for seed in SEEDS:
                key = f"{task}__{arm}__{seed}"
                model, sha = load_model(run, task, arm, seed)
                if sha != freeze["checkpoint_sha256"][key]:
                    raise ValueError("Content model changed after control freeze")
                row = paired(model, task, "confirm", freeze["confirmation_episodes"], CONFIRM_SEED)
                controller_start = time.process_time()
                gain = np.clip(row["features"] @ np.asarray(policy["value_coefficients"]), -1., 1.)
                value_choice = gain > row["price"]
                value_cpu = time.process_time() - controller_start
                controller_start = time.process_time()
                fixed_choice = row["price"] < policy["lightweight_threshold"]
                lightweight_cpu = time.process_time() - controller_start
                choices = dict(lightweight=fixed_choice, value=value_choice,
                               always_read=np.ones(len(gain), bool), never_read=np.zeros(len(gain), bool))
                result = dict(task=task, core=arm, seed=seed, checkpoint_sha256=sha,
                    policy_freeze_sha256=frozen_sha, value_controller_cpu_seconds=value_cpu,
                    lightweight_controller_cpu_seconds=lightweight_cpu,
                    feature_extraction_cpu_seconds=float(row["feature_cpu_seconds"]),
                    measured_gain_mse=float(np.mean((gain - (row["read_quality"] - row["stop_quality"])) ** 2)),
                    policies={})
                for name, choice in choices.items():
                    quality = np.where(choice, row["read_quality"], row["stop_quality"])
                    utility = quality - choice * row["price"]
                    row[name + "_action_read"] = choice
                    row[name + "_utility"] = utility
                    result["policies"][name] = dict(accuracy=float(quality.mean()),
                        utility=float(utility.mean()), read_rate=float(choice.mean()),
                        all4=float(np.where(choice, row["read_all4"], row["stop_all4"]).mean()))
                row["predicted_gain"] = gain
                archive = out / "confirmation" / f"{key}.npz"
                archive.parent.mkdir(parents=True, exist_ok=True)
                np.savez_compressed(archive, **row)
                result["raw_sha256"] = digest(archive)
                write(archive.with_suffix(".json"), result)
                records.append(result)
    write(out / "SUMMARY.json", dict(records=records, policy_freeze_sha256=frozen_sha,
        cpu_seconds=time.process_time() - start_cpu, wall_seconds=time.perf_counter() - start_wall,
        scope="Offline execution of both actual continuations, plus frozen policy selection; no deployment energy claim"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--phase", choices=("train", "evaluate"), required=True)
    parser.add_argument("--freeze-sha256")
    parser.add_argument("--candidate-freeze-sha256")
    args = parser.parse_args()
    torch.set_num_threads(1)
    if args.phase == "train":
        if not args.candidate_freeze_sha256:
            parser.error("Calibration requires frozen content candidate manifest")
        train(args.run, args.out, args.candidate_freeze_sha256)
    else:
        if not args.freeze_sha256:
            parser.error("Evaluation requires published policy freeze SHA256")
        evaluate(args.run, args.out, args.freeze_sha256)


if __name__ == "__main__":
    main()
