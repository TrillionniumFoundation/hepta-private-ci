"""Adversarial independent decoded-object, cost and frozen census tests."""
import unittest
from factorial import decode_raw
from independent_observer import observe


class IndependentObserverTests(unittest.TestCase):
    def test_factual_shared_wrong_is_not_exonerated_by_agreement(self):
        raw = decode_raw((1, 1, 1, 1))
        self.assertEqual(observe(raw, 0, "EMIT"), (4, 4, 0, 4))
        self.assertEqual(observe(raw, 1, "EMIT"), (0, 0, 0, 4))

    def test_nontrivial_four_modal_disagreement_is_independent_of_facts(self):
        raw = decode_raw((1, 0, 1, 0))
        self.assertEqual(observe(raw, 0, "REFINE_VIDEO"), (6, 2, 2, 5))

    def test_unfunded_or_malformed_output_cannot_receive_external_score(self):
        raw = decode_raw((.2, .3, .4, .5))
        bad = raw.copy()
        bad.pop("video")
        with self.assertRaises(ValueError):
            observe(bad, 0, "EMIT")
        bad = raw.copy()
        bad["image"] = ((0, 1), (0, 0))
        with self.assertRaises(ValueError):
            observe(bad, 0, "EMIT")
        bad = raw.copy()
        bad["audio"] = (0, 0, 0)
        with self.assertRaises(ValueError):
            observe(bad, 0, "QUERY")
        with self.assertRaises(ValueError):
            observe(raw, 0, "INJECTED_ACTION")
        with self.assertRaises(ValueError):
            observe(raw, True, "EMIT")

    def test_budget_accounting_all_actions_without_model_scoring(self):
        raw = decode_raw((.6, .6, .6, .6))
        self.assertEqual(observe(raw, 1, "QUERY")[-1], 7)
        self.assertEqual(observe(raw, 1, "REFINE_AUDIO")[-1], 5)
        self.assertEqual(observe(raw, 1, "EMIT")[-1], 4)


if __name__ == "__main__":
    unittest.main()
