"""Small behavioral checks; scientific results come only from actual SciFact."""
from collections import Counter
import hashlib
import unittest

from prepare import families, normalized
from retrieve import Index, fuse
from score import metrics


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.corpus = [{"doc_id": i, "title": title, "abstract": sentences, "structured": False} for i, title, sentences in [(1, "alpha", ["beta alpha", "gamma"]), (2, "alpha beta", ["beta", "delta"]), (3, "gamma", ["gamma delta", "alpha"])]]
        self.index = Index(self.corpus)

    def test_bm25_and_empty_graph_fusion(self):
        ordering = self.index.bm25("beta")
        self.assertEqual(ordering, [2, 1])
        self.assertEqual(fuse(ordering, []), ordering)

    def test_permutation_preserves_incidence_degree_distribution(self):
        before = Counter(map(len, self.index.features.values()))
        after = Counter(len(self.index.features[self.index.permutation[d]]) for d in self.index.ids)
        self.assertEqual(before, after)
        self.assertEqual(set(self.index.permutation.values()), set(self.index.ids))

    def test_whole_sentence_byte_budget_and_gold_rationale(self):
        corpus = [{"doc_id": 1, "title": "alpha", "abstract": ["alpha " + "é" * 3000, "alpha beta", "gamma"], "structured": False}]
        index = Index(corpus)
        context = index.pack("alpha", [1])
        self.assertEqual(context["sentences"], [[1, 1], [1, 2]])
        self.assertLessEqual(context["utf8_bytes"], 4096)
        pred = {"ranked_doc_ids": [1], "context": context}
        evidence = {"1": [{"sentences": [0, 1], "label": "SUPPORT"}]}
        result = metrics(pred, evidence)
        self.assertEqual((result["all_gold_docs_hit@5"], result["context_any_complete_rationale"]), (1.0, 0.0))
        self.assertIsNone(metrics(pred, {}))

    def test_source_family_link_and_unknown_component_quarantine_inputs(self):
        claims = [{"id": i, "claim": text, "cited_doc_ids": cited, "evidence": {}} for i, text, cited in [(1, "one", [9]), (2, "two", [9]), (3, "three", [10])]]
        source_map = {hashlib.sha256(normalized("one").encode()).hexdigest(): {"44"}, hashlib.sha256(normalized("three").encode()).hexdigest(): {"55"}}
        groups, missing = families(claims, source_map)
        self.assertEqual((groups, missing), ([[1, 2], [3]], {2}))


if __name__ == "__main__":
    unittest.main()
