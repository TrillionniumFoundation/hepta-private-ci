"""Behavioral checks for public information and actual-draft feature semantics."""

from dataclasses import replace
import unittest

import torch

from ..v6.data import Observation, Target
from ..v6.neural import parameter_hash
from ..v7.model import SlotPortfolio
from ..abc_recovery.runtime import initialize, public_frame, transition
from .observability import (ENRICHED_DIM, PublicDigitSensor, input_evidence,
                            observed_features, semantic_features)


def observation(*, command=9, hints=(11, 11), reliability=(12, 13), missing=True):
    pixels = torch.zeros(1, 1, 28, 56)
    mask = torch.zeros_like(pixels) if missing else torch.ones_like(pixels)
    tokens = torch.tensor([[1, command, reliability[0], hints[0], reliability[1], hints[1], 2, 0]])
    return Observation(pixels, mask, tokens)


class PublicFeatureTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        self.sensor = PublicDigitSensor(123).eval().requires_grad_(False)
        self.model = SlotPortfolio(noise_scale=0).eval().requires_grad_(False)

    def test_missing_hint_channel_and_routing_are_public(self):
        plain = input_evidence(self.sensor, observation())
        self.assertTrue(torch.equal(plain.probabilities, torch.full((1, 2, 10), .1)))
        untrusted = input_evidence(self.sensor, observation(hints=(17, 11), reliability=(11, 13)))
        self.assertAlmostEqual(float(untrusted.probabilities[0, 0, 3]), .5, places=6)
        self.assertAlmostEqual(float(untrusted.probabilities[0, 0, 2]), .5 / 9, places=6)
        trusted = input_evidence(self.sensor, observation(command=10, hints=(17, 11)))
        self.assertEqual(float(trusted.probabilities[0, 1, 3]), 1.)
        self.assertEqual(float(trusted.probabilities[0, 1].sum()), 1.)
        self.assertTrue(torch.equal(trusted.probabilities[0, 0], plain.probabilities[0, 1]))

    def test_feature_extraction_has_no_rng_or_parameter_mutation(self):
        obs = observation(missing=False)
        run = initialize(self.model, obs, generator=torch.Generator().manual_seed(881))
        frame = public_frame(run)
        sensor_hash, model_hash = parameter_hash(self.sensor), parameter_hash(self.model)
        before = torch.random.get_rng_state().clone()
        evidence = input_evidence(self.sensor, obs)
        first = observed_features(self.model, frame, sensor=self.sensor, evidence=evidence)
        torch.Generator().manual_seed(999).get_state()  # A private future stream cannot be an input.
        second = observed_features(self.model, frame, sensor=self.sensor, evidence=evidence)
        self.assertTrue(torch.equal(first, second))
        self.assertTrue(torch.equal(before, torch.random.get_rng_state()))
        self.assertEqual((parameter_hash(self.sensor), parameter_hash(self.model)), (sensor_hash, model_hash))
        self.assertEqual(tuple(first.shape), (1, ENRICHED_DIM))
        self.assertEqual(float(first[0, -1]), 1.)
        child = transition(self.model, run, "refine_semantic", generator=torch.Generator().manual_seed(2))
        feature = observed_features(self.model, public_frame(child), sensor=self.sensor, evidence=evidence)
        self.assertEqual(float(feature[0, -1]), .5)

    def test_real_token_invalidity_is_not_repaired(self):
        obs = observation(hints=(17, 21))
        run = initialize(self.model, obs, generator=torch.Generator().manual_seed(9))
        frame = public_frame(run)
        tokens = torch.tensor([[1, 3, 17, 4, 21, 5, 6, 2]])
        valid = replace(frame, tokens=tokens)
        invalid_tokens = tokens.clone()
        invalid_tokens[0, 3] = 2
        invalid = replace(frame, tokens=invalid_tokens)
        evidence = input_evidence(self.sensor, obs)
        first = semantic_features(self.sensor, valid, evidence)
        second = semantic_features(self.sensor, invalid, evidence)
        self.assertEqual(float(first[0, -1]), 1.)
        self.assertEqual(float(second[0, -1]), 0.)
        self.assertEqual(float(second[0, 40:63].sum()), 0.)
        self.assertTrue(torch.equal(invalid.tokens, invalid_tokens))

    def test_private_target_and_unfrozen_reader_are_rejected(self):
        obs = observation()
        target = Target(obs.pixels, obs.text_tokens, torch.tensor([[3, 7]]))
        with self.assertRaises(TypeError):
            input_evidence(self.sensor, target)
        self.sensor.train()
        with self.assertRaises(TypeError):
            input_evidence(self.sensor, obs)


if __name__ == "__main__":
    unittest.main()
