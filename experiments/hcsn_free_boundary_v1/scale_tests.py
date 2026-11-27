"""Focused instrumentation, bounded-state, and new-process continuation checks."""

from pathlib import Path
import tempfile
import unittest

import torch

from . import model as model_module
from . import oracle_torch
from .scale import measure_configuration, recovery_probe, streaming_probe


class ScalingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def test_solver_attribution_is_bounded_and_restores_functions(self):
        original_forward = model_module.free_boundary
        original_backward = oracle_torch._ImplicitBoundary.backward
        result = measure_configuration("free_dual", 2, 4, width=8, repeats=1)
        self.assertIs(model_module.free_boundary, original_forward)
        self.assertIs(oracle_torch._ImplicitBoundary.backward, original_backward)
        for phase in ("forward", "train_step"):
            record = result[phase]
            self.assertGreater(record["root_fraction_of_measured_cpu"], 0)
            self.assertLess(record["root_fraction_of_measured_cpu"], 1)
            self.assertEqual(record["repeats"][0]["root"]["forward_calls"], 1)
        self.assertEqual(result["train_step"]["repeats"][0]["root"]["backward_calls"], 1)
        baseline = measure_configuration("two_gates", 2, 4, width=8, repeats=1)
        self.assertEqual(baseline["train_step"]["root_fraction_of_measured_cpu"], 0)

    def test_stream_state_storage_does_not_retain_prefix(self):
        result = streaming_probe(width=8, depth=2, batch=2, length=40)
        self.assertTrue(result["passed"])
        self.assertEqual(len(result["samples"]), 2)
        for sample in result["samples"]:
            self.assertEqual(sample["tensor_elements"], 2 * (1 + 4 * 8 * 2))
            self.assertEqual(sample["unique_storage_bytes"], sample["tensor_bytes"])
            self.assertFalse(sample["retains_autograd_graph"])

    def test_numeric_state_recovers_in_new_process_with_live_refractory(self):
        with tempfile.TemporaryDirectory(prefix="hcsn_recovery_test_") as directory:
            result = recovery_probe(Path(directory) / "recovery", width=8,
                                     depth=1, batch=2, length=12, split_at=5)
            self.assertTrue(result["passed"])
            self.assertNotEqual(result["child"]["pid"], result["parent_pid"])
            self.assertGreater(result["mid_refractory_max"], 0)
            self.assertEqual(result["max_logit_error"], 0)
            self.assertEqual(max(result["final_state_max_errors"].values()), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
