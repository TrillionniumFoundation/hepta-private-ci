"""Hand probability checks, source equivalence and finite differences only."""

import unittest

import numpy as np

from content_joint.objectives import NativeObjective
from content_theory.categorical import (
    ALPHA, RHO, additive_population_optimum, binary_face_geometry,
    binary_population_stationary, logit_geometry, maximal_coupling,
    probability_geometry, softmax, symmetric_binary,
)


def frozen_source_kernel(arm, reward):
    """Build ONLY the frozen categorical cache; no model constructor/forward."""
    objective = object.__new__(NativeObjective)
    objective.arm, objective.ce_weight, objective.rho = arm, ALPHA, RHO
    objective.reward = np.asarray(reward)
    objective.shift = objective.reward.min(1) if arm == "N" else None
    objective.kernel = (np.exp(-RHO * (reward - objective.shift[:, None]))
                        if arm == "N" else None)
    return objective


class GeometryChecks(unittest.TestCase):
    def setUp(self):
        self.reward = .075 + .002 * ((np.arange(12)[:, None] + 3 * np.arange(12)[None, :]) % 7)
        np.fill_diagonal(self.reward, .999)
        self.z = np.linspace(-1., 1., 12)

    def test_matches_frozen_native_value_and_gradient(self):
        zs = np.stack((self.z, self.z[::-1], np.roll(self.z, 4)))
        probabilities = np.stack([softmax(z) for z in zs])
        labels = np.array([0, 4, 11])
        for arm in ("A", "N"):
            original = frozen_source_kernel(arm, self.reward)
            loss, gradient = original._policy_checked(probabilities, labels)
            values, directions = [], []
            for z, label in zip(zs, labels):
                eta = np.eye(12)[label]
                value, direction, _ = logit_geometry(z, eta, self.reward, arm)
                values.append(value)
                directions.append(direction)
            self.assertAlmostEqual(loss, float(np.mean(values)), places=13)
            np.testing.assert_allclose(gradient, np.asarray(directions) / 3, atol=2e-16, rtol=0)

    def test_label_average_is_outside_log_in_frozen_source(self):
        s = softmax(self.z)
        labels = np.array([0, 1])
        eta = np.zeros(12)
        eta[:2] = .5
        for arm in ("A", "N"):
            value, gradients = frozen_source_kernel(arm, self.reward)._policy_checked(np.stack((s, s)), labels)
            expected, gradient, _ = logit_geometry(self.z, eta, self.reward, arm)
            self.assertAlmostEqual(value, expected, places=13)
            np.testing.assert_allclose(gradients.sum(0), gradient, atol=2e-16, rtol=0)

    def test_logit_gradients_and_hessians_by_finite_difference(self):
        laws = (np.eye(12)[3], np.arange(1., 13.) / 78)
        for eta in laws:
            for arm in ("A", "N"):
                _, gradient, hessian = logit_geometry(self.z, eta, self.reward, arm)
                for index in range(12):
                    d = np.eye(12)[index] * 1e-5
                    plus, gp, _ = logit_geometry(self.z + d, eta, self.reward, arm)
                    minus, gm, _ = logit_geometry(self.z - d, eta, self.reward, arm)
                    self.assertAlmostEqual((plus - minus) / 2e-5, gradient[index], places=9)
                    np.testing.assert_allclose((gp - gm) / 2e-5, hessian[:, index], atol=2e-10, rtol=0)
                np.testing.assert_allclose(hessian @ np.ones(12), 0, atol=1e-14)

    def test_probability_tangent_gradient_and_hessian(self):
        s, eta = softmax(self.z), np.arange(1., 13.) / 78
        d = np.linspace(-.8, .8, 12)
        for arm in ("A", "N"):
            _, gradient, hessian = probability_geometry(s, eta, self.reward, arm)
            plus, gp, _ = probability_geometry(s + 1e-6 * d, eta, self.reward, arm)
            minus, gm, _ = probability_geometry(s - 1e-6 * d, eta, self.reward, arm)
            self.assertAlmostEqual((plus - minus) / 2e-6, gradient @ d, places=8)
            np.testing.assert_allclose((gp - gm) / 2e-6, hessian @ d, atol=1e-7, rtol=0)

    def test_known_label_improves_by_every_wrong_to_correct_transfer(self):
        s, y = softmax(self.z), 3
        for arm in ("A", "N"):
            _, gradient, _ = probability_geometry(s, np.eye(12)[y], self.reward, arm)
            for other in range(12):
                if other != y:
                    self.assertLess(gradient[y] - gradient[other], 0)

    def test_wrong_only_probability_curvature_differs(self):
        s, y = softmax(self.z), 3
        d = np.eye(12)[1] - np.eye(12)[2]
        _, _, ha = probability_geometry(s, np.eye(12)[y], self.reward, "A")
        _, _, hn = probability_geometry(s, np.eye(12)[y], self.reward, "N")
        self.assertEqual(float(d @ ha @ d), 0)
        self.assertLess(float(d @ hn @ d), 0)

    def test_A_and_N_can_both_be_nonconvex_in_logits(self):
        reward = np.array([[1., .1], [.1, 1.]])
        eta, p = np.array([1., 0.]), .1
        z = np.array([np.log(p / (1 - p)), 0.])
        for arm in ("A", "N"):
            self.assertLess(logit_geometry(z, eta, reward, arm)[2][0, 0], 0)

    def test_additive_population_optimum_KKT(self):
        eta = np.arange(1., 13.) / 78
        s, lam = additive_population_optimum(eta, self.reward)
        self.assertAlmostEqual(float(s.sum()), 1., places=13)
        _, gradient, hessian = probability_geometry(s, eta, self.reward, "A")
        np.testing.assert_allclose(gradient + lam, 0, atol=1e-14)
        self.assertGreater(float(np.linalg.eigvalsh(hessian).min()), 0)

    def test_binary_population_optima_and_opposite_directions(self):
        reward = np.array([[1., .1], [.1, 1.]])
        theorem = symmetric_binary(.9)
        self.assertEqual(len(theorem["N_optima"]), 2)
        self.assertLess(theorem["N_center_probability_curvature"], 0)
        self.assertAlmostEqual(binary_face_geometry(.5, reward, "N")[2], theorem["N_center_probability_curvature"], places=13)
        self.assertGreater(binary_face_geometry(.51, reward, "A")[1], 0)
        self.assertLess(binary_face_geometry(.51, reward, "N")[1], 0)
        for p in theorem["N_optima"]:
            loss, derivative, curvature = binary_face_geometry(p, reward, "N")
            self.assertAlmostEqual(derivative, 0., places=12)
            self.assertGreater(curvature, 0)
            self.assertLess(loss, binary_face_geometry(.5, reward, "N")[0])
            self.assertGreater(binary_face_geometry(p, reward, "A")[0], binary_face_geometry(.5, reward, "A")[0])
            self.assertAlmostEqual(.5 * p + .5 * (1 - p), .5)

    def test_cubic_returns_all_binary_stationary_points(self):
        reward = np.array([[1., .1], [.1001, .9999]])
        result = binary_population_stationary(reward)
        self.assertEqual([r["kind"] for r in result["N_stationary"]], ["minimum", "maximum", "minimum"])
        self.assertTrue(all(abs(row["gradient"]) < 1e-10 for row in result["N_stationary"]))
        self.assertAlmostEqual(binary_face_geometry(result["A_optimum"], reward, "A")[1], 0, places=12)

    def test_pooling_labels_inside_log_would_erase_the_mechanism(self):
        reward = np.array([[1., .1], [.1, 1.]])
        kernel = np.exp(-RHO * reward)
        pooled, correct = [], []
        for p in (.28, .5):
            normalizers = kernel @ np.array([p, 1 - p])
            pooled.append(float(-np.log(normalizers.mean()) / RHO))
            correct.append(float(-np.log(normalizers).mean() / RHO))
        self.assertAlmostEqual(pooled[0], pooled[1], places=14)
        self.assertGreater(correct[0], correct[1])

    def test_maximal_coupling_preserves_marginals_and_has_no_sampler(self):
        p = np.arange(1., 13.) / 78
        for q in (p, p[::-1], np.roll(p, 3)):
            joint = maximal_coupling(p, q)
            np.testing.assert_allclose(joint.sum(1), p, atol=1e-15)
            np.testing.assert_allclose(joint.sum(0), q, atol=1e-15)
            np.testing.assert_allclose(joint.diagonal(), np.minimum(p, q), atol=1e-15)
            self.assertAlmostEqual(float(joint.trace()), float(np.minimum(p, q).sum()))
        np.testing.assert_array_equal(maximal_coupling(np.eye(12)[0], np.eye(12)[1]),
                                      np.outer(np.eye(12)[0], np.eye(12)[1]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
