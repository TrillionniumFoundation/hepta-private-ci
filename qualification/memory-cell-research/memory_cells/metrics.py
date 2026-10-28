"""Evaluation separates sample correctness, independent clusters and full cost."""

import math
from pathlib import Path

import numpy as np


def summarize_predictions(expected, predicted, groups=None):
    expected, predicted = list(expected), list(predicted)
    if len(expected) != len(predicted) or not expected:
        raise ValueError("nonempty aligned outcomes are required")
    if groups is not None and len(groups) != len(expected):
        raise ValueError("group count mismatch")
    known = sum(value is not None for value in expected)
    answered = sum(value is not None for value in predicted)
    correct_answers = sum(a is not None and a == b for a, b in zip(expected, predicted))
    correct_abstentions = sum(
        a is None and b is None for a, b in zip(expected, predicted)
    )
    incorrect_answers = sum(
        b is not None and a != b for a, b in zip(expected, predicted)
    )
    missed_answerable = sum(
        a is not None and b is None for a, b in zip(expected, predicted)
    )
    result = {
        "total": len(expected),
        "answerable": known,
        "answered": answered,
        "correct": correct_answers + correct_abstentions,
        "incorrect": incorrect_answers,
        "abstained": len(expected) - answered,
        "correct_answers": correct_answers,
        "correct_abstentions": correct_abstentions,
        "missed_answerable": missed_answerable,
        "total_errors": incorrect_answers + missed_answerable,
        "outcome_partition": {
            "correct_answer": correct_answers,
            "incorrect_answer": incorrect_answers,
            "abstention": len(expected) - answered,
        },
        "count_semantics": "correct includes valid abstentions; outcome_partition is disjoint",
        "accuracy": (correct_answers + correct_abstentions) / len(expected),
        "known_accuracy": correct_answers / known if known else None,
        "unknown_abstention_rate": correct_abstentions / (len(expected) - known)
        if known < len(expected)
        else None,
        "coverage": answered / len(expected),
        "selective_accuracy": correct_answers / answered if answered else None,
    }
    if groups is not None:
        result["per_group"] = {}
        for group in sorted(set(groups)):
            indices = [index for index, value in enumerate(groups) if value == group]
            result["per_group"][str(group)] = summarize_predictions(
                [expected[index] for index in indices],
                [predicted[index] for index in indices],
            )
    return result


def paired_cluster_interval(
    candidate, baseline, clusters, bootstrap_seed=0, n_boot=4000, confidence=0.95
):
    """Equal-weight cluster means; paraphrases never become independent n.

    Clusters must be the independently assigned seed/task/episode units used by
    the experiment. This function cannot authenticate caller-supplied independence.
    """
    candidate, baseline = (
        np.asarray(candidate, dtype=float),
        np.asarray(baseline, dtype=float),
    )
    if (
        candidate.ndim != 1
        or candidate.shape != baseline.shape
        or len(candidate) != len(clusters)
    ):
        raise ValueError("aligned one-dimensional scores and clusters are required")
    if (
        not len(candidate)
        or not np.isfinite(candidate).all()
        or not np.isfinite(baseline).all()
    ):
        raise ValueError("scores must be nonempty and finite")
    if not 0 < confidence < 1 or n_boot < 1:
        raise ValueError("invalid bootstrap settings")
    names = sorted(set(clusters))
    differences = candidate - baseline
    means = np.array(
        [differences[[label == name for label in clusters]].mean() for name in names]
    )
    result = {
        "paired_difference": float(means.mean()),
        "clusters": len(names),
        "observations": len(candidate),
        "confidence": confidence,
        "method": "percentile bootstrap of equal-weight independent-cluster mean differences",
        "cluster_differences": {
            str(key): float(value) for key, value in zip(names, means)
        },
        "lower": None,
        "upper": None,
        "status": "insufficient_independent_clusters",
    }
    if len(names) >= 2:
        rng = np.random.default_rng(bootstrap_seed)
        draws = rng.choice(means, size=(n_boot, len(means)), replace=True).mean(axis=1)
        alpha = (1 - confidence) / 2
        result.update(
            lower=float(np.quantile(draws, alpha)),
            upper=float(np.quantile(draws, 1 - alpha)),
            status="few_independent_clusters" if len(names) < 5 else "estimated",
        )
    return result


def measure_bytes(paths):
    """Charge physical files once even when a shared artifact is referenced twice."""
    seen = set()
    total = 0
    for name in paths:
        path = Path(name)
        if not path.exists():
            raise FileNotFoundError(path)
        files = path.rglob("*") if path.is_dir() else (path,)
        for item in files:
            if not item.is_file():
                continue
            resolved = item.resolve()
            if resolved not in seen:
                seen.add(resolved)
                total += item.stat().st_size
    return total


def resource_accounting(storage_components, compute_components):
    """Components must already partition actual work; no double-charging parents."""
    if any(
        not isinstance(value, int) or value < 0 for value in storage_components.values()
    ):
        raise ValueError("storage values must be nonnegative integer bytes")
    if any(
        not math.isfinite(value) or value < 0 for value in compute_components.values()
    ):
        raise ValueError("compute values must be nonnegative finite seconds")
    return {
        "storage_bytes": dict(storage_components),
        "total_storage_bytes": sum(storage_components.values()),
        "compute_seconds": dict(compute_components),
        "total_compute_seconds": sum(compute_components.values()),
        "cost_scope": "caller-supplied components; unmeasured costs must be reported separately",
    }


def break_even_reads(neural_write, baseline_write, neural_read, baseline_read):
    costs = (neural_write, baseline_write, neural_read, baseline_read)
    if any(not math.isfinite(value) or value < 0 for value in costs):
        raise ValueError("costs must be nonnegative finite and use the same unit")
    saving = baseline_read - neural_read
    if saving <= 0:
        return {"minimum_reads": None, "reason": "no_positive_per_read_saving"}
    additional_write = neural_write - baseline_write
    return {
        "minimum_reads": max(0, math.floor(additional_write / saving) + 1),
        "reason": "strictly_lower_measured_total_cost",
        "per_read_saving": saving,
        "additional_write_cost": additional_write,
    }
