"""Focused mathematical regressions for conservative polynomial acceleration."""

import unittest

import torch

from . import validation


class ConservativeKernelTests(unittest.TestCase):
    def test_same_finite_generator_against_independent_dense_exponential(self):
        rows = validation.forward_audit()
        self.assertEqual(len(rows), 17)

    def test_all_nine_parameter_gradients_include_reset_and_value_continuation(self):
        report = validation.gradient_audit()
        self.assertEqual([row["parameter"] for row in report["parameters"]],
                         list(validation.NAMES))

    def test_batch_future_independence_and_piecewise_reset_knots(self):
        self.assertEqual(validation.batch_and_knots_audit()["unrelated_batch_future_gradient"], 0)

    def test_invalid_numerical_and_physical_contracts_are_rejected(self):
        self.assertEqual(len(validation.guard_audit()), 8)

    def test_instant_reset_self_events_and_nondefault_refractory_chain(self):
        self.assertEqual([row["refractory_stages"] for row in
                          validation.refractory_semantics_audit()], [0, 3])

    def test_float32_state_retains_probability_through_repeated_regeneration(self):
        report = validation.long_float32_audit(observations=128)
        self.assertEqual(report["observations"], 128)


if __name__ == "__main__":
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    unittest.main()
