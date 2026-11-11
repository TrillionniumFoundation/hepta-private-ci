"""Independent renewal expression, age transport and actual schedule oracle."""

import math
import unittest
from itertools import repeat

import mpmath as mp
import numpy as np
import torch

from qualification.hcsn_differentiable.contract import GridSpec, PhysicalParameters
from qualification.hcsn_differentiable.finite_renewal import finite_renewal_value
from qualification.hcsn_differentiable.operator import (
    DifferentiableDistributionOperator,
)
from qualification.hcsn_differentiable.training_domain_finite import (
    _error_diagnostics,
    _fixed_gap_schedule,
    _point,
    audit_finite_schedule,
)


class FiniteDomainTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        self.values = [0.0, -0.12, 0.35, math.exp(0.32), 0.15]
        self.params = PhysicalParameters(
            *(torch.tensor(v, dtype=torch.float64) for v in self.values)
        )

    def test_eighty_digit_point_reference_matches_differentiable_renewal(self):
        with mp.workdps(80):
            for horizon in (0.037, 0.2, 1.3, 10.0):
                reference = _point(0.15, horizon, self.values, 0.2, 0.4, 1.0, 0.2)
                actual = finite_renewal_value(
                    0.15, self.params, horizon=horizon, refractory=0.2
                )
                for a, b in zip(
                    (
                        actual.value,
                        actual.expected_events,
                        actual.discounted_events,
                        actual.active_probability,
                    ),
                    reference,
                ):
                    self.assertLess(abs(float(a) - float(b)), 2e-12)

    def test_zero_horizon_pays_active_terminal_once(self):
        grid = GridSpec(active_cells=8, phase_cells=4, refractory=0.2)
        probability = torch.zeros(grid.state_count, dtype=torch.float64)
        probability[2], probability[-1] = 0.6, 0.4
        report = audit_finite_schedule(
            probability, grid, self.params, [0.0, 0.0], reference_order=8
        )
        self.assertEqual(report["status"], "passed_fixture")
        torch.testing.assert_close(
            torch.tensor(report["reference"]), torch.tensor([0.12, 0.0, 0.0, 0.6])
        )
        custom = DifferentiableDistributionOperator(grid, terminal_reward=0.7)
        report = audit_finite_schedule(
            probability,
            grid,
            self.params,
            [0.0, 0.0],
            reference_order=8,
            operator=custom,
        )
        torch.testing.assert_close(
            torch.tensor(report["reference"]), torch.tensor([0.42, 0.0, 0.0, 0.6])
        )
        self.assertEqual(report["inputs"]["operator"], custom.configuration())
        with self.assertRaisesRegex(ValueError, "matching regenerative operator"):
            audit_finite_schedule(
                probability,
                grid,
                self.params,
                [0.0],
                operator=DifferentiableDistributionOperator(grid, reset_enabled=False),
            )

    def test_reference_uses_total_time_and_retained_age_not_step_count(self):
        grid = GridSpec(active_cells=8, phase_cells=4, refractory=0.2)
        probability = torch.zeros(grid.state_count, dtype=torch.float64)
        probability[1], probability[-1] = 0.4, 0.6
        a = audit_finite_schedule(
            probability, grid, self.params, [0.05, 0.2], reference_order=16
        )
        b = audit_finite_schedule(
            probability, grid, self.params, [0.01, 0.04, 0.1, 0.1], reference_order=16
        )
        self.assertLess(
            max(abs(x - y) for x, y in zip(a["reference"], b["reference"])), 2e-12
        )
        self.assertLess(a["reference_refinement_delta"], 2e-8)
        self.assertLess(b["mass_residual"], 5e-11)
        self.assertNotEqual(a["inputs_sha256"], b["inputs_sha256"])
        self.assertEqual(a["inputs"]["durations"], [0.05, 0.2])
        self.assertEqual(a["inputs"]["probability"], probability.tolist())
        self.numerical_evidence = {"first_schedule": a, "second_schedule": b}


    def test_fixed_gap_admission_rejects_tensor_string_bool_and_infinite_stream(self):
        self.assertEqual(_fixed_gap_schedule((0.0, np.float64(0.05))), (0.0, 0.05))
        for schedule in (
            (False,),
            ("0.01",),
            (torch.tensor(0.01, dtype=torch.float64),),
            (torch.tensor(0.01, dtype=torch.float64, requires_grad=True),),
        ):
            with self.subTest(schedule=str(schedule)):
                with self.assertRaisesRegex(ValueError, "fixed real scalars"):
                    _fixed_gap_schedule(schedule)
        with self.assertRaisesRegex(ValueError, "finite"):
            _fixed_gap_schedule((float("nan"),))
        with self.assertRaisesRegex(ValueError, "1 to 4096"):
            _fixed_gap_schedule(repeat(0.01))
        grid = GridSpec(active_cells=8, phase_cells=4, refractory=0.2)
        probability = torch.zeros(grid.state_count, dtype=torch.float64)
        probability[1] = 1.0
        with self.assertRaisesRegex(ValueError, "fixed real scalars"):
            audit_finite_schedule(
                probability,
                grid,
                self.params,
                (torch.tensor(0.05, dtype=torch.float64, requires_grad=True),),
                reference_order=8,
            )

    def test_relative_diagnostic_exposes_rare_count_and_undefined_zero(self):
        projected = np.array([0.00052, 0.2, 0.0])
        reference = np.array([0.0005, 0.0, 0.0])
        absolute, scaled, relative = _error_diagnostics(projected, reference)
        self.assertLess(float(scaled[0]), 0.01)
        self.assertAlmostEqual(relative[0], 0.04, places=12)
        self.assertIsNone(relative[1])
        self.assertEqual(relative[2], 0.0)
        self.assertAlmostEqual(float(absolute[0]), 0.00002, places=12)


if __name__ == "__main__":
    unittest.main()
