#!/usr/bin/env python3
"""No external models are loaded in these retrieval metric contract tests."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bakeoff import EvidenceError
from retrieval import ranked_metrics, retrieval_query_kwargs


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


if __name__ == "__main__":
    unittest.main()
