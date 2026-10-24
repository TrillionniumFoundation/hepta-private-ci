"""Exercise source selection, local weights and candidate-order symmetry."""

import unittest

import numpy as np

from long_document_sources import sha
from operational_source_regions import (ACTION_PREFIX, CHOICE_PREFIX, REGRESSION_PREFIX,
    feature_definition, identifiers, parse_regions, pool_region, readout_features)


DIFF = ("diff --git a/private_project.py b/private_project.py\n--- a/private_project.py\n"
    "+++ b/private_project.py\n@@ -1,3 +1,3 @@\n unchanged_context()\n-old_name(value)\n+new_name(value)\n")
TEST_A = "COMMAND pytest hidden_project/test_a.py\nTEST SOURCE hidden_project/test_a.py\ndef test_a():\n    old_name(value)\n"
TEST_B = "COMMAND pytest hidden_project/test_b.py\nTEST SOURCE hidden_project/test_b.py\ndef test_b():\n    unrelated(other)\n"


def choice(a=TEST_A, b=TEST_B):
    return CHOICE_PREFIX + DIFF + "\nACTION 0\n" + a + "\nACTION 1\n" + b


class SourceRegionTests(unittest.TestCase):
    def test_changed_source_selection_uses_only_supplied_diff_and_body(self):
        text = choice()
        regions = parse_regions(text)
        self.assertEqual(regions.family, "diagnostic_choice")
        self.assertEqual("".join(text[a:b] for a, b in regions.spans("change")),
                         "old_name(value)\nnew_name(value)\n")
        names = identifiers(text, regions.spans("action0"))
        self.assertEqual(names, {"test_a", "old_name", "value"})
        receipt = regions.receipt(text)
        for fields in receipt["fields"].values():
            for field in fields:
                a, b = field["char_span"]
                e, f = field["utf8_span"]
                self.assertEqual(text.encode()[e:f], text[a:b].encode())
                self.assertEqual(sha(text[a:b].encode()), field["sha256"])

    def test_pointwise_regression_does_not_require_the_other_revision(self):
        text = (REGRESSION_PREFIX + "COMMAND pytest tests.py\nIMPLEMENTATION package.py\n"
                "implementation(α)\n\nTEST SOURCE tests.py\nassert implementation(α)\n")
        regions = parse_regions(text)
        self.assertEqual(regions.family, "regression")
        self.assertEqual("".join(text[a:b] for a, b in regions.spans("implementation")), "implementation(α)\n")
        features = readout_features(regions, {"implementation": np.array([1, 0], np.float32),
            "test": np.array([0, 1], np.float32)}, text)
        np.testing.assert_array_equal(features, [1, 0, 0, 1])
        with self.assertRaises(ValueError):
            features.setflags(write=True)

    def test_exact_source_character_overlap_weights_and_spill_are_measured(self):
        text = "αβγδεζ"
        doc = {"source_utf8_sha256": sha(text.encode()), "source_characters": len(text),
               "chunks": [{"char_span": [0, 4]}, {"char_span": [2, 6]}]}
        values = np.eye(2, dtype=np.float32)
        pooled, receipt = pool_region(text, ((1, 5),), doc, values)
        np.testing.assert_array_equal(pooled, np.asarray([2**-.5, 2**-.5], np.float32))
        self.assertEqual(receipt["chunk_weights"], [2, 2])
        self.assertEqual(receipt["character_weight_sum"], 4)
        self.assertEqual(receipt["unselected_context_characters_in_windows"], 2)
        with self.assertRaises(ValueError):
            pooled[0] = 0
        with self.assertRaisesRegex(ValueError, "source-bound"):
            pool_region(text + "η", ((1, 5),), doc, values)
        with self.assertRaisesRegex(ValueError, "unavailable"):
            pool_region(text, ((1, 5),), doc, np.zeros_like(values))

    def test_action_swap_negates_the_complete_contrast_without_labels(self):
        text, swapped = choice(), choice(TEST_B, TEST_A)
        pools = {"change": np.array([.6, .8], np.float32),
                 "action0": np.array([0, 1], np.float32), "action1": np.array([1, 0], np.float32)}
        original = readout_features(parse_regions(text), pools, text)
        reverse = readout_features(parse_regions(swapped),
            {"change": pools["change"], "action0": pools["action1"], "action1": pools["action0"]}, swapped)
        np.testing.assert_array_equal(reverse, -original)
        self.assertEqual(original.shape, (4,))

    def test_prospective_single_action_does_not_require_candidate_role_or_outcome(self):
        text = ACTION_PREFIX + DIFF + "\nACTION\n" + TEST_A
        regions = parse_regions(text)
        self.assertEqual(regions.family, "diagnostic_action")
        value = readout_features(regions, {"change": np.array([1, 0], np.float32),
                                          "test": np.array([0, 1], np.float32)}, text)
        np.testing.assert_array_equal(value, [0, 0, 1, 1, 0, .5])

    def test_ambiguous_missing_empty_and_uncovered_inputs_are_unavailable(self):
        for text in (choice().replace("+new_name(value)\n", " unchanged()\n").replace("-old_name(value)\n", ""),
                     choice() + "\nACTION 1\n", choice().replace("ACTION 0", "ACTION 7"),
                     "label=1\n" + choice()):
            with self.subTest(text=text[:40]), self.assertRaises(ValueError):
                parse_regions(text)
        doc = {"source_utf8_sha256": sha(b"abcdef"), "source_characters": 6,
               "chunks": [{"char_span": [0, 2]}]}
        with self.assertRaisesRegex(ValueError, "coverage"):
            pool_region("abcdef", ((1, 4),), doc, np.array([[1, 0]], np.float32))
        with self.assertRaisesRegex(ValueError, "intervals"):
            pool_region("abcdef", ((0, 2), (1, 2)), doc, np.array([[1, 0]], np.float32))

    def test_new_identity_binds_parent_width_family_and_implementation(self):
        _, original = feature_definition("a" * 64, 384, "diagnostic_choice")
        for parent, width, family in (("b" * 64, 384, "diagnostic_choice"),
                ("a" * 64, 768, "diagnostic_choice"), ("a" * 64, 384, "diagnostic_action")):
            self.assertNotEqual(feature_definition(parent, width, family)[1], original)


if __name__ == "__main__":
    unittest.main()
