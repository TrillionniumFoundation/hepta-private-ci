"""Synthetic scoring fixtures; never model or target-host evidence."""
import math
import unittest

from evaluate import EvidenceError
from run_retrieval import score
from scale_reference import percentile


class ReferenceMetricTests(unittest.TestCase):
    def setUp(self):
        self.corpus = [{"id": f"d{i}"} for i in range(12)]
        self.query = [{"id": "q0", "split": "test",
                       "relevant_doc_ids": ["d0", "d1"]}]

    def test_recall_is_fraction_of_relevant_documents_not_hit_rate(self):
        result = score(self.query, self.corpus, [["d0", "d2"]])
        self.assertEqual(result["recall_at_10"], 0.5)
        self.assertEqual(result["hit_rate_at_10"], 1.0)
        self.assertEqual(result["mrr_at_10"], 1.0)
        self.assertAlmostEqual(result["ndcg_at_10"],
                               1 / (1 + 1 / math.log2(3)))

    def test_query_denominator_cannot_silently_truncate_or_ignore_results(self):
        for results in ([], [["d0"], ["d1"]]):
            with self.subTest(results=results):
                with self.assertRaisesRegex(EvidenceError, "result count"):
                    score(self.query, self.corpus, results)

    def test_duplicate_ranking_cannot_inflate_recall_or_ndcg(self):
        with self.assertRaisesRegex(EvidenceError, "duplicate retrieval"):
            score(self.query, self.corpus, [["d0", "d0"]])

    def test_unknown_ranking_document_fails(self):
        with self.assertRaisesRegex(EvidenceError, "missing from corpus"):
            score(self.query, self.corpus, [["unknown"]])

    def test_duplicate_qrel_fails(self):
        self.query[0]["relevant_doc_ids"] = ["d0", "d0"]
        with self.assertRaisesRegex(EvidenceError, "duplicate relevance"):
            score(self.query, self.corpus, [["d0"]])

    def test_cutoff_and_recall_denominator_are_distinct(self):
        self.query[0]["relevant_doc_ids"] = [f"d{i}" for i in range(12)]
        result = score(self.query, self.corpus,
                       [[f"d{i}" for i in range(12)]])
        self.assertAlmostEqual(result["recall_at_10"], 10 / 12)
        self.assertEqual(result["ndcg_at_10"], 1.0)
        self.query[0]["relevant_doc_ids"] = ["d10"]
        result = score(self.query, self.corpus,
                       [[f"d{i}" for i in range(12)]])
        self.assertEqual(result["recall_at_10"], 0.0)

    def test_macro_recall_and_empty_ranking(self):
        query = self.query + [{"id": "q1", "split": "test",
                              "relevant_doc_ids": ["d0"]}]
        result = score(query, self.corpus, [["d0"], []])
        self.assertEqual(result["n"], 2)
        self.assertEqual(result["recall_at_10"], 0.25)
        self.assertEqual(result["hit_rate_at_10"], 0.5)

    def test_reference_module_import_and_percentile(self):
        # Importing the real module also checks the repaired function indentation.
        self.assertEqual(percentile([30, 10, 20], 50), 20)
        self.assertEqual(percentile([1, 3], 95), 2.9)


if __name__ == "__main__":
    unittest.main()
