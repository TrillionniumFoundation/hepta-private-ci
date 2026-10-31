"""Independent small checks of scoring and search used by the natural study."""
import unittest

import numpy as np

from .speech import score
from .video import search


class NaturalChecks(unittest.TestCase):
    def test_word_edit_distance_keeps_deletions_and_insertions(self):
        self.assertEqual(score("one two three", "one three four"),
                         {"word_errors": 2, "reference_words": 3, "WER": 2/3})
        self.assertEqual(score("She's here.", "she's HERE"),
                         {"word_errors": 0, "reference_words": 2, "WER": 0.0})

    def test_global_search_finds_patch_local_search_remains_local(self):
        rng = np.random.default_rng(1701)
        frame = rng.normal(size=(20, 30))
        template = frame[10:14, 20:25].copy()
        box, confidence = search(frame, template, [2, 2, 5, 4], None)
        self.assertEqual(box, [20, 10, 5, 4])
        self.assertAlmostEqual(confidence, 1.0, places=10)
        local, _ = search(frame, template, [2, 2, 5, 4], 2)
        self.assertLessEqual(local[0], 4)
        self.assertLessEqual(local[1], 4)


if __name__ == "__main__":
    unittest.main()
