"""Bounded PFT1 diagnostic regression; no historical matrix or training runs."""

import importlib.util
import json
from pathlib import Path
import unittest
import warnings

import numpy as np


SOURCE = Path(__file__).with_name("identifiability.py")
SPEC = importlib.util.spec_from_file_location("pft1_rank_zero_subject", SOURCE)
SUBJECT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SUBJECT)


class IdentifiabilityRankZeroTests(unittest.TestCase):
    @staticmethod
    def measurement(design):
        weight = np.diag([1.0, 2.0, 3.0])
        targets = design @ weight.T
        tests = [{
            "q": np.array([[1.0, 0.0, -1.0]]),
            "true": np.array([[0.0, 0.0, 0.0], [1.0, 0.0, -3.0]]),
        }]
        with warnings.catch_warnings():
            warnings.simplefilter("error", RuntimeWarning)
            return SUBJECT.fit_and_measure(design, targets, weight, tests, 0.001)

    def test_zero_rank_serializes_as_unidentifiable(self):
        result = self.measurement(np.zeros((2, 3)))
        decoded = json.loads(json.dumps(result, allow_nan=False))
        fields = (
            "design_rank", "full_parameter_operator_rank", "parameter_count",
            "rank_fraction", "per_output_singular_values",
            "nonzero_condition_number", "effective_ridge",
        )
        self.assertEqual({name: decoded[name] for name in fields}, {
            "design_rank": 0,
            "full_parameter_operator_rank": 0,
            "parameter_count": 9,
            "rank_fraction": 0.0,
            "per_output_singular_values": [0.0, 0.0, 0.0],
            "nonzero_condition_number": None,
            "effective_ridge": 0.0,
        })

    def test_nonzero_spectrum_and_parameter_rank_are_unchanged(self):
        for diagonal, rank, condition in (
            ([3.0, 1.0, 0.0], 2, 3.0),
            ([4.0, 2.0, 1.0], 3, 4.0),
        ):
            with self.subTest(diagonal=diagonal):
                result = self.measurement(np.diag(diagonal))
                decoded = json.loads(json.dumps(result, allow_nan=False))
                fields = (
                    "design_rank", "full_parameter_operator_rank",
                    "parameter_count", "nonzero_condition_number",
                )
                self.assertEqual({name: decoded[name] for name in fields}, {
                    "design_rank": rank,
                    "full_parameter_operator_rank": 3 * rank,
                    "parameter_count": 9,
                    "nonzero_condition_number": condition,
                })


if __name__ == "__main__":
    unittest.main()
