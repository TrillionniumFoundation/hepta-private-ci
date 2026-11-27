"""Boundary integrity, concurrency rejection and policy-preserving hash reuse."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import torch

from .data import Observation
from .forecast import ForecastBackend, ForecastBundle, RidgeHead
from .neural import NeuralPortfolio, NeuralSnapshot
from .plan_training import ControlledSnapshot, PlanHead
from .run import rollout


class StrictBackend(ForecastBackend):
    def inference_guard(self):
        return nullcontext(self)


class InferenceGuardTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(2)
        torch.manual_seed(913)
        self.snapshot = ControlledSnapshot(NeuralSnapshot(NeuralPortfolio(hidden=16)), PlanHead(16))
        self.observation = Observation(torch.zeros(1, 1, 28, 56), torch.ones(1, 1, 28, 56),
                                       torch.tensor([[1, 9, 12, 11, 13, 11, 2, 0]]))
        self.state = self.snapshot.encode(self.observation, noise_seed=13)
        features = self.snapshot.state_features(self.state).shape[1]
        utility, actions = RidgeHead(features, 1), RidgeHead(features, 4)
        utility.weight[:3, 0] = torch.tensor([.1, -.2, .3])
        self.forecast = ForecastBundle(utility, actions, torch.tensor([-.2, 0., .2]),
                                       self.snapshot.fingerprint, ("refine_image",))
        self.backend = self.forecast.backend(self.snapshot, "guard-fixture")

    def mutate_model(self):
        with torch.no_grad():
            next(self.snapshot._base._model.parameters()).add_(.01)

    def test_standalone_identity_retains_parameter_mutation_detection(self):
        self.backend.identity(self.state)
        self.mutate_model()
        with self.assertRaisesRegex(RuntimeError, "changed"):
            self.backend.identity(self.state)
        with self.assertRaisesRegex(RuntimeError, "changed"):
            with self.backend.inference_guard():
                self.fail("A changed snapshot must not enter the inference body")
        self.assertIsNone(self.backend._guard_owner)

    def test_persistent_model_or_forecast_mutation_blocks_guard_exit(self):
        returned = []
        with self.assertRaisesRegex(RuntimeError, "changed"):
            with self.backend.inference_guard():
                self.mutate_model()
                self.backend.identity(self.state)  # Model verification is deferred to exit.
            returned.append("published")
        self.assertEqual(returned, [])
        self.assertIsNone(self.backend._guard_owner)
        self.setUp()
        with self.assertRaisesRegex(RuntimeError, "changed"):
            with self.backend.inference_guard():
                self.forecast.utility_head.weight[0, 0] += .1
        self.assertIsNone(self.backend._guard_owner)

    def test_nested_cross_thread_and_exceptional_use_do_not_leak_guard(self):
        def enter_from_worker():
            with self.backend.inference_guard():
                return "entered"

        with self.backend.inference_guard():
            with self.assertRaisesRegex(RuntimeError, "Nested or concurrent"):
                with self.backend.inference_guard():
                    self.fail("Nested inference may not enter")
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(self.backend.identity, self.state)
                with self.assertRaisesRegex(RuntimeError, "another thread"):
                    future.result()
                with self.assertRaisesRegex(RuntimeError, "Nested or concurrent"):
                    pool.submit(enter_from_worker).result()
            self.backend.identity(self.state)
        with self.assertRaisesRegex(ValueError, "body failed"):
            with self.backend.inference_guard():
                raise ValueError("body failed")
        with self.backend.inference_guard():
            self.backend.identity(self.state)
        self.assertIsNone(self.backend._guard_owner)

    def test_guarded_and_strict_real_rollouts_have_identical_decisions_and_outputs(self):
        strict = SimpleNamespace(static_sequence=self.forecast.static_sequence,
                                 public_summary_work=self.forecast.public_summary_work,
                                 backend=lambda snapshot, context, observation=None: StrictBackend(snapshot, self.forecast, context))
        config = {"inference_horizon": 2, "control": {"horizon": 2, "search_fraction": .5}}
        for policy in ("fixed", "risk_aware_recursive", "allocation_only"):
            with self.subTest(policy=policy):
                expected = rollout(self.snapshot, strict, self.observation, policy, 64, config, "same-case", 13)
                actual = rollout(self.snapshot, self.forecast, self.observation, policy, 64, config, "same-case", 13)
                self.assertTrue(torch.equal(actual[0], expected[0]))
                self.assertEqual(actual[1], expected[1])
                self.assertEqual({k: v for k, v in actual[2].items() if k != "cost"},
                                 {k: v for k, v in expected[2].items() if k != "cost"})
                for key in ("modeled_work", "search_units", "execution_units"):
                    self.assertEqual(actual[2]["cost"][key], expected[2]["cost"][key])

    def test_decode_time_mutation_prevents_rollout_return(self):
        original_decode = self.snapshot.decode

        def corrupting_decode(state):
            output = original_decode(state)
            self.mutate_model()
            return output

        returned = []
        with patch.object(self.snapshot, "decode", side_effect=corrupting_decode):
            with self.assertRaisesRegex(RuntimeError, "changed"):
                returned.append(rollout(self.snapshot, self.forecast, self.observation, "fixed", 64,
                                        {"inference_horizon": 0, "control": {}}, "mutation", 13))
        self.assertEqual(returned, [])


if __name__ == "__main__":
    unittest.main()
