"""Stdlib receipt tests; fixture answers are not native Reader observations."""

import copy
import unittest

from system2_reader_outcome_audit import ARMS, READER, analyze


def fixture():
    plan = dict(
        arms=list(ARMS),
        production_accepted=False,
        reader_inventory=READER,
        groups=[dict(family="f", support_ids=["s0", "s1"], query_ids=["q0", "q1"])],
        excluded_question_ids=["old"],
        planned_queries=2,
        planned_answers=16,
    )
    raw, scored = [], []
    for q in ("q0", "q1"):
        for arm in ARMS:
            selected = [] if arm == "no_evidence" else [0]
            rec = dict(
                reader_identity=READER,
                reader_profile="profile",
                query_digest=q,
                input_ids_digest=q + arm,
                generated_ids_digest="emission",
                token_limit=4096,
                answer_postprocessed=False,
                trainable_parameters=0,
                omitted_evidence_bytes=0,
                production_accepted=False,
                semantic_sufficiency=None,
                semantic_citation_precision=None,
                delivered_evidence=[{} for _ in selected],
                input_tokens=100,
                generated_tokens=3,
                seconds=0.1,
            )
            row = dict(
                query_id=q,
                family="f",
                arm=arm,
                status="succeeded",
                reader_attempted=True,
                selected=selected,
                feature_digest=q + "-feature",
                answer="original",
                receipt=rec,
                seconds=0.2,
            )
            raw.append(row)
            scored.append(
                copy.deepcopy(row)
                | dict(
                    diagnostic_f1=0.5,
                    weak_source_hit=bool(selected),
                    native_unanswerable=False,
                    source_labels_unresolved=False,
                    semantic_correctness_independently_verified=False,
                )
            )
    return plan, raw, scored


class OutcomeTests(unittest.TestCase):
    def test_complete_census_and_distinct_metrics(self):
        report = analyze(*fixture())
        self.assertEqual(report["recorded"], 16)
        self.assertEqual(report["unique_queries"], 2)
        self.assertEqual(report["by_arm"]["no_evidence"]["source_hits"], 0)
        self.assertEqual(report["by_arm"]["no_evidence"]["conditional_f1"], 0.5)
        self.assertFalse(report["production_accepted"])

    def test_missing_and_duplicate_rows_reject(self):
        plan, raw, scored = fixture()
        for rows in (raw[:-1], raw + raw[:1]):
            with self.assertRaises(ValueError):
                analyze(plan, rows, scored)

    def test_scoring_cannot_rewrite_answer_or_receipt(self):
        for key in ("answer", "receipt", "selected"):
            plan, raw, scored = fixture()
            scored[0][key] = "rewritten"
            with self.assertRaises(ValueError):
                analyze(plan, raw, scored)

    def test_unknown_keeps_full_bounds(self):
        plan, raw, scored = fixture()
        scored[0]["diagnostic_f1"] = None
        observed = analyze(plan, raw, scored)["by_arm"]["frozen"]
        self.assertEqual(observed["scored"], 1)
        self.assertEqual(observed["f1_bounds"], [0.25, 0.75])

    def test_failure_is_not_scored_or_removed(self):
        plan, raw, scored = fixture()
        raw[0]["status"] = scored[0]["status"] = "failed"
        with self.assertRaises(ValueError):
            analyze(plan, raw, scored)
        scored[0]["diagnostic_f1"] = scored[0]["weak_source_hit"] = None
        self.assertEqual(analyze(plan, raw, scored)["by_arm"]["frozen"]["failed"], 1)

    def test_invalid_numeric_and_fabricated_semantic_verdict(self):
        for key, value in (
            ("diagnostic_f1", True),
            ("diagnostic_f1", float("nan")),
            ("weak_source_hit", 1),
            ("semantic_correctness_independently_verified", True),
        ):
            plan, raw, scored = fixture()
            scored[0][key] = value
            with self.assertRaises(ValueError):
                analyze(plan, raw, scored)

    def test_query_family_and_shared_features_cannot_drift(self):
        for key, value in (("family", "other"), ("feature_digest", "changed")):
            plan, raw, scored = fixture()
            raw[1][key] = scored[1][key] = value
            with self.assertRaises(ValueError):
                analyze(plan, raw, scored)

    def test_same_request_different_output_not_learning(self):
        plan, raw, scored = fixture()
        for rows in (raw, scored):
            rows[1]["receipt"]["input_ids_digest"] = rows[0]["receipt"][
                "input_ids_digest"
            ]
            rows[1]["answer"] = "different"
        with self.assertRaises(ValueError):
            analyze(plan, raw, scored)

    def test_mixed_reader_and_boolean_tokens_rejected(self):
        for key, value in (("reader_profile", "other"), ("generated_tokens", True)):
            plan, raw, scored = fixture()
            for rows in (raw, scored):
                rows[0]["receipt"][key] = value
            with self.assertRaises(ValueError):
                analyze(plan, raw, scored)

    def test_support_query_overlap_or_old_query_rejected(self):
        for old in (False, True):
            plan, raw, scored = fixture()
            if old:
                plan["excluded_question_ids"].append("q0")
            else:
                plan["groups"][0]["support_ids"][0] = "q0"
            with self.assertRaises(ValueError):
                analyze(plan, raw, scored)


if __name__ == "__main__":
    unittest.main()
