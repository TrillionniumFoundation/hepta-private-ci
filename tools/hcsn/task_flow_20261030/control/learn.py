"""Matched-capacity Q-value and ordinary action-boundary readouts."""
import json
import time
import numpy as np
from common import HERE, ACTIONS, protocol, save, sha, verify
from oracle import Bellman, feasible, features


def calibrate(seed, adapter):
    start, cpu = time.perf_counter(), time.process_time()
    labels = json.loads((HERE / "data" / f"calibration_seed{seed}" / "labels_train_only.json").read_text())
    counts = np.zeros((2, 2), np.int64)
    rows = []
    for item in labels:
        observed = adapter.read(HERE / item["path"])
        counts[item["symbol"], observed["observation"]] += 1
        rows.append(dict(**item, **observed))
    confusion = (counts+.5)/(counts.sum(axis=1, keepdims=True)+1.)
    result = dict(seed=seed, counts=counts.tolist(), confusion=confusion.tolist(), packets=rows,
                  wall_seconds=time.perf_counter()-start, cpu_seconds=time.process_time()-cpu,
                  policy_access="Only this TRAIN-fitted confusion matrix enters controllers")
    save(HERE / "fits" / f"calibration_seed{seed}.json", result)
    return confusion, result


def state_dataset(seed, split, records, confusion):
    p = protocol()
    rng = np.random.default_rng(p["data_seed_base"]+seed*1000000+(700001 if split == "train" else 800001))
    xs, targets, first, labels, masks, provenance = [], [], [], [], [], []
    for row in records:
        if row["seed"] != seed or row["split"] != split:
            continue
        meta = json.loads((HERE / row["folder"] / "public.json").read_text())
        for multiplier in p["cost_multipliers"]:
            full = Bellman(meta, confusion, multiplier)
            stopped = Bellman(meta, confusion, multiplier, future=False)
            for _ in range(p["states_per_training_metadata"]):
                job = int(rng.integers(2))
                tick = int(rng.integers(meta["deadline"]))
                budget = int(rng.integers(meta["budget"]+1))
                posterior = float(1/(1+np.exp(-rng.uniform(-4., 4.))))
                valid = feasible(meta, job, tick, budget)
                values = np.asarray(full.q(job, tick, budget, posterior))
                xs.append(features(meta, job, tick, budget, posterior, confusion, multiplier))
                targets.append(values)
                first.append(stopped.q(job, tick, budget, posterior))
                labels.append(int(np.argmax(np.where(valid, values, -np.inf))))
                masks.append(valid)
                provenance.append([row["id"], job, tick, budget, posterior, multiplier])
    return dict(x=np.asarray(xs), q=np.asarray(targets), first=np.asarray(first),
                action=np.asarray(labels), valid=np.asarray(masks), provenance=provenance)


def fit_seed(seed, records, confusion):
    verify()
    p = protocol()
    start, cpu = time.perf_counter(), time.process_time()
    train = state_dataset(seed, "train", records, confusion)
    val = state_dataset(seed, "validation", records, confusion)
    label_wall, label_cpu = time.perf_counter()-start, time.process_time()-cpu
    folder = HERE / "fits" / f"seed{seed}"
    folder.mkdir(parents=True, exist_ok=True)
    for split, data in (("train", train), ("validation", val)):
        np.savez_compressed(folder / f"{split}_states.npz", **{k: v for k, v in data.items() if k != "provenance"})
        save(folder / f"{split}_provenance.json", data["provenance"])
    start, cpu = time.perf_counter(), time.process_time()
    mean, scale = train["x"].mean(axis=0), train["x"].std(axis=0)
    mean[0], scale[0] = 0., 1.
    scale[scale < 1e-8] = 1.
    x, vx = (train["x"]-mean)/scale, (val["x"]-mean)/scale
    model, candidates, fit_by_policy = {}, [], {}
    for name, key in (("learned_value", "q"), ("ordinary_boundary", "action"), ("first_event_value", "first")):
        policy_start, policy_cpu = time.perf_counter(), time.process_time()
        y = np.eye(4)[train[key]] if key == "action" else train[key]
        vy = np.eye(4)[val[key]] if key == "action" else val[key]
        choices = []
        for ridge in p["ridge_candidates"]:
            regularizer = ridge*np.eye(x.shape[1])
            regularizer[0, 0] = 0.
            weights = np.linalg.solve(x.T @ x + regularizer, x.T @ y)
            predicted = vx @ weights
            discrepancy = float(np.mean(np.argmax(np.where(val["valid"], predicted, -np.inf), axis=1) != val["action"]))
            mse = float(np.mean((predicted-vy)**2))
            criterion = discrepancy if key == "action" else mse
            choices.append((criterion, ridge, weights))
            path = folder / f"{name}_ridge{ridge}.npz"
            np.savez_compressed(path, weights=weights, mean=mean, scale=scale)
            candidates.append(dict(policy=name, ridge=ridge, validation_mse=mse,
                                   validation_action_disagreement=discrepancy,
                                   checkpoint=str(path.relative_to(HERE)), checkpoint_sha256=sha(path)))
        selected = min(choices, key=lambda item: (item[0], item[1]))
        model[name] = dict(weights=selected[2], mean=mean, scale=scale, ridge=selected[1])
        fit_by_policy[name] = dict(wall_seconds=time.perf_counter()-policy_start,
                                   cpu_seconds=time.process_time()-policy_cpu)
    result = dict(seed=seed, candidates=candidates, selected={name: value["ridge"] for name, value in model.items()},
                  parameter_count_per_readout=int(x.shape[1]*4), feature_count=int(x.shape[1]),
                  shared_preprocessing_scalars=int(2*x.shape[1]), train_states=len(x), validation_states=len(vx),
                  targets_use_realized_future=False, oracle_label_wall_seconds=label_wall,
                  oracle_label_cpu_seconds=label_cpu, fit_wall_seconds=time.perf_counter()-start,
                  fit_cpu_seconds=time.process_time()-cpu,
                  fit_by_policy=fit_by_policy,
                  train_states_sha256=sha(folder / "train_states.npz"),
                  validation_states_sha256=sha(folder / "validation_states.npz"),
                  learned_content_parameters=0, frozen_content=True)
    save(folder / "selection.json", result)
    return model, result


def predict(model, meta, job, tick, budget, posterior, confusion, multiplier):
    x = features(meta, job, tick, budget, posterior, confusion, multiplier)
    scores = ((x-model["mean"])/model["scale"]) @ model["weights"]
    return ACTIONS[int(np.argmax(np.where(feasible(meta, job, tick, budget), scores, -np.inf)))]
