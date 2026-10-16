"""Synthetic *observed* paired-outcome Critic; never production NDU or FBSDE.

One public state gives independent Bernoulli probabilities and inspection costs.
The fit uses only training-world sampled payoffs for identical task/action arms.
No future outcomes or evaluation seeds enter the candidate prediction process.
The cheap exact one-step Bellman policy is intentionally a strong control.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from fractions import Fraction
from pathlib import Path
from random import Random
from time import process_time_ns

import numpy as np

ACTIONS = ("stop", "observe_0", "observe_1")
ARMS = ("no_search", "fixed_depth_1", "exact_tree", "learned_critic")
PROFILE = "hepta.ndu-system2.paired-continuation.v1"
FEATURE_DIM = 15


def canon(o):
    return json.dumps(o, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(o):
    return hashlib.sha256(canon(o).encode("utf-8")).hexdigest()


def strict_fraction(v):
    if type(v) is not str or len(v) > 64:
        raise ValueError("canonical rational string required")
    try:
        q = Fraction(v)
    except (ValueError, ZeroDivisionError):
        raise ValueError("invalid rational") from None
    if str(q) != v or abs(q.numerator) > 100000 or q.denominator > 100000:
        raise ValueError("noncanonical/out-of-range rational")
    return q


def public_case(row):
    required = {"case_id", "group_id", "observed_at", "split", "prior", "cost"}
    if type(row) is not dict or set(row) != required:
        raise ValueError("exact public schema required; future outcome leakage rejected")
    if type(row["case_id"]) is not str or not row["case_id"] or len(row["case_id"]) > 96:
        raise ValueError("invalid case id")
    if row["split"] not in ("train", "future_1", "future_2"):
        raise ValueError("unknown split")
    if type(row["observed_at"]) is not int or row["observed_at"] <= 0:
        raise ValueError("positive exact observation time required")
    if type(row["prior"]) is not list or type(row["cost"]) is not list or len(row["prior"]) != 2 or len(row["cost"]) != 2:
        raise ValueError("two-bit prior and inspection costs required")
    p = tuple(map(strict_fraction, row["prior"]))
    c = tuple(map(strict_fraction, row["cost"]))
    if any(not 0 < v < 1 for v in p) or any(not 0 <= v <= 1 for v in c):
        raise ValueError("invalid probability / inspection cost")
    if row["group_id"] != digest([row["prior"], row["cost"]]):
        raise ValueError("source/group binding mismatch")
    return p, c


def public_panel(rows, split):
    if type(rows) is not list or not 1 <= len(rows) <= 8192:
        raise ValueError("bounded rows required")
    cases, groups, times = set(), set(), []
    for row in rows:
        p, c = public_case(row)
        if row["split"] != split:
            raise ValueError("mixed cohorts")
        if row["case_id"] in cases or row["group_id"] in groups:
            raise ValueError("reused case/group")
        cases.add(row["case_id"])
        groups.add(row["group_id"])
        times.append(row["observed_at"])
    lo, hi = {"train": (1, 9999), "future_1": (10000, 19999), "future_2": (20000, 29999)}[split]
    if min(times) < lo or max(times) > hi or len(times) != len(set(times)):
        raise ValueError("timestamp order/leakage")
    return groups


def generate_public(split, *, seed, count):
    if split not in ("train", "future_1", "future_2") or type(seed) is not int or not 0 <= seed < 2**32:
        raise ValueError("bounded deterministic cohort")
    if type(count) is not int or not 1 <= count <= 8192:
        raise ValueError("bounded deterministic count")
    d, cd, epoch = {"train": (101, 151, 1), "future_1": (109, 167, 10000), "future_2": (127, 181, 20000)}[split]
    rng = Random(seed)
    rows = []
    seen = set()
    while len(rows) < count:
        p = [str(Fraction(rng.randrange(8, d-7), d)) for _ in range(2)]
        costs = [str(Fraction(rng.randrange(0, cd//4), cd)) for _ in range(2)]
        gid = digest([p, costs])
        if gid in seen:
            continue
        seen.add(gid)
        j = len(rows)
        rows.append({"case_id": f"{split}-{j}", "group_id": gid,
                     "observed_at": epoch+j, "split": split, "prior": p, "cost": costs})
    public_panel(rows, split)
    return rows


def world_for_training(row, *, rng):
    p, _ = public_case(row)
    return (int(rng.random() < float(p[0])), int(rng.random() < float(p[1])))


def predicted_bit(p, observed_index=None, observed_value=None):
    pr = p[0]*p[1]
    if observed_index is not None:
        if observed_value == 0:
            pr = Fraction(0)
        else:
            pr = p[1-observed_index]
    return int(pr >= Fraction(1, 2))


def realized(row, action, world):
    if action not in ACTIONS or type(world) is not tuple or len(world) != 2 or any(type(v) is not int or v not in (0, 1) for v in world):
        raise ValueError("invalid action or simulator hidden world")
    p, costs = public_case(row)
    if action == "stop":
        answer, acquired = predicted_bit(p), Fraction(0)
    else:
        i = int(action[-1])
        answer, acquired = predicted_bit(p, i, world[i]), costs[i]
    return Fraction(1 if answer == int(world[0] and world[1]) else -1) - acquired


def expected_values(row):
    p, costs = public_case(row)
    stop = abs(2*p[0]*p[1] - 1)
    observe_0 = (1-p[0]) + p[0]*abs(2*p[1]-1) - costs[0]
    observe_1 = (1-p[1]) + p[1]*abs(2*p[0]-1) - costs[1]
    return (stop, observe_0, observe_1)


def choose_exact(row):
    # Ties prefer the cheaper stop action; no action exploits hidden future truth.
    values = expected_values(row)
    return ACTIONS[max(range(3), key=lambda i: (values[i], -i))]


def features(row):
    p, cost = public_case(row)
    a, b, c, d = map(float, (p[0], p[1], cost[0], cost[1]))
    values = [1., a, b, c, d, a*b, a*a, b*b, a*c, a*d, b*c, b*d, c*c, d*d, a*b*(a+b)]
    if len(values) != FEATURE_DIM or not all(math.isfinite(v) for v in values):
        raise ValueError("invalid bounded public feature")
    return values


def fit(train_rows, train_worlds, *, ridge=10., train_seed=7331):
    """Actual paired-return ridge regression; no oracle Q-values as labels."""
    groups = public_panel(train_rows, "train")
    if type(train_worlds) is not list or len(train_worlds) != len(train_rows):
        raise ValueError("train worlds must match immutable rows")
    if type(ridge) not in (int, float) or not 0 < ridge <= 1000:
        raise ValueError("frozen positive ridge coefficient")
    # Deterministic immutable public-feature matrix; actual payoffs are observed on TRAIN.
    start = process_time_ns()
    x = np.asarray([features(r) for r in train_rows], dtype=np.float64)
    y = np.asarray([[float(realized(row, act, w)) for act in ACTIONS]
                    for row, w in zip(train_rows, train_worlds)], dtype=np.float64)
    if x.shape != (len(train_rows), FEATURE_DIM) or y.shape != (len(train_rows), len(ACTIONS)):
        raise ValueError("incorrect physical paired training arrays")
    gram = x.T@x + float(ridge)*np.eye(FEATURE_DIM, dtype=np.float64)
    w = np.linalg.solve(gram, x.T@y)
    if w.shape != (FEATURE_DIM, 3) or not np.isfinite(w).all():
        raise ValueError("ill-conditioned or nonfinite critic")
    return {"weights": w, "training_cpu_ns": process_time_ns()-start,
            "train_groups": sorted(groups), "train_rows_sha256": digest(train_rows),
            "train_worlds_sha256": digest(train_worlds), "head_parameters": int(w.size),
            "training_pairs_observed": int(y.size), "source_model": "synthetic-bernoulli"}


def action_report(future_rows, critic):
    model = critic["weights"]
    if type(model) is not np.ndarray or model.shape != (FEATURE_DIM, 3) or not np.isfinite(model).all():
        raise ValueError("frozen train-only critic required")
    predictions = {}
    metering = {}
    for arm in ARMS:
        a = process_time_ns()
        actions = {}
        visits = 0
        for row in future_rows:
            if arm == "no_search":
                choice = "stop"
                visits += 1
            elif arm == "fixed_depth_1":
                choice = "observe_0"
                visits += 1
            elif arm == "exact_tree":
                choice = choose_exact(row)
                visits += 3
            else:
                values = np.asarray(features(row), dtype=np.float64) @ model
                choice = ACTIONS[max(range(3), key=lambda i: (float(values[i]), -i))]
                visits += 3
            actions[row["case_id"]] = choice
        metering[arm] = {"cpu_prediction_ns": process_time_ns()-a,
                         "legal_actions_compared": visits,
                         "observation_action_count": sum(a != "stop" for a in actions.values())}
        predictions[arm] = actions
    return predictions, metering


def produce_seal(train_rows, train_worlds, future_panels):
    train_groups = public_panel(train_rows, "train")
    if set(future_panels) != {"future_1", "future_2"}:
        raise ValueError("two prospective windows required")
    groups = {}
    for split, rows in future_panels.items():
        groups[split] = public_panel(rows, split)
    if train_groups & groups["future_1"] or train_groups & groups["future_2"] or groups["future_1"] & groups["future_2"]:
        raise ValueError("cross-cohort source group reuse")
    c = fit(train_rows, train_worlds)
    results, meters = {}, {}
    for split in ("future_1", "future_2"):
        results[split], meters[split] = action_report(future_panels[split], c)
    return {"schema": PROFILE, "source_only_future_inputs_sha256": {k:digest(future_panels[k]) for k in results},
            "train_rows_sha256":c["train_rows_sha256"],
            "training_observations_sha256":c["train_worlds_sha256"],
            "trained_critic_weights_sha256": hashlib.sha256(c["weights"].astype('<f8').tobytes()).hexdigest(),
            "actual_fit_cpu_ns":c["training_cpu_ns"], "actual_training_pairs":c["training_pairs_observed"],
            "frozen_ridge_penalty":10.0, "critic_parameters":c["head_parameters"],
            "predictions":results,"meters":meters,
            "future_labels_provided_to_critic":False, "exact_tree_control":True,
            "pretrained_encoder_executed":False,"natural_task_success_measured":False,
            "ndu_stochastic_fbsde_solved":False,"production_accepted":False,"authority":"DENY_ALL"}


def load_json(filename):
    with Path(filename).open('r', encoding='utf-8') as f:
        return json.load(f)


def write_create_only(filename, data):
    with Path(filename).open('x', encoding='utf-8') as f:
        f.write(canon(data)+'\n')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--train-rows", required=True)
    p.add_argument("--train-worlds", required=True)
    p.add_argument("--future-1", required=True)
    p.add_argument("--future-2", required=True)
    p.add_argument("--seal", required=True)
    args = p.parse_args()
    train = load_json(args.train_rows)
    worlds = load_json(args.train_worlds)
    if type(worlds) is not dict or set(worlds) != {"train_rows_sha256", "worlds"} or worlds["train_rows_sha256"] != digest(train):
        raise ValueError("training-world binding missing")
    train_worlds = [tuple(x) for x in worlds["worlds"]]
    fut = {"future_1":load_json(args.future_1), "future_2":load_json(args.future_2)}
    write_create_only(args.seal,produce_seal(train,train_worlds,fut))
    print(canon({"created": args.seal, "future_1_rows":len(fut["future_1"]), "future_2_rows":len(fut["future_2"]), "authority":"DENY_ALL"}))

if __name__ == "__main__":
    main()
