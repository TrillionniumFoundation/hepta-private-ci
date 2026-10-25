"""Synthetic boundary and exact-cache tests; no reserved sources are opened."""

from collections import Counter
from dataclasses import replace
import json
import tempfile
import unittest

import numpy as np
import torch

from ...abc_next.observability import PublicDigitSensor, input_evidence, observed_features
from ...abc_recovery.runtime import initialize, public_frame, transition
from ...v6.data import Observation
from ...v7.model import SlotPortfolio
from .features import ExactFeatureCache, compact_frame, compact_from_full
from .value import pick
from .serial import request


class CacheTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        torch.manual_seed(931)
        self.model = SlotPortfolio().eval().requires_grad_(False)
        self.sensor = PublicDigitSensor().eval().requires_grad_(False)
        pixels = torch.rand(2, 1, 28, 56)
        tokens = torch.tensor([[1, 9, 12, 11, 13, 11, 2, 0], [1, 10, 11, 15, 13, 11, 2, 0]])
        self.observation = Observation(pixels, torch.ones_like(pixels), tokens)
        self.root = initialize(self.model, self.observation, generator=torch.Generator().manual_seed(901))

    def test_exact_features_after_each_real_action_and_mutation(self):
        evidence = input_evidence(self.sensor, self.observation)
        for action in ("refine_semantic", "refine_text", "refine_image", "couple"):
            work = Counter()
            cache = ExactFeatureCache(self.model, self.sensor, self.observation, work)
            frame = public_frame(self.root)
            expected = observed_features(self.model, frame, sensor=self.sensor, evidence=evidence)
            self.assertTrue(torch.equal(cache.read(frame), expected))
            child = transition(self.model, self.root, action, generator=torch.Generator().manual_seed(902))
            frame = public_frame(child)
            expected = observed_features(self.model, frame, sensor=self.sensor, evidence=evidence)
            self.assertTrue(torch.equal(cache.read(frame), expected), action)
            self.assertTrue(torch.equal(compact_frame(frame), compact_from_full(expected)))
            self.assertEqual(work["exact_pixel_cache_hits"], int(action in {"refine_semantic", "refine_text"}))
            changed_pixels = frame.pixels.clone(); changed_pixels[0, 0, 0, 0] = 1 - changed_pixels[0, 0, 0, 0]
            changed = replace(frame, pixels=changed_pixels)
            self.assertTrue(torch.equal(cache.read(changed), observed_features(self.model, changed, sensor=self.sensor, evidence=evidence)))
            self.assertEqual(work["public_draft_sensor_calls"], 3 - int(action in {"refine_semantic", "refine_text"}))

    def test_success_constraint_does_not_admit_dominated_or_all_masked_actions(self):
        z = torch.tensor([[.8, .1, .4, .3, .5], [.9, .1, .8, .7, .6]])
        p = torch.tensor([[.7, 1., .4, .69, .2], [.6, 1., .55, .4, .65]])
        self.assertEqual(pick(z, p, 1, .02).tolist(), [3, 4])
        self.assertEqual(pick(z, p, 1, None).tolist(), [3, 4])

    def test_private_run_object_is_not_a_public_feature_input(self):
        with self.assertRaises(TypeError):
            compact_frame(self.root)
        cache = ExactFeatureCache(self.model, self.sensor, self.observation)
        with self.assertRaises(TypeError):
            cache.read(self.root)

    def test_actual_durable_cached_and_old_paths_match(self):
        class Choosing:
            mode = "enriched"

            def choose(self, values, remaining):
                return torch.full((len(values),), 1 if remaining == 2 else 3, dtype=torch.long)

        observation = Observation(*(x[:1] for x in
            (self.observation.pixels, self.observation.mask, self.observation.text_tokens)))
        with tempfile.TemporaryFile("w+b") as media:
            rows = [request(self.model, observation, name, old=Choosing(), compact=None, sensor=self.sensor,
                            reference="fixed", static_index=0, seed=17, case=0, view="synthetic", scenario=0, media=media)
                    for name in ("old_feedback", "cached_feedback")]
        self.assertEqual([r["status"] for r in rows], ["completed", "completed"])
        for key in ("completed_path", "decisions", "output_sha256", "runtime_ledger_sha256"):
            self.assertEqual(rows[0][key], rows[1][key])
        self.assertEqual(rows[0]["work"]["public_draft_sensor_calls"], 2)
        self.assertEqual(rows[1]["work"]["public_draft_sensor_calls"], 1)


class CensusTests(unittest.TestCase):
    def fixture(self):
        from ...abc_next.settings import MANIFEST
        from .serial import POLICIES
        ids = json.loads(MANIFEST.read_text())["roles"]["test"]["source_ids"][:4]
        spec = {"profile": {"training_seeds": [17, 29], "views": ["synthetic"], "pair_start": 0,
                            "pair_count": 2, "scenarios": 1},
                "controllers": [{"seed": s, "selected_candidate": "cached", "selected_nonfeedback": "fixed"} for s in (17, 29)]}
        rows = []
        for seed in (17, 29):
            for case in range(2):
                for policy in POLICIES:
                    rows.append({"seed": seed, "case": case, "view": "synthetic", "scenario": 0, "policy": policy,
                        "source_ids": ids[2 * case:2 * case + 2], "selected_candidate": "cached", "selected_nonfeedback": "fixed",
                        "status": "completed", "request_wall_ns": 1000000 * (case + 1), "request_cpu_ns": 900000,
                        "completed_path": [], "decisions": ["stop"], "output_sha256": ["a"], "runtime_ledger_sha256": "b",
                        "required_output_complete": True, "observer_scores": {o: {"utility": .5, "joint_fact_correct": 1,
                            "joint_loss": .25} for o in ("primary", "secondary")}})
        return rows, spec

    def test_duplicate_missing_and_source_misbinding_are_rejected(self):
        from .analysis import cubes
        rows, spec = self.fixture()
        for altered in (rows + [rows[0]], rows[:-1], [{**rows[0], "source_ids": ["x", "y"]}, *rows[1:]]):
            with self.assertRaises(ValueError):
                cubes(altered, spec)

    def test_failure_blocks_quality_and_outlier_is_retained(self):
        from .analysis import cubes
        rows, spec = self.fixture()
        rows[0]["request_wall_ns"] = 10**12
        costs, _, audit = cubes(rows, spec)
        self.assertEqual(costs["reference"]["wall_ms"][0, 0, 0, 0], 1e6)
        self.assertTrue(audit["quality_inference_allowed"])
        rows[0]["status"] = "request_failed"
        costs, _, audit = cubes(rows, spec)
        self.assertIsNone(costs)
        self.assertFalse(audit["quality_inference_allowed"])

    def test_price_curve_preserves_quality_cost_dependence(self):
        from ...abc_recovery.statistics import crossed_bootstrap
        from .analysis import price_curve
        utility = np.array([[[[.8, -.2]], [[.6, .1]]]])
        cost = np.array([[[[1., 9.]], [[2., 8.]]]])
        baseline = np.zeros_like(utility)
        plan = crossed_bootstrap(1, 2, replicates=100, seed=31)
        result = price_curve(utility, baseline, cost, np.zeros_like(cost), plan)
        point = next(row for row in result["grid"] if row["utility_per_ms"] == .02)
        expected = -np.log(np.exp(-2 * (utility - .02 * cost)).mean()) / 2
        incorrect = -np.log(np.exp(-2 * utility).mean()) / 2 - .02 * cost.mean()
        self.assertAlmostEqual(point["CE_gain"], expected, places=13)
        self.assertGreater(abs(expected - incorrect), .01)


if __name__ == "__main__":
    unittest.main()
