"""Behavioral checks for content-only accepted-prefix AV feature encoding."""

import unittest

import numpy as np

from .av_probe import KINDS, prefix_features


class AcceptedPrefixTests(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(87431)
        self.x = np.zeros((18, 40))
        self.x[:, :32] = rng.normal(size=(18, 32))
        for row in range(len(self.x)):
            self.x[row, 32 + row % 2] = 1
            self.x[row, 34 + row % 2] = 1
        self.observed = np.ones(18, bool)

    def test_rejected_payload_cannot_change_features(self):
        accepted = self.observed.copy()
        accepted[[2, 5, 9, 12]] = False
        altered = self.x.copy()
        altered[~accepted, :32] = 10000
        for kind in KINDS:
            np.testing.assert_array_equal(prefix_features(self.x, accepted, kind),
                                          prefix_features(altered, accepted, kind))

    def test_source_delta_age_and_unobserved_timing_are_not_features(self):
        changed = self.x.copy()
        changed[:, 16:32] += 3000
        changed[:, 36:] = 9000
        for kind in KINDS:
            np.testing.assert_array_equal(prefix_features(self.x, self.observed, kind),
                                          prefix_features(changed, self.observed, kind))

    def test_content_and_temporal_order_change_features(self):
        changed = self.x.copy()
        changed[8, :16] += 2
        self.assertFalse(np.array_equal(prefix_features(self.x, self.observed, "combined"),
                                       prefix_features(changed, self.observed, "combined")))
        changed = self.x.copy()
        changed[1::2, :16] = changed[1::2, :16][::-1]
        self.assertFalse(np.array_equal(prefix_features(self.x, self.observed, "synchrony"),
                                       prefix_features(changed, self.observed, "synchrony")))

    def test_empty_and_one_modality_prefixes_are_defined(self):
        for kind in KINDS:
            self.assertTrue(np.isfinite(prefix_features(self.x[:0], self.observed[:0], kind)).all())
            self.assertTrue(np.isfinite(prefix_features(self.x[:1], self.observed[:1], kind)).all())


if __name__ == "__main__":
    unittest.main()
