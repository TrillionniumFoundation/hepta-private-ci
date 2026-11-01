"""Independent short-path checks for the R15 finite policy ceiling diagnostic."""

import copy
import itertools
import unittest

import numpy as np
from scipy.linalg import expm

from .attainability import audit_pair, exact_episode, oracle_table, schedule_support
from ..task_aligned_r14_20261101.qpi import encode, policy_alpha
from ..unified_cell_r12_20261031.task_value import ExactBeliefDP


class ToyWorld:
    def __init__(self, moving=False):
        self.Q = np.array([[-.2, .2], [.1, -.1]]) if moving else np.zeros((2, 2))
        self.R = np.array([[.7, .3], [.9, .1]])
        self.prior = np.array([.4, .6])
        self.E = np.zeros((2, 8))
        self.E[:, :2] = np.array([[.9, .1], [.2, .8]])
        self.reward = np.eye(2)
        self.read_cost = np.array([.03, .07])
        self.reset_cost, self.latency_price = .025, .01
        self.state_count = 2

    def transition(self, dt):
        return expm(self.Q * dt)


class ToyActor:
    def __init__(self, world):
        self.world, self.current, self.history = world, None, []

    def start(self):
        self.current = self.world.prior.copy()
        self.history = []
        return self.current.copy()

    def step(self, x):
        self.history.append(x.copy())
        if x[10]:
            self.current = self.current @ self.world.R
        self.current = self.current @ self.world.transition(x[9])
        if x[8]:
            self.current *= self.world.E[:, x[:8].argmax()]
            self.current /= self.current.sum()
        return self.current.copy()


class ScriptPlanner(ExactBeliefDP):
    """An observable-policy fixture that necessarily exercises reset and wait."""

    def choose(self, belief, schedule, budget=2):
        if len(schedule) == 3:
            return "RESET"
        if len(schedule) == 2:
            return "WAIT"
        if schedule:
            return "READ"
        return "STOP" + str(int(np.argmax(belief)))


def brute_latent_script(world, schedule):
    """Direct sum over initial/reset/three successor states and observed symbols.

    This uses neither the diagnostic recursion nor the inherited alpha vectors.
    It checks endpoint fees, reset-before-transition order and the entire time.
    """
    matrices = [world.transition(dt) for dt in schedule]
    answer = np.zeros(3)
    for initial, reset, one, two, three, token in itertools.product(range(2), repeat=6):
        probability = (world.prior[initial] * world.R[initial, reset] * matrices[0][reset, one]
                       * matrices[1][one, two] * matrices[2][two, three] * world.E[three, token])
        posterior = world.prior @ world.R @ matrices[0] @ matrices[1] @ matrices[2]
        posterior *= world.E[:, token]
        prediction = int(np.argmax(posterior))
        reward = world.reward[three, prediction]
        fee = world.reset_cost + world.latency_price * sum(schedule) + world.read_cost[three]
        answer += probability * np.array([reward - fee, reward, fee])
    return answer


class AttainabilityTests(unittest.TestCase):
    def test_forward_mass_matches_direct_latent_paths_and_backward_alpha(self):
        world = ToyWorld(moving=True)
        actor = ToyActor(world)
        planner = ScriptPlanner(world, reset_cost=world.reset_cost, latency_price=world.latency_price)
        schedule = (.15, .45, 1.05)
        result = exact_episode(world, actor, planner, schedule)
        np.testing.assert_allclose([result[k] for k in ("utility", "reward", "fee")],
                                   brute_latent_script(world, schedule), rtol=0, atol=1e-13)
        self.assertEqual(result["first_action"], "RESET")
        # These are floating expectations after matrix products, not integer counts.
        np.testing.assert_allclose([result["reads"], result["resets"]], [1., 1.],
                                   rtol=0, atol=16 * np.finfo(np.float64).eps)
        self.assertAlmostEqual(result["elapsed"], sum(schedule), places=13)
        self.assertIsNone(actor.current)
        self.assertEqual(actor.history, [])
        actor.start()
        backward = policy_alpha(world, actor, planner, schedule, 2)
        self.assertAlmostEqual(result["utility"], world.prior @ backward["RESET"], places=13)

    def test_complete_schedule_distribution_and_oracle_equality(self):
        world = ToyWorld()
        actor = ToyActor(world)
        planner = ExactBeliefDP(world, reset_cost=world.reset_cost, latency_price=world.latency_price)
        report = audit_pair(world, actor, actor, planner, (.15, .45, 1.05))
        self.assertEqual(report["schedule_count"], 27)
        self.assertEqual(len(set(tuple(r["schedule"]) for r in report["schedules"])), 27)
        self.assertAlmostEqual(sum(r["probability"] for r in report["schedules"]), 1.)
        self.assertEqual(report["D_minus_B"], 0.)
        for arm in ("B", "D"):
            self.assertAlmostEqual(report["arms"][arm]["oracle_headroom"], 0., places=12)
        self.assertLess(report["max_forward_backward_error"], 1e-12)

    def test_misspecified_actor_is_evaluated_in_true_world(self):
        world, fitted = ToyWorld(), ToyWorld()
        fitted.E = fitted.E[::-1].copy()
        actor = ToyActor(fitted)
        planner = ExactBeliefDP(fitted, reset_cost=fitted.reset_cost, latency_price=fitted.latency_price)
        schedule = (.2,)
        result = exact_episode(world, actor, planner, schedule, first_action="READ")
        expected_reward = 0.
        for token in range(2):
            prediction = int(np.argmax(fitted.prior * fitted.E[:, token]))
            expected_reward += world.prior[prediction] * world.E[prediction, token]
        self.assertAlmostEqual(result["reward"], expected_reward)
        self.assertAlmostEqual(result["fee"], world.prior @ world.read_cost + .002)
        oracle = oracle_table(world, (.2,), horizon=1)[0]["upper_value"]
        self.assertGreater(oracle - result["utility"], .2)

    def test_all_forced_actions_preserve_actor_and_match_alpha(self):
        world = ToyWorld(moving=True)
        actor = ToyActor(world)
        planner = ExactBeliefDP(world, reset_cost=world.reset_cost, latency_price=world.latency_price)
        actor.start()
        before = copy.deepcopy(actor.current)
        alpha = policy_alpha(world, actor, planner, (.3, .7), 2)
        for action, vector in alpha.items():
            result = exact_episode(world, actor, planner, (.3, .7), first_action=action)
            self.assertAlmostEqual(result["utility"], world.prior @ vector, places=12)
        np.testing.assert_array_equal(actor.current, before)
        self.assertEqual(actor.history, [])

    def test_initial_stop_and_empty_schedule(self):
        world = ToyWorld()
        actor = ToyActor(world)
        planner = ExactBeliefDP(world, reset_cost=world.reset_cost, latency_price=world.latency_price)
        result = exact_episode(world, actor, planner, ())
        self.assertEqual({k: result[k] for k in ("utility", "reward", "fee", "elapsed", "reads", "resets", "terminal_mass")},
                         dict(utility=.6, reward=.6, fee=0., elapsed=0., reads=0., resets=0., terminal_mass=1.))
        self.assertEqual(schedule_support((.1,), 0), ((),))

    def test_invalid_or_mismatched_schedule_support_refuses(self):
        for durations, horizon in (((.1, .1), 3), ((float("nan"),), 3), ((0.,), 3), ((.1,), 4), ((.1,), True)):
            with self.subTest(durations=durations, horizon=horizon), self.assertRaises(ValueError):
                schedule_support(durations, horizon)
        world = ToyWorld()
        actor = ToyActor(world)
        planner = ExactBeliefDP(world)
        wrong = oracle_table(world, (.3,), horizon=1)
        with self.assertRaises(ValueError):
            audit_pair(world, actor, actor, planner, (.2,), horizon=1, oracle_rows=wrong)


if __name__ == "__main__":
    unittest.main()
