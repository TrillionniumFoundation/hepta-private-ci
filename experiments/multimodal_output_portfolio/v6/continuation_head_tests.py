"""Real v6 neural/media contract fixtures; these are NOT efficacy experiments."""

from dataclasses import replace
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import torch

from .conditioned import ConditionedPortfolio, ConditionedSnapshot
from .continuation_differential import compare_native
from .continuation_head import (ContinuationHead, DecisionContext, encoder_only,
                                paired_record, public_features, validate_observation)
from .data import Observation, render_tokens
from .forecast import ForecastBackend, ForecastBundle, RidgeHead
from .neural import ACTIONS
from .observer import Recognizer, observe_tensors, read_bundle, write_bundle
from .plan_training import ControlledSnapshot, PlanHead


class ContinuationContractTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        torch.manual_seed(41)
        self.base = ConditionedSnapshot(ConditionedPortfolio(hidden=16, noise_scale=0.))
        forecast = ForecastBundle(RidgeHead(64, 1), RidgeHead(64, 4), torch.zeros(2), self.base.fingerprint, ())
        self.backend = ForecastBackend(self.base, forecast, "continuation-contract-fixture")
        self.observation = Observation(torch.rand(1, 1, 28, 56), torch.ones(1, 1, 28, 56),
                                       torch.tensor([[1, 9, 12, 11, 13, 11, 2, 0]]))
        self.context = DecisionContext(16., 4., 0, 3)
        self.tariff = hashlib.sha256(b"fixture:actual-cpu-wall-tariff:0.001").hexdigest()
        self.observer = Recognizer().eval().requires_grad_(False)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.counter = 0

    def collect(self, gamma=2.):
        records, states = [], []
        for index in range(2):
            obs = self.observation if index == 0 else replace(self.observation, pixels=1 - self.observation.pixels)
            _, state = encoder_only(self.base, obs)
            states.append(state)
            ids = [hashlib.sha256(block.numpy().tobytes()).hexdigest() for block in obs.pixels.split(28, dim=3)]

            def evaluate(candidate, path, seed, measurement):
                wall, cpu = time.perf_counter(), time.process_time()
                output = self.base.decode(candidate)
                directory = Path(self.directory.name) / str(self.counter)
                self.counter += 1
                paths = write_bundle(directory, render_tokens(output.token_ids[0]), output.image_logits[0].sigmoid())
                pixels, caption, hashes = read_bundle(paths)
                score = observe_tensors(self.observer, pixels, [caption], obs.pixels, torch.tensor([[2, 7]]))[0]
                cost = .001 * (time.process_time() - cpu + time.perf_counter() - wall
                               + measurement["transition_cpu_seconds"] + measurement["transition_wall_seconds"])
                return {"utility": score["utility"], "actual_cost": cost,
                        "output_sha256": hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()}

            records.append(paired_record(self.backend, state, self.context, source_ids=ids,
                            suffix=("refine_image",), cost_profile_digest=self.tariff,
                            evaluate=evaluate, gamma=gamma))
        return records, states

    def test_encoder_only_bypasses_the_actual_two_transition_plan(self):
        controlled = ControlledSnapshot(self.base, PlanHead(16))
        with patch.object(self.base, "step", wraps=self.base.step) as step:
            base, state = encoder_only(controlled, self.observation, noise_seed=17)
            self.assertEqual(step.call_count, 0)
            planned = controlled.encode(self.observation, noise_seed=17)
            self.assertEqual(step.call_count, 2)
        self.assertIs(base, self.base)
        self.assertNotEqual(self.base.state_key(state), self.base.state_key(planned.neural))
        x = public_features(base, state, self.context)
        swapped = replace(state, image=state.text, text=state.image)
        self.assertFalse(torch.equal(x, public_features(base, swapped, self.context)))
        self.assertEqual(x[0, -9:].tolist(), [16., 4., 0., 3., 0., 0., 0., 0., 0.])

    def test_actual_media_pair_fit_and_pinned_data_only_restore(self):
        for gamma in (0., 2.):
            records, states = self.collect(gamma)
            head = ContinuationHead.fit(self.base, records, ridge=1e-6)
            path = Path(self.directory.name) / f"head-{gamma}.json"
            restored = ContinuationHead.load(path, expected_file_sha256=head.save(path))
            self.assertEqual(head.to_record(), restored.to_record())
            self.assertEqual(self.counter, 10 if gamma == 0 else 20)
            for row, state in zip(records, states):
                inferred = restored.infer(self.backend, state, self.context, cost_profile_digest=self.tariff)
                self.assertEqual(inferred["STOP"], 0.)
                returns = [o["net_return"] for o in row["outcomes"]]
                expected = [r - returns[0] if gamma == 0 else math.exp(-gamma * returns[0]) - math.exp(-gamma * r)
                            for r in returns[1:]]
                torch.testing.assert_close(torch.tensor([inferred[a] for a in ACTIONS]), torch.tensor(expected), atol=1e-6, rtol=1e-4)
            self.base.verify_integrity()
            self.assertTrue(all(not p.requires_grad for p in self.base._model.parameters()))
            with self.assertRaisesRegex(ValueError, "file SHA-256"):
                ContinuationHead.load(path, expected_file_sha256="0" * 64)

    def test_unsupported_input_coverage_cost_profile_and_mutation_reject(self):
        invalid = replace(self.observation, text_tokens=torch.tensor([[1, 8, 12, 11, 13, 11, 2, 0]]))
        for obs in (invalid, replace(self.observation, pixels=torch.full_like(self.observation.pixels, float("nan")))):
            with self.assertRaises(ValueError):
                encoder_only(self.base, obs)
        with self.assertRaises(ValueError):
            validate_observation(self.observation, ("text", "audio"))
        records, states = self.collect()
        head = ContinuationHead.fit(self.base, records)
        with self.assertRaises(ValueError):
            paired_record(self.backend, states[0], self.context, source_ids=records[0]["source_pixels"],
                          suffix=(), cost_profile_digest=self.tariff, evaluate=None,
                          gamma=1e-309, return_bounds=(-1e308, 1e308))
        for context, tariff in ((replace(self.context, observation_version=99), self.tariff), (self.context, "0" * 64)):
            with self.assertRaises(ValueError):
                head.infer(self.backend, states[0], context, cost_profile_digest=tariff)
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            ContinuationHead.fit(self.base, records + records[:1])
        with torch.no_grad():
            head._head.weight[0, 0] += 1
        with self.assertRaisesRegex(RuntimeError, "artifact changed"):
            head.to_record()

    @unittest.skipUnless(os.environ.get("HEPTA_CONTINUATION_NATIVE"), "Rust binary unavailable: parity NOT executed")
    def test_actual_fitted_head_torch_rust_parity(self):
        records, states = self.collect()
        head = ContinuationHead.fit(self.base, records)
        features = [row["features"] for row in records]
        expected = [head.predict(self.backend, state, self.context, cost_profile_digest=self.tariff).tolist() for state in states]
        report = compare_native(os.environ["HEPTA_CONTINUATION_NATIVE"], head.to_record(), features, expected)
        self.assertEqual(report["scope"], "standardized_linear_continuation_head_only")
        self.assertLessEqual(report["max_abs_error"], 1e-10)


if __name__ == "__main__":
    unittest.main()
