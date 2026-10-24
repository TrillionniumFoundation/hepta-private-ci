"""Unknown feature rows cannot silently enter finite-only private learning."""

import unittest

import numpy as np

from operational_feature_availability import availability_record, validate_matrix


class FeatureAvailabilityTests(unittest.TestCase):
    def test_unavailable_placeholder_must_be_nan_and_cannot_be_treated_as_valid(self):
        record = availability_record(["yes", "no"], [True, False], [None, "empty identifier source"])
        valid = np.asarray([[1, 2], [np.nan, np.nan]], np.float32)
        np.testing.assert_array_equal(validate_matrix(valid, record), [True, False])
        for invalid in (np.nan_to_num(valid), np.asarray([[np.nan, 2], [np.nan, np.nan]], np.float32)):
            with self.assertRaisesRegex(ValueError, "finite"):
                validate_matrix(invalid, record)
        with self.assertRaises(ValueError): availability_record(["x"], [False], [None])

if __name__ == "__main__":
    unittest.main()
