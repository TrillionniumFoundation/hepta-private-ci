"""Pre-label frozen candidate inventory and zero-recall controls."""
from copy import deepcopy
from hashlib import sha256
import unittest

from amcn_core import Evidence, Refused
from amcn_source_first import lexical_shortlist, source_first_weak_score


def evidence(name, content, revoked=False):
    return Evidence(name, "root-" + name, "test-scope", 1, content,
                    sha256(content.encode()).hexdigest(),
                    "generation-one", revoked)


class SourceFirstNoOracleTests(unittest.TestCase):
    def sources(self):
        return [
            evidence("support", "database deadlock due to transaction locks"),
            evidence("irrelevant", "rainbow sunshine landscape"),
            evidence("competing", "database transaction connection pool"),
        ]

    def test_unlabelled_plan_independent_of_source_order_and_future_labels(self):
        docs = self.sources()
        a = lexical_shortlist("database deadlock", docs, scope="test-scope",
                              generation="generation-one", top_k=2)
        b = lexical_shortlist("database deadlock", list(reversed(docs)),
                              scope="test-scope", generation="generation-one",
                              top_k=2)
        self.assertEqual(a, b)
        self.assertEqual(a["ranked_source_ids"][0], "support")
        self.assertFalse(a["labels_accessed"])
        self.assertEqual(a["eligible_source_count"], 3)
        # Externally supplied publisher references are opened only in scoring.
        c = source_first_weak_score(a, ["support"])
        self.assertTrue(c["lexical_hit_at_1"])
        self.assertTrue(c["lexical_any_hit_at_k"])
        self.assertFalse(c["publisher_support_is_human_entailment"])

    def test_zero_hit_and_nonanswerable_denominators_survive(self):
        docs = self.sources()
        a = lexical_shortlist("database deadlock", docs, scope="test-scope",
                              generation="generation-one", top_k=1)
        no_hit = source_first_weak_score(a, ["unretrieved-but-publisher-supported"])
        self.assertEqual(no_hit["publisher_support_in_shortlist"], 0)
        self.assertFalse(no_hit["lexical_any_hit_at_k"])
        self.assertEqual(no_hit["publisher_recall_at_k"], 0.0)
        annotated_empty = source_first_weak_score(a, [])
        self.assertIsNone(annotated_empty["publisher_recall_at_k"])
        self.assertIsNone(annotated_empty["independent_test_success"])

    def test_duplicate_changed_revoked_or_foreign_sources_refused(self):
        docs = self.sources()
        for variant in (
            [docs[0], docs[0]],
            [docs[0], evidence("expired", "some other text", revoked=True)],
            [docs[0], Evidence("foreign", "root-foreign", "wrong-scope", 1, "text",
                               sha256(b"text").hexdigest(), "generation-one")],
        ):
            with self.assertRaises(Refused):
                lexical_shortlist("query", variant, scope="test-scope",
                                  generation="generation-one")
        a = lexical_shortlist("deadlock", docs, scope="test-scope",
                              generation="generation-one")
        damaged = deepcopy(a)
        damaged["ranked_source_ids"].append("bogus")
        with self.assertRaises(Refused):
            source_first_weak_score(damaged, ["support"])

    def test_preplanned_budget_never_silent_truncation(self):
        with self.assertRaises(Refused):
            lexical_shortlist("query", self.sources(), scope="test-scope",
                              generation="generation-one", top_k=17)
        with self.assertRaises(Refused):
            lexical_shortlist("query", self.sources() * 3000, scope="test-scope",
                              generation="generation-one", top_k=16)


if __name__ == "__main__":
    unittest.main()
