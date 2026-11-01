"""Behavioral/numerical checks for the actual joint training/execution cell.

Finite differences are an independent derivative audit only. The trainable
cell uses the full financial Dual kernel and expm Frechet derivatives.
"""

import itertools
import unittest

import numpy as np
from scipy.linalg import expm

from .cell import Cell, DEFAULT_THETA, PHYSICAL_LOWER, PHYSICAL_UPPER


def uniformization(generator, duration):
    """Independent positive Poisson expansion, split to avoid underflow."""
    size = generator.shape[0]
    rate = max(-np.diag(generator))
    if duration == 0 or rate == 0:
        return np.eye(size)
    pieces = max(1, int(np.ceil(rate * duration / 10)))
    mean = rate * duration / pieces
    jump = np.eye(size) + generator / rate
    weight = np.exp(-mean)
    total_weight = weight
    power = np.eye(size)
    transition = weight * power
    for k in range(1, 1000):
        power = power @ jump
        weight *= mean / k
        transition += weight * power
        total_weight += weight
        if k > mean and weight < 1e-17:
            break
    else:
        raise AssertionError("Independent uniformization failed to converge")
    if abs(total_weight - 1.) > 3e-15:
        raise AssertionError("Independent Poisson mass truncation")
    return np.linalg.matrix_power(transition, pieces)


class JointCellTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cell = Cell()

    def test_registered_box_corners_have_representable_reset_and_positive_rates(self):
        for theta in itertools.product(*zip(PHYSICAL_LOWER, PHYSICAL_UPPER)):
            with self.subTest(theta=theta):
                cell = Cell(theta)
                self.assertTrue(cell.centers[0] < cell.reset_log_distance < cell.centers[-1])
                self.assertGreater(min(cell.rates.values()), 0)
                np.testing.assert_allclose(cell.Q.sum(1), 0, atol=2e-13)
                np.testing.assert_allclose(cell.E.sum(1), 1, atol=2e-15)
                np.testing.assert_allclose(cell.dQ.sum(2), 0, atol=1e-11)
        with self.assertRaisesRegex(ValueError, "registered R12 box"):
            Cell([.1, .01, 1.])

    def test_physical_semigroup_and_independent_uniformization(self):
        cell = self.cell
        direct = cell.transition(2.1)
        split = cell.transition(.75) @ cell.transition(1.35)
        np.testing.assert_allclose(direct, split, rtol=3e-13, atol=2e-14)
        np.testing.assert_allclose(direct, uniformization(cell.Q, 2.1), rtol=5e-12, atol=2e-14)
        self.assertGreaterEqual(direct.min(), 0)
        np.testing.assert_allclose(direct.sum(1), 1, atol=3e-14)
        np.testing.assert_array_equal(cell.transition(0), np.eye(20))

    def test_recovery_restart_preserves_bit_and_completion_uses_retention(self):
        cell = self.cell
        p = np.zeros(20)
        p[19] = 1  # bit one, second recovery phase
        after_action = cell.reset(p)
        expected = np.zeros(20)
        expected[17] = 1  # bit one, restarted first recovery phase
        np.testing.assert_array_equal(after_action, expected)
        # The *generator* separates exit-bit retention from recovery residence.
        outgoing = cell.Q[19, :16]
        self.assertAlmostEqual(outgoing[1::2].sum() / outgoing.sum(), .875)
        self.assertAlmostEqual(outgoing[0::2].sum() / outgoing.sum(), .125)
        self.assertEqual(cell.Q[0, 16], cell.event_rate[0])
        self.assertEqual(cell.Q[0, 17], 0)

    def test_repeat_count_is_not_first_hit_and_killed_state_retains_uncertainty(self):
        cell = self.cell
        nohit, survival = cell.surviving_state(cell.prior, 2.1)
        first = cell.first_event_probability(cell.prior, 2.1)
        self.assertGreater(first, 0)
        self.assertLess(first, 1)
        self.assertAlmostEqual(first + survival, 1, places=13)
        conditional, mass = cell.surviving_state(cell.prior, 2.1, conditional=True)
        np.testing.assert_allclose(conditional * mass, nohit, atol=1e-15)
        self.assertAlmostEqual(conditional.sum(), 1, places=14)
        self.assertGreater(np.count_nonzero(conditional > 1e-5), 4)
        self.assertGreater(cell.expected_events(cell.prior, 20), 1)
        self.assertGreater(cell.expected_events(cell.prior, 2.1), first)
        tiny = cell.first_event_probability(cell.prior, 1e-8)
        self.assertGreater(tiny, 0)  # positive flux survives 1-S cancellation
        self.assertLess(tiny, 1e-20)

    def test_full_hx_prior_generator_reward_and_cost_gradients(self):
        cell = self.cell
        epsilon = 2e-6
        for j in range(3):
            step = np.zeros(3)
            step[j] = epsilon
            plus, minus = Cell(cell.theta + step), Cell(cell.theta - step)
            for name, derivative in (("Q", cell.dQ), ("prior", cell.dprior),
                                     ("reward", cell.dreward), ("read_cost", cell.dread_cost),
                                     ("financial_values", cell.dfinancial_values)):
                with self.subTest(parameter=j, quantity=name):
                    numeric = (getattr(plus, name) - getattr(minus, name)) / (2 * epsilon)
                    np.testing.assert_allclose(derivative[j], numeric, rtol=3e-5, atol=2e-7)
        self.assertGreater(np.linalg.norm(cell.dprior[1]), 1e-3)
        self.assertGreater(np.linalg.norm(cell.dreward[1]), 1e-5)
        self.assertGreater(np.linalg.norm(cell.dread_cost[2]), 1e-5)

    def test_transition_and_full_prefix_gradients(self):
        cell = self.cell
        transition, derivatives = cell.transition(.45, with_grad=True)
        epsilon = 2e-6
        for j in range(3):
            step = np.zeros(3)
            step[j] = epsilon
            numeric = (Cell(cell.theta + step).transition(.45) - Cell(cell.theta - step).transition(.45)) / (2 * epsilon)
            np.testing.assert_allclose(derivatives[j], numeric, rtol=3e-5, atol=2e-8)
        p = cell.prior @ transition
        gradient = np.zeros((15, 20))
        gradient[:3] = cell.dprior @ transition + np.einsum("i,kij->kj", cell.prior, derivatives)
        posterior, dp, evidence, dz = cell.observe_with_grad(p, gradient, 2)
        self.assertGreater(evidence, 0)
        np.testing.assert_allclose(dp.sum(1), 0, atol=3e-13)
        for parameter in (0, 1, 2, 3, 8, 9, 14):
            vector = cell.parameters()
            direction = np.zeros(15)
            direction[parameter] = epsilon
            results = []
            for v in (vector + direction, vector - direction):
                candidate = Cell(v[:3], v[3:])
                pp = candidate.predict(candidate.prior, .45)
                results.append(candidate.observe(pp, 2, return_likelihood=True))
            np.testing.assert_allclose(dp[parameter], (results[0][0] - results[1][0]) / (2 * epsilon),
                                       rtol=4e-5, atol=4e-8)
            self.assertAlmostEqual(dz[parameter], (results[0][1] - results[1][1]) / (2 * epsilon), places=7)
        np.testing.assert_allclose(posterior, cell.observe(p, 2), atol=1e-16)

    def test_missing_and_recovery_observations_are_different(self):
        cell = self.cell
        p = cell.predict(cell.prior, .45)
        np.testing.assert_array_equal(cell.observe(p, None), p)
        unavailable = cell.observe(p, 6)
        np.testing.assert_array_equal(unavailable[:16], np.zeros(16))
        self.assertAlmostEqual(unavailable[16:].sum(), 1)
        batch = np.stack((p, p))
        outputs = cell.observe(batch, np.array([2, 6]))
        np.testing.assert_allclose(outputs[0], cell.observe(p, 2))
        np.testing.assert_allclose(outputs[1], unavailable)
        with self.assertRaisesRegex(ValueError, "zero probability"):
            cell.observe(cell.prior, 6)
        with self.assertRaises(ValueError):
            cell.observe(p, 7)

    def test_event_derivative_and_count_composition(self):
        cell = self.cell
        value, derivative = cell.expected_events(cell.prior, .75, with_grad=True)
        epsilon = 2e-6
        for j in range(3):
            step = np.zeros(3)
            step[j] = epsilon
            # The API derivative holds the supplied belief fixed.
            numeric = (Cell(cell.theta + step).expected_events(cell.prior, .75)
                       - Cell(cell.theta - step).expected_events(cell.prior, .75)) / (2 * epsilon)
            self.assertAlmostEqual(derivative[j], numeric, places=6)
        composed = (cell.expected_events(cell.prior, .25)
                    + cell.expected_events(cell.predict(cell.prior, .25), .5))
        self.assertAlmostEqual(value, composed, places=13)


if __name__ == "__main__":
    unittest.main()
