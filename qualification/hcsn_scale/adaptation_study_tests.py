"""Check independent preservation windows, normalization and physical clocks."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from qualification.hcsn_adaptive.real_sensor_data import FEATURES
from .adaptation_study import PLAN, prepare_data


class AdaptationStudyTests(unittest.TestCase):
    def test_preservation_rows_cannot_fit_normalizer_or_change_training_inputs(self):
        count = 8000
        values = (
            np.arange(count * len(FEATURES), dtype=np.float64).reshape(count, -1)
            / 1000.0
        )
        labels = np.zeros(count, dtype=np.int64)
        stamps = np.cumsum(np.where(np.arange(count) % 7 == 0, 31, 30)).astype(np.int64)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.csv"
            path.write_bytes(b"fixture; real runs still use the source SHA guard")
            with patch(
                "qualification.hcsn_scale.adaptation_study.read_rows",
                return_value=(values, labels, stamps),
            ):
                original, metadata, clock = prepare_data(path)
            edited = values.copy()
            for identity in original["preservation"]["ids"]:
                start, stop = (int(v) for v in identity.split(":")[1:3])
                edited[start : stop + 1] += 1000.0
            with patch(
                "qualification.hcsn_scale.adaptation_study.read_rows",
                return_value=(edited, labels, stamps),
            ):
                changed, second, second_clock = prepare_data(path)
        self.assertEqual(
            metadata["contract"]["normalization_train_only"],
            second["contract"]["normalization_train_only"],
        )
        self.assertEqual(clock, second_clock)
        np.testing.assert_array_equal(original["train"]["x"], changed["train"]["x"])
        np.testing.assert_array_equal(original["dev"]["x"], changed["dev"]["x"])
        self.assertFalse(
            np.array_equal(original["preservation"]["x"], changed["preservation"]["x"])
        )
        self.assertLessEqual(len(original["train"]["x"]), PLAN["max_train_windows"])
        self.assertLessEqual(len(original["dev"]["x"]), PLAN["max_dev_windows"])
        rows = {}
        for name, data in original.items():
            rows[name] = set()
            for identity, duration in zip(data["ids"], data["dt"]):
                start, stop = (int(v) for v in identity.split(":")[1:3])
                rows[name].update(range(start, stop + 1))
                np.testing.assert_array_equal(
                    duration, np.diff(stamps[start : stop + 1])
                )
        self.assertFalse(rows["train"] & rows["preservation"])
        self.assertFalse(rows["train"] & rows["dev"])
        self.assertFalse(rows["preservation"] & rows["dev"])


if __name__ == "__main__":
    unittest.main()
