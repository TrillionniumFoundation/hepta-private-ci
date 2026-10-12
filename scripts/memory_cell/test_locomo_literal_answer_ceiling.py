"""Synthetic byte-exact locked k4/k8 answer-surface diagnostics; no model."""

from copy import deepcopy
import unittest

from locomo_literal_answer_ceiling import (
    audit_locked_literal_capacity, literal_occurs, sealed_candidates,
)


def fixture():
    docs, cases, decisions, targets = {}, [], {}, {}
    for i in range(16):
        qid = f"q-{i}"
        scope = f"scope-{i}"
        family = "family-1" if i < 8 else "family-2"
        identities = []
        for j in range(8):
            sid = f"{qid}/D{j}"
            identities.append(sid)
            # q0 is support outside k4 but inside k8. q2 has annotated
            # document support but no literal answer occurrence.
            answer_text = "An unrelated historical note."
            if (i == 0 and j == 6) or (i not in (0, 2) and j == 0):
                answer_text = "The exact destination was Tokyo."
            docs[sid] = dict(identity=sid, scope=scope, content=answer_text)
        case = dict(
            question_id=qid, scope=scope, family_proxy_digest=family,
            source_census_sha256="sealed-" + qid,
            source_ids=identities,
        )
        cases.append(case)
        for arm, k in (("lexical_k4", 4), ("lexical_k8", 8)):
            selected = identities[:k]
            decisions[(qid, arm)] = dict(
                question_id=qid, arm=arm, selected=selected,
                source_census_sha256=case["source_census_sha256"],
                family_proxy_digest=family,
                selected_source_bytes=sum(
                    len(docs[x]["content"].encode("utf-8")) for x in selected
                ),
            )
        targets[qid] = dict(
            answer="Osaka" if i == 2 else "Tokyo",
            support=[identities[6] if i == 0 else identities[0]],
            unanswerable=i == 3,
            unresolved_support=["unreviewed"] if i == 4 else [],
        )
    return cases, docs, decisions, targets


class LiteralAccessibleTests(unittest.TestCase):
    def test_two_pinned_frozen_source_prefixes_and_actual_denominators(self):
        cases, docs, decisions, targets = fixture()
        lock = sealed_candidates(cases, docs, decisions)
        receipt = audit_locked_literal_capacity(lock, docs, targets)
        four, eight = (
            receipt["per_arm"][arm] for arm in ("lexical_k4", "lexical_k8")
        )
        self.assertEqual(four["planned"], 16)
        self.assertEqual(eight["planned"], 16)
        self.assertEqual(four["weak_document_support_evaluable"], 14)
        self.assertEqual(four["full_weak_source_covered"], 13)
        self.assertEqual(eight["full_weak_source_covered"], 14)
        self.assertEqual(four["literal_in_selected_sources"], 12)
        self.assertEqual(eight["literal_in_selected_sources"], 13)
        self.assertEqual(four["literal_missing_from_source_pool"], 1)
        self.assertEqual(receipt["reader_executions"], 0)
        self.assertIsNone(receipt["semantic_citation_precision"])
        self.assertFalse(receipt["production_accepted"])

    def test_literal_boundary_unicode_and_large_original_history(self):
        self.assertFalse(literal_occurs("Ann", "Anna moved to London"))
        self.assertTrue(literal_occurs("Tokyo", "From Tokyo, with love"))
        self.assertTrue(literal_occurs("CAFÉ", "The café is open"))
        self.assertTrue(literal_occurs("Tokyo", "a" * 20000 + " Tokyo."))
        with self.assertRaises(ValueError):
            literal_occurs("Tokyo", "a" * 1048577)

    def test_unanswerable_unresolved_and_paraphrase_not_recovered_as_literal(self):
        cases, docs, decisions, targets = fixture()
        receipt = audit_locked_literal_capacity(
            sealed_candidates(cases, docs, decisions), docs, targets
        )
        rows = {(x["question_id"], x["arm"]): x for x in receipt["rows"]}
        self.assertFalse(rows[("q-3", "lexical_k8")]["literal_answer_comparable"])
        self.assertFalse(rows[("q-4", "lexical_k8")]["literal_answer_comparable"])
        self.assertEqual(
            rows[("q-2", "lexical_k8")]["weak_full_document_support_selected"],
            True,
        )
        self.assertFalse(
            rows[("q-2", "lexical_k8")]["literal_answer_in_selected_source_text"]
        )

    def test_rank_order_budget_and_scope_mutations_reject_without_labels(self):
        for mutation in ("prefix", "bytes", "source", "duplicate", "scope"):
            cases, docs, decisions, _ = fixture()
            if mutation == "prefix":
                decisions[("q-0", "lexical_k4")]["selected"].reverse()
            elif mutation == "bytes":
                decisions[("q-0", "lexical_k4")]["selected_source_bytes"] += 1
            elif mutation == "source":
                decisions[("q-0", "lexical_k4")]["selected"][0] = "invented"
            elif mutation == "duplicate":
                cases[1]["question_id"] = "q-0"
            else:
                docs["q-0/D0"]["scope"] = "other-scope"
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                sealed_candidates(cases, docs, decisions)

    def test_targets_cannot_enter_unsealed_or_differently_bound_source_plan(self):
        cases, docs, decisions, targets = fixture()
        locked = sealed_candidates(cases, docs, decisions)
        with self.assertRaises(ValueError):
            audit_locked_literal_capacity(
                locked, docs, {k: v for k, v in targets.items() if k != "q-0"}
            )
        altered = deepcopy(locked)
        altered["cases"][0]["lexical_k4"][0] = "another-source"
        with self.assertRaisesRegex(ValueError, "sealed"):
            audit_locked_literal_capacity(altered, docs, targets)
        corrupted = deepcopy(locked)
        corrupted["label_bytes_read_before_seal"] = True
        with self.assertRaises(ValueError):
            audit_locked_literal_capacity(corrupted, docs, targets)

    def test_answer_missing_or_oversized_never_becomes_perfect_literal(self):
        cases, docs, decisions, targets = fixture()
        targets["q-1"]["answer"] = "a" * 9000
        targets["q-5"]["answer"] = None
        receipt = audit_locked_literal_capacity(
            sealed_candidates(cases, docs, decisions), docs, targets
        )
        by_question = {(row["question_id"], row["arm"]): row
                       for row in receipt["rows"]}
        for qid in ("q-1", "q-5"):
            self.assertFalse(
                by_question[(qid, "lexical_k8")]["literal_answer_comparable"]
            )
        self.assertEqual(
            receipt["per_arm"]["lexical_k8"]["weak_document_support_evaluable"], 14
        )


if __name__ == "__main__":
    unittest.main()
