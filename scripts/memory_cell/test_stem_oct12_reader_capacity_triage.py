"""No-execution tests: privileged source oracle is not independent sufficiency."""

from copy import deepcopy
import math
import unittest

from stem_oct12_reader_capacity_triage import ARMS, PHASES, STAGES, SOURCE, triage


def fixtures():
    question_ids = {"train": ["train-%02d" % i for i in range(48)]}
    question_ids.update({p: ["%s-%d" % (p, i) for i in range(8)] for p in PHASES})
    plan = dict(
        source_commit=SOURCE,
        production_accepted=False,
        source_visibility_policy="strict-as-of-before-index-and-every-Encoder-v1",
        arms=list(ARMS),
        curriculum_attempted_examples=list(STAGES),
        questions=question_ids,
    )
    records, oracles, zero, scored, ceilings = [], [], [], [], []
    for stage in STAGES:
        for phase in PHASES:
            for qid in question_ids[phase]:
                for arm in ARMS:
                    record = dict(
                        stage=stage,
                        phase=phase,
                        arm=arm,
                        question_id=qid,
                        status="succeeded",
                        family="family-" + qid,
                    )
                    if stage == 48 and arm == "frozen_rerank":
                        receipt = dict(
                            generator_identity="reader-digest",
                            generator_profile="prompt-digest",
                            observable_query=dict(
                                identity=qid,
                                scope="scope-" + qid,
                                observed_at="2024-01-01",
                                content="Question?",
                            ),
                            delivered_evidence=[dict(label="E1")],
                        )
                        record.update(
                            receipt=deepcopy(receipt), diagnostic_answer_f1=0.4
                        )
                    records.append(record)
    for phase in PHASES:
        for i, qid in enumerate(question_ids[phase]):
            fam = "family-" + qid
            ref = next(
                x
                for x in records
                if x["stage"] == 48
                and x["arm"] == "frozen_rerank"
                and x["question_id"] == qid
            )
            receipt = deepcopy(ref["receipt"])
            receipt["delivered_evidence"] = []
            zero.append(
                dict(
                    phase=phase,
                    question_id=qid,
                    family=fam,
                    evidence_count=0,
                    status="succeeded",
                    answer_target_opened_by_generation=False,
                    receipt=receipt,
                )
            )
            scored.append(
                dict(
                    phase=phase,
                    question_id=qid,
                    family=fam,
                    status="succeeded",
                    was_zero_evidence=True,
                    diagnostic_answer_f1=0.2,
                )
            )
            kind = (
                "native-source-literal-span"
                if i < 2
                else "no-admitted-literal-reference-span"
                if i < 6
                else "annotated-unanswerable"
            )
            oracle = dict(
                phase=phase,
                question_id=qid,
                oracle_kind=kind,
                policy_comparator=False,
                semantic_entailment_independently_verified=False,
            )
            if kind == "native-source-literal-span":
                oracle["status"] = "succeeded"
                oracle["diagnostic_f1"] = 0.6
                oracle["receipt"] = deepcopy(ref["receipt"])
            elif kind == "annotated-unanswerable":
                oracle["status"] = "succeeded"
                oracle["receipt"] = receipt
            else:
                oracle["status"] = "unavailable"
            oracles.append(oracle)
            ceilings.append(
                dict(
                    phase=phase,
                    question_id=qid,
                    source_family=fam,
                    native_source_unanswerable=(kind == "annotated-unanswerable"),
                    weak_native_support_resolved=(kind != "annotated-unanswerable"),
                    native_support_available_in_pool=True if i < 4 else False,
                    frozen_selected_native_support=False,
                )
            )
    ceiling = dict(
        final_checkpoint=48,
        independent_semantic_review_performed=False,
        decisions=ceilings,
    )
    return plan, records, oracles, zero, scored, ceiling


class ReaderCapacityTriageTests(unittest.TestCase):
    def test_complete_source_only_census_does_not_certify_oracle(self):
        result = triage(*fixtures())
        summary = result["per_phase"]["all"]
        self.assertEqual(summary["planned"], 32)
        self.assertEqual(summary["answer_conditioned_literal_span_available"], 8)
        self.assertEqual(summary["privileged_literal_unavailable"], 16)
        self.assertEqual(summary["annotated_unanswerable"], 8)
        self.assertEqual(summary["missing_literal_despite_native_source_in_pool"], 8)
        self.assertAlmostEqual(summary["literal_vs_empty_diagnostic_f1_mean"], 0.4)
        self.assertAlmostEqual(summary["literal_vs_frozen_diagnostic_f1_mean"], 0.2)
        self.assertFalse(result["all_possible_evidence_reader_capacity_proven"])
        self.assertFalse(result["production_accepted"])

    def test_missing_and_duplicate_question_are_not_dropped(self):
        for mode in ("drop", "duplicate"):
            items = list(fixtures())
            if mode == "drop":
                items[2].pop()
            else:
                items[2][-1] = deepcopy(items[2][0])
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                triage(*items)

    def test_wrong_reader_prompt_or_question_identity_fails(self):
        for mode in ("reader", "prompt", "question"):
            items = list(fixtures())
            oracle = items[2][0]
            if mode == "reader":
                oracle["receipt"]["generator_identity"] = "different-model"
            elif mode == "prompt":
                oracle["receipt"]["generator_profile"] = "different-prompt"
            else:
                oracle["receipt"]["observable_query"]["identity"] = "wrong-id"
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                triage(*items)

    def test_unavailable_oracle_is_not_a_reader_failure(self):
        items = list(fixtures())
        x = next(x for x in items[2] if x["status"] == "unavailable")
        x["answer"] = "invented"
        with self.assertRaisesRegex(ValueError, "unavailable oracle"):
            triage(*items)

    def test_source_provenance_and_human_authority_cannot_be_forged(self):
        items = list(fixtures())
        items[2][0]["semantic_entailment_independently_verified"] = True
        with self.assertRaises(ValueError):
            triage(*items)
        items = list(fixtures())
        items[5]["decisions"][0]["native_source_unanswerable"] = True
        with self.assertRaises(ValueError):
            triage(*items)

    def test_null_or_nonfinite_score_rejected_for_observed_oracle(self):
        for value in (math.nan, math.inf, 1.4):
            items = list(fixtures())
            items[2][0]["diagnostic_f1"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                triage(*items)

    def test_raw_empty_input_cannot_hide_supplied_evidence(self):
        items = list(fixtures())
        items[3][0]["receipt"]["delivered_evidence"] = [dict(label="E1")]
        with self.assertRaises(ValueError):
            triage(*items)

    def test_mixed_training_and_evaluation_question_disallowed(self):
        items = list(fixtures())
        items[0]["questions"]["train"][0] = items[0]["questions"]["select"][0]
        with self.assertRaises(ValueError):
            triage(*items)


if __name__ == "__main__":
    unittest.main()
