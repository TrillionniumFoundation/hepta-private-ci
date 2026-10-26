from pathlib import Path
import tempfile
import unittest

from memory_cells.metrics import (
    break_even_reads,
    measure_bytes,
    paired_cluster_interval,
    resource_accounting,
    summarize_predictions,
)


class MetricTests(unittest.TestCase):
    def test_correctness_and_abstention_remain_separate(self):
        result = summarize_predictions(
            [1, 2, None, None], [1, None, None, 3], ["old", "old", "deleted", "deleted"]
        )
        self.assertEqual(
            {
                key: result[key]
                for key in (
                    "correct",
                    "incorrect",
                    "abstained",
                    "correct_answers",
                    "correct_abstentions",
                )
            },
            {
                "correct": 2,
                "incorrect": 1,
                "abstained": 2,
                "correct_answers": 1,
                "correct_abstentions": 1,
            },
        )
        self.assertEqual(result["known_accuracy"], 0.5)
        self.assertEqual(result["per_group"]["deleted"]["unknown_abstention_rate"], 0.5)
        self.assertEqual(sum(result["outcome_partition"].values()), result["total"])
        self.assertEqual(result["correct"] + result["total_errors"], result["total"])

    def test_bootstrap_counts_clusters_not_paraphrases(self):
        scores = [1.0, 0.0, 1.0]
        baseline = [0.0, 0.0, 1.0]
        groups = ["seed-a", "seed-b", "seed-c"]
        first = paired_cluster_interval(scores, baseline, groups, bootstrap_seed=7)
        repeated = paired_cluster_interval(
            scores * 20, baseline * 20, groups * 20, bootstrap_seed=7
        )
        for key in ("paired_difference", "lower", "upper", "clusters", "status"):
            self.assertEqual(first[key], repeated[key])
        singleton = paired_cluster_interval([1.0] * 100, [0.0] * 100, ["one"] * 100)
        self.assertEqual((singleton["lower"], singleton["upper"]), (None, None))
        self.assertEqual(singleton["status"], "insufficient_independent_clusters")

    def test_negative_results_are_preserved(self):
        result = paired_cluster_interval(
            [0.0] * 6, [1.0] * 6, [f"seed-{index}" for index in range(6)]
        )
        self.assertEqual(
            (result["paired_difference"], result["lower"], result["upper"]),
            (-1.0, -1.0, -1.0),
        )
        with self.assertRaises(ValueError):
            paired_cluster_interval([float("nan")], [0.0], ["a"])

    def test_physical_storage_is_charged_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "shared").write_bytes(b"abc")
            (root / "cell").write_bytes(b"defgh")
            self.assertEqual(measure_bytes([root, root / "shared"]), 8)
            with self.assertRaises(FileNotFoundError):
                measure_bytes([root / "missing-artifact"])
        result = resource_accounting(
            {"shared": 3, "adapters": 5},
            {"accepted_training": 2.0, "rejected_candidate_training": 3.0},
        )
        self.assertEqual(result["total_storage_bytes"], 8)
        self.assertEqual(result["total_compute_seconds"], 5.0)

    def test_break_even_requires_positive_read_savings(self):
        self.assertIsNone(break_even_reads(10, 1, 2, 1)["minimum_reads"])
        self.assertEqual(break_even_reads(10, 1, 1, 2)["minimum_reads"], 10)
        self.assertEqual(break_even_reads(0, 1, 1, 2)["minimum_reads"], 0)


if __name__ == "__main__":
    unittest.main()
