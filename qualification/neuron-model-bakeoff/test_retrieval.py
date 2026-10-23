#!/usr/bin/env python3
"""No external models are loaded in these retrieval metric contract tests."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bakeoff import EvidenceError
from retrieval import ranked_metrics, retrieval_query_kwargs, validate_embeddings


class RetrievalMetricTests(unittest.TestCase):
    def test_perfect_ranking(self):
        self.assertEqual(ranked_metrics(["a", "b", "c"], {"a"}), (1.0, 1.0, 1.0))

    def test_distractor_reduces_mrr_and_ndcg(self):
        mrr, ndcg, recall = ranked_metrics(["b", "a", "c"], {"a"})
        self.assertEqual(mrr, 0.5)
        self.assertTrue(0 < ndcg < 1)
        self.assertEqual(recall, 1.0)

    def test_harrier_query_instruction_must_be_present(self):
        with self.assertRaisesRegex(EvidenceError, "harrier-270m query-side"):
            retrieval_query_kwargs("harrier-270m", {})
        with self.assertRaisesRegex(EvidenceError, "harrier-270m query-side"):
            retrieval_query_kwargs("harrier-270m", {"web_search_query": ""})

    def test_harrier_query_only_prompt(self):
        options = retrieval_query_kwargs(
            "harrier-270m", {"web_search_query": "Instruct: Retrieve relevant passages\\nQuery: "},
        )
        self.assertEqual(options, {"prompt_name": "web_search_query"})
        self.assertEqual(retrieval_query_kwargs(
            "arctic-embed-305m", {"query": "query: "},
        ), {"prompt_name": "query"})

    def test_arctic_query_instruction_must_be_present(self):
        with self.assertRaisesRegex(EvidenceError, "arctic-embed-305m query-side"):
            retrieval_query_kwargs("arctic-embed-305m", {})
        with self.assertRaisesRegex(EvidenceError, "arctic-embed-305m query-side"):
            retrieval_query_kwargs("arctic-embed-305m", {"query": ""})

    def test_missing_relevant_document(self):
        self.assertEqual(ranked_metrics(["a", "b"], {"c"}), (0.0, 0.0, 0.0))

    def test_normalized_embeddings_are_valid(self):
        self.assertEqual(validate_embeddings([[1.0, 0.0], [0.6, 0.8]], 2), 2)

    def test_empty_or_incomplete_embedding_batch_fails(self):
        for vectors, count in (([], 0), ([], 1), ([[1.0, 0.0]], 2)):
            with self.subTest(vectors=vectors, count=count):
                with self.assertRaisesRegex(EvidenceError, "row count"):
                    validate_embeddings(vectors, count)

    def test_wrong_width_or_ragged_embeddings_fail(self):
        for vectors, width in (([[1.0, 0.0]], 3), ([[1.0, 0.0], [1.0]], 2), ([[]], None)):
            with self.subTest(vectors=vectors):
                with self.assertRaisesRegex(EvidenceError, "dimension"):
                    validate_embeddings(vectors, len(vectors), width)

    def test_nonfinite_and_nonunit_embeddings_fail(self):
        for vector in ([float("nan"), 0], [float("inf"), 0], [0, 0], [2, 0]):
            with self.subTest(vector=vector):
                with self.assertRaises(EvidenceError):
                    validate_embeddings([vector], 1)


if __name__ == "__main__":
    unittest.main()
