"""Counterexamples for complete, unchanged-threshold retained-array admission."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from .verify_retained_values import verify


ORIGINAL = Path(__file__).parent / "evidence" / "all-visits-attempt002"


class TestRetainedValueAdmission(unittest.TestCase):
    def test_all_actual_rows_recompute_without_model_execution(self):
        result = verify(ORIGINAL)
        self.assertEqual(result["model_executions"], 0)
        self.assertEqual([p["visits"] for p in result["panels"]], [14336] * 3)
        self.assertEqual(
            [p["failures_at_original_0_01"] for p in result["panels"]], [0] * 3
        )

    def test_threshold_relaxation_is_rejected_before_array_reads(self):
        with tempfile.TemporaryDirectory() as name:
            summary = json.loads((ORIGINAL / "SUMMARY.json").read_text())
            summary["original_scaled_value_error_limit"] = 0.02
            Path(name, "SUMMARY.json").write_text(json.dumps(summary))
            with self.assertRaises(ValueError):
                verify(name)

    def test_source_mutation_and_missing_visit_are_rejected(self):
        for mutate in (
            lambda s: s["source_sha256_after"].update({"changed": "source"}),
            lambda s: s.update({"audited_positions": 14335}),
        ):
            with tempfile.TemporaryDirectory() as name:
                summary = json.loads((ORIGINAL / "SUMMARY.json").read_text())
                mutate(summary)
                Path(name, "SUMMARY.json").write_text(json.dumps(summary))
                with self.assertRaises(ValueError):
                    verify(name)

    def test_duplicate_visit_cannot_replace_missing_one_even_with_updated_file_hash(
        self,
    ):
        with tempfile.TemporaryDirectory() as name:
            summary = json.loads((ORIGINAL / "SUMMARY.json").read_text())
            filename = "ALL_VISITS_128.npz"
            with np.load(ORIGINAL / filename, allow_pickle=False) as archive:
                rows, columns = archive["rows"].copy(), archive["columns"].copy()
            rows[-1] = rows[0]
            path = Path(name, filename)
            np.savez_compressed(path, rows=rows, columns=columns)
            summary["array_sha256"][filename] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            Path(name, "SUMMARY.json").write_text(json.dumps(summary))
            with self.assertRaisesRegex(ValueError, "duplicated visit identity"):
                verify(name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
