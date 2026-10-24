"""No fitted vocabulary, no metadata predictors and exact source field binding."""

import unittest
import hashlib

import numpy as np

from operational_field_features import baseline_definition, clean_fields, source_only_features
from operational_source_regions import ACTION_PREFIX
from test_operational_source_regions import DIFF, TEST_A


def action_fixture():
    test = TEST_A.split("\n", 1)[1]
    head = ACTION_PREFIX + DIFF + "\nACTION\n" + TEST_A.split("\n", 1)[0] + "\n"
    text = head + test
    return text, {"change": [len(ACTION_PREFIX), len(ACTION_PREFIX) + len(DIFF)],
                  "action": [len(head), len(text)]}


class FieldFeatureTests(unittest.TestCase):
    def test_exact_clean_field_slices_and_fixed_source_only_shapes(self):
        text, spans = action_fixture()
        _, fields, receipt = clean_fields(text, spans)
        self.assertNotIn("private_project", fields["change"])
        self.assertNotIn("hidden_project", fields["test"])
        self.assertEqual(receipt["source_sha256"], hashlib.sha256(text.encode()).hexdigest())
        features, scalars, counts = source_only_features(text, spans)
        self.assertEqual(features.shape, (770,))
        np.testing.assert_array_equal(scalars, np.asarray([.5, 2 / 3, 2 / 3], np.float32))
        self.assertEqual(counts["hash_accounting"]["change"]["identifiers"], 3)
        for value in (features, scalars):
            with self.assertRaises(ValueError):
                value.setflags(write=True)

    def test_explicit_spans_reject_rebinding_or_empty_source(self):
        text, spans = action_fixture()
        bad = {name: list(value) for name, value in spans.items()}
        bad["action"][0] += 1
        with self.assertRaisesRegex(ValueError, "template"):
            clean_fields(text, bad)
        bad = {name: list(value) for name, value in spans.items()}
        bad["change"][0] = True
        with self.assertRaisesRegex(ValueError, "integer"):
            clean_fields(text, bad)
        with self.assertRaises(ValueError):
            clean_fields(text + "\nlabel=1", spans)

    def test_header_path_changes_do_not_change_numeric_identifier_features(self):
        text, spans = action_fixture()
        other = text.replace("hidden_project", "another_project")
        delta = len(other) - len(text)
        new_spans = {"change": list(spans["change"]),
                     "action": [spans["action"][0] + delta // 2, len(other)]}
        first, scalar_first, _ = source_only_features(text, spans)
        second, scalar_second, _ = source_only_features(other, new_spans)
        np.testing.assert_array_equal(first, second)
        np.testing.assert_array_equal(scalar_first, scalar_second)
        self.assertNotEqual(baseline_definition("identifier_hash770")[1],
                            baseline_definition("identifier_overlap3")[1])


if __name__ == "__main__":
    unittest.main()
