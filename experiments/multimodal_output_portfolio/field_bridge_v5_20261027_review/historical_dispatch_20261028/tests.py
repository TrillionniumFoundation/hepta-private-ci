"""Pure-array checks; no Torch import, model construction or endpoint generation."""

import gzip
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np


SPEC = importlib.util.spec_from_file_location("dispatch_diagnostic", Path(__file__).with_name("run.py"))
RUN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUN)


class DiagnosticTests(unittest.TestCase):
    def test_exact_comparison_keeps_single_ulp_difference(self):
        left = np.asarray([[1., .25], [-.5, .125]], dtype=np.float64)
        right = left.copy()
        right[1, 0] = np.nextafter(right[1, 0], np.inf)
        result = RUN.compare(left, right)
        self.assertFalse(result["exact"])
        self.assertEqual(result["indices"], [[1, 0]])
        self.assertEqual(result["different_values"], 1)
        self.assertEqual(result["delta"], [left[1, 0] - right[1, 0]])
        self.assertIsNone(result["tolerance"])

    def test_exact_comparison_rejects_shape_dtype_and_nonfinite(self):
        left = np.asarray([1., 2.], dtype=np.float64)
        for right in (left.astype(np.float32), left.reshape(1, 2), np.asarray([1., np.nan])):
            with self.assertRaises(ValueError):
                RUN.compare(left, right)

    def test_exact_comparison_preserves_both_observers(self):
        left = np.asarray([[.25, .5], [.125, .75]], dtype=np.float64)
        self.assertTrue(RUN.compare(left, left.copy())["exact"])
        self.assertFalse(RUN.compare(left, left[::-1].copy())["exact"])

    def fixture(self, directory):
        weights = dict(zip(RUN.FIELDS, (.30, .15, .35, .10, .10), strict=True))
        charge, mse, shifted = .002, [.125, .25], [.125, .375]
        rows = [{"refinement_charge": charge, "observers": {
            name: dict(zip(RUN.FIELDS, (float(i), 0., float(j) / 2, .5, mse[i]), strict=True))
            for j, name in enumerate(("reward", "audit"))}} for i in range(2)]

        def values(pixel_mse):
            return np.asarray([[1 - 2 * sum(weights[key] * (pixel_mse[i] if key == "pixel_mse"
                else rows[i]["observers"][name][key]) for key in RUN.FIELDS) - charge
                for i in range(2)] for name in ("reward", "audit")], dtype=np.float64)

        current, old = values(mse), values(shifted)
        current_file, old_file = directory / "current.npz", directory / "old.npz"
        np.savez(current_file, frozen_task=current, frozen_clean=current)
        np.savez(old_file, original_task=old, original_clean=old)
        for case in RUN.CASES:
            (directory / case).mkdir()
            for panel in ("task", "clean"):
                with gzip.open(directory / case / (panel + "_components.json.gz"), "wt") as stream:
                    json.dump({"rows": rows, "fixed_v5_raw_mse": shifted if case == "avx2" else mse}, stream)
        return {"old_endpoint_arrays": old_file, "current_endpoint_arrays": current_file}, {"utility_weights": weights}

    def test_scoring_only_substitution_is_full_ordered_exact_arithmetic(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            inputs, protocol = self.fixture(directory)
            result = RUN.scoring_only_comparison(directory, inputs, protocol)
            for panel in ("task", "clean"):
                self.assertTrue(result[panel]["avx2"]["vs_old_v3"]["exact"])
                self.assertFalse(result[panel]["avx2"]["vs_current_v5"]["exact"])
                self.assertTrue(result[panel]["unset_before"]["vs_current_v5"]["exact"])
                self.assertEqual(result[panel]["unset_before"]["vs_old_v3"]["different_values"], 2)

    def test_scoring_only_rejects_missing_rows(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            inputs, protocol = self.fixture(directory)
            path = directory / "avx2/task_components.json.gz"
            with gzip.open(path, "rt") as stream:
                value = json.load(stream)
            value["fixed_v5_raw_mse"].pop()
            with gzip.open(path, "wt") as stream:
                json.dump(value, stream)
            with self.assertRaises(ValueError):
                RUN.scoring_only_comparison(directory, inputs, protocol)

    def test_scoring_only_rejects_incorrect_charge_or_weight(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            inputs, protocol = self.fixture(directory)
            protocol["utility_weights"]["pixel_mse"] = .11
            with self.assertRaisesRegex(ValueError, "Baseline primitive reconstruction differs"):
                RUN.scoring_only_comparison(directory, inputs, protocol)


if __name__ == "__main__":
    unittest.main()
