"""Contrast correctness cannot be rescued by changing the evaluated inputs."""

from copy import deepcopy
import unittest

from selector_evaluation import factorial_contrasts


class ContrastTests(unittest.TestCase):
    def setUp(self):
        arms = (
            "prefix_frozen_top1",
            "windows_frozen_top1",
            "windows_frozen_null",
            "windows_trained_null",
        )
        self.rows = [
            dict(
                phase="test",
                arm=arm,
                question_id=f"q{i}",
                family=f"f{i}",
                status="succeeded",
                pool_digest="prefix" if arm.startswith("prefix") else "expanded",
                scored_features_digest="features",
                candidate_ids=["candidate"],
                source_choice_correct=int(arm == "windows_trained_null"),
            )
            for i in range(3)
            for arm in arms
        ]

    def test_paired_parameter_effect_separate_from_window_effect(self):
        results = factorial_contrasts(self.rows)
        self.assertEqual(results["test/coverage"]["family_mean_delta"], 0)
        self.assertEqual(results["test/learning"]["family_mean_delta"], 1)
        self.assertEqual(results["test/learning"]["planned_pairs"], 3)
        self.assertLess(results["test/learning"]["simultaneous_95_interval"][0], 0)
        self.assertFalse(results["test/learning"]["production_accepted"])

    def test_missing_duplicate_or_changed_pool_cannot_look_like_a_gain(self):
        for change in (
            lambda r: r.pop(),
            lambda r: r.append(r[-1]),
            lambda r: r[-1].update(pool_digest="other"),
            lambda r: r[-1].update(scored_features_digest="other"),
            lambda r: r[-1].update(family="other"),
        ):
            rows = deepcopy(self.rows)
            change(rows)
            with self.assertRaises(ValueError):
                factorial_contrasts(rows)


if __name__ == "__main__":
    unittest.main()
