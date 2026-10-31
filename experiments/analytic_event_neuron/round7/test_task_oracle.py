"""Independent finite enumeration checks, including joint evidence and guards."""

from dataclasses import replace
import itertools
import json
import unittest

import numpy as np

from . import oracle, task


def fixtures(parameters):
    """Enumerate the complete generative distribution independently of the DP."""
    p = parameters
    for truth in (-1, 1):
        for ordinary in itertools.product((-1, 1), repeat=p.ordinary_count):
            for delayed, corrupt in itertools.product((-1, 1), (False, True)):
                probability = p.prior_probability if truth == 1 else 1 - p.prior_probability
                for vote in ordinary:
                    probability *= p.ordinary_reliability if vote == truth else 1 - p.ordinary_reliability
                probability *= p.delayed_reliability if delayed == truth else 1 - p.delayed_reliability
                probability *= p.corruption_probability if corrupt else 1 - p.corruption_probability
                if probability:
                    yield task.Episode(-1, p, truth, ordinary, delayed, corrupt), probability


def rollout(episode, first_action, *, myopic=False, state=None):
    state = state or task.initial_state(episode)
    result = task.step(state, first_action, episode)
    reward = result.reward
    while not result.done:
        action = "STOP" if myopic else oracle.best_action(result.state)
        result = task.step(result.state, action, episode)
        reward += result.reward
    return reward


class TaskOracleTests(unittest.TestCase):
    def test_exact_dp_and_myopic_equal_all_latent_outcome_rollouts(self):
        domains = (
            task.TaskParameters(),
            task.TaskParameters(horizon=2, budget=2),
            task.TaskParameters(horizon=4, budget=1, corruption_probability=1),
            task.TaskParameters(horizon=5, budget=4, ordinary_reliability=0.61,
                                delayed_reliability=0.82, prior_probability=0.23),
        )
        for parameters in domains:
            initial = task.initial_state(task.generate_episode(0, parameters))
            for myopic in (False, True):
                reference = oracle.myopic_action_values(initial) if myopic else oracle.action_values(initial)
                for action in task.ACTIONS:
                    expected = sum(probability * rollout(ep, action, myopic=myopic)
                                   for ep, probability in fixtures(parameters))
                    self.assertAlmostEqual(expected, reference[action], places=12,
                                           msg=(parameters, action, myopic))

    def test_joint_arrival_and_read_are_conditionally_not_marginally_independent(self):
        p = task.TaskParameters(corruption_probability=0)
        episode = task.generate_episode(1, p)
        state = task.step(task.initial_state(episode), "WAIT", episode).state
        law = oracle.transition_distribution(state, "READ")
        probability_both_positive = sum(m for m, s, _ in law if s.vote_sum == 1 and s.delayed_vote == 1)
        self.assertAlmostEqual(probability_both_positive, 0.33, places=14)
        self.assertAlmostEqual(sum(m for m, _, _ in law), 1.0, places=14)
        empirical_exact = {}
        for ep, mass in fixtures(p):
            prefix = task.step(task.initial_state(ep), "WAIT", ep).state
            result = task.step(prefix, "READ", ep)
            key = json.dumps(result.state.to_dict(), sort_keys=True)
            empirical_exact[key] = empirical_exact.get(key, 0) + mass
        independent_law = {json.dumps(s.to_dict(), sort_keys=True): m for m, s, _ in law}
        self.assertEqual(set(empirical_exact), set(independent_law))
        for key in empirical_exact:
            self.assertAlmostEqual(empirical_exact[key], independent_law[key], places=14)

    def test_repair_recovers_original_vote_and_repeated_request_has_no_new_information(self):
        p = task.TaskParameters(corruption_probability=1)
        ep = task.generate_episode(8, p)
        s = task.initial_state(ep)
        for _ in range(2):
            s = task.step(s, "WAIT", ep).state
        self.assertEqual(s.delayed_status, "corrupt")
        self.assertEqual(s.posterior, 0.5)
        repaired = task.step(s, "REPAIR", ep)
        self.assertEqual(repaired.state.delayed_vote, ep.delayed_vote)
        self.assertEqual(repaired.info["new_observations"][0]["source_id"], "delayed/0")
        duplicate = task.step(repaired.state, "REPAIR", ep)
        stop = task.step(repaired.state, "STOP", ep)
        self.assertEqual(duplicate.info["new_observations"], [])
        self.assertEqual(duplicate.state.posterior, stop.state.posterior)
        self.assertAlmostEqual(stop.reward - duplicate.reward, p.invalid_attempt_cost)
        self.assertTrue(duplicate.info["guard_fallback"])

    def test_stop_initially_available_and_every_action_respects_submission_deadline(self):
        for horizon in (1, 2, 6):
            ep = task.generate_episode(2, horizon=horizon)
            initial = task.initial_state(ep)
            self.assertIn("STOP", task.legal_actions(initial))
            stopped = task.step(initial, "STOP", ep)
            self.assertEqual(stopped.state.tick, 1)
            self.assertEqual(stopped.info["new_observations"], [])
            state = initial
            while not state.terminated:
                result = task.step(state, "WAIT", ep)
                self.assertLessEqual(result.state.tick, horizon)
                state = result.state
            self.assertEqual(state.tick, horizon)
            self.assertEqual(oracle.action_values(state), {a: 0 for a in task.ACTIONS})

    def test_sunk_cost_serialization_and_private_future_do_not_change_policy_inputs(self):
        ep = task.generate_episode(99)
        state = task.initial_state(ep)
        restored = task.State.from_dict(json.loads(json.dumps(state.to_dict())))
        self.assertEqual(state, restored)
        self.assertEqual(oracle.action_values(state), oracle.action_values(replace(state, total_cost=100)))
        other = replace(ep, truth=-ep.truth, ordinary_votes=tuple(-x for x in ep.ordinary_votes),
                        delayed_vote=-ep.delayed_vote, delayed_corrupt=not ep.delayed_corrupt)
        np.testing.assert_array_equal(task.features(state), task.features(task.initial_state(other)))
        self.assertEqual(task.conditional_episode(state, 100, ep), task.conditional_episode(state, 100, other))
        self.assertEqual(len(task.features(state)), len(task.FEATURE_NAMES))

    def test_conditional_sampler_resamples_truth_from_posterior_and_keeps_seen_sources(self):
        ep = next(e for e, _ in fixtures(task.TaskParameters()) if e.ordinary_votes[0] == 1)
        state = task.step(task.initial_state(ep), "READ", ep).state
        episodes = [task.conditional_episode(state, i, ep) for i in range(6000)]
        self.assertTrue(all(e.ordinary_votes[0] == 1 for e in episodes))
        posterior_frequency = sum(e.truth == 1 for e in episodes) / len(episodes)
        self.assertAlmostEqual(posterior_frequency, state.posterior, delta=0.025)
        for action in task.legal_actions(state):
            observed = np.mean([rollout(e, action, myopic=True, state=state) for e in episodes])
            self.assertAlmostEqual(observed, oracle.myopic_action_values(state)[action], delta=0.035)

    def test_budget_guard_charges_attempt_without_reading(self):
        ep = task.generate_episode(3, budget=0)
        state = task.initial_state(ep)
        result = task.step(state, "READ", ep)
        self.assertEqual(result.info["guard_reason"], "insufficient_budget")
        self.assertEqual(result.info["new_observations"], [])
        self.assertEqual(result.state.remaining_budget, 0)
        self.assertEqual(result.info["costs"]["budget_debit"], 0)
        self.assertEqual(result.info["executed_action"], "STOP")


if __name__ == "__main__":
    unittest.main()
