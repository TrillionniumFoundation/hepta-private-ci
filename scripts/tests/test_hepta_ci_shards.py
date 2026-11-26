"""Guard exact-source impact sharding against omission, injection and drift."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hepta_ci_shards import matrix_for_packages, verify_shard


class CargoShardTests(unittest.TestCase):
    def test_fully_covers_large_reverse_consumer_plan(self):
        names = [f"codex-owner-{i:03d}" for i in range(143)]
        matrix = matrix_for_packages(names, maximum_per_shard=12)
        self.assertEqual(len(matrix["include"]), 12)
        all_selected = [p for item in matrix["include"] for p in item["packages"]]
        self.assertEqual(sorted(all_selected), sorted(names))
        self.assertEqual(len(set(all_selected)), 143)
        self.assertTrue(all(len(row["packages"]) <= 12 for row in matrix["include"]))
        for i, item in enumerate(matrix["include"]):
            self.assertEqual(verify_shard(matrix, i, item["packages"]), item["packages"])

    def test_exact_small_set_stays_single_shard(self):
        matrix = matrix_for_packages(["owner-b", "owner-a"], 12)
        self.assertEqual(len(matrix["include"]), 1)
        self.assertEqual(matrix["include"][0]["packages"], ["owner-a", "owner-b"])

    def test_empty_plan_is_one_explicit_empty_shard(self):
        matrix = matrix_for_packages([], 12)
        self.assertEqual(matrix["include"], [{"index": 0, "packages": []}])
        self.assertEqual(verify_shard(matrix, 0, []), [])

    def test_full_workspace_package_selection_is_not_waived(self):
        # Full-workspace selection is passed to this function just like
        # a scoped one. The complete selected set must be retained.
        names = [f"pkg{i:03d}" for i in range(300)]
        matrix = matrix_for_packages(names, 8)
        self.assertEqual(
            sorted(p for row in matrix["include"] for p in row["packages"]), names
        )

    def test_rejects_duplicate_or_command_like_package_names(self):
        for packages in (
            ["same", "same"],
            ["--workspace"],
            ["safe", "unsafe name"],
            ["a/b"],
            [""],
        ):
            with self.subTest(packages=packages):
                with self.assertRaises(ValueError):
                    matrix_for_packages(packages, 12)

    def test_rejects_unbounded_matrix_and_resource_controls(self):
        with self.assertRaises(ValueError):
            matrix_for_packages(["p"], 0)
        with self.assertRaises(ValueError):
            matrix_for_packages(["p"], 65)
        with self.assertRaises(ValueError):
            matrix_for_packages([f"p{i:05d}" for i in range(129)], 1)

    def test_shard_index_membership_cannot_drift(self):
        matrix = matrix_for_packages(["pkg-a", "pkg-b", "pkg-c"], 2)
        with self.assertRaises(ValueError):
            verify_shard(matrix, 0, ["pkg-a"])
        with self.assertRaises(ValueError):
            verify_shard(matrix, 1, matrix["include"][0]["packages"])
        with self.assertRaises(ValueError):
            verify_shard(matrix, 3, ["pkg-b"])


if __name__ == "__main__":
    unittest.main()
