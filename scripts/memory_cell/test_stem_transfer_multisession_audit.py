import copy
import unittest
from stem_transfer_multisession_audit import audit_transfer_support


def fixture():
    qids = [f"longmemeval:q{i}" for i in range(8)]
    plan = {"questions": {"transfer": qids}}
    native = []
    policy = []
    for i, q in enumerate(qids):
        sid = f"support-{i}"
        required = [sid, "other-" + str(i)] if i < 4 else [sid]
        native.append(
            dict(
                question_id=q.split(":")[1],
                haystack_session_ids=required + ["distractor"],
                answer_session_ids=required,
                answer="literal target",
            )
        )
        evidence = [
            dict(original_id=q + "/" + sid, excerpt="some short evidence")
        ]  # one window
        policy.append(
            dict(
                stage=48,
                arm="frozen_rerank",
                phase="transfer",
                question_id=q,
                status="succeeded",
                selected=0,
                source_choice_correct=1,
                receipt=dict(delivered_evidence=evidence),
            )
        )
    return plan, policy, native


class CeilingTests(unittest.TestCase):
    def test_multi_support_cannot_fit_one_delivery(self):
        r = audit_transfer_support(*fixture())
        self.assertEqual(r["answerable_questions"], 8)
        self.assertEqual(r["answerable_with_multiple_annotated_sessions"], 4)
        self.assertEqual(r["answerable_with_native_support_selected"], 8)
        self.assertEqual(
            r["supporting_document_selected_but_multiple_sessions_required"], 4
        )
        self.assertEqual(
            r["supporting_document_selected_with_full_answer_literal_in_excerpt"], 0
        )
        self.assertFalse(r["production_accepted"])

    def test_no_answer_does_not_count_as_retrieval_gain(self):
        p, rr, d = fixture()
        p["questions"]["transfer"][-1] = "longmemeval:q7_abs"
        rr[-1]["question_id"] = "longmemeval:q7_abs"
        rr[-1]["source_choice_correct"] = 0
        rr[-1]["receipt"]["delivered_evidence"][0]["original_id"] = (
            "longmemeval:q7_abs/support-7"
        )
        d[-1]["question_id"] = "q7_abs"
        x = audit_transfer_support(p, rr, d)
        self.assertEqual(x["unanswerable_questions"], 1)
        self.assertEqual(x["answerable_with_native_support_selected"], 7)

    def test_missing_duplicate_and_fabricated_native_sources_reject(self):
        for mode in ("missing", "duplicate", "dangling"):
            p, rr, d = fixture()
            if mode == "missing":
                d.pop()
            elif mode == "duplicate":
                d.append(copy.deepcopy(d[0]))
            else:
                d[0]["answer_session_ids"].append("forged-source")
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                audit_transfer_support(p, rr, d)

    def test_multiple_delivery_or_outside_identity_is_rejected(self):
        for mode in ("two-windows", "outside"):
            p, rr, d = fixture()
            if mode == "two-windows":
                rr[0]["receipt"]["delivered_evidence"] *= 2
            else:
                rr[0]["receipt"]["delivered_evidence"][0]["original_id"] = (
                    "longmemeval:q0/forged"
                )
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                audit_transfer_support(p, rr, d)

    def test_cross_scope_source_identity_and_detached_receipt_fail(self):
        p, rows, native = fixture()
        rows[0]["receipt"]["delivered_evidence"][0]["original_id"] = (
            "another-scope/support-0"
        )
        with self.assertRaisesRegex(ValueError, "unbound"):
            audit_transfer_support(p, rows, native)
        p, rows, native = fixture()
        rows[0]["receipt"] = None
        with self.assertRaisesRegex(ValueError, "missing completed"):
            audit_transfer_support(p, rows, native)

    def test_forged_correctness_does_not_launder_reader_selection(self):
        p, rr, d = fixture()
        rr[0]["source_choice_correct"] = 0
        with self.assertRaisesRegex(ValueError, "scorer"):
            audit_transfer_support(p, rr, d)


if __name__ == "__main__":
    unittest.main()
