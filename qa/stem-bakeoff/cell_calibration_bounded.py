"""Calibrate binary margins with a finite non-sharpening prior mixture.

The confidence envelope is a deterministic policy, not a confidence interval.
It bounds loss relative to the calibration prior under arbitrary score shift;
it neither guarantees calibration nor establishes task learning.
"""

import hashlib
from pathlib import Path
import re
import time

import numpy as np

from cell_learning_models import canonical


SCHEMA = "hepta.bounded-prior-mixture-calibration.v1"
ALPHAS = (0.0, 1/16, 1/8, 1/4, 1/2, 1.0)
PRIOR_STRENGTH = 16.0
TIE_TOLERANCE = 1e-12
BINDING_KEYS = {"feature_identity", "predictor_sha256", "calibration_context_sha256"}


def _margins(values):
    values = np.asarray(values, dtype=np.float64)
    if values.ndim != 1 or not 1 <= len(values) <= 16384 or not np.isfinite(values).all():
        raise ValueError("bounded finite one-dimensional margins required")
    return values


def _bindings(value):
    if (not isinstance(value, dict) or set(value) != BINDING_KEYS
            or any(type(v) is not str or not re.fullmatch(r"[0-9a-f]{64}", v) for v in value.values())):
        raise ValueError("explicit feature, predictor and calibration-context SHA256 bindings required")
    return dict(value)


def _prior(value):
    prior = np.asarray(value, dtype=np.float64)
    if (prior.shape != (2,) or not np.isfinite(prior).all() or np.any(prior <= 0)
            or abs(float(prior.sum()) - 1) > 1e-12):
        raise ValueError("effective loss-weighted binary training prior required")
    return prior


def _predict(margins, alpha, q, mixture, training_log_odds, symmetric):
    if alpha == 0:
        positive = np.full(len(margins), q, dtype=np.float64)
    elif symmetric or (q == .5 and training_log_odds == 0):
        # Calculate a common high probability so the reflected class columns
        # are bitwise complements, including arbitrarily large finite margins.
        exponential = np.exp(-alpha * np.abs(margins))
        high = .5 + mixture * (1/(1+exponential) - .5)
        positive = np.where(margins >= 0, high, 1-high)
    else:
        score = alpha * (margins - training_log_odds) + np.log(q/(1-q))
        exponential = np.exp(-np.abs(score))
        evidence = np.where(score >= 0, 1/(1+exponential), exponential/(1+exponential))
        positive = (1-mixture)*q + mixture*evidence
        positive = np.where(margins == training_log_odds, q, positive)
    return np.column_stack((1-positive, positive))


def validate_bounded_calibrator(fitted, *, expected_bindings):
    if fitted.get("schema") != SCHEMA or fitted.get("bindings") != _bindings(expected_bindings):
        raise ValueError("calibrator schema or predictor binding differs")
    g, mode = fitted["calibration_groups"], fitted["mode"]
    if type(g) is not int or not 1 <= g <= 16384 or mode not in ("pointwise", "complement_symmetric"):
        raise ValueError("invalid independent calibration-group count or mode")
    alpha, q, mixture, odds = [fitted[k] for k in
                              ("alpha", "prior_positive", "mixture_weight", "training_log_odds")]
    if (not np.isfinite([alpha, q, mixture, odds]).all() or alpha not in ALPHAS
            or not 0 < q < 1 or mixture != g/(g+PRIOR_STRENGTH)
            or fitted["prior_strength"] != PRIOR_STRENGTH):
        raise ValueError("invalid frozen confidence policy")
    training_prior = _prior(fitted["effective_training_prior"])
    if odds != float(np.log(training_prior[1]/training_prior[0])):
        raise ValueError("training-prior correction differs")
    mass = np.asarray(fitted["group_weighted_class_mass"], dtype=np.float64)
    if (mass.shape != (2,) or not np.isfinite(mass).all() or np.any(mass < 0)
            or abs(float(mass.sum())-g) > 1e-10):
        raise ValueError("invalid independent-group class mass")
    expected_q = .5 if mode == "complement_symmetric" else float((mass[1]+1)/(g+2))
    if (q != expected_q or not np.array_equal(fitted["prior"], [1-q, q])
            or (mode == "complement_symmetric" and not np.array_equal(training_prior, [.5, .5]))):
        raise ValueError("prior or complement-symmetry contract differs")
    return fitted


def apply_bounded_calibrator(margins, fitted, *, expected_bindings):
    fitted = validate_bounded_calibrator(fitted, expected_bindings=expected_bindings)
    return _predict(_margins(margins), fitted["alpha"], fitted["prior_positive"],
                    fitted["mixture_weight"], fitted["training_log_odds"],
                    fitted["mode"] == "complement_symmetric")


def fit_bounded_calibrator(margins, labels, rows, *, effective_training_prior,
                           bindings, mode="pointwise", fit_role="calibration", forbidden_groups=()):
    start, cpu = time.perf_counter_ns(), time.process_time_ns()
    margins, labels = _margins(margins), np.asarray(labels)
    prior, bindings = _prior(effective_training_prior), _bindings(bindings)
    if (fit_role not in ("calibration", "out_of_fold_calibration")
            or mode not in ("pointwise", "complement_symmetric")
            or labels.shape != margins.shape or labels.dtype.kind not in "iu"
            or np.any((labels < 0) | (labels > 1)) or len(rows) != len(labels)):
        raise ValueError("explicit calibration role and binary calibration rows required")
    if mode == "complement_symmetric" and not np.array_equal(prior, [.5, .5]):
        raise ValueError("complement symmetry requires effective training prior .5 and zero bias")
    groups, sources = {}, []
    for index, row in enumerate(rows):
        if any(type(row.get(k)) is not str or not 1 <= len(row[k].encode()) <= 512
               for k in ("source_id", "group_id")):
            raise ValueError("bounded source and group identities required")
        groups.setdefault(row["group_id"], []).append(index)
        sources.append(row["source_id"])
    if len(set(sources)) != len(sources) or set(groups) & set(forbidden_groups):
        raise ValueError("duplicate calibration source or overlap with fitting/tuning groups")
    g = len(groups)
    weights = np.empty(len(labels), dtype=np.float64)
    positive_mass = 0.0
    for group in sorted(groups):
        indices = groups[group]
        weights[indices] = 1/len(indices)
        positive_mass += float(labels[indices].mean())
    q = .5 if mode == "complement_symmetric" else float((positive_mass+1)/(g+2))
    mixture, odds = g/(g+PRIOR_STRENGTH), float(np.log(prior[1]/prior[0]))
    candidates = []
    for alpha in ALPHAS:
        probabilities = _predict(margins, alpha, q, mixture, odds, mode == "complement_symmetric")
        loss = float(-np.dot(weights, np.log(probabilities[np.arange(len(labels)), labels]))/g)
        candidates.append({"alpha": alpha, "group_weighted_calibration_nll": loss})
    minimum = min(candidate["group_weighted_calibration_nll"] for candidate in candidates)
    chosen = next(candidate for candidate in candidates
                  if candidate["group_weighted_calibration_nll"] <= minimum+TIE_TOLERANCE)
    selected, best = chosen["alpha"], chosen["group_weighted_calibration_nll"]
    lower, upper = (1-mixture)*q, q+mixture*(1-q)
    result = {"schema": SCHEMA, "mode": mode, "fit_role": fit_role, "bindings": bindings,
        "alpha": selected, "prior_positive": q, "prior": [1-q, q], "mixture_weight": mixture,
        "training_log_odds": odds, "effective_training_prior": prior.tolist(),
        "prior_strength": PRIOR_STRENGTH, "calibration_groups": g, "calibration_rows": len(labels),
        "calibration_source_ids": sources, "calibration_group_ids": sorted(groups),
        "forbidden_fitting_or_tuning_groups": sorted(set(forbidden_groups)),
        "class_support_rows": np.bincount(labels, minlength=2).tolist(),
        "group_weighted_class_mass": [g-positive_mass, positive_mass],
        "group_weighting": "one total weight per independent bug, divided among its action rows",
        "candidates": candidates, "selection": "minimum calibration NLL; within1e-12 prefer smaller alpha",
        "weighted_calibration_nll": best, "minimum_candidate_calibration_nll": minimum,
        "prior_only_calibration_nll": candidates[0]["group_weighted_calibration_nll"],
        "prior_only_selected": selected == 0, "zero_evidence_returns_prior_exactly": True,
        "positive_probability_bounds": [lower, upper],
        "maximum_nll_excess_over_prior_per_row": float(np.log1p(g/PRIOR_STRENGTH)),
        "bounds_are_policy_not_confidence_intervals": True, "holdout_supplied_to_fit": False,
        "calibration_prior_pseudocounts": [1, 1] if mode == "pointwise" else None,
        "mixture_prior_mass_is_not_observed_labels": True,
        "stored_prediction_scalars": 4, "free_temperature_grid_candidates": len(ALPHAS),
        "estimated_prior_parameters": int(mode == "pointwise"), "gradient_updates": 0,
        "fit_input_sha256": hashlib.sha256(canonical([sources, [r["group_id"] for r in rows],
            labels.tolist(), margins.tolist()])).hexdigest(),
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "wall_ns": time.perf_counter_ns()-start, "cpu_ns": time.process_time_ns()-cpu,
        "quality_qualified": False, "authority": "DENY_ALL"}
    return validate_bounded_calibrator(result, expected_bindings=bindings)
