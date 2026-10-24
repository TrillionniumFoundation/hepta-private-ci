"""Check the source-only predictor boundary without importing target pandas."""

import unittest

from pandas_pilot_actions import source_only_row


class SourceOnlyTests(unittest.TestCase):
    def test_outcome_and_metadata_fields_do_not_enter_predictor(self):
        case = {"bug": {"group_id": "bugsinpy/pandas/5"},
            "implementation": {"diff": "supplied change"}, "outcome": "secret-outcome"}
        action = {"runner": "pytest", "args": ["tests/test_example.py::test_original"],
            "view": {"text": "original test body", "source_files": {"test.py": {"sha256": "a" * 64}}},
            "outcome": "secret-outcome"}
        row, error = source_only_row(case, action, "b" * 64)
        self.assertIsNone(error)
        self.assertEqual(row["labels"], {"action_usefulness": None})
        self.assertEqual(row["split"], "train")
        self.assertNotIn("secret-outcome", row["text"])
        for name, text in (("change", "supplied change"), ("action", "original test body")):
            start, end = row["input_regions"][name]
            self.assertEqual(row["text"][start:end], text)
        action["args"] = ["tests/test_example.py::test_other"]
        changed, _ = source_only_row(case, action, "b" * 64)
        self.assertNotEqual(row["source_id"], changed["source_id"])

    def test_oversize_and_missing_source_remain_unavailable(self):
        case = {"bug": {"group_id": "bugsinpy/pandas/5"}, "implementation": {"diff": "x"}}
        action = {"runner": "pytest", "args": ["test.py"], "view": None}
        self.assertEqual(source_only_row(case, action, "b" * 64), (None, "source_view_unavailable"))
        action["view"] = {"text": "x" * 131072, "source_files": {}}
        self.assertEqual(source_only_row(case, action, "b" * 64),
                         (None, "complete_source_view_exceeds_131072_bytes"))


if __name__ == "__main__":
    unittest.main()
