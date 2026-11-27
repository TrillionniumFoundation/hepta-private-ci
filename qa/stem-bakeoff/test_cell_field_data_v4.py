"""Source-only cleaning, transitive identity closure and balanced role isolation."""

from collections import Counter
import unittest

from cell_field_data_v4 import clean_message, connected_components, select_candidates


class FreshSourceTests(unittest.TestCase):
    def test_headers_quotes_and_footer_removed_before_truncation_or_hashing(self):
        raw = (b"From: hidden@example.org\nSubject: Re: RE: Graphics question\n"
               b"Message-ID: <ABC@example.org>\n\n"
               b"Independent content for the retained message.\n"
               b"> a quoted answer\n  | another quote\nPerson writes:\n"
               b"Second original line.\n-- \nSecret footer and signature")
        body, subject, message_id, date = clean_message(raw)
        self.assertEqual(body, "Independent content for the retained message.\nSecond original line.")
        self.assertEqual((subject, message_id, date), ("graphics question", "<abc@example.org>", False))
        long = b"Subject: x\n\n" + b"content " * 1000
        self.assertGreater(len(clean_message(long)[0]), 6000)
        with self.assertRaises(ValueError):
            clean_message(b"a" * ((2 << 20) + 1))

    def test_transitive_graph_closes_across_labels_and_original_splits(self):
        rows = [{"edges": [("subject", "thread"), ("body", "first")], "split": "train"},
                {"edges": [("subject", "thread"), ("message_id", "m")], "split": "train"},
                {"edges": [("message_id", "m"), ("body", "third")], "split": "test"},
                {"edges": [("body", "other")], "split": "test"}]
        self.assertEqual(connected_components(rows), [[0, 1, 2], [3]])
        # Equal truncated inputs are a link even if full cleaned bodies differ.
        truncated = [{"edges": [("body", "a"), ("truncated_body", "same")]},
                     {"edges": [("body", "b"), ("truncated_body", "same")]}]
        self.assertEqual(connected_components(truncated), [[0, 1]])

    def candidates(self):
        return [{"component_id": f"c{label}-{index}", "label": label,
                 "bucket": "old", "text": "source-only text"}
                for label in range(4) for index in range(6)]

    def test_roles_balanced_disjoint_and_input_order_does_not_select_different_sources(self):
        roles = [{"role": "old_train", "bucket": "old", "rows": 8, "access": "train"},
                 {"role": "old_test", "bucket": "old", "rows": 8, "access": "final"}]
        selected, support = select_candidates(self.candidates(), roles, "synthetic")
        reverse, reverse_support = select_candidates(list(reversed(self.candidates())), roles, "synthetic")
        self.assertEqual((selected, support), (reverse, reverse_support))
        self.assertEqual(len({r["component_id"] for r in selected}), 16)
        for role in ("old_train", "old_test"):
            self.assertEqual(Counter(r["label"] for r in selected if r["role"] == role), {i: 2 for i in range(4)})

    def test_source_exhaustion_is_explicit_without_replacement_or_class_dropping(self):
        roles = [{"role": "old_train", "bucket": "old", "rows": 28, "access": "train"}]
        with self.assertRaisesRegex(ValueError, "insufficient"):
            select_candidates(self.candidates(), roles, "synthetic")


if __name__ == "__main__":
    unittest.main()
