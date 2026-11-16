"""Numeric LocalHead composition, deterministic budgets, and evaluation primitives."""

import copy
import hashlib
import json
import math
import time

import numpy as np

from hepta_cells.semantic import LocalHead, LocalObjective


ARMS = ("single", "fixed", "random_sparse", "learned_sparse")


COST_SCOPE = (
    "local float64 head/router projections and parameter-gradient MACs; 2 FLOPs/MAC; "
    "excludes mixing, router sensitivity, softmax, comparisons, hashing, IO, encoder and tools"
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def sha(value):
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(c in "0123456789abcdef" for c in value)
        and value != "0" * 64
    )


def unique_tasks(rows):
    result = {}
    for row in rows:
        previous = result.setdefault(row["observation_digest"], row)
        require(
            (previous["features"], previous["target"], previous["family_id"])
            == (row["features"], row["target"], row["family_id"]),
            "teacher copies disagree on observation or verified target",
        )
    return list(result.values())


class SparseCircuit:
    """Small trainable mixture over real LocalHeads; not the native Rust Circuit."""

    def __init__(self, width, classes, cells, active, arm, seed):
        require(
            all(type(v) is int for v in (width, classes, cells, active, seed))
            and 1 <= width <= 1024
            and 2 <= classes <= 128
            and width * classes * cells <= 1000000
            and 0 <= seed < 2**32,
            "invalid bounded model dimensions or seed",
        )
        require(arm in ARMS and 1 <= active <= cells <= 16, "invalid bounded graph")
        self.width, self.classes, self.arm = width, classes, arm
        self.cells, self.active = (1, 1) if arm == "single" else (cells, active)
        rng = np.random.default_rng(seed)
        self.heads = [
            LocalHead(rng.normal(0, 0.02, (width, classes)), np.zeros(classes))
            for _ in range(self.cells)
        ]
        self.router = (
            LocalHead(rng.normal(0, 0.02, (width, self.cells)), np.zeros(self.cells))
            if arm == "learned_sparse"
            else None
        )
        self.fixed = (
            rng.choice(self.cells, self.active, replace=False).tolist()
            if arm == "random_sparse"
            else list(range(self.active))
        )

    def record(self):
        return dict(
            arm=self.arm,
            width=self.width,
            classes=self.classes,
            cells=self.cells,
            active=self.active,
            fixed=self.fixed,
            heads=[
                dict(first=h.first.tolist(), bias=h.bias.tolist()) for h in self.heads
            ],
            router=None
            if self.router is None
            else dict(first=self.router.first.tolist(), bias=self.router.bias.tolist()),
        )

    @property
    def digest(self):
        return digest(self.record())

    @classmethod
    def restore(cls, record, expected_digest):
        require(
            sha(expected_digest) and digest(record) == expected_digest,
            "model bytes differ",
        )
        model = cls(
            record["width"],
            record["classes"],
            record["cells"],
            record["active"],
            record["arm"],
            0,
        )
        require(len(record["heads"]) == model.cells, "head count differs")
        model.heads = [LocalHead(h["first"], h["bias"]) for h in record["heads"]]
        require(
            all(h.first.shape == (model.width, model.classes) for h in model.heads),
            "head shape differs",
        )
        router = record["router"]
        require(
            (router is not None) == (model.router is not None), "router kind differs"
        )
        if router is not None:
            model.router = LocalHead(router["first"], router["bias"])
            require(
                model.router.first.shape == (model.width, model.cells),
                "router shape differs",
            )
        model.fixed = record["fixed"]
        require(
            type(model.fixed) is list
            and len(set(model.fixed)) == len(model.fixed) == model.active
            and all(type(i) is int and 0 <= i < model.cells for i in model.fixed),
            "fixed graph differs",
        )
        require(model.digest == expected_digest, "restored model identity differs")
        return model

    def forward(self, features, *, drop_cell=None, drop_edge=None):
        x = np.asarray(features, dtype=np.float64)
        allowed = [i for i in range(self.cells) if i != drop_cell]
        require(allowed, "ablation removes every Cell")
        scores = self.router.predict(x) if self.router is not None else None
        weights, values = (
            np.zeros((len(x), self.cells)),
            np.zeros((len(x), self.cells, self.classes)),
        )
        for row in range(len(x)):
            selected = (
                [i for i in self.fixed if i in allowed]
                if scores is None
                else sorted(allowed, key=lambda i: (-scores[row, i], i))[: self.active]
            )
            if not selected:
                continue
            probabilities = (
                np.ones(len(selected))
                if scores is None
                else np.exp(scores[row, selected] - np.max(scores[row, selected]))
            )
            weights[row, selected] = probabilities / probabilities.sum()
            for cell in selected:
                values[row, cell] = self.heads[cell].predict(x[row : row + 1])[0]
        if drop_edge is not None:
            values[:, drop_edge[0], drop_edge[1]] = 0.0
        return np.einsum("ni,nic->nc", weights, values), weights, values

    def cost(self, weights, *, training=False, freeze_heads=False, drop_edge=None):
        routes = int(np.count_nonzero(weights))
        router_mac = (
            len(weights) * self.width * self.cells if self.router is not None else 0
        )
        expert_mac = routes * self.width * self.classes
        gradient = ((0 if freeze_heads else expert_mac) + router_mac) if training else 0
        parameters = sum(a.size for h in self.heads for a in h.arrays)
        if self.router is not None:
            parameters += sum(a.size for a in self.router.arrays)
        edges = routes * self.classes
        if drop_edge is not None:
            edges -= int(np.count_nonzero(weights[:, drop_edge[0]]))
        return dict(
            linear_mac=int(expert_mac + router_mac + gradient),
            linear_flops=int(2 * (expert_mac + router_mac + gradient)),
            messages=routes,
            message_bytes=edges * 8,
            active_parameter_uses=routes * (self.width + 1) * self.classes
            + (len(weights) * (self.width + 1) * self.cells if self.router else 0),
            active_parameters=int(np.count_nonzero(np.any(weights, axis=0)))
            * (self.width + 1)
            * self.classes
            + ((self.width + 1) * self.cells if self.router else 0),
            resident_parameters=int(parameters),
            scope=COST_SCOPE,
            message_scope="logical local Cell output vectors; not network traffic",
            network_messages=0,
        )

    def update(self, x, targets, rate, *, freeze_heads=False):
        logits, weights, values = self.forward(x)
        loss, gradient = LocalObjective(
            "cross_entropy", self.classes, "observed-action"
        ).loss_and_gradient(logits, np.asarray(targets, dtype=np.int64))
        costs = self.cost(weights, training=True, freeze_heads=freeze_heads)
        if self.router is not None:
            sensitivity = np.einsum("nc,nic->ni", gradient, values)
            router_gradient = weights * (
                sensitivity - (sensitivity * weights).sum(axis=1, keepdims=True)
            )
            self.router = self.router.gradient_step(x, router_gradient, rate)
        if not freeze_heads:
            for cell, head in enumerate(self.heads):
                selected = weights[:, cell] != 0
                if selected.any():
                    self.heads[cell] = head.gradient_step(
                        x[selected],
                        gradient[selected] * weights[selected, cell, None],
                        rate,
                    )
        require(math.isfinite(loss), "nonfinite training loss")
        return loss, costs


def schedule(rows):
    require(bool(rows), "no training observations")
    groups = {}
    for row in sorted(
        rows, key=lambda r: (r["timestamp"], r["task_id"], str(r.get("teacher_id")))
    ):
        groups.setdefault(row["source_id"], []).append(row)
    return [
        groups[source][i]
        for i in range(max(map(len, groups.values())))
        for source in sorted(groups)
        if i < len(groups[source])
    ]


def fit(model, rows, budget, rate, passes, *, target_key="target", freeze_heads=False):
    """Actual bounded SGD; repeated exposure is counted, never new source novelty."""
    candidate, ordered = copy.deepcopy(model), schedule(rows)
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    counter = dict(
        linear_mac=0,
        linear_flops=0,
        messages=0,
        message_bytes=0,
        active_parameter_uses=0,
        updates=0,
        attempted_updates=0,
        losses=[],
        examples_by_source={},
        mac_by_source={},
        status="completed_candidate_only",
    )
    routes = np.zeros((1, candidate.cells))
    routes[0, : candidate.active] = 1
    bound = candidate.cost(routes, training=True, freeze_heads=freeze_heads)
    try:
        for index in range(passes * len(ordered)):
            row, unit = ordered[index % len(ordered)], bound["linear_mac"]
            source = row["source_id"]
            if (
                counter["updates"] >= budget["max_examples"]
                or counter["linear_mac"] + unit > budget["max_train_mac"]
            ):
                break
            if counter["examples_by_source"].get(source, 0) >= budget.get(
                "per_source_max_examples", math.inf
            ) or counter["mac_by_source"].get(source, 0) + unit > budget.get(
                "per_source_max_train_mac", math.inf
            ):
                continue
            counter["attempted_updates"] += 1
            x = np.asarray([row["features"]], dtype=np.float64)
            loss, costs = candidate.update(
                x, [row[target_key]], rate, freeze_heads=freeze_heads
            )
            for key in (
                "linear_mac",
                "linear_flops",
                "messages",
                "message_bytes",
                "active_parameter_uses",
            ):
                counter[key] += costs[key]
            counter["updates"] += 1
            counter["losses"].append(loss)
            counter["examples_by_source"][source] = (
                counter["examples_by_source"].get(source, 0) + 1
            )
            counter["mac_by_source"][source] = (
                counter["mac_by_source"].get(source, 0) + costs["linear_mac"]
            )
    except Exception as error:
        counter.update(
            status="FAILED",
            error=f"{type(error).__name__}: {error}",
            failed_attempt_arithmetic_known=False,
        )
    if not counter["updates"] and counter["status"] != "FAILED":
        counter["status"] = "BLOCKED_BUDGET"
    counter.update(
        parent_digest=model.digest,
        candidate_digest=candidate.digest,
        wall_ns=time.perf_counter_ns() - wall,
        process_cpu_ns=time.process_time_ns() - cpu,
        scope=COST_SCOPE,
        full_cost_known=False,
        energy_joules=None,
    )
    return candidate, counter


def evaluate(model, rows, **ablation):
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    rows = unique_tasks(rows)
    x, targets = (
        np.asarray([r["features"] for r in rows]),
        np.asarray([r["target"] for r in rows]),
    )
    logits, weights, _ = model.forward(x, **ablation)
    require(np.isfinite(logits).all(), "nonfinite evaluation logits")
    loss, _ = LocalObjective(
        "cross_entropy", model.classes, "observed-action"
    ).loss_and_gradient(logits, targets)
    require(math.isfinite(loss), "nonfinite evaluation loss")
    predictions = np.argmax(logits, axis=1)
    costs = model.cost(weights, drop_edge=ablation.get("drop_edge"))
    costs.update(
        wall_ns=time.perf_counter_ns() - wall,
        process_cpu_ns=time.process_time_ns() - cpu,
    )
    return dict(
        candidate_digest=model.digest,
        loss=loss,
        accuracy=float(np.mean(predictions == targets)),
        rows=[
            dict(
                task_id=r["task_id"],
                source_id=r["source_id"],
                family_id=r["family_id"],
                target=int(t),
                prediction=int(p),
                logits=l.tolist(),
            )
            for r, t, p, l in zip(rows, targets, predictions, logits)
        ],
        cost=costs,
    )
