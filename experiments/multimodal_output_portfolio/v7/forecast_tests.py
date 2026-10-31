"""Real distribution ranking, identical cache outputs and identity rejection."""

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

import torch

from ..v6.data import Observation
from .data import make_batch
from .forecast import CategoricalForecast, DistributionHead, certainty_equivalent
from .metric import MetricContract
from .model import SlotPortfolio
from .model_tests import fixture_corpus
from .snapshot import Snapshot


class ForecastTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(2)
        torch.manual_seed(17)
        self.snapshot = Snapshot(SlotPortfolio())
        self.batch = make_batch(fixture_corpus(), "train", 1, 31, "clean")
        self.state = self.snapshot.encode(self.batch.observation)
        self.head = DistributionHead()
        self.contract = MetricContract("test", 3, 3, -1., 1., "a" * 64,
                                        (("fixed_observer", "b" * 64),), "raw_png_utf8")

    def test_risk_changes_choice_from_the_same_categorical_distribution(self):
        with torch.no_grad():
            for parameter in self.head.parameters():
                parameter.zero_()
            logits = self.head.net[-1].bias.reshape(21, 201)
            logits[:] = -1000
            logits[:, 0] = 0
            logits[0, 0] = -1000
            logits[0, 140] = 0  # certain utility .4
            logits[1, 0] = -1000
            logits[1, 100] = torch.log(torch.tensor(.4))
            logits[1, 200] = torch.log(torch.tensor(.6))  # mean .6, entropic CE < .4
        artifact = CategoricalForecast(self.head, self.snapshot.fingerprint, self.contract)
        values, probabilities = artifact.all_plan_distributions(self.state, self.batch.observation)
        mean = certainty_equivalent(values, probabilities, 0)
        risk = certainty_equivalent(values, probabilities, 2)
        self.assertEqual(int(mean.argmax()), 1)
        self.assertEqual(int(risk.argmax()), 0)
        self.assertLess(float((certainty_equivalent(values, probabilities, 1e-10) - mean).abs().max()), 1e-9)

    def test_binding_roundtrip_and_foreign_input_are_fail_closed(self):
        artifact = CategoricalForecast(self.head, self.snapshot.fingerprint, self.contract)
        direct = artifact.predict(self.state, self.batch.observation)
        binding = artifact.bind_observation(self.batch.observation)
        self.assertEqual(direct, artifact.predict_bound(self.state, binding))
        pixels = self.batch.observation.pixels.clone()
        pixels[0, 0, 0, 0] = 1 - pixels[0, 0, 0, 0]
        changed = Observation(pixels, self.batch.observation.mask, self.batch.observation.text_tokens)
        with self.assertRaises(ValueError):
            artifact.predict(self.state, changed)
        with self.assertRaises(TypeError):
            artifact.bind_observation(self.batch.target)
        with self.assertRaises(ValueError):
            artifact.predict_bound(self.state, replace(binding, forecast_digest="c" * 64))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "distribution.pt"
            sha = artifact.save(path)
            restored = CategoricalForecast.load(path, expected_file_sha256=sha)
            self.assertEqual(direct, restored.predict(self.state, self.batch.observation))
            restored.temperature = 2
            with self.assertRaises(RuntimeError):
                restored.predict(self.state, self.batch.observation)


if __name__ == "__main__":
    unittest.main()
