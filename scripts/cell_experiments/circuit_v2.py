"""Matched two-Cell path diagnostics; these are not native Cell capabilities.

All arms perform identical useful dense kernels per SGD step and prediction.
The learned arm chooses ordered paths using A-only online loss statistics, so
there are no uncharged search forwards or trainable router weights. Its Python
selection overhead is recorded separately. Wall time and full-system cost are
not asserted equal. The monolithic/fixed pair is a semantic-equivalence control.
"""

import itertools
import math
import time

import numpy as np

from .composition_core import ARMS, digest, require, sha


class PathCircuit:
    """A shared input/readout with a sparse, ordered two-Cell activation path."""

    def __init__(self, width, hidden, classes, cells, arm, seed):
        require(arm in ARMS, "unknown arm")
        require(
            all(type(v) is int for v in (width, hidden, classes, cells, seed))
            and 1 <= width <= 1024
            and 1 <= hidden <= 64
            and 2 <= classes <= 128
            and 2 <= cells <= 16
            and 0 <= seed < 2**32,
            "invalid bounded dimensions",
        )
        self.width, self.hidden, self.classes = width, hidden, classes
        self.arm, self.pool = arm, 2 if arm == "single" else cells
        rng = np.random.default_rng(seed)
        self.parameters = {
            "input_w": rng.normal(0, 1 / math.sqrt(width), (width, hidden)),
            "input_b": np.zeros(hidden),
        }
        # Consume the same initialization stream even for the two-Cell control.
        bank = [
            rng.normal(0, 1 / math.sqrt(hidden), (hidden, hidden)) for _ in range(cells)
        ]
        for index in range(self.pool):
            self.parameters[f"cell_{index}_w"] = bank[index]
            self.parameters[f"cell_{index}_b"] = np.zeros(hidden)
        self.parameters["output_w"] = rng.normal(
            0, 1 / math.sqrt(hidden), (hidden, classes)
        )
        self.parameters["output_b"] = np.zeros(classes)
        self.paths = list(itertools.permutations(range(self.pool), 2))
        self.path = (
            self.paths[int(rng.integers(len(self.paths)))]
            if arm == "random_sparse"
            else (0, 1)
        )

    def record(self):
        return {
            "schema": "hepta.path-circuit.v2",
            "width": self.width,
            "hidden": self.hidden,
            "classes": self.classes,
            "cells": self.pool,
            "arm": self.arm,
            "path": list(self.path),
            "parameters": {
                key: value.tolist() for key, value in self.parameters.items()
            },
        }

    @classmethod
    def restore(cls, record, expected_digest):
        require(
            sha(expected_digest) and digest(record) == expected_digest,
            "checkpoint bytes differ",
        )
        model = cls(
            record["width"],
            record["hidden"],
            record["classes"],
            record["cells"],
            record["arm"],
            0,
        )
        require(
            record.get("schema") == "hepta.path-circuit.v2", "unknown checkpoint schema"
        )
        require(
            set(record["parameters"]) == set(model.parameters), "parameter names differ"
        )
        for key, original in model.parameters.items():
            value = np.asarray(record["parameters"][key], dtype=np.float64)
            require(
                value.shape == original.shape and np.isfinite(value).all(),
                "invalid parameter",
            )
            model.parameters[key] = value
        model.path = tuple(record["path"])
        require(model.path in model.paths, "invalid frozen path")
        require(digest(model.record()) == expected_digest, "restored identity differs")
        return model

    def forward(self, features, *, path=None, drop_cell=None, drop_edge=None):
        selected = self.path if path is None else tuple(path)
        require(selected in self.paths, "invalid path")
        require(
            drop_cell is None or type(drop_cell) is int and 0 <= drop_cell < self.pool,
            "invalid Cell ablation",
        )
        require(
            drop_edge is None or type(drop_edge) is int and 0 <= drop_edge < 3,
            "invalid edge ablation",
        )
        x = np.asarray(features, dtype=np.float64)
        require(
            x.shape == (self.width,) and np.isfinite(x).all(), "invalid feature vector"
        )
        p = self.parameters
        value = np.tanh(x @ p["input_w"] + p["input_b"])
        activations = [x, value]
        for stage, cell in enumerate(selected):
            if drop_edge == stage:
                value = np.zeros_like(value)
            value = np.tanh(value @ p[f"cell_{cell}_w"] + p[f"cell_{cell}_b"])
            if drop_cell == cell:
                value = np.zeros_like(value)
            activations.append(value)
        if drop_edge == 2:
            value = np.zeros_like(value)
        logits = value @ p["output_w"] + p["output_b"]
        return logits, activations

    def loss_gradient(self, features, target, *, path=None):
        require(type(target) is int and 0 <= target < self.classes, "invalid target")
        selected = self.path if path is None else tuple(path)
        logits, states = self.forward(features, path=selected)
        probabilities = np.exp(logits - np.max(logits))
        probabilities /= probabilities.sum()
        loss = -math.log(max(float(probabilities[target]), np.finfo(np.float64).tiny))
        gradient = probabilities.copy()
        gradient[target] -= 1
        p = self.parameters
        gradients = {
            "output_w": np.outer(states[-1], gradient),
            "output_b": gradient.copy(),
        }
        upstream = gradient @ p["output_w"].T
        for stage in (1, 0):
            cell = selected[stage]
            delta = upstream * (1 - states[stage + 2] ** 2)
            gradients[f"cell_{cell}_w"] = np.outer(states[stage + 1], delta)
            gradients[f"cell_{cell}_b"] = delta.copy()
            upstream = delta @ p[f"cell_{cell}_w"].T
        delta = upstream * (1 - states[1] ** 2)
        gradients["input_w"] = np.outer(states[0], delta)
        gradients["input_b"] = delta
        require(
            math.isfinite(loss)
            and all(np.isfinite(g).all() for g in gradients.values()),
            "nonfinite gradient",
        )
        return loss, gradients

    def cost(self, *, training=False):
        d, h, c = self.width, self.hidden, self.classes
        weights = d * h + 2 * h * h + h * c
        parameters = weights + 3 * h + c
        # Outer products are multiplications, not multiply-add pairs.
        return {
            "matrix_dot_mac": weights + (2 * h * h + h * c if training else 0),
            "outer_product_multiplications": weights if training else 0,
            "model_mac_equivalent": weights
            + (weights + 2 * h * h + h * c if training else 0),
            "bias_additions": 3 * h + c,
            "tanh_evaluations": 3 * h,
            "tanh_backward_scalar_ops": 9 * h if training else 0,
            "parameter_update_scalar_ops": 2 * parameters if training else 0,
            "loss_exp_evaluations": c if training else 0,
            "loss_log_evaluations": 1 if training else 0,
            "loss_scalar_ops": 3 * c if training else 0,
            "loss_max_comparisons": c if training else 0,
            "active_parameters_per_example": parameters,
            "resident_parameters": sum(
                value.size for value in self.parameters.values()
            ),
            "logical_cell_messages": 3,
            "logical_cell_message_bytes": 3 * h * 8,
            "network_messages": 0,
        }


def validate_rows(rows, width, classes):
    require(
        type(rows) is list and 0 < len(rows) <= 16384, "bounded nonempty rows required"
    )
    for row in rows:
        for key in ("task_id", "source_id", "project_id", "lineage_id"):
            require(
                isinstance(row.get(key), str) and 0 < len(row[key]) <= 256,
                "missing " + key,
            )
        values = np.asarray(row.get("features"), dtype=np.float64)
        require(
            values.shape == (width,) and np.isfinite(values).all(), "invalid features"
        )
        require(
            type(row.get("target")) is int and 0 <= row["target"] < classes,
            "invalid class",
        )
        require(
            sha(row.get("observation_digest")), "original observation digest required"
        )


def fit_arm(rows, plan, arm):
    """Use the same actual SGD kernel budget; A-only bandit history learns paths."""
    model = PathCircuit(
        plan["width"], plan["hidden"], plan["classes"], plan["cells"], arm, plan["seed"]
    )
    validate_rows(rows, model.width, model.classes)
    steps, rate = plan["updates"], plan["rate"]
    require(type(steps) is int and 1 <= steps <= 100000, "bounded updates required")
    require(
        type(rate) in (int, float) and math.isfinite(rate) and 0 < rate <= 1,
        "bounded rate required",
    )
    require(
        steps >= len(model.paths) or arm != "learned_sparse",
        "budget cannot visit all learned paths",
    )
    ordered = sorted(
        rows,
        key=lambda row: (row["source_id"], row["task_id"], row["observation_digest"]),
    )
    counts, means, visited, history = (
        np.zeros(len(model.paths), dtype=np.int64),
        np.zeros(len(model.paths)),
        set(),
        [],
    )
    overhead = {
        "path_score_reads": 0,
        "log_evaluations": 0,
        "sqrt_evaluations": 0,
        "score_scalar_ops": 0,
        "mean_scalar_ops": 0,
        "path_comparisons": 0,
    }
    initial = digest(model.record())
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    for step in range(steps):
        if arm == "learned_sparse":
            if step < len(model.paths):
                index = step
            else:
                exploration = math.log(step + 1)
                scores = means - np.sqrt(2 * exploration / counts)
                index = int(np.argmin(scores))
                overhead["path_score_reads"] += len(model.paths)
                overhead["log_evaluations"] += 1
                overhead["sqrt_evaluations"] += len(model.paths)
                overhead["score_scalar_ops"] += 2 * len(model.paths) + 2
                overhead["path_comparisons"] += len(model.paths) - 1
            path = model.paths[index]
        else:
            path = model.path
        row = ordered[step % len(ordered)]
        loss, gradients = model.loss_gradient(row["features"], row["target"], path=path)
        for key, gradient in gradients.items():
            model.parameters[key] -= rate * gradient
        visited.update(path)
        if arm == "learned_sparse":
            counts[index] += 1
            means[index] += (loss - means[index]) / counts[index]
            overhead["mean_scalar_ops"] += 4
        history.append(
            {"step": step, "task_id": row["task_id"], "path": list(path), "loss": loss}
        )
    if arm == "learned_sparse":
        model.path = model.paths[
            min(
                range(len(model.paths)),
                key=lambda index: (float(means[index]), model.paths[index]),
            )
        ]
        overhead["path_score_reads"] += len(model.paths)
        overhead["path_comparisons"] += len(model.paths) - 1
    elapsed = {
        "wall_seconds": (time.perf_counter_ns() - wall) / 1e9,
        "cpu_seconds": (time.process_time_ns() - cpu) / 1e9,
    }
    unit = model.cost(training=True)
    totals = {
        key: value * steps
        for key, value in unit.items()
        if key not in ("active_parameters_per_example", "resident_parameters")
    }
    common = (
        model.width * model.hidden
        + model.hidden
        + model.hidden * model.classes
        + model.classes
    )
    return model, {
        "schema": "hepta.path-training.v2",
        "arm": arm,
        "updates": steps,
        "initial_model_digest": initial,
        "model_digest": digest(model.record()),
        "input_digest": digest(rows),
        "plan_digest": digest(plan),
        "frozen_path": list(model.path),
        "kernel_totals": totals,
        "kernel_per_update": unit,
        "control_overhead": overhead,
        "trainable_parameter_union": common
        + len(visited) * (model.hidden**2 + model.hidden),
        "visited_cells": sorted(visited),
        "path_counts": counts.tolist() if arm == "learned_sparse" else None,
        "path_mean_training_losses": means.tolist()
        if arm == "learned_sparse"
        else None,
        "history": history,
        **elapsed,
        "full_system_cost_known": False,
        "kernel_convention": "matrix dot MAC counts and outer-product multiplications are distinct; model_mac_equivalent is their sum, not a full FLOP or hardware-instruction count",
        "control_counter_scope": "bandit numeric scores/means only; Python branching, allocations and history recording are not completely counted",
        "full_control_operation_count_known": False,
        "scope": "NumPy float64 forward/backward/update kernels; control overhead separate; excludes frozen encoder, IO, allocation, BLAS implementation, communication and energy",
        "topology_selection": "A-only online mean loss; nonstationary bandit heuristic, no convergence claim",
    }


def evaluate(model, rows, *, drop_cell=None, drop_edge=None):
    validate_rows(rows, model.width, model.classes)
    before, outputs = digest(model.record()), []
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    for row in rows:
        logits, _ = model.forward(
            row["features"], drop_cell=drop_cell, drop_edge=drop_edge
        )
        prediction = int(np.argmax(logits))
        probabilities = np.exp(logits - np.max(logits))
        probabilities /= probabilities.sum()
        outputs.append(
            {
                "task_id": row["task_id"],
                "prediction": prediction,
                "target": row["target"],
                "correct": prediction == row["target"],
                "logits": logits.tolist(),
                "cross_entropy": -math.log(
                    max(float(probabilities[row["target"]]), np.finfo(np.float64).tiny)
                ),
            }
        )
    require(digest(model.record()) == before, "evaluation changed frozen parameters")
    return {
        "model_digest": before,
        "input_digest": digest(rows),
        "rows": outputs,
        "classification_accuracy": sum(row["correct"] for row in outputs)
        / len(outputs),
        "mean_cross_entropy": sum(row["cross_entropy"] for row in outputs)
        / len(outputs),
        "task_success_rate": None,
        "kernel_per_prediction": model.cost(),
        "wall_seconds": (time.perf_counter_ns() - wall) / 1e9,
        "cpu_seconds": (time.process_time_ns() - cpu) / 1e9,
        "ablation": {"cell": drop_cell, "edge": drop_edge},
        "edge_definition": [
            "input projection -> first Cell",
            "first Cell -> second Cell",
            "second Cell -> readout",
        ],
        "scope": "input-feature class diagnostic; no repository execution or agent-task success claim",
    }
