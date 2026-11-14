"""Execution/accounting behavior with a fake model and real PNG artifacts.

These tests are not evidence of Florence or learned-controller capability.
"""

import hashlib
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image

from backend import OBSERVATION_FIELDS
from generation import run_episode


class Clock:
    def __init__(self):
        self.now = 0.0

    def advance(self, seconds):
        self.now += seconds

    def read(self):
        return self.now


class Model:
    def __init__(self, clock, terminations=("eos", "eos"), fail_at=None):
        self.clock, self.terminations, self.fail_at = clock, terminations, fail_at
        self.observations, self.generations = [], 0

    def encode(self, observation):
        if set(observation) != OBSERVATION_FIELDS:
            raise ValueError("private observation fields reached the model")
        self.observations.append(dict(observation))
        self.clock.advance(0.2)
        return SimpleNamespace(costs={"encoder_seconds": 0.2})

    def generate(self, encoded, **kwargs):
        index = self.generations
        self.generations += 1
        self.clock.advance(0.3)
        if index == self.fail_at:
            raise RuntimeError("decoder failure")
        left = 0.1 if index == 0 else 0.6
        return {"boxes": [[left, 0.1, left + 0.3, 0.8]], "tokens": [0, 2, 3],
                "raw_text": f"candidate-{index}", "controls": [],
                "termination": self.terminations[min(index, len(self.terminations) - 1)],
                "costs": {"decoder_seconds": 0.3, "parsing_seconds": 0.,
                          "loop_overhead_seconds": 0., "modifier_seconds": 0.}}


class Verifier:
    def __init__(self, clock, qualities=(0.5, 0.8), fail=False):
        self.clock, self.qualities, self.fail, self.calls = clock, qualities, fail, 0

    def predict(self, result):
        self.clock.advance(0.05)
        if self.fail:
            raise RuntimeError("verifier failure")
        quality = self.qualities[min(self.calls, len(self.qualities) - 1)]
        self.calls += 1
        return {"quality": quality, "severe_probability": 0.2, "wall_seconds": 0.05}


class GenerationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.clock = Clock()
        self.model = Model(self.clock)
        self.observation = self.image_observation("source", "blue", (32, 24))

    def image_observation(self, task, color, size):
        path = self.root / (task + ".png")
        Image.new("RGB", size, color).save(path)
        return {"task_id": task, "image_path": str(path),
                "image_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "prompt": "Count cats and mark boxes.", "target_category": "cat"}

    def run_one(self, method="base", verifier=None, **kwargs):
        with patch("generation.time.perf_counter", self.clock.read):
            return run_episode(self.model, None, None, verifier, self.observation, method,
                               str(self.root / "artifacts"), **kwargs)

    def assert_artifact(self, episode):
        path = Path(episode["artifact_path"])
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), episode["artifact_sha256"])
        with Image.open(path) as image:
            self.assertEqual((image.format, image.size), ("PNG", (32, 24)))

    def assert_cost(self, episode):
        self.assertAlmostEqual(sum(row["wall_seconds"] for row in episode["costs"]), self.clock.now)
        self.assertAlmostEqual(episode["actual_wall_seconds"], self.clock.now)
        self.assertAlmostEqual(episode["ledger_minus_wall_seconds"], 0)

    def test_completed_and_truncated_outputs_preserve_real_artifacts(self):
        result = self.run_one()
        self.assertEqual(result["termination"], "completed")
        self.assertEqual(set(self.model.observations[0]), OBSERVATION_FIELDS)
        self.assert_artifact(result)
        self.assert_cost(result)
        self.model.terminations = ("max_tokens",)
        result = self.run_one()
        self.assertEqual(result["termination"], "incomplete")
        self.assert_artifact(result)
        with self.assertRaises(TypeError):
            self.run_one(reference={"boxes": [[0, 0, 1, 1]]})

    def test_best_of_n_reuses_one_encoder_and_charges_both_decoders_and_verifiers(self):
        result = self.run_one("best_of_n", Verifier(self.clock))
        self.assertEqual(len(self.model.observations), 1)
        self.assertEqual(len(result["candidates"]), 2)
        self.assertEqual(result["raw_text"], "candidate-1")
        self.assertEqual(result["generated_tokens"], 4)
        self.assertEqual([row["encoder_reused"] for row in result["candidates"]], [False, True])
        ledger = {row["component"]: row for row in result["costs"]}
        self.assertEqual([ledger[key]["calls"] for key in ("encoder", "backbone", "verifier")], [1, 2, 2])
        self.assertAlmostEqual(self.clock.now, 0.9)
        self.assert_cost(result)

    def test_verifier_exception_does_not_double_charge_decoder(self):
        result = self.run_one(verifier=Verifier(self.clock, fail=True))
        self.assertEqual(result["termination"], "completed")
        self.assertTrue(result["verification"]["verification_failed"])
        self.assertIn("verifier failure", str(result["failures"]))
        self.assert_cost(result)
        self.assert_artifact(result)

    def test_failed_later_candidate_preserves_deliverable_first_candidate(self):
        self.model.fail_at = 1
        result = self.run_one("best_of_n", Verifier(self.clock))
        self.assertEqual(result["termination"], "completed")
        self.assertEqual(result["raw_text"], "candidate-0")
        self.assert_cost(result)
        self.assert_artifact(result)

    def test_best_of_n_prioritizes_completed_over_truncated_candidate(self):
        self.model.terminations = ("eos", "max_tokens")
        result = self.run_one("best_of_n", Verifier(self.clock, (0.1, 0.99)))
        self.assertEqual(result["termination"], "completed")
        self.assertEqual(result["raw_text"], "candidate-0")
        self.assert_cost(result)

    def test_interventions_change_observed_hash_and_keep_original_canvas(self):
        partner = self.image_observation("partner", "red", (20, 16))
        for method in ("ablate_missing_modality", "ablate_shuffled_pair"):
            result = self.run_one(method, partner=partner)
            observed = self.model.observations[-1]
            self.assertNotEqual(observed["image_sha256"], self.observation["image_sha256"])
            self.assertEqual(observed["target_category"], self.observation["target_category"])
            if method == "ablate_shuffled_pair":
                self.assertEqual(observed["image_sha256"], partner["image_sha256"])
            self.assertEqual(result["actual_input_image_sha256"], observed["image_sha256"])
            self.assert_artifact(result)

    def test_exhausted_budget_retains_empty_artifact_without_executing_model(self):
        result = self.run_one(budget_cap=0.1)
        self.assertFalse(self.model.observations)
        self.assertEqual((result["termination"], result["candidates"]), ("incomplete", []))
        self.assert_artifact(result)


if __name__ == "__main__":
    unittest.main()
