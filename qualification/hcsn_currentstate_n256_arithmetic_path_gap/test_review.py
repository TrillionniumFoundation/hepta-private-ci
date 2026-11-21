"""Tests for the zero-numerical arithmetic-path gap review."""

import unittest

from .review import inspect_source, review


class ReviewTest(unittest.TestCase):
    def test_review(self):
        record = review()
        self.assertEqual(record["finding"]["arithmetic_or_path_cause"], "UNKNOWN")
        self.assertEqual(
            record["finding"]["cross_worker_hardware_arithmetic_path"], "UNBOUND"
        )

    def test_source_is_zero_numerical(self):
        inspect_source()


if __name__ == "__main__":
    unittest.main()

