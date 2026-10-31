"""Opt-in PyTorch-only synthetic regression tests; not a production CI gate."""

import importlib.util
import unittest

from hepta_sngr_learned_shadow import experiment


class LearnedContinuationShadowTests(unittest.TestCase):
    def test_preflight_bounds_do_not_require_torch(self):
        invalid = (
            {"seed": -1},
            {"train_steps": 0},
            {"train_steps": 2001},
            {"train_count": 127},
            {"test_count": 8193},
        )
        for kwargs in invalid:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                experiment(**kwargs)

    @unittest.skipUnless(importlib.util.find_spec("torch"), "optional PyTorch missing")
    def test_heldout_u_and_z_and_explicit_ood_boundary(self):
        for seed in (17, 19):
            with self.subTest(seed=seed):
                report = experiment(seed=seed)
                self.assertEqual(report["heldout_samples"], 512)
                self.assertEqual(report["model_parameters"], 1218)
                self.assertLess(report["test_value_mae"], 0.025)
                self.assertLess(report["test_z_mae"], 0.01)
                self.assertLess(report["test_value_mae"], report["linear_value_mae"])
                self.assertFalse(report["ood_supported"])
                self.assertIsNone(report["real_task_accuracy"])
                self.assertFalse(report["global_stochastic_fbsde_solved"])


if __name__ == "__main__":
    unittest.main()
