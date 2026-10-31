"""Deterministic sampled/distribution consistency and actual-owner trace checks."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from .cells import augmented_features, initial, physical
from .controller import parameters
from .execution import execute, sample_interval, sampled_features
from .propagation import flow, generator
from .task_tests import FixtureAdapter, make_fixture


class ScriptedRng:
    def __init__(self, choices):
        self.holdings, self.choices = iter([.1, .15, 999.]), iter(choices)
        self.scales, self.probabilities = [], []

    def exponential(self, scale):
        self.scales.append(float(scale))
        return next(self.holdings)

    def choice(self, size, p):
        self.probabilities.append(np.asarray(p).copy())
        index = next(self.choices)
        if not 0 <= index < size or p[index] <= 0 or abs(sum(p)-1) > 1e-12:
            raise AssertionError("Script selected an impossible CTMC transition")
        return index


def fixture_model():
    return dict(confusion=[[.9, .1], [.1, .9]],
        norm=dict(mean=[0.]*62, scale=[1.]*62),
        cellfits=dict(analytic=dict(parameters=[0.]*11)),
        controllers=dict(analytic_value=dict(weights={k:v.tolist()
            for k,v in parameters(73, 67, 2).items()})))


class ExecutionTests(unittest.TestCase):
    def test_onehot_and_distribution_agree_for_linear_observables(self):
        theta = np.array([.2, -.3, .4, -.5, .6, .1, .7, -.2, .3, .4, -.1])
        history = [dict(driver=-.15, duration=.2, reset=False),
                   dict(driver=.5, duration=.9, reset=False)]
        distribution = initial(physical(theta, 0.))
        for interval in history:
            transition, _, _, _ = flow((physical(theta, interval["driver"]),), interval["duration"])
            distribution = distribution @ transition
        driver, horizon = .35, .7
        onehots = np.array([sampled_features(theta, index, driver, horizon) for index in range(5)])
        record = dict(history=history, driver=driver, horizon=horizon)
        mixture = augmented_features("analytic", theta, [record])[0]
        # Position, refractory mass and first-hit probability are linear in p.
        linear = [0, 1, 3]
        np.testing.assert_allclose(distribution @ onehots[:, linear], mixture[linear], atol=2e-13)
        np.testing.assert_allclose(onehots[:, 0], [1/6, .5, 5/6, 0., 0.], atol=1e-15)
        np.testing.assert_array_equal(onehots[:, 1], [0., 0., 0., 1., 1.])
        # Bounded count and logistic readout are nonlinear. Undo the count
        # transform before asserting the corresponding expectation identity.
        state_counts = onehots[:, 2]/(1-onehots[:, 2])
        mixture_count = mixture[2]/(1-mixture[2])
        self.assertAlmostEqual(float(distribution @ state_counts), mixture_count, places=13)

    def test_scripted_gillespie_jump_count_and_task_reset(self):
        theta = np.zeros(11)
        driver, duration = .2, .4
        rng = ScriptedRng([4, 3, 0])
        successor, receipt = sample_interval(theta, 2, driver, duration, True, rng)
        self.assertEqual(successor, 0)
        self.assertEqual(receipt["before_task_reset"], 3)
        self.assertEqual(receipt["count"], 1)
        self.assertTrue(receipt["task_reset"])
        self.assertEqual(receipt["jumps"], [dict(time=.1, before=2, after=4, fired=True),
            dict(time=.25, before=4, after=3, fired=False)])
        q = generator((physical(theta, driver),))[0]
        np.testing.assert_allclose(rng.scales, [-1/q[index, index] for index in (2, 4, 3)])
        np.testing.assert_array_equal(rng.probabilities[-1], initial(physical(theta, 0.)))
        no_reset_rng = ScriptedRng([4, 3])
        successor, receipt = sample_interval(theta, 2, driver, duration, False, no_reset_rng)
        self.assertEqual(successor, 3)
        self.assertFalse(receipt["task_reset"])
        self.assertEqual(len(no_reset_rng.probabilities), 2)

    def test_sampled_execution_preserves_actual_owner_history_costs_and_resets(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            make_fixture(folder)
            adapter = FixtureAdapter()
            session = dict(id="fixture", seed=17, split="validation", folder=str(folder))
            predicted = [(np.eye(4)[action][None], np.zeros((1, 2))) for action in (2, 3, 2, 3)]
            with patch("tools.hcsn.task_value_factorial_20261030.execution.forward", side_effect=predicted):
                result = execute(session, "analytic_value_sampled", fixture_model(), adapter,
                    dict(multiplier=1., latency_price=.1), rng_seed=314)
            self.assertEqual(result["status"], "complete")
            self.assertIsNone(result["error"])
            self.assertEqual([event["action"] for event in result["events"]], ["READ", "FIRE", "READ", "FIRE"])
            self.assertEqual(len(adapter.reads), 2)
            self.assertEqual(result["counts"]["content_invocations"], 2)
            self.assertEqual(result["counts"]["payload_bytes"],
                             sum(event.get("payload_bytes", 0) for event in result["events"]))
            self.assertAlmostEqual(result["task_elapsed"], 2.7)
            self.assertAlmostEqual(result["score"]["charged_cost"], .47)
            self.assertAlmostEqual(result["score"]["utility"], 1.53)
            history, previous = [], None
            for decision, event in zip(result["decision_trace"], result["events"], strict=True):
                self.assertEqual(decision["record"]["history"], history)
                if previous is not None:
                    self.assertEqual(decision["sampled_state_before"], previous)
                latent = decision["latent_transition"]
                self.assertEqual(latent["task_reset"], event["action"] == "FIRE")
                self.assertTrue(all(0 <= jump["time"] <= event["duration"] for jump in latent["jumps"]))
                self.assertEqual(latent["count"], sum(jump["fired"] for jump in latent["jumps"]))
                if latent["task_reset"]:
                    self.assertIn(latent["after"], (0, 1))
                history.append(dict(driver=decision["record"]["driver"], duration=event["duration"],
                                    reset=event["action"] == "FIRE"))
                previous = latent["after"]
            self.assertAlmostEqual(result["decision_trace"][1]["record"]["history"][0]["driver"], .12)

    def test_failed_read_retains_execution_receipt_and_charge(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            metadata = make_fixture(folder)
            (folder / metadata["packets"][0][0]).unlink()
            session = dict(id="fixture", seed=17, split="validation", folder=str(folder))
            predicted = (np.array([[0., 0., 1., 0.]]), np.zeros((1, 2)))
            with patch("tools.hcsn.task_value_factorial_20261030.execution.forward", return_value=predicted):
                result = execute(session, "analytic_value_sampled", fixture_model(), FixtureAdapter(),
                    dict(multiplier=1., latency_price=.1), rng_seed=314)
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["error"]["type"], "FileNotFoundError")
            self.assertEqual(result["counts"]["failed_read_attempts"], 1)
            self.assertEqual(result["counts"]["content_invocations"], 0)
            self.assertEqual(len(result["decision_trace"]), 1)
            self.assertEqual(result["events"][0]["status"], "failed_read")
            self.assertAlmostEqual(result["score"]["utility"], -.12)


if __name__ == "__main__":
    unittest.main()
