import unittest

import numpy as np

from experiments.first_passage_adaptive.training import fit_joint, make_contexts, objective


class JointTrainingTests(unittest.TestCase):
    def test_task_gradient_matches_full_objective_perturbation(self):
        contexts = make_contexts(81,count=4)
        parameters = np.array([.2,.8,.4])
        _,gradient,_ = objective(parameters,contexts)
        reference = []
        for index in range(3):
            delta = np.eye(3)[index]*1e-5
            plus = objective(parameters+delta,contexts,derivatives=0)[0]
            minus = objective(parameters-delta,contexts,derivatives=0)[0]
            reference.append((plus-minus)/2e-5)
        np.testing.assert_allclose(gradient,reference,atol=2e-8,rtol=2e-7)

    def test_all_dynamics_parameters_actually_update_without_readout(self):
        result = fit_joint(make_contexts(81,count=4),steps=5)
        self.assertTrue(np.all(np.abs(result["physical_delta"]) > 1e-5))
        self.assertLess(result["train_final"],result["train_initial"])
        self.assertEqual(len(result["history"]),5)
        self.assertTrue(all(row["loss_after"] <= row["loss_before"]+1e-12
                            for row in result["history"]))


if __name__ == "__main__":
    unittest.main()
