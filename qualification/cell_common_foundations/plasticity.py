"""Read-only plasticity diagnostics and immutable research candidates.

This NumPy reference is evidence for declared finite probes, not the native
learning.plasticity writer, an adoption authority, or a production efficacy test.
Effective rank follows singular-value entropy, as in Prakash et al. (ICML 2026).
The exact ER derivative below is available only away from rank-deficient points.
The author's training code alternates task and ER steps; this reference exposes
its -ER objective plus L2 explicitly and does not claim an identical optimizer.
"""

from dataclasses import dataclass
import hashlib
import json
import math
import time
from typing import Mapping, Sequence

import numpy as np


RANK_DEFINITION = (
    "exp(-sum(p*log(p))); p=sigma/sum(sigma); singular values, not eigenvalues"
)


def _array(values, name: str, ndim: int | None = None) -> np.ndarray:
    out = np.asarray(values, dtype=np.float64)
    if not out.size or (ndim is not None and out.ndim != ndim):
        raise ValueError(f"{name}: nonempty array of dimension {ndim} required")
    if not np.isfinite(out).all():
        raise ValueError(f"{name}: all entries must be finite")
    return out


def _nonnegative(value: float, name: str) -> float:
    if isinstance(value, (bool, np.bool_)) or not math.isfinite(value) or value < 0:
        raise ValueError(f"{name}: finite nonnegative number required")
    return float(value)


def _id(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name}: nonempty identifier required")
    return value


def _l2_norm(values, name: str) -> float:
    """Scale before squaring; never confuse an underflowed sum with zero."""
    x = _array(values, name)
    scale = float(np.max(np.abs(x)))
    if scale == 0:
        return 0.0
    normalized = x / scale
    norm = scale * math.sqrt(float(np.sum(normalized * normalized)))
    if not math.isfinite(norm):
        raise ValueError(f"{name}: L2 norm exceeds finite float64 range")
    return norm


def _projected_step(
    selected: np.ndarray, change: np.ndarray, bound: float
) -> tuple[np.ndarray, bool]:
    """Project using a normalized direction and verify the stored update."""
    change = _array(change, "proposed change")
    if selected.shape != change.shape:
        raise ValueError("proposed change shape differs from selected weights")
    change_norm = _l2_norm(change, "proposed change")
    baseline_norm = _l2_norm(selected, "selected weights")
    limit = bound * baseline_norm
    if not math.isfinite(limit) or (bound > 0 and baseline_norm > 0 and limit == 0):
        raise ValueError("trust-region radius is not representable in float64")
    projected = change_norm > limit
    if projected:
        # Multiplying by limit/change_norm first can underflow to zero even
        # when the projected components themselves are representable.
        change = (change / change_norm) * limit
    with np.errstate(over="ignore", invalid="ignore"):
        candidate = _array(selected + change, "candidate weights")
    if not update_metrics(selected, candidate, maximum_relative_norm=bound)[
        "within_bound"
    ]:
        raise ValueError(
            "stored update cannot satisfy the trust region at this float64 scale"
        )
    return candidate, projected


def array_digest(values: np.ndarray) -> str:
    """Digest shape and canonical little-endian FP64 bytes, not an authority."""
    data = _array(values, "digest input")
    return hashlib.sha256(
        str(data.shape).encode() + data.astype("<f8").tobytes()
    ).hexdigest()


def feature_metrics(
    features,
    *,
    probe_id: str,
    centered: bool = False,
    activation_semantics: str = "signed_magnitude",
    active_epsilon: float = 1e-8,
    low_utilization_ratio: float = 0.05,
) -> dict:
    """Measure one fixed sample-by-unit panel with explicit activation semantics.

    Low utilization means mean absolute activation < ratio * across-unit mean.
    A zero panel is degenerate (ER=0, every unit low/dead), never ER=1.
    ReLU and spike panels must be nonnegative; this does not estimate firing rate
    in hertz because an exposure duration was not supplied.
    """
    x = _array(features, "features", 2)
    _id(probe_id, "probe_id")
    _nonnegative(active_epsilon, "active_epsilon")
    if not 0 <= low_utilization_ratio <= 1:
        raise ValueError("low_utilization_ratio must be within [0,1]")
    if activation_semantics not in {
        "signed_magnitude",
        "relu_nonnegative",
        "spike_count",
    }:
        raise ValueError("unsupported activation semantics")
    if activation_semantics != "signed_magnitude" and np.any(x < 0):
        raise ValueError("nonnegative activation semantics cannot consume signed data")
    if activation_semantics == "spike_count" and np.any(x != np.floor(x)):
        raise ValueError("spike_count requires integer counts")
    z = x - x.mean(axis=0, keepdims=True) if centered else x
    singular = np.linalg.svd(z, compute_uv=False)
    total = float(singular.sum())
    if not math.isfinite(total):
        raise ValueError("feature singular-value sum exceeds finite reference range")
    degenerate = total == 0
    p = singular[singular > 0] / total if total else np.empty(0)
    erank = math.exp(float(-(p * np.log(p)).sum())) if total else 0.0
    magnitude = np.abs(x)
    mean_activity = magnitude.mean(axis=0)
    overall = float(mean_activity.mean())
    normalized = mean_activity / overall if overall else np.zeros(x.shape[1])
    dead = np.all(magnitude <= active_epsilon, axis=0)
    low = normalized < low_utilization_ratio if overall else np.ones(x.shape[1], bool)
    tolerance = max(z.shape) * np.finfo(np.float64).eps * singular[0]
    return {
        "probe_id": probe_id,
        "feature_digest": array_digest(x),
        "sample_count": int(x.shape[0]),
        "unit_count": int(x.shape[1]),
        "rank_definition": RANK_DEFINITION,
        "centered": bool(centered),
        "effective_rank": erank,
        "degenerate": degenerate,
        "numerical_rank": int(np.count_nonzero(singular > tolerance)),
        "singular_values": singular.tolist(),
        "activation_semantics": activation_semantics,
        "active_epsilon": active_epsilon,
        "low_utilization_ratio": low_utilization_ratio,
        "normalized_mean_activity": normalized.tolist(),
        "low_utilization_fraction": float(low.mean()),
        "dead_unit_fraction": float(dead.mean()),
        "always_active_fraction": float(
            np.all(magnitude > active_epsilon, axis=0).mean()
        ),
        "energy_joules": None,
    }


def representation_drift(
    before, after, *, before_probe_id: str, after_probe_id: str
) -> dict:
    """Compare aligned examples in one caller-identified probe; IDs are not signed."""
    a, b = _array(before, "before", 2), _array(after, "after", 2)
    _id(before_probe_id, "before_probe_id")
    if before_probe_id != after_probe_id or a.shape != b.shape:
        raise ValueError("drift requires the same ordered probe and feature shape")
    delta = float(np.linalg.norm(b - a))
    baseline = float(np.linalg.norm(a))
    ac, bc = a - a.mean(axis=0), b - b.mean(axis=0)
    cka_num = float(np.linalg.norm(ac.T @ bc) ** 2)
    cka_den = float(np.linalg.norm(ac.T @ ac) * np.linalg.norm(bc.T @ bc))
    return {
        "probe_id": before_probe_id,
        "absolute_frobenius": delta,
        "relative_frobenius": delta / baseline if baseline else None,
        "linear_cka": cka_num / cka_den if cka_den else None,
        "definition": "paired Frobenius drift and centered linear CKA",
        "status": "observed" if baseline and cka_den else "degenerate_reference",
    }


def retention_metrics(
    baseline_scores: Mapping[str, float],
    current_scores: Mapping[str, float],
    *,
    panel_id: str,
    maximum_drop: float = 0.02,
) -> dict:
    """Retention of unit-interval higher-is-better scores, with per-slice gates.

    The threshold is an absolute difference (0.02 = 2 percentage points). It
    must be changed explicitly if a registered study uses a relative percentage.
    Missing slices and an unmeasured panel cannot become passing evidence.
    """
    _id(panel_id, "panel_id")
    _nonnegative(maximum_drop, "maximum_drop")
    if set(baseline_scores) != set(current_scores):
        raise ValueError("retention panels must contain exactly the same slices")
    if not baseline_scores:
        return {
            "panel_id": panel_id,
            "status": "unknown",
            "reason": "no_old_task_measurements",
            "per_slice": {},
            "worst_drop": None,
            "passed": None,
        }
    drops = {}
    for key, baseline in baseline_scores.items():
        _id(key, "slice")
        current = current_scores[key]
        if not all(math.isfinite(v) and 0 <= v <= 1 for v in (baseline, current)):
            raise ValueError("retention scores must be finite and within [0,1]")
        drops[key] = float(baseline - current)
    return {
        "panel_id": panel_id,
        "status": "observed",
        "per_slice": drops,
        "worst_drop": max(drops.values()),
        "mean_drop": float(np.mean(list(drops.values()))),
        "threshold": maximum_drop,
        "threshold_units": "absolute_score_difference",
        "passed": all(drop <= maximum_drop + 1e-12 for drop in drops.values()),
    }


def _retention_evidence_error(retention: dict) -> str | None:
    """Validate the complete measured panel and recompute its decision."""
    if not isinstance(retention, Mapping) or retention.get("status") != "observed":
        return "retention_not_passed"
    fields = {
        "panel_id",
        "per_slice",
        "worst_drop",
        "mean_drop",
        "threshold",
        "threshold_units",
        "passed",
    }
    if not fields <= retention.keys():
        return "incomplete_retention_evidence"
    try:
        _id(retention["panel_id"], "retention panel_id")
        threshold = _nonnegative(retention["threshold"], "retention threshold")
        if retention["threshold_units"] != "absolute_score_difference":
            raise ValueError("unsupported retention threshold units")
        slices = retention["per_slice"]
        if not isinstance(slices, Mapping) or not slices:
            raise ValueError("observed retention requires a nonempty per-slice panel")
        for key, drop in slices.items():
            _id(key, "retention slice")
            if isinstance(drop, bool) or not math.isfinite(drop) or not -1 <= drop <= 1:
                raise ValueError(
                    "retention drops must be finite unit-interval score differences"
                )
        actual_worst = max(slices.values())
        actual_mean = math.fsum(slices.values()) / len(slices)
        for key, actual in (("worst_drop", actual_worst), ("mean_drop", actual_mean)):
            supplied = retention[key]
            if (
                isinstance(supplied, bool)
                or not math.isfinite(supplied)
                or not math.isclose(supplied, actual, rel_tol=1e-12, abs_tol=1e-12)
            ):
                return "inconsistent_retention_evidence"
        actual_passed = all(drop <= threshold + 1e-12 for drop in slices.values())
        if retention["passed"] is not actual_passed:
            return "inconsistent_retention_evidence"
        return None if actual_passed else "retention_not_passed"
    except (TypeError, ValueError, OverflowError):
        return "invalid_retention_evidence"


def learning_speed(
    steps: Sequence[int], losses: Sequence[float], *, target_loss: float, task_id: str
) -> dict:
    """Sampled loss AUC and observed time-to-target, with explicit censoring."""
    x, y = _array(steps, "steps", 1), _array(losses, "losses", 1)
    _id(task_id, "task_id")
    _nonnegative(target_loss, "target_loss")
    if len(x) != len(y) or len(x) < 2 or np.any(np.diff(x) <= 0) or np.any(x < 0):
        raise ValueError("need at least two matching increasing nonnegative steps")
    if np.any(x != np.floor(x)) or np.any(y < 0):
        raise ValueError("steps must be integers and losses nonnegative")
    hit = np.flatnonzero(y <= target_loss)
    auc = float(np.sum(np.diff(x) * (y[:-1] + y[1:]) / 2))
    return {
        "task_id": task_id,
        "target_loss": target_loss,
        "loss_auc": auc,
        "mean_loss_over_steps": auc / float(x[-1] - x[0]),
        "first_observed_target_step": int(x[hit[0]]) if hit.size else None,
        "target_censored": not bool(hit.size),
        "observed_until_step": int(x[-1]),
        "initial_loss": float(y[0]),
        "final_loss": float(y[-1]),
    }


def update_metrics(before, after, *, maximum_relative_norm: float = 0.0025) -> dict:
    a, b = _array(before, "before"), _array(after, "after")
    _nonnegative(maximum_relative_norm, "maximum_relative_norm")
    if a.shape != b.shape:
        raise ValueError("parameter shapes differ")
    with np.errstate(over="ignore", invalid="ignore"):
        change = _array(b - a, "parameter change")
    absolute, baseline = (
        _l2_norm(change, "parameter change"),
        _l2_norm(a, "baseline parameters"),
    )
    relative = absolute / baseline if baseline else (0.0 if absolute == 0 else None)
    if relative is not None and (
        not math.isfinite(relative) or (absolute > 0 and relative == 0)
    ):
        raise ValueError("relative update norm is not representable in float64")
    within_bound = relative is not None and (
        relative <= maximum_relative_norm
        or math.isclose(relative, maximum_relative_norm, rel_tol=1e-12, abs_tol=0.0)
    )
    return {
        "absolute_l2": absolute,
        "baseline_l2": baseline,
        "relative_l2": relative,
        "maximum_relative_norm": maximum_relative_norm,
        "within_bound": within_bound,
        "maximum_component_change": float(np.max(np.abs(change))),
    }


def stability_metrics(values, *, declared_absolute_bound: float) -> dict:
    """Record divergence without placing NaN or infinity in JSON reports."""
    bound = _nonnegative(declared_absolute_bound, "declared_absolute_bound")
    x = np.asarray(values, dtype=np.float64)
    if not x.size:
        raise ValueError("empty stability window")
    finite = np.isfinite(x)
    return {
        "value_count": int(x.size),
        "nonfinite_count": int((~finite).sum()),
        "bound_exceedance_count": int((np.abs(x[finite]) > bound).sum()),
        "maximum_finite_magnitude": float(np.max(np.abs(x[finite])))
        if finite.any()
        else None,
        "declared_absolute_bound": bound,
        "passed": bool(finite.all() and np.all(np.abs(x) <= bound)),
    }


def rank_l2_objective(
    inputs,
    weights,
    *,
    rank_weight: float,
    l2_weight: float,
    centered: bool = False,
    minimum_singular_ratio: float = 1e-10,
) -> tuple[dict, np.ndarray | None]:
    """L(W) = -rank_weight * ER(XW) + l2_weight/2 * ||W||_F^2.

    The spectral gradient is U diag(alpha*ER*(log(p)+H)/sum(s)) V^T.
    Rank deficiency is a nondifferentiable boundary: return no gradient if ER is
    requested there. No epsilon-created rank or invented revival direction is
    used. L2-only proposals remain defined at rank-deficient inputs.
    """
    x, w = _array(inputs, "inputs", 2), _array(weights, "weights", 2)
    if x.shape[1] != w.shape[0]:
        raise ValueError("input and weight dimensions disagree")
    alpha, beta = (
        _nonnegative(rank_weight, "rank_weight"),
        _nonnegative(l2_weight, "l2_weight"),
    )
    if not 0 < minimum_singular_ratio < 1:
        raise ValueError("minimum_singular_ratio must be within (0,1)")
    features = _array(x @ w, "feature product", 2)
    z = features - features.mean(axis=0) if centered else features
    u, s, vt = np.linalg.svd(z, full_matrices=False)
    total = float(s.sum())
    if not math.isfinite(total):
        raise ValueError("singular-value sum exceeds finite reference range")
    p = s[s > 0] / total if total else np.empty(0)
    entropy = float(-(p * np.log(p)).sum()) if total else 0.0
    erank = math.exp(entropy) if total else 0.0
    rank_deficient = total == 0 or s[-1] <= minimum_singular_ratio * s[0]
    info = {
        "rank_definition": RANK_DEFINITION,
        "centered": bool(centered),
        "effective_rank": erank,
        "rank_weight": alpha,
        "l2_weight": beta,
        "rank_loss": -alpha * erank,
        "l2_loss": beta * float(np.sum(w * w)) / 2,
        "minimum_singular_ratio": minimum_singular_ratio,
        "rank_gradient_status": "unavailable_rank_boundary"
        if alpha and rank_deficient
        else "available",
    }
    info["objective"] = info["rank_loss"] + info["l2_loss"]
    if not math.isfinite(info["objective"]):
        raise ValueError("rank/L2 objective exceeds finite reference range")
    if alpha and rank_deficient:
        return info, None
    gradient = beta * w
    if alpha:
        probabilities = s / total
        dsingular = alpha * erank * (np.log(probabilities) + entropy) / total
        dfeatures = (u * dsingular) @ vt
        if centered:
            dfeatures = dfeatures - dfeatures.mean(axis=0)
        gradient = gradient + x.T @ dfeatures
    if not np.isfinite(gradient).all():
        raise ValueError("nonfinite rank/L2 gradient")
    return info, gradient


@dataclass(frozen=True)
class RankL2Candidate:
    """Immutable candidate bytes and a research receipt; contains no grant."""

    weights: np.ndarray
    receipt: dict


def rank_l2_candidate(
    inputs,
    selected_weights,
    *,
    probe_id: str,
    rank_weight: float,
    l2_weight: float,
    learning_rate: float,
    maximum_relative_norm: float = 0.0025,
    centered: bool = False,
) -> RankL2Candidate:
    selected = _array(selected_weights, "selected weights", 2)
    _id(probe_id, "probe_id")
    rate = _nonnegative(learning_rate, "learning_rate")
    bound = _nonnegative(maximum_relative_norm, "maximum_relative_norm")
    info, gradient = rank_l2_objective(
        inputs,
        selected,
        rank_weight=rank_weight,
        l2_weight=l2_weight,
        centered=centered,
    )
    candidate = selected.copy()
    projected = False
    if gradient is not None:
        with np.errstate(over="ignore", invalid="ignore"):
            change = -rate * gradient
        candidate, projected = _projected_step(selected, change, bound)
    # Bytes-backed arrays cannot be made writable again by toggling setflags.
    candidate = np.frombuffer(candidate.tobytes(), dtype=np.float64).reshape(
        candidate.shape
    )
    receipt = {
        "probe_id": probe_id,
        "selected_digest": array_digest(selected),
        "candidate_digest": array_digest(candidate),
        "input_digest": array_digest(_array(inputs, "inputs", 2)),
        "status": "candidate"
        if gradient is not None and np.any(candidate != selected)
        else "no_update",
        "learning_rate": rate,
        "trust_region_projected": projected,
        "objective_before": info,
        "update": update_metrics(selected, candidate, maximum_relative_norm=bound),
        "proposal_only": True,
        "runtime_authority": False,
        "production_retention": None,
        "energy_joules": None,
    }
    return RankL2Candidate(candidate, receipt)


def maintenance_gate(
    operation: str,
    *,
    measured_costs: Mapping[str, float | None],
    budget: Mapping[str, float],
    retention: dict,
    fixed_graph_comparison: Mapping[str, float] | None,
    minimum_net_gain: float = 0.0,
) -> dict:
    """Research gate for maintenance, never a native apply or adoption permit.

    Every structural candidate needs measured migration and relearning costs.
    Phase measurements must account for all attempted work without overlap.
    Separately declared failed-attempt and retry phases are additive; unknown
    cost names are rejected instead of disappearing from the total. An explicit
    unknown duration makes the total unknown, including optional phases.
    Utility scores must already use the same preregistered cost conversion as the
    fixed-graph scheduler. Missing measurements remain unknown and fail the gate.
    """
    _nonnegative(minimum_net_gain, "minimum_net_gain")
    operations = {"no_change", "rank_l2", "sleep", "regenerate", "split", "merge"}
    if operation not in operations:
        raise ValueError("unsupported maintenance operation")
    seconds_keys = {
        "training_seconds",
        "tuning_seconds",
        "evaluation_seconds",
        "migration_seconds",
        "relearning_seconds",
        "failed_attempt_seconds",
        "retry_seconds",
    }
    known_costs = seconds_keys | {"peak_memory_bytes", "energy_joules"}
    if set(measured_costs) - known_costs:
        raise ValueError(
            "unknown measured cost keys: "
            + repr(sorted(set(measured_costs) - known_costs))
        )
    if set(budget) - (known_costs | {"total_seconds"}):
        raise ValueError(
            "unknown budget keys: "
            + repr(sorted(set(budget) - known_costs - {"total_seconds"}))
        )
    required = {
        "training_seconds",
        "tuning_seconds",
        "evaluation_seconds",
        "peak_memory_bytes",
    }
    if operation in {"sleep", "regenerate", "split", "merge"}:
        required |= {"migration_seconds", "relearning_seconds"}
    required |= seconds_keys & measured_costs.keys()
    missing = sorted(key for key in required if measured_costs.get(key) is None)
    for key, value in measured_costs.items():
        if value is not None:
            _nonnegative(value, key)
    for key, value in budget.items():
        _nonnegative(value, key)
    try:
        total_seconds = (
            None
            if any(key in missing for key in seconds_keys)
            else math.fsum(
                float(measured_costs.get(key, 0)) for key in sorted(seconds_keys)
            )
        )
    except OverflowError as exc:
        raise ValueError("total measured time exceeds finite float64 range") from exc
    if total_seconds is not None and not math.isfinite(total_seconds):
        raise ValueError("total measured time must be finite")
    measured = dict(measured_costs)
    measured["total_seconds"] = total_seconds
    reasons = ["missing_cost:" + key for key in missing]
    reasons += [
        "missing_budget:" + key
        for key in ("total_seconds", "peak_memory_bytes")
        if key not in budget
    ]
    for key, maximum in budget.items():
        if measured.get(key) is None:
            reasons.append("unmeasured_budget_axis:" + key)
        elif measured[key] > maximum:
            reasons.append("budget_exceeded:" + key)
    retention_error = _retention_evidence_error(retention)
    if retention_error is not None:
        reasons.append(retention_error)
        if retention_error != "retention_not_passed":
            reasons.append("retention_not_passed")
    net_gain = None
    if fixed_graph_comparison is None:
        reasons.append("fixed_graph_scheduler_comparison_unknown")
    else:
        if set(fixed_graph_comparison) != {
            "candidate_net_utility",
            "baseline_net_utility",
        }:
            raise ValueError(
                "comparison requires exactly candidate/baseline net utility"
            )
        scores = list(fixed_graph_comparison.values())
        if not all(math.isfinite(value) for value in scores) or not math.isfinite(
            minimum_net_gain
        ):
            raise ValueError("comparison values must be finite")
        net_gain = float(fixed_graph_comparison["candidate_net_utility"]) - float(
            fixed_graph_comparison["baseline_net_utility"]
        )
        if not math.isfinite(net_gain):
            raise ValueError("net utility difference must be finite")
        if net_gain <= minimum_net_gain:
            reasons.append("insufficient_net_gain")
    return {
        "operation": operation,
        "research_eligible": not reasons,
        "reasons": reasons,
        "measured_costs": measured,
        "net_utility_gain": net_gain,
        "production_retention": None,
        "runtime_authority": False,
        "energy_joules": measured_costs.get("energy_joules"),
    }


PLASTICITY_METHODS = ("fixed_graph_scheduler_l2", "fixed_graph_scheduler_l2_er")


def _continual_plasticity_probe(
    seed: int, steps_per_task: int, methods: Sequence[str], progress: dict
) -> dict:
    """Run a small reproducible continual regression diagnostic on local copies.

    Both variants use the same initial matrix, three ordered tasks, samples,
    decaying learning-rate schedule, 25% old-task replay and update-norm bound.
    The only intervention difference is a -ER gradient in the second variant.
    Extra SVD work and measured wall time are reported; equal optimizer steps do
    not imply equal compute cost. Proxy scores are 1/(1+MSE), never production
    retention or true terminal reward. No held-out hyperparameter search occurs.
    """
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError("seed must be a nonnegative integer")
    if (
        isinstance(steps_per_task, bool)
        or not isinstance(steps_per_task, int)
        or steps_per_task < 2
    ):
        raise ValueError("steps_per_task must be an integer at least 2")
    rng = np.random.default_rng(seed)
    x_train = rng.normal(size=(32, 3))
    x_probe = rng.normal(size=(40, 3))
    teachers = [np.eye(3) + 0.25 * rng.normal(size=(3, 3)) for _ in range(3)]
    train_targets = [x_train @ teacher for teacher in teachers]
    probe_targets = [x_probe @ teacher for teacher in teachers]
    initial = np.diag([1.0, 0.45, 0.08])
    original_digest = array_digest(initial)
    probe_id = "synthetic-continual-regression-v1-seed-" + str(seed)
    task_ids = [probe_id + "-task-" + str(index) for index in range(3)]

    def data_entry(values):
        return {
            "shape": list(values.shape),
            "dtype": "little_endian_float64",
            "sha256": array_digest(values),
        }

    data_manifest = {
        "schema": "continual_regression_supervised_split_v1",
        "input_splits": {
            "train": data_entry(x_train),
            "held_out_probe": data_entry(x_probe),
        },
        "task_order": task_ids,
        "tasks": [
            {
                "task_id": task_ids[index],
                "teacher": data_entry(teachers[index]),
                "target_splits": {
                    "train": data_entry(train_targets[index]),
                    "held_out_probe": data_entry(probe_targets[index]),
                },
            }
            for index in range(len(task_ids))
        ],
    }
    data_digest = hashlib.sha256(
        json.dumps(
            data_manifest, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()
    alpha, beta, rate, replay, update_bound = 0.05, 0.02, 0.1, 0.25, 0.0025
    variants = {}

    def loss(matrix, task, probe=False):
        data = x_probe if probe else x_train
        targets = probe_targets if probe else train_targets
        return float(np.mean((data @ matrix - targets[task]) ** 2))

    for name in methods:
        if name not in PLASTICITY_METHODS:
            raise ValueError("unknown plasticity method")
        rank_weight = alpha if name == "fixed_graph_scheduler_l2_er" else 0.0
        start = time.perf_counter()
        weights = initial.copy()
        after_first_learning, speed, ranks, shifts = {}, [], [], []
        all_updates, losses_by_task = [], []
        task_gradient_evaluations = 0
        er_gradient_evaluations = 0
        projected_count = 0
        for task in range(3):
            prior_features = x_probe @ weights
            task_losses = [loss(weights, task)]
            for step in range(steps_per_task):
                residual = x_train @ weights - train_targets[task]
                gradient = 2 * x_train.T @ residual / residual.size
                task_gradient_evaluations += 1
                if task:
                    old_gradient = np.zeros_like(weights)
                    for old_task in range(task):
                        residual_old = x_train @ weights - train_targets[old_task]
                        old_gradient += (
                            2 * x_train.T @ residual_old / residual_old.size / task
                        )
                        task_gradient_evaluations += 1
                    gradient = (1 - replay) * gradient + replay * old_gradient
                if rank_weight:
                    _, regularizer_gradient = rank_l2_objective(
                        x_train, weights, rank_weight=rank_weight, l2_weight=beta
                    )
                    er_gradient_evaluations += 1
                    if regularizer_gradient is None:
                        raise ValueError(
                            "synthetic diagnostic reached the declared spectral boundary"
                        )
                else:
                    regularizer_gradient = beta * weights
                gradient += regularizer_gradient
                delta = -(rate / (1 + step / steps_per_task)) * gradient
                candidate, projected = _projected_step(weights, delta, update_bound)
                if projected:
                    projected_count += 1
                all_updates.append(
                    update_metrics(
                        weights, candidate, maximum_relative_norm=update_bound
                    )
                )
                weights = candidate
                progress["actual_steps"] = progress.get("actual_steps", 0) + 1
                task_losses.append(loss(weights, task))
            progress["completed_tasks"] = progress.get("completed_tasks", 0) + 1
            after_first_learning[task_ids[task]] = 1 / (
                1 + loss(weights, task, probe=True)
            )
            speed.append(
                learning_speed(
                    range(steps_per_task + 1),
                    task_losses,
                    target_loss=0.5 * task_losses[0],
                    task_id=task_ids[task],
                )
            )
            losses_by_task.append(task_losses)
            ranks.append(
                feature_metrics(
                    x_probe @ weights,
                    probe_id=probe_id,
                    activation_semantics="signed_magnitude",
                )
            )
            shifts.append(
                representation_drift(
                    prior_features,
                    x_probe @ weights,
                    before_probe_id=probe_id,
                    after_probe_id=probe_id,
                )
            )
        # Only already learned old tasks enter retention, not the just-learned last task.
        old_baseline = {
            task_ids[task]: after_first_learning[task_ids[task]] for task in range(2)
        }
        old_current = {
            task_ids[task]: 1 / (1 + loss(weights, task, probe=True))
            for task in range(2)
        }
        variants[name] = {
            "initial_digest": original_digest,
            "candidate_digest": array_digest(weights),
            "rank_weight": rank_weight,
            "l2_weight": beta,
            "learning_speed": speed,
            "training_losses": losses_by_task,
            "features_after_tasks": ranks,
            "drift_after_tasks": shifts,
            "old_task_proxy_retention": retention_metrics(
                old_baseline, old_current, panel_id=probe_id + "-old-task-panel"
            ),
            "maximum_step_relative_update": max(
                item["relative_l2"] for item in all_updates
            ),
            "all_step_bounds_pass": all(item["within_bound"] for item in all_updates),
            "stability": stability_metrics(weights, declared_absolute_bound=10),
            "costs": {
                "wall_seconds": time.perf_counter() - start,
                "optimizer_steps": 3 * steps_per_task,
                "task_gradient_evaluations": task_gradient_evaluations,
                "er_gradient_evaluations": er_gradient_evaluations,
                "projected_updates": projected_count,
                "tuning_trials": 0,
                "peak_memory_bytes": None,
                "energy_joules": None,
                "migration_seconds": None,
                "relearning_seconds": None,
            },
            "production_retention": None,
            "runtime_authority": False,
        }
    assert array_digest(initial) == original_digest
    return {
        "evidence_scope": "finite_synthetic_diagnostic",
        "seed": seed,
        "task_count": 3,
        "steps_per_task": steps_per_task,
        "probe_id": probe_id,
        "data_digest": data_digest,
        "data_manifest": data_manifest,
        "scheduler": "fixed graph; decaying step size; uniform 25% old-task replay",
        "matched_budget_axes": [
            "optimizer_steps",
            "task_gradient_evaluations",
            "tuning_trials",
        ],
        "unmatched_cost_axes": ["er_gradient_evaluations", "wall_seconds"],
        "proxy_score_definition": "1/(1+held_out_MSE); higher is better",
        "production_retention": None,
        "energy_joules": None,
        "runtime_authority": False,
        "variants": variants,
    }


def continual_plasticity_probe(seed: int = 19, steps_per_task: int = 24) -> dict:
    """Return both method trajectories on the same finite synthetic task stream."""
    return _continual_plasticity_probe(seed, steps_per_task, PLASTICITY_METHODS, {})


def run_plasticity_pilot(
    seeds: Sequence[int] = (3, 7, 11), *, steps_per_task: int = 24, on_attempt=None
) -> dict:
    """Retain one raw outcome for every planned independent seed/method attempt.

    A failed method does not discard another method or seed. Actual completed
    optimizer steps survive a failure; no failed/missing run becomes an efficacy
    observation. Wall and process CPU timings include data preparation and the
    complete diagnostic; memory and sensor energy remain unmeasured.
    An optional persistence callback receives started/finished events outside
    the training exception handler; callback failures stop the pilot visibly.
    """
    try:
        from .protocol import AttemptSpec, cost_observation, summarize_attempts
    except ImportError:
        from protocol import AttemptSpec, cost_observation, summarize_attempts
    seeds = tuple(seeds)
    if not seeds or len(set(seeds)) != len(seeds):
        raise ValueError("nonempty unique independent seeds required")
    if any(
        isinstance(seed, bool) or not isinstance(seed, int) or seed < 0
        for seed in seeds
    ):
        raise ValueError("seeds must be nonnegative integers")
    if (
        isinstance(steps_per_task, bool)
        or not isinstance(steps_per_task, int)
        or steps_per_task < 2
    ):
        raise ValueError("steps_per_task must be an integer at least 2")
    if on_attempt is not None and not callable(on_attempt):
        raise ValueError("on_attempt must be callable or None")
    roster = [
        AttemptSpec(
            "plasticity-" + str(seed) + "-" + method, "plasticity", method, seed
        )
        for seed in seeds
        for method in PLASTICITY_METHODS
    ]
    rows = []
    for spec in roster:
        if on_attempt is not None:
            on_attempt(
                "started",
                {
                    "attempt_id": spec.attempt_id,
                    "family": spec.family,
                    "method": spec.method,
                    "seed": spec.seed,
                    "status": "running",
                    "planned_steps": 3 * steps_per_task,
                    "actual_steps": 0,
                    "completed_tasks": 0,
                },
            )
        start_wall, start_cpu = time.perf_counter(), time.process_time()
        progress = {"actual_steps": 0, "completed_tasks": 0}
        result, reason, status = None, None, "completed"
        try:
            diagnostic = _continual_plasticity_probe(
                spec.seed, steps_per_task, (spec.method,), progress
            )
            result = diagnostic["variants"][spec.method]
            result["probe_id"] = diagnostic["probe_id"]
            result["data_digest"] = diagnostic["data_digest"]
            result["data_manifest"] = diagnostic["data_manifest"]
            result["proxy_score_definition"] = diagnostic["proxy_score_definition"]
            result["evidence_scope"] = diagnostic["evidence_scope"]
        except Exception as exc:
            status, reason = "failed", type(exc).__name__ + ": " + str(exc)
        costs = cost_observation(
            wall_seconds=time.perf_counter() - start_wall,
            cpu_seconds=time.process_time() - start_cpu,
        )
        row = {
            "attempt_id": spec.attempt_id,
            "family": spec.family,
            "method": spec.method,
            "seed": spec.seed,
            "status": status,
            "reason": reason,
            "actual_steps": progress["actual_steps"],
            "planned_steps": 3 * steps_per_task,
            "completed_tasks": progress["completed_tasks"],
            "result": result,
            "cost": costs,
        }
        rows.append(row)
        if on_attempt is not None:
            on_attempt("finished", row)
    return {
        "raw_rows": rows,
        "summary": summarize_attempts(roster, rows),
        "evidence_scope": "finite_synthetic_diagnostic",
        "rank_definition": RANK_DEFINITION,
        "centered": False,
        "activation_semantics": "signed_magnitude",
        "scheduler": "fixed graph; decaying step size; uniform 25% old-task replay",
        "matched_budget_axes": [
            "optimizer_steps",
            "task_gradient_evaluations",
            "tuning_trials",
        ],
        "unmatched_cost_axes": ["er_gradient_evaluations", "wall_seconds"],
        "production_retention": None,
        "energy_joules": None,
        "migration_seconds": None,
        "relearning_seconds": None,
        "runtime_authority": False,
    }
