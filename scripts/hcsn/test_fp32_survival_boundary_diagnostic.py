#!/usr/bin/env python3
"""Fixed-source FP32 first-passage survival *negative control*, not an HCSN kernel.

Run: PYTHONPATH=scripts/hcsn python3 -m unittest discover -s scripts/hcsn \
     -p 'test_fp32_survival_boundary_diagnostic.py' -v
Or:  PYTHONPATH=scripts/hcsn python3 scripts/hcsn/test_fp32_survival_boundary_diagnostic.py --report

No model training, NPU, autograd, reset-neuron recurrence or GPU execution is tested.
The operations below intentionally mimic a naive FP32 evaluation of a FP64
formula and are *not* an implementation recommendation for a production path.
"""

import hashlib
import json
import math
from pathlib import Path
import sys
import unittest

import numpy as np
from scipy.special import erf, log_ndtr, ndtr

from hepta_free_boundary_reference import first_passage_cdf


REFERENCE_BLOB = "54e9e2440eb73399a95adf04d98674df68c191b3"
REFERENCE_FILE = Path(__file__).with_name("hepta_free_boundary_reference.py")


def reference_blob():
    data = REFERENCE_FILE.read_bytes()
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def naive_fp32_cdf(x, horizon, mu, sigma):
    """Explicit single-precision intermediates of the reference CDF, no reset."""
    x, horizon, mu, sigma = map(np.float32, (x, horizon, mu, sigma))
    scale = np.float32(sigma * np.sqrt(horizon))
    exponent = np.float32(-np.float32(2) * mu * x / np.float32(sigma * sigma))
    z1 = np.float32((-x - mu * horizon) / scale)
    z2 = np.float32((-x + mu * horizon) / scale)
    reflected = np.exp(np.float32(exponent + log_ndtr(z2)))
    return np.float32(ndtr(z1) + reflected)


def stable_zero_drift_survival_fp32(x, horizon, sigma):
    """Only for mu=0: P(tau_0>t)=erf(x/(sigma*sqrt(2*t)))."""
    x, horizon, sigma = map(np.float32, (x, horizon, sigma))
    argument = np.float32(x / np.float32(sigma * np.sqrt(np.float32(2) * horizon)))
    return np.float32(erf(argument))


def diagnostic_report():
    worst = (0.0, None)
    count = 0
    outside_unit = 0
    for x in (0., 1e-8, 1e-6, 1e-4, .01, .05, .2, .7, 1.2, 5.):
        for t in (1e-6, 1e-4, .01, .25, 1., 3., 10.):
            for mu in (-.08, 0., .08):
                for sigma in (.02, .2, .5):
                    fp64 = float(first_passage_cdf(x, t, mu, sigma))
                    fp32 = float(naive_fp32_cdf(x, t, mu, sigma))
                    err = abs(fp32 - fp64)
                    count += 1
                    outside_unit += int(not (0.0 <= fp32 <= 1.0))
                    if err > worst[0]:
                        worst = (err, dict(x=x, horizon=t, mu=mu, sigma=sigma,
                                           fp64_cdf=fp64, fp32_cdf=fp32))
    x, t, sigma = 1e-9, 1.0, 0.2
    fp32 = naive_fp32_cdf(x, t, 0., sigma)
    naive_survival = float(np.float32(np.float32(1) - fp32))
    stable_survival = float(stable_zero_drift_survival_fp32(x, t, sigma))
    return {
        "reference_git_blob": reference_blob(),
        "grid_cases": count,
        "grid_outside_unit_count": outside_unit,
        "max_abs_cdf_error_fp32_vs_fp64": worst[0],
        "worst_case": worst[1],
        "zero_drift_counterexample": {
            "x": x, "horizon": t, "sigma": sigma,
            "fp32_naive_cdf": float(fp32),
            "fp32_naive_one_minus_cdf": naive_survival,
            "fp32_erf_survival": stable_survival,
            "fp32_naive_log_survival_finite": naive_survival > 0,
            "fp32_erf_log_survival": math.log(stable_survival),
        },
        "scope": "synthetic CPU FP32 diagnostic only; no HCSN training/autograd/reset/NPU",
    }


class FP32SurvivalBoundaryDiagnostic(unittest.TestCase):
    def test_exact_parent_scalar_source(self):
        self.assertEqual(reference_blob(), REFERENCE_BLOB)

    def test_finite_grid_within_declared_absolute_tolerance(self):
        report = diagnostic_report()
        self.assertEqual(report["grid_cases"], 630)
        self.assertEqual(report["grid_outside_unit_count"], 0)
        self.assertLess(report["max_abs_cdf_error_fp32_vs_fp64"], 2e-7)

    def test_zero_drift_survival_formula_matches_fp64_reference(self):
        for x in (1e-10, 1e-9, 1e-8, 1e-5):
            for horizon in (.1, 1.0, 10.0):
                stable = float(stable_zero_drift_survival_fp32(x, horizon, .2))
                reference = float(erf(x / (.2 * math.sqrt(2 * horizon))))
                self.assertGreater(stable, 0)
                self.assertLess(abs(stable - reference) / reference, 2e-7)

    def test_naive_one_minus_cdf_loses_positive_survival(self):
        for x in (1e-10, 1e-9):
            cdf = naive_fp32_cdf(x, 1., 0., .2)
            self.assertEqual(float(cdf), 1.0)
            self.assertEqual(float(np.float32(np.float32(1) - cdf)), 0.0)
            self.assertGreater(float(stable_zero_drift_survival_fp32(x, 1., .2)), 0.0)


if __name__ == "__main__":
    if sys.argv[1:] == ["--report"]:
        print(json.dumps(diagnostic_report(), sort_keys=True, indent=2))
    else:
        unittest.main(verbosity=2)
