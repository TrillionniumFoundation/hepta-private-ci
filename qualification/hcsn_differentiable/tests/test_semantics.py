"""Drift-regime diagnostics against independent density/renewal calculations."""

import math
import unittest

import torch

from qualification.hcsn_differentiable.contract import PhysicalParameters
from qualification.hcsn_differentiable.finite_renewal import finite_renewal_value
from qualification.hcsn_differentiable.semantics import long_run_regime


def density_moment(mu, distance, sigma, moment, upper_log_time=12.0):
    # Independent positive Simpson integral in log(time); no analytic F/G use.
    lower, count = -16.0, 8192
    width = (upper_log_time - lower) / count
    values = []
    for index in range(count + 1):
        log_time = lower + index * width
        time = math.exp(log_time)
        log_density = (
            math.log(distance / sigma)
            - 0.5 * math.log(2 * math.pi)
            - 1.5 * log_time
            - (distance + mu * time) ** 2 / (2 * sigma**2 * time)
        )
        weight = 1 if index in (0, count) else 2 if index % 2 == 0 else 4
        values.append(weight * math.exp(log_density + (moment + 1) * log_time))
    return math.fsum(values) * width / 3


class DriftRegimeTests(unittest.TestCase):
    def test_nonzero_drift_hit_probability_and_mean_against_density(self):
        rows = []
        for mu in (-0.3, 0.3):
            report = long_run_regime(
                mu=mu, sigma=0.45, distance=0.7, reset_distance=0.4, refractory=0.2
            )
            mass = density_moment(mu, 0.7, 0.45, 0)
            conditional_mean = density_moment(mu, 0.7, 0.45, 1) / mass
            self.assertAlmostEqual(
                mass, report["eventual_hit_probability"], delta=2e-12
            )
            self.assertAlmostEqual(conditional_mean, 0.7 / abs(mu), delta=2e-11)
            if mu < 0:
                self.assertAlmostEqual(
                    conditional_mean, report["mean_first_hit_time"], delta=2e-11
                )
            else:
                self.assertIsNone(report["mean_first_hit_time"])
                self.assertIn("mean_first_hit_time", report["infinite_quantities"])
            rows.append(
                dict(mu=mu, integrated_mass=mass, conditional_mean=conditional_mean)
            )
        self.numerical_evidence = {"independent_density_checks": rows}

    def test_three_regimes_agree_with_long_finite_horizon_event_counts(self):
        rows = []
        for mu in (-0.4, 0.0, 0.4):
            report = long_run_regime(
                mu=mu, sigma=0.4, distance=0.3, reset_distance=0.3, refractory=0.2
            )
            params = PhysicalParameters(
                *(
                    torch.tensor(v, dtype=torch.float64)
                    for v in (0.0, mu, 0.4, math.exp(0.3), 0.15)
                )
            )
            early = float(
                finite_renewal_value(
                    0.3, params, horizon=20.0, refractory=0.2
                ).expected_events
            )
            late = float(
                finite_renewal_value(
                    0.3, params, horizon=80.0, refractory=0.2
                ).expected_events
            )
            if mu < 0:
                self.assertAlmostEqual(
                    late / 80, report["asymptotic_event_rate"], delta=0.01
                )
            elif mu == 0:
                self.assertGreater(late, early)
                self.assertLess(late / 80, early / 20)
                truncated_mean = [
                    density_moment(0, 0.3, 0.4, 1, math.log(t)) for t in (100, 10000)
                ]
                self.assertGreater(truncated_mean[1], 9 * truncated_mean[0])
            else:
                self.assertAlmostEqual(
                    late, report["expected_total_events"], delta=2e-10
                )
                self.assertLessEqual(early, report["expected_total_events"] + 2e-14)
            rows.append(
                dict(
                    mu=mu,
                    regime=report["regime"],
                    count_20=early,
                    count_80=late,
                    asymptotic_rate=report["asymptotic_event_rate"],
                )
            )
        self.numerical_evidence = {"finite_horizon_vs_regime": rows}

    def test_near_zero_drift_is_not_silently_classified_as_zero(self):
        negative, zero, positive = [
            long_run_regime(
                mu=mu, sigma=0.4, distance=0.3, reset_distance=0.3, refractory=0.2
            )
            for mu in (-1e-14, 0.0, 1e-14)
        ]
        self.assertGreater(negative["asymptotic_event_rate"], 0)
        self.assertIsNone(zero["expected_total_events"])
        self.assertTrue(math.isfinite(positive["expected_total_events"]))
        self.assertLess(positive["log_reset_hit_probability"], 0)
        self.assertGreater(positive["expected_total_events"], 1e12)
