"""Capacity-matched structural candidates over a frozen pretrained encoder.

Partition learning sees training examples only. Selection sees calibration only.
All experts inherit the same parent, retain complete optimizer state, and then
train on their own partition. The wider single model has exactly the aggregate
expert parameter count; the router is additional and separately accounted for.
"""

import copy
import hashlib
from itertools import combinations
import json
from pathlib import Path
import time

import numpy as np

from adapter import Adapter


def parameter_count(model):
    return sum(value.size for value in model.params.values())


def balanced_partition(X, y, groups=3):
    """Training-only balanced spherical clustering of class prototypes."""
    X, y = np.asarray(X), np.asarray(y)
    if not isinstance(groups, int) or isinstance(groups, bool) or groups < 1:
        raise ValueError("Partition group count must be a positive integer")
    if X.ndim != 2 or y.ndim != 1 or not len(y) or len(X) != len(y):
        raise ValueError("Partition requires nonempty aligned features and labels")
    if not np.isfinite(X).all() or not np.issubdtype(y.dtype, np.integer):
        raise ValueError("Partition requires finite features and integer labels")
    classes = sorted(set(map(int, y)))
    if len(classes) < groups or len(classes) % groups:
        raise ValueError("Balanced partition requires divisible class count")
    centers = np.stack([X[y == label].mean(axis=0) for label in classes])
    centers /= np.maximum(np.linalg.norm(centers, axis=1, keepdims=True), 1e-12)
    chosen = [0]
    while len(chosen) < groups:
        similarity = (centers @ centers[chosen].T).max(axis=1)
        similarity[chosen] = np.inf
        chosen.append(int(similarity.argmin()))
    prototypes = centers[chosen].copy()
    capacity = len(classes) // groups
    for _ in range(8):
        scores = centers @ prototypes.T
        assignments = [[] for _ in range(groups)]
        allocated = set()
        edges = sorted((-float(scores[i, g]), i, g)
                       for i in range(len(classes)) for g in range(groups))
        for _, i, g in edges:
            if i not in allocated and len(assignments[g]) < capacity:
                assignments[g].append(i)
                allocated.add(i)
        prototypes = np.stack([centers[indices].mean(axis=0) for indices in assignments])
        prototypes /= np.maximum(np.linalg.norm(prototypes, axis=1, keepdims=True), 1e-12)
    return [sorted(classes[i] for i in group) for group in assignments]


def interference_partition(parent, X, y, groups=3):
    """Separate conflicting shared-adapter gradients using training data only.

    Exhaustive balanced partitions are practical for this declared 12-class
    experiment. A/B gradients exclude the classifier head. This is a candidate
    heuristic, not evidence that negative cosine guarantees future benefit.
    """
    started = time.perf_counter()
    if not isinstance(groups, int) or isinstance(groups, bool) or groups < 1:
        raise ValueError("Interference group count must be a positive integer")
    X, y = np.asarray(X), np.asarray(y)
    classes = sorted(set(map(int, y)))
    if classes != list(range(parent.config["num_classes"])) or len(classes) % groups:
        raise ValueError("Interference search requires all classes and balanced groups")
    width = len(classes) // groups
    if not 1 <= groups <= len(classes) or len(classes) > 12:
        raise ValueError("Exhaustive interference search is bounded to twelve classes")
    vectors, gradient_norms = [], []
    for label in classes:
        _, gradients = parent.loss_and_grads(X[y == label], y[y == label])
        vector = np.concatenate([gradients[key].ravel() for key in ("A", "B")])
        norm = float(np.linalg.norm(vector))
        gradient_norms.append(norm)
        vectors.append(vector / max(norm, 1e-12))
    cosine = np.stack(vectors) @ np.stack(vectors).T
    conflict = np.maximum(-cosine, 0)

    def candidates(remaining):
        if len(remaining) == width:
            yield [list(remaining)]
            return
        for tail in combinations(remaining[1:], width - 1):
            group = (remaining[0],) + tail
            rest = tuple(label for label in remaining if label not in group)
            for other in candidates(rest):
                yield [list(group)] + other

    best, cost, considered = None, float("inf"), 0
    for partition in candidates(tuple(classes)):
        candidate_cost = sum(float(conflict[np.ix_(part, part)].sum()) / 2
                             for part in partition)
        considered += 1
        if candidate_cost < cost:
            best, cost = partition, candidate_cost
    return best, {"shared_gradient_cosine": cosine.tolist(),
                  "gradient_l2_norms": gradient_norms, "normalization_floor": 1e-12,
                  "degenerate_classes": [i for i, norm in enumerate(gradient_norms) if norm < 1e-12],
                  "within_group_negative_cosine": cost,
                  "all_pairs_negative_cosine": float(conflict.sum()) / 2,
                  "candidates_considered": considered,
                  "proposal_seconds": time.perf_counter() - started,
                  "training_only": True, "future_benefit_is_not_guaranteed": True}


def inherit_subset(parent, labels):
    child = parent.clone()
    child.config["num_classes"] = len(labels)
    for group in (child.params, child.m, child.v):
        group["W"] = group["W"][:, labels].copy()
        group["b"] = group["b"][labels].copy()
    # The old sampler is deliberately retained until train explicitly admits
    # the new partition and resets the permutation, without resetting Adam.
    return child


def widen(parent, multiple):
    old_rank = parent.config["rank"]
    config = {**parent.config, "rank": old_rank * multiple}
    result = Adapter(**config, encoder_hash=parent.encoder_hash,
                     source_version=parent.source_version)
    for name in ("W", "b"):
        for group in ("params", "m", "v"):
            getattr(result, group)[name] = getattr(parent, group)[name].copy()
    for group in ("params", "m", "v"):
        target, original = getattr(result, group), getattr(parent, group)
        target["A"][:, :old_rank] = original["A"]
        target["B"][:old_rank] = original["B"]
        # Extra columns of A stay initialized; zero B preserves the exact
        # parent function while allowing gradients into new capacity.
        target["B"][old_rank:] = 0
        if group != "params":
            target["A"][:, old_rank:] = 0
    result.rng.bit_generator.state = copy.deepcopy(parent.rng.bit_generator.state)
    result.sampler = copy.deepcopy(parent.sampler)
    result.optimizer = copy.deepcopy(parent.optimizer)
    result.step = parent.step
    return result


class SparseExperts:
    """A ridge router plus real selected-only expert invocations."""

    def __init__(self, parent, partition, top_k=2):
        self.partition = [list(map(int, part)) for part in partition]
        if sorted(sum(self.partition, [])) != list(range(parent.config["num_classes"])):
            raise ValueError("Partition must cover every class exactly once")
        if any(not part for part in self.partition):
            raise ValueError("Experts must each own at least one class")
        if not isinstance(top_k, int) or isinstance(top_k, bool) or not 1 <= top_k <= len(partition):
            raise ValueError("Sparse top-k must be within the expert count")
        self.experts = [inherit_subset(parent, labels) for labels in self.partition]
        self.router = None
        self.top_k = top_k
        self.num_classes = parent.config["num_classes"]
        self.stats = {"requests": 0, "expert_example_invocations": 0, "batch_calls": 0}

    def train(self, X, y, *, steps, batch_size, lr, data_id, source_version):
        started = time.perf_counter()
        group_for = {label: g for g, part in enumerate(self.partition) for label in part}
        targets = np.eye(len(self.partition))[np.asarray([group_for[int(a)] for a in y])]
        augmented = np.column_stack([X, np.ones(len(X))]).astype(np.float64)
        # Dual ridge solve: lambda is fixed before observing calibration/test.
        self.router = augmented.T @ np.linalg.solve(
            augmented @ augmented.T + 0.1 * np.eye(len(X)), targets)
        receipts = []
        for group, (labels, expert) in enumerate(zip(self.partition, self.experts)):
            mask = np.isin(y, labels)
            lookup = {label: local for local, label in enumerate(labels)}
            local_y = np.array([lookup[int(label)] for label in y[mask]], dtype=np.int64)
            receipts.append(expert.train(
                X[mask], local_y, steps=steps, batch_size=batch_size, lr=lr,
                data_id=f"{data_id}:partition:{group}", source_version=source_version,
                allow_data_change=True))
        return {"seconds": time.perf_counter() - started, "experts": receipts,
                "examples": sum(item["examples"] for item in receipts),
                "partition": self.partition, "router_parameters": self.router.size}

    def predict_proba(self, X):
        X = np.asarray(X)
        if self.router is None:
            raise ValueError("Router is not fitted")
        logits = np.column_stack([X, np.ones(len(X))]) @ self.router
        weights = np.exp(logits - logits.max(axis=1, keepdims=True))
        weights /= weights.sum(axis=1, keepdims=True)
        chosen = np.argsort(-weights, axis=1, kind="stable")[:, :self.top_k]
        output = np.zeros((len(X), self.num_classes))
        for group, (labels, expert) in enumerate(zip(self.partition, self.experts)):
            rows = np.flatnonzero(np.any(chosen == group, axis=1))
            if not len(rows):
                continue
            result = expert.predict_proba(X[rows]) * weights[rows, group, None]
            output[np.ix_(rows, labels)] = result
            self.stats["batch_calls"] += 1
            self.stats["expert_example_invocations"] += len(rows)
        self.stats["requests"] += len(X)
        return output / np.maximum(output.sum(axis=1, keepdims=True), 1e-12)

    def predict(self, X):
        return self.predict_proba(X).argmax(axis=1)

    def save(self, directory):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        for group, expert in enumerate(self.experts):
            expert.save(directory / f"expert-{group}.npz")
        np.save(directory / "router.npy", self.router, allow_pickle=False)
        descriptor = {"partition": self.partition, "top_k": self.top_k,
                      "num_classes": self.num_classes, "stats": self.stats,
                      "router_sha256": hashlib.sha256((directory / "router.npy").read_bytes()).hexdigest()}
        (directory / "network.json").write_text(json.dumps(descriptor, sort_keys=True, indent=2) + "\n")

    @property
    def parameter_count(self):
        return sum(parameter_count(expert) for expert in self.experts) + self.router.size
