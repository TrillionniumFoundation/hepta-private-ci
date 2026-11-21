"""Tests for the duplicate-run evidence review."""

import unittest

from .review import review


class ReviewTest(unittest.TestCase):
    def test_review(self):
        self.assertEqual(
            review(),
            {
                "status": "RED_DUPLICATE_KEY",
                "artifact_crc_ok": 2,
                "binary_files_compared": 12,
                "cross_run_binary_mismatches": 0,
                "single_execution_gate": False,
                "all_closed": False,
            },
        )


if __name__ == "__main__":
    unittest.main()
