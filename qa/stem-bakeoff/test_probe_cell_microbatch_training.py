import unittest

import numpy as np

from cell_microbatch_training import FrozenTrainingBank
from probe_cell_microbatch_training import compare_condition


class MicrobatchProbeTests(unittest.TestCase):
    def test_actual_paired_training_uses_distinct_states_and_matched_initializations(self):
        rng = np.random.default_rng(93)
        matrices = {"a": rng.normal(size=(8, 5)), "b": rng.normal(size=(8, 5))}
        sources = {task: [f"{task}-{i}" for i in range(8)] for task in matrices}
        bank = FrozenTrainingBank.build(matrices, sources, "a"*64)
        labels = {"a": np.arange(8) % 2, "b": 1-np.arange(8) % 2}
        for mode in ("linear", "gated", "residual"):
            result, states = compare_condition(bank, labels, 7, mode, steps=4, microbatch=3, first="batched")
            self.assertEqual(result["task_count"], 2)
            self.assertEqual(result["actual_total_private_optimizer_updates_both_methods"], 56)
            self.assertEqual(result["actual_total_example_updates_both_methods"], 448)
            for kind in ("scalar", "batched"):
                self.assertEqual(result["executions"][kind]["distinct_trained_private_states"], 7)
            for name in states["scalar"]:
                np.testing.assert_allclose(states["scalar"][name], states["batched"][name], atol=1e-10, rtol=1e-10)
            self.assertFalse(result["new_tasks_inferred_from_cell_count"])


if __name__ == "__main__":
    unittest.main()
