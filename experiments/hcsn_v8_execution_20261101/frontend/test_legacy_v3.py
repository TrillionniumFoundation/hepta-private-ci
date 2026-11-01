"""Behavioral checks for real frozen heads across causal cache boundaries."""

from dataclasses import replace
import unittest

import numpy as np

from experiments.hcsn_v7_support_20261101.content_interface.content_interface import (
    CacheBudget, ContractError, Modality, VisibleContent,
)
from .legacy_v3 import BinnedCorrectness, LegacyV3Head, prepared_observation


class CausalHeadTests(unittest.TestCase):
    def setUp(self):
        self.x = np.zeros((4, 40))
        self.x[:, :16] = np.arange(64).reshape(4, 16) / 32
        self.x[0::2, 32] = self.x[0::2, 34] = 1
        self.x[1::2, 33] = self.x[1::2, 35] = 1
        self.times = np.array([.25, .5, 1.25, 1.5])
        self.observed = np.ones(4, bool)
        self.head = LegacyV3Head("av_binding")

    def cache(self, x=None):
        x = self.x if x is None else x
        cache = VisibleContent("fixture", CacheBudget(65536))
        for index, modality in enumerate(Modality):
            observation = prepared_observation(
                x, self.observed, self.times, object_id="fixture", modality=modality,
                prefix_end=1, completed_at=1 + index * .01)
            cache = cache.accept(observation, observation.completed_at)
        return cache

    def test_future_content_cannot_change_prediction(self):
        baseline = self.cache()
        changed = self.x.copy()
        changed[2:, :16] += 100000
        candidate = self.cache(changed)
        self.assertEqual(baseline, candidate)
        np.testing.assert_array_equal(self.head.classify(baseline), self.head.classify(candidate))

    def test_mutated_input_does_not_change_retained_cache(self):
        cache = self.cache()
        before = self.head.classify(cache)
        self.x[:] = 123456
        np.testing.assert_array_equal(before, self.head.classify(cache))

    def test_malformed_future_payload_cannot_reject_current_read(self):
        baseline = self.cache()
        changed = self.x.copy()
        changed[2:, :16] = np.nan
        candidate = self.cache(changed)
        self.assertEqual(baseline, candidate)
        np.testing.assert_array_equal(self.head.classify(baseline), self.head.classify(candidate))

    def test_malformed_available_payload_is_rejected(self):
        changed = self.x.copy()
        changed[0, :16] = np.nan
        with self.assertRaises(ContractError):
            self.cache(changed)

    def test_source_identity_is_not_a_prediction_feature(self):
        cache = self.cache()
        renamed = replace(cache, object_id="different-unrelated-source-id",
                          audio=replace(cache.audio, object_id="different-unrelated-source-id"),
                          video=replace(cache.video, object_id="different-unrelated-source-id"))
        np.testing.assert_array_equal(self.head.classify(cache), self.head.classify(renamed))

    def test_invalid_packed_future_row_is_rejected(self):
        cache = self.cache()
        raw = list(cache.audio.raw)
        raw[2] = 2.0
        corrupted = replace(cache, audio=replace(cache.audio, raw=tuple(raw)))
        with self.assertRaises(ContractError):
            self.head.classify(corrupted)

    def test_unknown_layout_cannot_be_misread_as_content(self):
        cache = self.cache()
        corrupted = replace(cache, audio=replace(cache.audio, raw=(2.0, 0.0)))
        with self.assertRaises(ContractError):
            self.head.classify(corrupted)

    def test_head_requires_empirical_correctness_target(self):
        cache = self.cache()
        with self.assertRaises(ContractError):
            self.head.evaluate(cache)
        p = np.tile(self.head.classify(cache), (4, 1))
        selected = int(p[0].argmax())
        labels = np.array([selected, selected, 1 - selected, 1 - selected])
        self.head.calibrator = BinnedCorrectness.fit(
            self.head.head_id, p, labels, source_sha256="0" * 64,
            data_role="explicit synthetic contract fixture, not scientific calibration")
        result = self.head.evaluate(cache)
        self.assertEqual(result.calibrated_correctness.probability, .5)
        np.testing.assert_array_equal(result.class_probabilities, p[0])

    def test_wrong_head_calibration_is_rejected(self):
        cache = self.cache()
        p = np.array([self.head.classify(cache)])
        self.head.calibrator = BinnedCorrectness.fit(
            "some-other-head", p, np.array([0]), source_sha256="0" * 64,
            data_role="explicit synthetic contract fixture")
        with self.assertRaises(ContractError):
            self.head.evaluate(cache)


if __name__ == "__main__":
    unittest.main()
