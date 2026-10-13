"""Synthetic protocol regressions; never publisher or independent semantic results."""

from copy import deepcopy
import unittest

from locomo_publisher_support_reader import (
    proposed,
    validate_plan,
    paired_deltas,
    checked_disposition,
    SCHEMA,
)
from locomo_ninearm_source_replay import ZIPS


def cases():
    questions = []
    documents = {}
    targets = {}
    for i in range(16):
        qid = f"q{i}"
        scope = f"scope{i // 8}"
        ids = [f"{qid}-s{j}" for j in range(8)]
        questions.append(
            dict(
                question_id=qid,
                family_proxy_digest=scope,
                scope=scope,
                source_census_sha256=f"pool{i}",
                source_ids=ids,
            )
        )
        for key in ids:
            documents[key] = dict(scope=scope)
        targets[qid] = dict(
            unanswerable=False, support=[ids[-1]], unresolved_support=[], answer="blue"
        )
    targets["q0"] = dict(
        unanswerable=True, support=[], unresolved_support=[], answer=""
    )
    targets["q1"] = dict(
        unanswerable=False,
        support=[],
        unresolved_support=[questions[1]["source_ids"][2]],
        answer="blue",
    )
    return questions, documents, targets


def payload(c, d, t):
    return dict(
        schema=SCHEMA + ".plan.v1",
        cases=proposed(c, d, t),
        original_public_zip_sha256=ZIPS["public"][1],
        original_decisions_zip_sha256=ZIPS["decisions"][1],
        publisher_target_zip_sha256=ZIPS["evaluation"][1],
        publisher_targets_sha256="a" * 64,
        publisher_support_selection_is_privileged=True,
        retrieval_policy_comparator=False,
        model_receives_answer_text=False,
        independent_source_review=False,
        production_accepted=False,
    )


class PrivilegedSupportTests(unittest.TestCase):
    def test_support_only_stays_in_original_scope_and_no_answer_in_plan(self):
        c, d, t = cases()
        p = payload(c, d, t)
        rows = validate_plan(p, c, d)
        self.assertEqual(rows[0]["mode"], "unanswerable_empty")
        self.assertEqual(rows[1]["mode"], "support_unavailable")
        self.assertEqual(rows[2]["selected"], [c[2]["source_ids"][-1]])
        self.assertNotIn('"answer"', str(p))
        self.assertFalse(p["production_accepted"])

    def test_no_support_is_not_unanswerable_and_missing_stays_unknown(self):
        c, d, t = cases()
        t["q3"]["support"] = []
        rows = proposed(c, d, t)
        self.assertEqual(rows[3]["mode"], "support_unavailable")
        self.assertEqual(rows[3]["selected"], [])

    def test_gold_answer_or_label_smuggling_rejected_in_generation_plan(self):
        c, d, t = cases()
        p = payload(c, d, t)
        p["answer"] = "blue"
        with self.assertRaises(ValueError):
            validate_plan(p, c, d)
        del p["answer"]
        p["cases"][2]["gold"] = "blue"
        with self.assertRaises(ValueError):
            validate_plan(p, c, d)

    def test_out_of_scope_duplicate_or_partial_source_never_admitted(self):
        c, d, t = cases()
        for mode in ("cross_scope", "duplicate", "partial"):
            changed = deepcopy(t)
            if mode == "cross_scope":
                changed["q2"]["support"] = [c[3]["source_ids"][-1]]
            elif mode == "duplicate":
                changed["q2"]["support"] = [c[2]["source_ids"][-1]] * 2
            else:
                changed["q2"]["unresolved_support"] = [c[2]["source_ids"][0]]
            if mode == "partial":
                self.assertEqual(
                    proposed(c, d, changed)[2]["mode"], "support_unavailable"
                )
            else:
                with self.assertRaises(ValueError):
                    proposed(c, d, changed)

    def test_changed_selection_pool_and_family_are_rejected(self):
        c, d, t = cases()
        for key, value in (
            ("selected", ["unrelated"]),
            ("mode", "unanswerable_empty"),
            ("family_proxy_digest", "other"),
        ):
            p = payload(c, d, t)
            p["cases"][2][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_plan(p, c, d)

    def test_two_previous_reader_arms_have_full_missing_denominator(self):
        c, d, t = cases()
        p = payload(c, d, t)
        rows = []
        old = []
        for case, planned in zip(c, p["cases"], strict=True):
            qid = case["question_id"]
            rows.append(
                dict(
                    question_id=qid,
                    status="unavailable"
                    if planned["mode"] == "support_unavailable"
                    else "succeeded",
                    answer="blue",
                )
            )
            for arm in ("lexical_k4", "lexical_k8"):
                old.append(
                    dict(
                        question_id=qid,
                        arm=arm,
                        status="succeeded",
                        selected=case["source_ids"][:4],
                        answer="red",
                    )
                )
        out = paired_deltas(c, rows, old, t)
        self.assertEqual(out["lexical_k4"]["all"]["planned"], 16)
        self.assertEqual(out["lexical_k4"]["all"]["missing_or_unscored"], 1)
        self.assertTrue(
            out["lexical_k8"]["all"]["missing_bounds_are_not_confidence_intervals"]
        )
        self.assertEqual(out["lexical_k4"]["answerable"]["planned"], 15)
        self.assertEqual(out["lexical_k4"]["support_missing_by_k4"]["planned"], 14)

    def test_unavailable_source_cannot_become_a_fake_model_attempt(self):
        self.assertEqual(
            checked_disposition(
                "support_unavailable",
                {"status": "unavailable", "reason": "incomplete_publisher_support"},
            ),
            "unavailable",
        )
        for bad in (
            {"status": "failed", "error_type": "TimeoutError"},
            {"status": "succeeded", "answer": "guess"},
            {"status": "unavailable", "answer": "fake"},
            {"status": "unavailable", "reason": "gold_available"},
        ):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                checked_disposition("support_unavailable", bad)
        with self.assertRaises(ValueError):
            checked_disposition("publisher_support", {"status": "unavailable"})
        with self.assertRaises(ValueError):
            checked_disposition("publisher_support", {"status": "failed"})

    def test_unanswerable_with_publisher_support_is_explicit_refusal_control(self):
        c, d, t = cases()
        t["q0"]["support"] = [c[0]["source_ids"][0]]
        p = payload(c, d, t)
        admitted = validate_plan(p, c, d)
        self.assertEqual(admitted[0]["mode"], "publisher_refusal_support")
        self.assertEqual(admitted[0]["selected"], [c[0]["source_ids"][0]])
        self.assertEqual(admitted[0]["support_count"], 1)
        self.assertNotIn('"answer"', str(p))
        self.assertFalse(p["model_receives_answer_text"])
        p["cases"][0]["mode"] = "unanswerable_empty"
        with self.assertRaises(ValueError):
            validate_plan(p, c, d)
        del c[-1]
        with self.assertRaises(ValueError):
            proposed(c, d, t)

    def test_refusal_with_native_support_cannot_be_rewritten_as_unavailable(self):
        c, d, t = cases()
        t["q0"]["support"] = [c[0]["source_ids"][0]]
        p = payload(c, d, t)
        p["cases"][0]["mode"] = "support_unavailable"
        p["cases"][0]["selected"] = []
        # A resolved 1..8 source set cannot be silently laundered as
        # unavailable, even when the tamperer removes selected IDs.
        with self.assertRaises(ValueError):
            validate_plan(p, c, d)
        with self.assertRaises(ValueError):
            checked_disposition(
                "publisher_refusal_support",
                {"status": "unavailable", "reason": "incomplete_publisher_support"},
            )
        self.assertEqual(
            checked_disposition(
                "publisher_refusal_support",
                {"status": "failed", "error_type": "RuntimeError"},
            ),
            "failed",
        )

    def test_native_supported_refusal_keeps_two_family_denominator(self):
        c, d, t = cases()
        for qid, index in (("q0", 0), ("q4", 4), ("q8", 8)):
            t[qid]["unanswerable"] = True
            t[qid]["support"] = [c[index]["source_ids"][0]]
            t[qid]["unresolved_support"] = []
        rows = proposed(c, d, t)
        self.assertEqual(sum(x["mode"] == "publisher_refusal_support" for x in rows), 3)
        self.assertEqual(sum(x["mode"] == "support_unavailable" for x in rows), 1)
        self.assertTrue(
            all(
                len(x["selected"]) == 1
                for x in rows
                if x["mode"] == "publisher_refusal_support"
            )
        )
        self.assertEqual(len({case["family_proxy_digest"] for case in c}), 2)
        self.assertEqual(len(validate_plan(payload(c, d, t), c, d)), 16)


if __name__ == "__main__":
    unittest.main()
