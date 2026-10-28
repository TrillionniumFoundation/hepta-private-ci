"""Independent likelihood, information-boundary and checkpoint behavior checks."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile

import numpy as np
from scipy.stats import multivariate_normal

from .. import task
from ..retention import _adapt
from . import adaptation


def validate():
    data = task.build_dataset(7070101, 32, "development")
    anchor = {"kind": "filter", "parameters": [.12, .18, 1.0],
              "planning_q": .18, "planning_noise_scale": 1.0}
    candidate = {"kind": "filter", "parameters": [.32, .21, .9],
                 "planning_q": .21, "planning_noise_scale": .9}
    model = adaptation.make_model(anchor, candidate)
    checks, errors = {}, []
    for stage in task.STAGES:
        h = task.history(data, stage)
        actual = adaptation.public_log_likelihood(candidate, h)
        expected = []
        for row in range(len(h["obs"])):
            seen = h["mask"][row] & h["occupied"][row]
            times = h["times"][row, seen]
            covariance = 1 + .21 * np.minimum(times[:, None], times[None, :])
            covariance += np.diag(.9 * h["obs_var"][row, seen])
            expected.append(multivariate_normal.logpdf(h["obs"][row, seen], mean=.32 * times,
                                                       cov=covariance))
        errors.append(float(np.max(np.abs(actual - expected))))
    checks["innovations_match_independent_joint_gaussian"] = max(errors) < 1e-10
    h = task.history(data)
    original = adaptation.predict(model, h)
    changed = deepcopy(h)
    changed["ids"] = np.array(["hidden-regime-leak-attempt"] * len(h["obs"]))
    changed["future"] = np.full((len(h["obs"]), 6), 1e9)
    changed["law"] = np.array(["drift_shift"] * len(h["obs"]))
    ignored = adaptation.predict(model, changed)
    checks["ids_regime_and_private_extra_fields_ignored"] = all(
        np.array_equal(a, b) for a, b in zip(original, ignored))
    changed = deepcopy(h)
    absent = ~changed["mask"] | ~changed["occupied"]
    changed["obs"][absent] = np.nan
    changed["obs_var"][absent] = np.nan
    ignored = adaptation.predict(model, changed)
    checks["missing_storage_not_observation"] = all(np.array_equal(a, b) for a, b in zip(original, ignored))
    changed = deepcopy(h)
    changed["mask"][:] = False
    weights = adaptation.routing_weights(model, changed)
    checks["no_observation_keeps_prior"] = np.array_equal(weights, np.full(len(weights), .5))
    classical = adaptation.make_model(anchor, candidate, classical=True)
    classic = adaptation.predict(classical, h)
    equivalent_error = max(float(np.max(np.abs(a - b))) for a, b in zip(original, classic))
    checks["independent_classical_predictor_equivalence"] = equivalent_error < 1e-10
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "checkpoint.json"
        path.write_text(json.dumps(model, sort_keys=True, allow_nan=False))
        loaded = json.loads(path.read_text())
        restored = adaptation.predict(loaded, h)
        checks["serialized_reconstruction_exact"] = all(np.array_equal(a, b) for a, b in zip(original, restored))
    rejected = False
    try:
        _adapt(anchor, [data])
    except ValueError:
        rejected = True
    checks["development_holdout_refused_by_optimizer"] = rejected
    malformed = deepcopy(h)
    malformed["times"][:, 1] = -1
    rejected = False
    try:
        adaptation.predict(model, malformed)
    except ValueError:
        rejected = True
    checks["clock_regression_rejected"] = rejected
    quantized = adaptation.make_model(anchor, candidate, output_quantization="guarded_q24_v1")
    qmean, qvariance, certificate = adaptation.predict_details(quantized, h)
    checks["quantized_gaussian_parameters_on_q24_lattice"] = bool(
        np.array_equal(qmean * (1 << 24), np.rint(qmean * (1 << 24)))
        and np.array_equal(qvariance * (1 << 24), np.rint(qvariance * (1 << 24))))
    checks["quantized_dispatch_preserves_pointwise_certificate"] = bool(
        np.max(certificate["pointwise_nll_bound"]) <= .02)
    quantized_classical = adaptation.make_model(anchor, candidate, classical=True,
                                                 output_quantization="guarded_q24_v1")
    qcmean, qcvariance = adaptation.predict(quantized_classical, h)
    quantized_equivalence = max(float(np.max(np.abs(a - b)))
                               for a, b in zip((qmean, qvariance), (qcmean, qcvariance)))
    checks["quantized_classical_control_within_one_lattice_unit"] = quantized_equivalence <= 2**-24
    checks["quantized_model_identity_differs_from_fp64"] = (
        adaptation.document_digest(quantized) != adaptation.document_digest(model))
    return {"schema": "hepta.analytic-event.adaptation-validation.v2", "checks": checks,
            "passed": all(checks.values()), "joint_likelihood_max_error": max(errors),
            "classical_prediction_max_error": equivalent_error,
            "quantized_classical_prediction_max_error": quantized_equivalence,
            "confirmation_data_used": False}


if __name__ == "__main__":
    print(json.dumps(validate(), indent=2, allow_nan=False))
