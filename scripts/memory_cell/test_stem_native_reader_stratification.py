"""Synthetic support-conditioned Reader contrast; never model or QA evidence."""

from copy import deepcopy
import unittest

from stem_audit_archive import AuditError
from stem_native_reader_stratification import stratify_original_reader
from test_stem_current_strict_readout_audit import fixtures


def example():
    plan, raw, _, _, ceiling = fixtures()
    paired = []
    empty = []
    for original in raw:
        if original["stage"] != 48 or original["arm"] != "frozen_rerank":
            continue
        phase, qid = original["phase"], original["question_id"]
        query = dict(
            identity=qid,
            scope="scope-" + qid,
            content="Original question",
            observed_at="2023-04-10",
        )
        original["receipt"]["observable_query"] = query
        original["receipt"]["delivered_evidence"] = [
            dict(label="E1", scope=query["scope"])
        ]
        empty.append(
            dict(
                phase=phase,
                question_id=qid,
                family=original["family"],
                status="succeeded",
                receipt=dict(
                    observable_query=deepcopy(query),
                    generator_identity="frozen-reader",
                    generator_profile="unchanged-prompt",
                    delivered_evidence=[],
                ),
            )
        )
        native = next(
            x
            for x in ceiling["decisions"]
            if x["phase"] == phase and x["question_id"] == qid
        )
        if native["weak_native_support_resolved"]:
            before = 0.75 if native["frozen_selected_native_support"] else 0.25
            blank = 0.30
        else:
            before = blank = 0.0
        paired.append(
            dict(
                phase=phase,
                question_id=qid,
                family=original["family"],
                frozen_reader_succeeded=True,
                zero_evidence_reader_succeeded=True,
                actual_frozen_evidence_count=1,
                evidence_exposure="one-evidence",
                scored_pair=True,
                frozen_reader_f1=before,
                zero_evidence_reader_f1=blank,
                diagnostic_answer_f1_delta=before - blank,
            )
        )
    receipt = dict(
        matched_pairs=32,
        pairs=paired,
        production_accepted=False,
        same_read_only_reader_weights_and_prompt=True,
        independent_correct_support_verification=False,
    )
    return plan, raw, ceiling, empty, receipt


class ConditionalReaderTests(unittest.TestCase):
    def test_strict_original_32_partition_is_not_a_reader_success_claim(self):
        x = stratify_original_reader(*example())
        groups = x["categories"]
        self.assertEqual(x["planned_original_fixed_reader_questions"], 32)
        self.assertEqual(groups["native-support-chosen"]["planned_questions"], 13)
        self.assertEqual(
            groups["native-support-retrieved-not-chosen"]["planned_questions"], 4
        )
        self.assertEqual(groups["native-support-not-retrieved"]["planned_questions"], 8)
        self.assertEqual(groups["native-unanswerable"]["planned_questions"], 7)
        self.assertTrue(all(n == 8 for n in x["phase_question_census"].values()))
        self.assertFalse(x["production_accepted"])
        self.assertIsNone(x["semantic_citation_precision"])

    def test_failed_empty_reader_retains_original_denominator(self):
        plan, raw, ceiling, empty, receipt = example()
        empty[0].update(status="failed", receipt=None)
        pair = next(
            r
            for r in receipt["pairs"]
            if r["phase"] == empty[0]["phase"]
            and r["question_id"] == empty[0]["question_id"]
        )
        pair.update(
            zero_evidence_reader_succeeded=False,
            scored_pair=False,
            frozen_reader_f1=None,
            zero_evidence_reader_f1=None,
            diagnostic_answer_f1_delta=None,
        )
        result = stratify_original_reader(plan, raw, ceiling, empty, receipt)
        self.assertEqual(result["planned_original_fixed_reader_questions"], 32)
        self.assertEqual(
            sum(
                x["failed_or_unscorable_reader_pairs"]
                for x in result["categories"].values()
            ),
            1,
        )

    def test_reader_model_prompt_and_observable_question_must_match(self):
        for corrupt in ("generator_identity", "generator_profile", "observable_query"):
            p, raw, ceiling, empty, receipt = example()
            if corrupt == "observable_query":
                empty[0]["receipt"][corrupt]["identity"] = "other-question"
            else:
                empty[0]["receipt"][corrupt] = "different"
            with self.subTest(field=corrupt), self.assertRaises(AuditError):
                stratify_original_reader(p, raw, ceiling, empty, receipt)

    def test_control_must_have_zero_sources(self):
        data = example()
        data[3][0]["receipt"]["delivered_evidence"] = [{"label": "E1"}]
        with self.assertRaises(AuditError):
            stratify_original_reader(*data)

    def test_missing_or_duplicate_registered_pair_is_rejected(self):
        for field in ("control", "pair", "ceiling"):
            data = example()
            index = {"control": 3, "pair": 4, "ceiling": 2}[field]
            if field == "pair":
                data[index]["pairs"].pop()
            elif field == "ceiling":
                data[index]["decisions"].append(deepcopy(data[index]["decisions"][0]))
            else:
                data[index].pop()
            with self.subTest(field=field), self.assertRaises(AuditError):
                stratify_original_reader(*data)

    def test_f1_or_paired_delta_forgery_rejected(self):
        for name, score in (
            ("frozen_reader_f1", 1.3),
            ("diagnostic_answer_f1_delta", 0.75),
            ("zero_evidence_reader_f1", float("nan")),
        ):
            data = example()
            data[4]["pairs"][0][name] = score
            with self.subTest(name=name), self.assertRaises(AuditError):
                stratify_original_reader(*data)

    def test_forged_paired_f1_cannot_override_saved_original_answer_score(self):
        plan, raw, ceiling, empty, receipt = example()
        original = next(
            x
            for x in raw
            if x["stage"] == 48
            and x["arm"] == "frozen_rerank"
            and x["question_id"] == empty[0]["question_id"]
        )
        paired = next(
            x
            for x in receipt["pairs"]
            if x["phase"] == empty[0]["phase"]
            and x["question_id"] == empty[0]["question_id"]
        )
        original["diagnostic_answer_f1"] = paired["frozen_reader_f1"]
        stratify_original_reader(plan, raw, ceiling, empty, receipt)
        original["diagnostic_answer_f1"] = 1.0 - paired["frozen_reader_f1"]
        with self.assertRaisesRegex(AuditError, "original F1"):
            stratify_original_reader(plan, raw, ceiling, empty, receipt)

    def test_changed_source_family_or_exposure_fails_closed(self):
        for name in ("family", "evidence_exposure", "actual_frozen_evidence_count"):
            data = example()
            data[4]["pairs"][0][name] = (
                "wrong" if name != "actual_frozen_evidence_count" else 0
            )
            with self.subTest(name=name), self.assertRaises(AuditError):
                stratify_original_reader(*data)


if __name__ == "__main__":
    unittest.main()
