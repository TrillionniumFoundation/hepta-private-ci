"""Postseal citation-address audit tests; never certify semantic entailment."""
import os
from copy import deepcopy
from pathlib import Path
from unittest import TestCase, main

import memory_reader_source_citation as c
import memory_reader_causal_panel as base


class OriginalSourceCitationTests(TestCase):
    def setUp(self):
        self.plan = {"planned_questions": 20, "requests": []}
        self.responses = []
        for j in range(20):
            qid = f"conv-1/q{j:04d}"
            for arm in base.ARMS:
                request = {"request_id": qid + ':' + arm, "question_id": qid,
                           "arm": arm, "family": "conv-1", "evidence": [{"label": "E1", "source_id": "D1:1", "text": "Paris"},
                                                    {"label": "E2", "source_id": "D1:2", "text": "Rome"}]}
                self.plan["requests"].append(request)
                self.responses.append({"request_id": request["request_id"],
                                       "status": "succeeded", "answer": "Paris [E1]"})
        self.gold = {f"conv-1/q{j:04d}": frozenset({'D1:1'}) for j in range(20)}

    def test_syntactic_source_mapping_does_not_grant_semantic_entailment(self):
        result = c.audit(self.plan, self.responses, self.gold)
        for arm, row in result["by_arm"].items():
            self.assertEqual(row["planned"], 20)
            self.assertEqual(row["in_range_markers_on_publisher_evidence"], 20)
            self.assertEqual(row["publisher_address_agreement_among_known_in_range_citations"], 1.0)
        self.assertFalse(result["human_semantic_entailment_verified"])
        self.assertFalse(result["production_accepted"])

    def test_syntactically_valid_but_source_wrong(self):
        rows = deepcopy(self.responses)
        rows[0]["answer"] = "Not evidence [E2]"
        result = c.audit(self.plan, rows, self.gold)["by_arm"][base.ARMS[0]]
        self.assertEqual(result["in_range_markers_off_publisher_evidence"], 1)
        self.assertEqual(result["in_range_markers_on_publisher_evidence"], 19)
        self.assertEqual(result["publisher_address_agreement_among_known_in_range_citations"], 19/20)

    def test_no_citations_never_means_perfect_precision(self):
        rows = deepcopy(self.responses)
        for item in rows:item["answer"] = "Paris but no citation"
        result = c.audit(self.plan, rows, self.gold)
        for row in result["by_arm"].values():
            self.assertEqual(row["citation_markers"], 0)
            self.assertIsNone(row["publisher_address_agreement_among_known_in_range_citations"])

    def test_unknown_publisher_source_preserved_nullable(self):
        sources = {key: None for key in self.gold}
        result = c.audit(self.plan, self.responses, sources)["by_arm"][base.ARMS[0]]
        self.assertEqual(result["in_range_markers_when_publisher_evidence_unknown"], 20)
        self.assertEqual(result["original_publisher_evidence_available"], 0)
        self.assertIsNone(result["publisher_address_agreement_among_known_in_range_citations"])

    def test_foreign_and_malformed_citation_addresses_denied_as_valid(self):
        rows = deepcopy(self.responses)
        rows[0]["answer"] = "[E0] and [E999] [E00] [E-1] [E1]"
        result = c.audit(self.plan, rows, self.gold)["by_arm"][base.ARMS[0]]
        self.assertEqual(result["invalid_or_foreign_citation_markers"], 4)
        self.assertEqual(result["canonical_in_range_citation_markers"], 20)
        self.assertFalse(result["publisher_address_agreement_among_known_in_range_citations"] is None)

    def test_duplicate_delivery_denied(self):
        p = deepcopy(self.plan)
        p["requests"][0]["evidence"][1]["source_id"] = "D1:1"
        with self.assertRaisesRegex(ValueError, "duplicate delivered"):
            c.audit(p, self.responses, self.gold)

    def test_missing_gold_and_changed_request_order_rejected(self):
        with self.assertRaisesRegex(ValueError, "missing publisher annotation"):
            c.audit(self.plan, self.responses, {})
        changed = deepcopy(self.responses)
        changed[0], changed[1] = changed[1], changed[0]
        with self.assertRaisesRegex(ValueError, "identity drift"):
            c.audit(self.plan, changed, self.gold)

    def test_original_publisher_evidence_corpus_normalization(self):
        originals = {"conv-1": {"qa": [{"evidence":["D1:1"]} for _ in range(20)]}}
        labels = c.publisher_sources(originals, self.plan)
        self.assertEqual(len(labels), 20)
        self.assertEqual(labels['conv-1/q0000'], frozenset({'D1:1'}))
        originals['conv-1']['qa'][0]['evidence']=['not canonical']
        labels = c.publisher_sources(originals, self.plan)
        self.assertIsNone(labels['conv-1/q0000'])

    def test_real_unmodified_135m_original_if_available(self):
        folder = os.environ.get("HEPTA_STRONG_HISTORICAL_RUN")
        source = os.environ.get("HEPTA_MEMORY_ORIGINAL")
        plan_dir = os.environ.get("HEPTA_STRONG_ACTUAL_PLAN")
        if not all((folder, source, plan_dir)):
            self.skipTest('real SHA-pinned original evidence not mounted')
        import memory_reader_strong_reference as strong
        plan, hashvalue = strong.preflight(plan_dir)
        self.assertEqual(hashvalue, strong.HISTORICAL_PLAN_SHA)
        original = base.strict(base.read(source))
        self.assertEqual(base.digest(base.read(source)), base.ORIGINAL_SHA)
        references = c.publisher_sources({rec['sample_id']:rec for rec in original}, plan)
        rows = base.strict(base.read(Path(folder)/'journal.json'))
        result = c.audit(plan, rows, references)
        self.assertEqual(sum(v['citation_markers'] for v in result['by_arm'].values()), 0)
        self.assertTrue(all(v['publisher_address_agreement_among_known_in_range_citations'] is None
                            for v in result['by_arm'].values()))
        self.assertFalse(result['production_accepted'])


if __name__ == '__main__':main()
