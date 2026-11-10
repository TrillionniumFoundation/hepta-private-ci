"""Train-only frozen-embedding repair; input pin authentication remains external.

Future results are descriptive prediction diagnostics, never a policy certificate.
"""

from collections import Counter
import hashlib
import json
import math

import numpy as np


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def features(encoded):
    x = np.asarray(encoded, dtype=np.float64)
    if (
        x.ndim != 2
        or not 1 <= len(x) <= 128
        or x.shape[1] != 24
        or not np.isfinite(x).all()
        or (np.abs(x) > 1.000001).any()
    ):
        raise ValueError("Expected finite bounded candidate embeddings of width 24")
    return x


def validate_rows(rows, sources):
    if (
        not rows
        or len(rows) > 8192
        or {r.get("source_id") for r in rows} != set(sources)
    ):
        raise ValueError("Rows must cover exactly the declared sources")
    result, states, ids = [], {}, {}
    for row in rows:
        if (
            set(row) != {"source_id", "observation_id", "role", "encoded", "positives"}
            or row["role"] != "train"
            or any(
                type(row[k]) is not str or not row[k]
                for k in ("source_id", "observation_id")
            )
        ):
            raise ValueError("Expected a train-role embedding observation")
        x, positives = features(row["encoded"]), row["positives"]
        if (
            type(positives) is not list
            or any(type(i) is not int or not 0 <= i < len(x) for i in positives)
            or len(set(positives)) != len(positives)
        ):
            raise ValueError("Invalid positive candidate indices")
        key, label = (row["source_id"], digest(x.tolist())), tuple(sorted(positives))
        if row["observation_id"] in ids and ids[row["observation_id"]] != (key, label):
            raise ValueError("Observation ID was reused for different contents")
        ids[row["observation_id"]] = key, label
        if key in states:
            if states[key] != label:
                raise ValueError(
                    "Identical source embedding state has conflicting labels"
                )
            continue
        states[key] = label
        result.append(dict(row, encoded=x.tolist(), positives=list(label)))
    return result


def validate_plan(plan):
    if plan.get("schema") != "ndu.ctrl.answer-repair-plan.v1":
        raise ValueError("Wrong prospective plan schema")
    sets = []
    for key, size in (
        ("original_fit_sources", 40),
        ("inner_train_sources", 32),
        ("inner_tune_sources", 8),
        ("future_sources", 37),
        ("excluded_sources", 20),
    ):
        values = plan.get(key)
        if (
            type(values) is not list
            or len(values) != size
            or any(type(v) is not str or not v for v in values)
            or len(set(values)) != size
        ):
            raise ValueError("Wrong declared source partition")
        sets.append(set(values))
    original, train, tune, future, excluded = sets
    if (
        train & tune
        or train | tune != original
        or original & (future | excluded)
        or future & excluded
    ):
        raise ValueError(
            "Source partitions overlap or fail to cover original fitting sources"
        )
    for key in (
        "fit_records_sha256",
        "base_weights_sha256",
        "source_inventory_sha256",
        "normalizer_sha256",
    ):
        value = plan.get(key)
        if (
            type(value) is not str
            or len(value) != 64
            or any(c not in "0123456789abcdef" for c in value)
        ):
            raise ValueError("Required input pin is not a SHA256")
    trials, steps = plan.get("trials"), plan.get("steps")
    if (
        type(steps) is not int
        or not 1 <= steps <= 2000
        or type(trials) is not list
        or not 1 <= len(trials) <= 16
    ):
        raise ValueError("Invalid fixed trial budget")
    for trial in trials:
        if (
            set(trial) != {"learning_rate", "l2"}
            or any(
                type(v) not in (float, int) or not math.isfinite(v)
                for v in trial.values()
            )
            or not 0 < trial["learning_rate"] <= 1
            or not 0 <= trial["l2"] <= 10
        ):
            raise ValueError("Invalid declared trial")
    margin = plan.get("minimum_quality_gain", 0.0)
    if (
        type(margin) not in (int, float)
        or not math.isfinite(margin)
        or not 0 <= margin <= 1
    ):
        raise ValueError("Invalid prospective quality threshold")
    return plan


def _weights(weights):
    w = np.asarray(weights, dtype=np.float64)
    if w.shape != (24,) or not np.isfinite(w).all():
        raise ValueError("Expected finite 24-wide answer weights")
    return w


def _softmax(logits):
    probability = np.exp(logits - logits.max())
    return probability / probability.sum()


def select(head, encoded):
    return int(np.argmax(features(encoded) @ _weights(head["weights"])))


def measure(rows, weights):
    w, groups = _weights(weights), {}
    unique = validate_rows(rows, {r.get("source_id") for r in rows})
    for row in unique:
        x, positives = features(row["encoded"]), row["positives"]
        logits = x @ w
        quality = float(int(np.argmax(logits)) in positives)
        maximum = float(logits.max())
        normalizer = maximum + math.log(float(np.exp(logits - maximum).sum()))
        if positives:
            chosen = logits[positives]
            top = float(chosen.max())
            loss = normalizer - top - math.log(float(np.exp(chosen - top).sum()))
        else:
            loss = None
        groups.setdefault(row["source_id"], []).append((quality, loss))
    losses = [
        np.mean([loss for _, loss in values if loss is not None])
        for values in groups.values()
        if any(loss is not None for _, loss in values)
    ]
    return {
        "source_count": len(groups),
        "unique_states": len(unique),
        "quality": float(
            np.mean([np.mean([q for q, _ in v]) for v in groups.values()])
        ),
        "nll": None if not losses else float(np.mean(losses)),
        "states_without_correct_candidate": sum(not r["positives"] for r in unique),
    }


def _train(rows, baseline, trial, steps):
    samples = [
        (r["source_id"], features(r["encoded"]), r["positives"])
        for r in rows
        if r["positives"]
    ]
    counts = Counter(source for source, _, _ in samples)
    if not samples:
        raise ValueError("No available positive candidate; never invent a target")
    w = baseline.copy()
    for _ in range(steps):
        gradient = np.zeros_like(w)
        for source, x, positives in samples:
            logits = x @ w
            probability, conditional = _softmax(logits), np.zeros(len(x))
            conditional[positives] = _softmax(logits[positives])
            gradient += (
                x.T @ (probability - conditional) / (counts[source] * len(counts))
            )
        w -= trial["learning_rate"] * (gradient + trial["l2"] * (w - baseline))
    return _weights(w)


def fit(rows, plan, original_weight, original_bias):
    validate_plan(plan)
    baseline = _weights(original_weight)
    if type(original_bias) not in (int, float) or not math.isfinite(original_bias):
        raise ValueError("Invalid shared bias")
    unique = validate_rows(rows, set(plan["original_fit_sources"]))
    training = [r for r in unique if r["source_id"] in plan["inner_train_sources"]]
    tuning = [r for r in unique if r["source_id"] in plan["inner_tune_sources"]]
    attempts = []
    for index, trial in enumerate(plan["trials"]):
        w = _train(training, baseline, trial, plan["steps"])
        attempts.append(
            {
                "trial": index,
                **trial,
                "steps": plan["steps"],
                "inner_tune": measure(tuning, w),
            }
        )
    selected = min(
        range(len(attempts)),
        key=lambda i: (
            -attempts[i]["inner_tune"]["quality"],
            float("inf")
            if attempts[i]["inner_tune"]["nll"] is None
            else attempts[i]["inner_tune"]["nll"],
            i,
        ),
    )
    candidate = _train(unique, baseline, plan["trials"][selected], plan["steps"])
    return {
        "schema": "ndu.ctrl.answer-repair-artifact.v1",
        "plan_sha256": digest(plan),
        "weights": candidate.tolist(),
        "original_weights": baseline.tolist(),
        "unchanged_shared_bias": original_bias,
        "training_sources": sorted(plan["original_fit_sources"]),
        "trials": attempts,
        "selected_trial": selected,
        "fitting": measure(unique, candidate),
        "baseline_inner_tune": measure(tuning, baseline),
        "selection": "NoUpdate",
        "reason": "Independent future evaluation pending",
        "production_admitted": False,
    }


def evaluate(head, rows, plan):
    validate_plan(plan)
    if head.get("schema") != "ndu.ctrl.answer-repair-artifact.v1" or head[
        "plan_sha256"
    ] != digest(plan):
        raise ValueError("Candidate does not bind this frozen prospective plan")
    unique = validate_rows(rows, set(plan["future_sources"]))
    baseline, candidate = (
        measure(unique, head["original_weights"]),
        measure(unique, head["weights"]),
    )
    gain = candidate["quality"] - baseline["quality"]
    return {
        "schema": "ndu.ctrl.answer-repair-prediction-evaluation.v1",
        "plan_sha256": digest(plan),
        "artifact_sha256": digest(head),
        "baseline": baseline,
        "candidate": candidate,
        "quality_gain": gain,
        "recommendation": "FurtherEvaluation"
        if gain > plan.get("minimum_quality_gain", 0.0)
        else "NoUpdate",
        "policy_evaluation_performed": False,
        "production_admitted": False,
    }
