import unittest

import numpy as np

from cell_full_text_lexical import FullTextLexical
from cell_learning_baselines import FrozenBaselines


class FullTextLexicalTests(unittest.TestCase):
    def rows(self, texts):
        return [{"source_id": f"source-{i}", "group_id": f"group-{i}", "text": text}
                for i, text in enumerate(texts)]

    def test_short_input_parity_matches_frozen_exact_and_bm25(self):
        rows = self.rows(["alpha alpha beta", "beta gamma", "delta Ωmega", "alpha gamma"])
        query = self.rows(["ALPHA alpha BETA", "gamma unknown", "nothing", "ΩMEGA delta"])
        labels = np.array([0, 1, 0, 1])
        frozen = FrozenBaselines(np.ones((4, 3)), labels, rows, 2)
        complete = FullTextLexical(labels, rows)
        for arm in ("exact", "bm25"):
            a = frozen.predict(arm, np.ones((4, 3)), query)
            b = complete.predict(arm, query)
            self.assertTrue(np.array_equal(a["logits"], b["logits"]))
            self.assertTrue(np.array_equal(a["eligible"], b["eligible"]))
            self.assertEqual(a["retrieved_source_ids"], b["retrieved_source_ids"])

    def test_long_tail_relevance_is_available_only_to_complete_control(self):
        prefix = "padding "*5000
        full_rows = self.rows([prefix+" actionabletail", prefix+" unrelatedtail"])
        labels = np.array([1, 0])
        prefix_rows = [{**row, "text": row["text"][:32768]} for row in full_rows]
        query = self.rows(["actionabletail"])
        bounded = FrozenBaselines(np.ones((2, 3)), labels, prefix_rows, 2)
        complete = FullTextLexical(labels, full_rows)
        short = bounded.predict("bm25", np.ones((1, 3)), query)
        long = complete.predict("bm25", query)
        self.assertFalse(short["eligible"][0])
        self.assertTrue(long["eligible"][0])
        self.assertEqual(int(long["logits"][0].argmax()), 1)
        self.assertEqual(long["retrieved_source_ids"], ["source-0"])
        self.assertGreater(long["cost"]["retained_source_utf8_bytes"], 65536)

    def test_inputs_cannot_include_outcomes_or_unbounded_sources(self):
        rows = self.rows(["first", "second"])
        model = FullTextLexical(np.array([0, 1]), rows)
        with self.assertRaises(ValueError):
            model.predict("bm25", [dict(rows[0], outcome=1)])
        with self.assertRaises(ValueError):
            model.predict("exact", self.rows(["a"*131073]))


if __name__ == "__main__":
    unittest.main()
