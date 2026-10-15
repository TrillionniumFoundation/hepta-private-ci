"""Scoring tests only; authored fixtures have zero pretrained model executions."""
import hashlib
import unittest

from memory_trial_independent_score import COMMITMENT_SCHEME, commit_identifier, score
from test_memory_trial_admission import fixture


def prepare():
    plan, raw, old_scored = fixture()
    plan["answer_commitment_scheme"] = COMMITMENT_SCHEME
    # One precommitted identifier per case; the original answers for other
    # arms/conditions remain independently generated distinct outputs.
    labels = []
    for case in plan["cases"]:
        selected = next(row for row in raw if row["id"] == case["id"] and
                        row["arm"] == "hybrid_rag" and row["condition"] == "oracle"
                        and row["reader"] == "frozen")
        # Fixture answers contain '|' and are not in the admitted grammar:
        # make an isolated actual-answer analogue with strict identifier.
        selected["answer"] = "site_" + hashlib.sha256(case["id"].encode()).hexdigest()[:8]
        expected = selected["answer"]
        nonce = hashlib.sha256(("fixture-nonce:" + case["id"]).encode()).hexdigest()
        case["answer_sha256"] = commit_identifier(expected, nonce)
        labels.append(dict(id=case["id"], expected=expected, nonce=nonce))
    for source, scored in zip(raw, old_scored, strict=True):
        source["cost"] = scored["cost"]
        source["diagnostic_count"] = scored["diagnostic_count"]
        source["recovery_success"] = scored["recovery_success"]
        if source["id"] == "case-3":
            for name in ("program_exit_code", "program_test_count", "program_tests_passed"):
                source.setdefault(name, scored[name])
    return plan, raw, labels


class UnopenedLabels(list):
    def __iter__(self):
        raise AssertionError("private labels accessed before raw verification")


class ExactScoringTests(unittest.TestCase):
    def test_full_matrix_derived_not_user_supplied(self):
        plan, raw, labels = prepare()
        result, audit = score(plan, raw, labels)
        self.assertEqual(len(result), 160)
        self.assertEqual(audit["recomputed_strict_successes"], 4)
        self.assertEqual(sum(x["success"] for x in result), 4)
        self.assertFalse(audit["human_semantic_review_performed"])
        self.assertFalse(audit["production_qualified"])

    def test_reader_drift_rejected_before_private_gold(self):
        plan, raw, _ = prepare()
        raw[0]["reader_revision"] = "swapped-model"
        with self.assertRaisesRegex(ValueError, "reader model revision drift"):
            score(plan, raw, UnopenedLabels())

    def test_private_gold_stays_closed_on_source_leak(self):
        plan, raw, _ = prepare()
        next(row for row in raw if row["arm"] == "knowledge_only")["raw_source_bytes"] = 1
        with self.assertRaisesRegex(ValueError, "leaked raw source"):
            score(plan, raw, UnopenedLabels())

    def test_private_gold_stays_closed_on_duplicate_model_call(self):
        plan, raw, _ = prepare()
        raw[1]["model_call_id"] = raw[0]["model_call_id"]
        with self.assertRaisesRegex(ValueError, "duplicate original model call"):
            score(plan, raw, UnopenedLabels())

    def test_prohibit_golden_answers_in_generation(self):
        plan, raw, labels = prepare()
        raw[0]["success"] = True
        with self.assertRaisesRegex(ValueError, "leaked scoring"):
            score(plan, raw, labels)

    def test_protected_label_after_freeze_tampering(self):
        plan, raw, labels = prepare()
        labels[0]["expected"] = "site_changed"
        with self.assertRaisesRegex(ValueError, "gold differs"):
            score(plan, raw, labels)

    def test_duplicate_nonce_rejected_before_label_hash(self):
        plan, raw, labels = prepare()
        labels[1]["nonce"] = labels[0]["nonce"]
        with self.assertRaisesRegex(ValueError, "reused protected answer nonce"):
            score(plan, raw, labels)

    def test_all_zero_nonce_rejected(self):
        plan, raw, labels = prepare()
        labels[0]["nonce"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "zero or reused"):
            score(plan, raw, labels)

    def test_missing_commitment_scheme(self):
        plan, raw, labels = prepare()
        del plan["answer_commitment_scheme"]
        with self.assertRaisesRegex(ValueError, "salted pre-exposure"):
            score(plan, raw, labels)

    def test_duplicate_protected_label(self):
        plan, raw, labels = prepare()
        with self.assertRaisesRegex(ValueError, "duplicate protected label"):
            score(plan, raw, labels + labels[:1])

    def test_incomplete_originals(self):
        plan, raw, labels = prepare()
        with self.assertRaisesRegex(ValueError, "incomplete original"):
            score(plan, raw[:-1], labels)

    def test_program_requires_tests_and_correct_answer(self):
        plan, raw, labels = prepare()
        program = next(row for row in raw if row["id"] == "case-3" and
                       row["arm"] == "hybrid_rag" and row["condition"] == "oracle"
                       and row["reader"] == "frozen")
        program["program_tests_passed"] = 2
        scored, audit = score(plan, raw, labels)
        self.assertFalse(next(row for row in scored if row["id"] == "case-3"
                              and row["arm"] == "hybrid_rag" and row["condition"] == "oracle"
                              and row["reader"] == "frozen")["success"])
        self.assertEqual(audit["recomputed_strict_successes"], 3)

    def test_unknown_cost_cannot_be_silently_zero(self):
        plan, raw, labels = prepare()
        raw[0]["cost"]["maintenance"] = None
        # Downstream no-promotion cost gate must preserve unknown, not convert to zero.
        # The original matrix analyzer historically rejected None; this is the
        # regression that requires explicit nullable-cost support in the gate.
        scored, audit = score(plan, raw, labels)
        self.assertIsNone(audit["arms"]["hybrid_rag"]["frozen"]["none"]["total_cost"]["maintenance"])
        self.assertIsNone(audit["amortized_tco"])


if __name__ == "__main__":
    unittest.main()