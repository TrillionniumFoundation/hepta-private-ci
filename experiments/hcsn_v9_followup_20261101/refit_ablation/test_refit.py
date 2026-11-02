"""Numerical and independent-simulation checks for readout-refit assay."""

import ast
from pathlib import Path
import unittest

import numpy as np
from scipy.optimize import check_grad, minimize

from .campaign import dataset, objective, probabilities
from .renewal_numpy import Physics, renewal_counts, sample_counts
from .transforms import transform_counts


class RefitChecks(unittest.TestCase):
    def test_extracted_definitions_preserve_baseline_ast(self):
        root = Path(__file__).resolve().parents[2]
        paths = [(root / "hcsn_mechanism_content_v2/renewal.py", Path(__file__).with_name("renewal_numpy.py")),
                 (root / "hcsn_v8_execution_20261101/mechanisms/count_interventions.py", Path(__file__).with_name("transforms.py"))]
        for original, extracted in paths:
            original_tree = ast.parse(original.read_text())
            original_definitions = {n.name: ast.dump(n, include_attributes=False)
                                    for n in original_tree.body if isinstance(n, (ast.ClassDef, ast.FunctionDef))}
            for node in ast.parse(extracted.read_text()).body:
                if isinstance(node, (ast.ClassDef, ast.FunctionDef)):
                    self.assertEqual(ast.dump(node, include_attributes=False), original_definitions[node.name])

    def test_likelihood_gradient_matches_finite_difference(self):
        rng = np.random.default_rng(103)
        x = rng.normal(size=(12, 6))
        y = rng.integers(5, size=12)
        w = rng.normal(size=30) * .1
        error = check_grad(lambda v: objective(v, x, y, .01)[0],
                           lambda v: objective(v, x, y, .01)[1], w)
        self.assertLess(error, 1e-6)

    def test_independent_ig_generator_matches_count_probabilities(self):
        physics = Physics(-.8, .55, .45, .18)
        p, _ = renewal_counts(.15, 2.4, physics)
        counts = sample_counts(np.random.default_rng(923), physics, .15, 2.4, 20000)
        empirical = np.bincount(counts, minlength=32) / len(counts)
        tolerance = 5 * np.sqrt(np.maximum(p * (1-p), 1/len(counts)) / len(counts))
        self.assertTrue(np.all(np.abs(empirical-p) <= tolerance))
        self.assertGreater((counts >= 2).mean(), .3)

    def test_refitting_changes_weights_and_improves_training_objective(self):
        data = dataset(999, 128)
        x, y = data["X_mean_two_point"], data["labels"]
        initial = np.vstack([np.eye(5), np.zeros((1, 5))]).ravel()
        before = objective(initial, x, y, .001)[0]
        result = minimize(objective, initial, args=(x, y, .001), jac=True,
                          method="L-BFGS-B", options={"maxiter": 120})
        self.assertLess(result.fun, before - .001)
        self.assertGreater(float(np.linalg.norm(result.x-initial)), .01)
        p = probabilities(result.x, x)
        np.testing.assert_allclose(p.sum(1), 1, atol=1e-12)

    def test_mean_preserving_shape_remains_a_different_content_feature(self):
        p, _ = renewal_counts(.15, 2.4, Physics(-.8, .55, .45, .18))
        q = transform_counts(p, "mean_two_point")
        self.assertAlmostEqual(p @ np.arange(32), q @ np.arange(32), places=12)
        self.assertGreater(float(np.abs(p-q).sum()), .1)


if __name__ == "__main__":
    unittest.main()
