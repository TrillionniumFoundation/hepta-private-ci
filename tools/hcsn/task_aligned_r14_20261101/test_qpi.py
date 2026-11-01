"""Independent mass recursion, actual owner sampling and Q^pi derivatives."""

import copy
import unittest

import numpy as np
from scipy.linalg import expm
from scipy.special import softmax

from ..unified_cell_r12_20261031.task_value import ExactBeliefDP
from .models import task_loss
from .qpi import cost_sensitive_weights, encode, loss_and_probability_gradient, monte_carlo_qpi, policy_alpha


class TinyWorld:
    """A separate four-state test owner with state-dependent READ fees."""

    def __init__(self, fault_rate=.17, reset_cost=.07):
        self.Q = np.array([[-.20-fault_rate, .20, fault_rate, 0.],
                           [.20, -.20-fault_rate, 0., fault_rate],
                           [0., 0., -.20, .20], [0., 0., .20, -.20]])
        self.R = np.eye(4)[[0, 1, 0, 1]]
        self.E = np.full((4, 8), .01)
        self.E[:2, :2] = [[.80, .05], [.05, .80]]
        self.E[:2, 7] = .10
        self.E[2:, :2], self.E[2:, 7] = .15, .65
        self.reward = (np.arange(4)[:, None] % 2 == np.arange(2)).astype(float)
        self.read_cost = np.array([.03, .05, .07, .09])
        self.reset_cost, self.latency_price = reset_cost, .02
        self.prior = np.array([.20, .10, .35, .35])
        self._cache = {}

    def transition(self, dt):
        if dt not in self._cache:
            self._cache[dt] = expm(self.Q * dt)
        return self._cache[dt]

    def sample_step(self, state, action, dt, rng):
        if action.startswith("STOP"):
            return state, None, self.reward[state, int(action[-1])], 0.
        if action == "RESET":
            state = int(rng.choice(4, p=self.R[state]))
        state = int(rng.choice(4, p=self.transition(dt)[state]))
        token = int(rng.choice(8, p=self.E[state])) if action == "READ" else None
        fee = self.latency_price * dt
        fee += self.read_cost[state] if action == "READ" else self.reset_cost if action == "RESET" else 0.
        return state, token, 0., fee


class MemoryActor:
    """A deliberately imperfect actor with real history beyond its output."""

    def __init__(self, model):
        self.cell = model
        self.current = np.array([.35, .15, .20, .30])
        self.hidden = np.array([.3, -.1])

    def step(self, x):
        if x[10]:
            self.current = self.current @ self.cell.R
        self.current = self.current @ self.cell.transition(x[9])
        self.hidden[1] += x[9]
        if x[8]:
            token = int(np.argmax(x[:8]))
            self.current *= self.cell.E[:, token]
            self.hidden[0] += token + 1
        # This distortion is part of the actual deployed recurrent policy.
        self.current *= np.exp(.07 * self.hidden[0] * (2 * (np.arange(4) % 2) - 1))
        self.current /= self.current.sum()
        return self.current.copy()


def mass_return(world, actor, planner, mass, times, reads, action):
    """Independent forward unnormalized-mass recursion for one action."""
    if action.startswith("STOP"):
        return float(mass @ world.reward[:, int(action[-1])])
    dt, rest = times[0], times[1:]
    successor = mass @ world.R if action == "RESET" else mass.copy()
    successor = successor @ world.transition(dt)
    result = -float(mass.sum()) * (world.latency_price * dt + (world.reset_cost if action == "RESET" else 0.))
    if action == "READ":
        result -= float(successor @ world.read_cost)
        tokens = range(8)
    else:
        tokens = (-1,)
    for token in tokens:
        branch_mass = successor * world.E[:, token] if token >= 0 else successor
        branch = copy.deepcopy(actor)
        branch.step(encode(token, dt, action == "RESET"))
        remaining_reads = reads - int(action == "READ")
        choice = planner.choose(branch.current, rest, remaining_reads)
        result += mass_return(world, branch, planner, branch_mass, rest, remaining_reads, choice)
    return result


class QPiTests(unittest.TestCase):
    def setUp(self):
        self.world = TinyWorld()
        fitted = TinyWorld(fault_rate=.43, reset_cost=.25)
        self.actor = MemoryActor(fitted)
        self.planner = ExactBeliefDP(fitted, reset_cost=fitted.reset_cost,
                                    latency_price=fitted.latency_price)

    def test_independent_actual_world_hidden_policy_and_fees(self):
        before_current, before_hidden = self.actor.current.copy(), self.actor.hidden.copy()
        before_cache_keys = set(self.actor.cell._cache)
        times, reads = (.15, .40), 1
        vectors = policy_alpha(self.world, self.actor, self.planner, times, reads)
        for action, vector in vectors.items():
            expected = mass_return(self.world, self.actor, self.planner,
                                   self.world.prior, times, reads, action)
            self.assertAlmostEqual(self.world.prior @ vector, expected, places=13)
        np.testing.assert_array_equal(self.actor.current, before_current)
        np.testing.assert_array_equal(self.actor.hidden, before_hidden)
        self.assertEqual(set(self.actor.cell._cache), before_cache_keys)
        fitted_vectors = policy_alpha(self.actor.cell, self.actor, self.planner, times, reads)
        self.assertGreater(np.max(np.abs(vectors["RESET"] - fitted_vectors["RESET"])), .1)

    def test_actual_owner_monte_carlo_agrees_with_expectation(self):
        times, reads = (.25,), 1
        vectors = policy_alpha(self.world, self.actor, self.planner, times, reads)
        samples = monte_carlo_qpi(self.world, self.actor, self.planner, self.world.prior,
                                 times, reads, draws=4096, seed=1721)
        for action, record in samples.items():
            error = abs(record["mean"] - self.world.prior @ vectors[action])
            self.assertLess(error, 5 * record["standard_error"] + .002)
            self.assertAlmostEqual(record["mean"], record["mean_reward"] - record["mean_fee"], places=13)
        self.assertAlmostEqual(samples["RESET"]["mean_fee"], self.world.reset_cost + .25 * self.world.latency_price, places=13)
        self.assertGreater(samples["READ"]["mean_fee"], samples["WAIT"]["mean_fee"])

    def test_q_loss_derivative_on_probability_simplex(self):
        rng = np.random.default_rng(173)
        probabilities = rng.dirichlet(np.ones(4), size=(2, 3))
        teacher = rng.dirichlet(np.ones(4), size=(2, 3))
        vectors = rng.normal(size=(2, 3, 5, 4))
        mask = np.array([True, True, False, True, True])
        loss, gradient = loss_and_probability_gradient(probabilities, teacher, vectors, .7, mask)
        self.assertGreater(loss, 0.)
        direction = rng.normal(size=probabilities.shape)
        direction -= direction.mean(axis=-1, keepdims=True)
        epsilon = 1e-6
        plus = loss_and_probability_gradient(probabilities + epsilon * direction, teacher, vectors, .7, mask)[0]
        minus = loss_and_probability_gradient(probabilities - epsilon * direction, teacher, vectors, .7, mask)[0]
        self.assertAlmostEqual((plus - minus) / (2 * epsilon), float(np.sum(gradient * direction)), places=9)
        shared = vectors[0, 0]
        broadcast = loss_and_probability_gradient(probabilities, teacher, shared)[0]
        tiled = loss_and_probability_gradient(probabilities, teacher, np.broadcast_to(shared, vectors.shape))[0]
        self.assertAlmostEqual(broadcast, tiled, places=13)

    def test_public_encoder_cannot_reveal_a_reset_observation(self):
        with self.assertRaises(ValueError):
            encode(7, .15, reset=True)
        x = encode(7, .15)
        np.testing.assert_array_equal(x, np.array([0., 0., 0., 0., 0., 0., 0., 1., 1., .15, 0.]))
        vectors = policy_alpha(self.world, self.actor, self.planner, (), 0)
        self.assertEqual(set(vectors), {"STOP0", "STOP1"})

    def test_known_fee_offsets_change_weighted_but_not_plain_parameter_gradient(self):
        p = softmax(np.array([.3, -.7, .4, .1]))[None, None, :]
        teacher = np.array([.1, .4, .3, .2])[None, None, :]
        alpha = np.array([[1., 0., 1., 0.], [0., 1., 0., 1.],
                          [.5, .3, .8, .2], [.8, .4, .3, .7], [.2, .9, .4, .6]])[None, None]
        fees = np.array([0., 0., 0., .8, .1])
        shifted = alpha - fees[None, None, :, None]
        legal = np.ones((1, 1, 5), dtype=bool)

        def parameter_gradient(vectors, weights):
            loss, score = task_loss(p, teacher, vectors, weights, ce_weight=0., q_weight=1.)
            return loss, p * (score - np.sum(p * score, axis=-1, keepdims=True))

        plain, plain_gradient = parameter_gradient(alpha, legal)
        adjusted, adjusted_gradient = parameter_gradient(shifted, legal)
        self.assertAlmostEqual(plain, adjusted, places=14)
        np.testing.assert_allclose(plain_gradient, adjusted_gradient, rtol=0, atol=2e-16)
        before_q = np.einsum("...s,...as->...a", teacher, alpha)
        after_q = np.einsum("...s,...as->...a", teacher, shifted)
        before_weights = cost_sensitive_weights(before_q, legal)
        after_weights = cost_sensitive_weights(after_q, legal)
        before_gradient = parameter_gradient(alpha, before_weights)[1]
        after_gradient = parameter_gradient(shifted, after_weights)[1]
        self.assertGreater(np.linalg.norm(before_gradient - after_gradient), 1e-4)
        self.assertLess(after_weights[0, 0, 3], before_weights[0, 0, 3])
        np.testing.assert_allclose(before_weights.sum(-1), legal.sum(-1), rtol=0, atol=1e-14)
        np.testing.assert_allclose(after_weights.sum(-1), legal.sum(-1), rtol=0, atol=1e-14)

    def test_weight_temperature_limits_and_read_mask(self):
        target_q = np.array([-2., .1, .7, 5., .3])
        legal = np.array([True, True, True, False, True])
        cold = cost_sensitive_weights(target_q, legal, temperature=1e-6)
        hot = cost_sensitive_weights(target_q, legal, temperature=1e10)
        np.testing.assert_allclose(cold, [0., 0., 4., 0., 0.], rtol=0, atol=1e-14)
        np.testing.assert_allclose(hot, legal.astype(float), rtol=0, atol=1e-9)
        self.assertEqual(cost_sensitive_weights(target_q, legal)[3], 0.)
        for temperature in (0., -1., np.nan, np.inf):
            with self.subTest(temperature=temperature), self.assertRaises(ValueError):
                cost_sensitive_weights(target_q, legal, temperature)
        for targets, mask in (([0., np.nan], [True, False]),
                              ([0., 1.], [True, np.nan]),
                              ([0., 1.], [False, False])):
            with self.assertRaises(ValueError):
                cost_sensitive_weights(targets, mask)


if __name__ == "__main__":
    unittest.main()
