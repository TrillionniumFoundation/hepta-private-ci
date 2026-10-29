import unittest

import numpy as np

from experiments.first_passage_adaptive.meta import (
    exact_inner_baseline, fit_meta, make_meta_examples, meta_objective,
)


class ExactOuterGradientTests(unittest.TestCase):
    def test_full_training_tree_gradient_matches_rerun_finite_difference(self):
        inner,outer = make_meta_examples(83),make_meta_examples(89)
        shape = np.array([.4,.9,.45])
        result = meta_objective(shape,inner,outer,inner_steps=3)
        reference = []
        for index in range(3):
            delta = np.eye(3)[index]*2e-5
            plus = meta_objective(shape+delta,inner,outer,inner_steps=3,derivatives=False).objective
            minus = meta_objective(shape-delta,inner,outer,inner_steps=3,derivatives=False).objective
            reference.append((plus-minus)/4e-5)
        np.testing.assert_allclose(result.hypergradient,reference,atol=1e-8,rtol=2e-6)
        self.assertGreater(float(np.linalg.norm(result.score_component)),1e-7)
        self.assertGreater(float(np.linalg.norm(result.pathwise_component-reference)),1e-7)
        self.assertAlmostEqual(result.probability_mass,1.0,places=12)
        np.testing.assert_allclose(result.probability_mass_gradient,np.zeros(3),atol=1e-12)

    def test_shapes_are_trained_through_real_inner_updates(self):
        inner,outer = make_meta_examples(83),make_meta_examples(89)
        result = fit_meta(inner,outer,steps=2,inner_steps=2)
        self.assertTrue(np.all(np.abs(result["shape_delta"]) > 1e-8))
        self.assertLess(result["outer_train_final"],result["outer_train_initial"])
        unmoved = meta_objective([.4,.9,.45],inner,outer,inner_steps=0)
        np.testing.assert_array_equal(unmoved.hypergradient,np.zeros(3))

    def test_exact_baseline_uses_same_hard_expected_loss_contract(self):
        inner,outer = make_meta_examples(83),make_meta_examples(89)
        exact = exact_inner_baseline(inner,outer,inner_steps=0)
        sg = meta_objective([.4,.9,.45],inner,outer,inner_steps=0)
        self.assertAlmostEqual(exact["objective"],sg.objective,places=14)
        trained = exact_inner_baseline(inner,outer,inner_steps=3)
        self.assertNotEqual(trained["final_weight"],0.)


if __name__ == "__main__":
    unittest.main()
