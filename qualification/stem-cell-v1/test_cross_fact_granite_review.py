"""Stdlib-only negative controls for training-score review."""
from dataclasses import dataclass
import unittest

from cross_fact_granite_review import independent_training_score


@dataclass(frozen=True)
class Case:
    paragraph_id: str
    candidate: str
    label: int


class IndependentScoringTests(unittest.TestCase):
    def setUp(self):
        self.cases = (Case('sample/world-0', 'red', 1), Case('sample/world-1', 'red', 0),
                      Case('sample/world-0', 'blue', 0), Case('sample/world-1', 'blue', 1))

    def test_known_worlds_and_probabilities(self):
        scored = independent_training_score(self.cases, [.9, .1, .1, .9])
        self.assertEqual(scored['accuracy'], 1.)
        self.assertEqual(scored['both_worlds_correct'], 1.)
        self.assertGreater(scored['probability_CE'], 0)

    def test_missing_world_rejected(self):
        with self.assertRaisesRegex(ValueError, 'paired-world'):
            independent_training_score(self.cases[:3], [.9, .1, .1])

    def test_nonfinite_and_missing_probability_rejected(self):
        with self.assertRaisesRegex(ValueError, 'invalid prediction'):
            independent_training_score(self.cases, [.9, .1, float('nan'), .9])
        with self.assertRaisesRegex(ValueError, 'complete training'):
            independent_training_score(self.cases, [.9, .1])

    def test_fabricated_flip_fails_full_pair(self):
        result = independent_training_score(self.cases, [.9, .1, .7, .9])
        self.assertEqual(result['accuracy'], .75)
        self.assertEqual(result['both_worlds_correct'], .5)


if __name__ == '__main__':
    unittest.main()
