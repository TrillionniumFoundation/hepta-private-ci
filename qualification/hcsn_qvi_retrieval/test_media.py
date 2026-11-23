"""Verify group isolation and frozen prefix matching without reading held-out media."""
import json
from pathlib import Path
import unittest

import numpy as np

from acquire_media import file_names
from media import match_scores


class MediaContract(unittest.TestCase):
    def test_predeclared_actor_and_recording_sets_are_disjoint(self):
        spec = json.loads(Path(__file__).with_name("data_manifest.json").read_text())
        groups = [set(values) for values in spec["splits"].values()]
        self.assertEqual([len(g) for g in groups], [10, 4, 4, 6])
        self.assertEqual(sum(map(len, groups)), len(set.union(*groups)))
        clips = [name for group in groups for actor in group for name in file_names(actor, spec)]
        self.assertEqual(len(clips), 192)
        self.assertEqual(len(set(clips)), len(clips))

    def test_future_query_and_gallery_do_not_change_past_scores(self):
        rng = np.random.default_rng(49)
        query, a, b = rng.normal(size=(3, 72, 6))
        reference = match_scores(query, [a, b], 6, 12)
        for signals in ([query], [a], [b], [query, a, b]):
            original = [signal.copy() for signal in signals]
            for signal in signals:
                signal[36:] += 1000
            mutated = match_scores(query, [a, b], 6, 12)
            np.testing.assert_array_equal(mutated[:3], reference[:3])
            for signal, old in zip(signals, original):
                signal[:] = old
        np.testing.assert_array_equal(match_scores(query, [b, a], 6, 12), reference[:, ::-1])
