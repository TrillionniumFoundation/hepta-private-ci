"""Pure fixture controls for privileged answer-literal Reader comparison.

Every assertion is synthetic; independent source entailment and model quality
are not inferred from any fixture, even when the diagnostic F1 is high.
"""

from copy import deepcopy
import unittest

from stem_audit_archive import AuditError
from stem_native_oracle_reader_capacity import reference_reader_capacity

PHASES = ("select", "retention", "test", "transfer")


def fixture():
    phases = {"train": [f"train-{i}" for i in range(48)]}
    phases.update({p: [f"{p}-{i}" for i in range(8)] for p in PHASES})
    families = {q: "family-" + q for group in phases.values() for q in group}
    plan = dict(questions=phases, question_families=families)
    original, oracle, raw_empty, scored_empty, ceiling = [], [], [], [], []
    eligible = 0
    for phase in PHASES:
        abstentions = {"select": 2, "retention": 2, "test": 2, "transfer": 1}[phase]
        for i, q in enumerate(phases[phase]):
            answerable = i >= abstentions
            if answerable:
                category = eligible
                eligible += 1
                available = category < 17
                chosen = category < 13
                literal = category < 8
            else:
                available = chosen = literal = False
            canonical = dict(
                identity=q,
                content="What happened?",
                scope="scope-" + q,
                observed_at="2024-01-01",
            )
            receipt = dict(
                generator_identity="fixed-reader",
                generator_profile="fixed-prompt",
                observable_query=canonical,
                delivered_evidence=[{"label": "E1"}],
            )
            original.append(
                dict(
                    stage=48,
                    phase=phase,
                    arm="frozen_rerank",
                    question_id=q,
                    family=families[q],
                    status="succeeded",
                    answer="Fixture",
                    diagnostic_answer_f1=0.1 if answerable else None,
                    receipt=deepcopy(receipt),
                )
            )
            if not answerable:
                kind, state = "annotated-unanswerable", "succeeded"
            elif literal:
                kind, state = "native-source-literal-span", "succeeded"
            else:
                kind, state = "no-admitted-literal-reference-span", "unavailable"
            o = dict(
                phase=phase,
                question_id=q,
                oracle_kind=kind,
                status=state,
                policy_comparator=False,
                semantic_entailment_independently_verified=False,
            )
            if state == "succeeded":
                o.update(
                    answer="Privileged synthetic response",
                    diagnostic_f1=0.7 if literal else None,
                    receipt=dict(
                        receipt,
                        delivered_evidence=(
                            [
                                dict(
                                    label="E1",
                                    id="source-native-id",
                                    root="scope-bound-root",
                                    scope="scope-" + q,
                                    observed_at="2023-12-31",
                                    offset_encoding="original-utf8-bytes",
                                    source_start=0,
                                    source_end=len(
                                        "Answer present in exact original bytes".encode(
                                            "utf-8"
                                        )
                                    ),
                                    excerpt="Answer present in exact original bytes",
                                )
                            ]
                            if literal
                            else []
                        ),
                    ),
                )
            oracle.append(o)
            raw_empty.append(
                dict(
                    phase=phase,
                    question_id=q,
                    family=families[q],
                    status="succeeded",
                    evidence_count=0,
                    receipt=dict(receipt, delivered_evidence=[]),
                )
            )
            scored_empty.append(
                dict(
                    phase=phase,
                    question_id=q,
                    family=families[q],
                    status="succeeded",
                    diagnostic_answer_f1=0.0 if answerable else None,
                )
            )
            ceiling.append(
                dict(
                    phase=phase,
                    question_id=q,
                    source_family=families[q],
                    weak_native_support_resolved=answerable,
                    native_source_unanswerable=not answerable,
                    native_support_available_in_pool=available if answerable else None,
                    frozen_selected_native_support=chosen if answerable else None,
                    native_weak_support_not_window_entailment=True,
                )
            )
    assert eligible == 25
    return (
        plan,
        original,
        oracle,
        raw_empty,
        dict(results=scored_empty, planned_controls=32, production_accepted=False),
        dict(decisions=ceiling),
    )


class OracleCapacityTests(unittest.TestCase):
    def test_all_32_classified_and_only_eight_have_literal_reference(self):
        receipt = reference_reader_capacity(*fixture())
        self.assertEqual(receipt["original_fixed_question_count"], 32)
        self.assertEqual(
            receipt["actual_oracle_statuses"], {"succeeded": 15, "unavailable": 17}
        )
        self.assertEqual(
            receipt["per_original_native_source_coverage"]["native-support-chosen"][
                "planned"
            ],
            13,
        )
        self.assertEqual(
            sum(
                r["oracle_literal_reference_available"]
                for r in receipt["per_original_native_source_coverage"].values()
            ),
            8,
        )
        self.assertFalse(receipt["independently_reviewed_sufficient_context"])
        self.assertFalse(receipt["production_accepted"])

    def test_source_end_offset_cannot_shadow_no_evidence_receipt(self):
        # Literal spans include a numeric UTF-8 end byte offset. That is
        # *not* the zero-evidence Reader's scored-row object.
        args = fixture()
        literal = next(
            row for row in args[2] if row["oracle_kind"] == "native-source-literal-span"
        )
        span = literal["receipt"]["delivered_evidence"][0]
        span["source_start"] += 7
        span["source_end"] += 7
        report = reference_reader_capacity(*args)
        row = next(
            item
            for item in report["rows"]
            if item["question_id"] == literal["question_id"]
        )
        self.assertEqual(row["no_evidence_token_f1"], 0.0)
        self.assertAlmostEqual(row["oracle_minus_empty"], 0.7)
        self.assertAlmostEqual(row["oracle_minus_frozen"], 0.6)
        self.assertFalse(report["production_accepted"])

    def test_oracle_f1_is_observed_only_where_reference_was_found(self):
        receipt = reference_reader_capacity(*fixture())
        row = receipt["per_original_native_source_coverage"]["native-support-chosen"][
            "comparisons"
        ]["oracle_minus_frozen"]
        self.assertEqual(row["compared"], 8)
        self.assertEqual(row["omitted"], 5)
        self.assertAlmostEqual(row["compared_mean"], 0.6)
        self.assertLess(row["all_planned_delta_bounds"][0], 0)
        self.assertGreater(row["all_planned_delta_bounds"][1], 0)
        self.assertIsNone(receipt["semantic_citation_precision"])

    def test_missing_duplicate_and_fake_oracle_sources_reject(self):
        for kind in ("missing", "duplicate", "source"):
            args = fixture()
            if kind == "missing":
                args[2].pop()
            elif kind == "duplicate":
                args[2][-1] = dict(args[2][0])
            else:
                obj = next(
                    x
                    for x in args[2]
                    if x["oracle_kind"] == "native-source-literal-span"
                )
                obj["receipt"]["delivered_evidence"] = []
            with self.subTest(kind=kind), self.assertRaises(AuditError):
                reference_reader_capacity(*args)

    def test_prompt_or_model_or_native_question_drift_reject(self):
        for name in ("generator_identity", "generator_profile", "observable_query"):
            args = fixture()
            changed = next(x for x in args[2] if x["status"] == "succeeded")
            if name == "observable_query":
                changed["receipt"][name] = dict(identity="wrong-question")
            else:
                changed["receipt"][name] = "different"
            with self.subTest(field=name), self.assertRaises(AuditError):
                reference_reader_capacity(*args)

    def test_utf8_offsets_source_scope_and_future_time_fail_closed(self):
        for corruption in ("byte-offset", "scope", "future", "invalid-time", "root"):
            args = fixture()
            oracle = next(
                x for x in args[2] if x["oracle_kind"] == "native-source-literal-span"
            )
            passage = oracle["receipt"]["delivered_evidence"][0]
            if corruption == "byte-offset":
                passage["source_end"] += 1
            elif corruption == "scope":
                passage["scope"] = "different-tenant-scope"
            elif corruption == "future":
                passage["observed_at"] = "2024-01-02"
            elif corruption == "invalid-time":
                passage["observed_at"] = "unknown-timestamp"
            else:
                passage["root"] = ""
            with self.subTest(kind=corruption), self.assertRaises(ValueError):
                reference_reader_capacity(*args)

    def test_unanswerable_cannot_be_promoted_to_positive_oracle(self):
        args = fixture()
        obj = next(x for x in args[2] if x["oracle_kind"] == "annotated-unanswerable")
        obj["oracle_kind"] = "native-source-literal-span"
        with self.assertRaises(AuditError):
            reference_reader_capacity(*args)

    def test_absent_oracle_receipt_cannot_forge_success(self):
        args = fixture()
        obj = next(x for x in args[2] if x["status"] == "unavailable")
        obj.update(status="succeeded", answer="Invented", diagnostic_f1=1.0)
        with self.assertRaises(AuditError):
            reference_reader_capacity(*args)

    def test_zero_evidence_failure_preserved_without_imputed_quality(self):
        args = fixture()
        obj = args[3][0]
        obj["status"] = "failed"
        del obj["receipt"]
        args[4]["results"][0]["status"] = "failed"
        args[4]["results"][0]["diagnostic_answer_f1"] = None
        receipt = reference_reader_capacity(*args)
        matched = next(x for x in receipt["rows"] if x["question_id"] == "select-0")
        self.assertIsNone(matched["oracle_minus_empty"])
        self.assertIsNone(matched["frozen_minus_empty"])
        self.assertFalse(receipt["production_accepted"])

    def test_weak_source_diagnostics_do_not_make_prospective_claims(self):
        receipt = reference_reader_capacity(*fixture())
        self.assertEqual(receipt["real_model_calls_added"], 0)
        self.assertTrue(receipt["unused_for_train_or_hyperparameter_selection"])
        self.assertTrue(receipt["answer_literal_reference_is_privileged"])
        self.assertFalse(receipt["generation_prompt_modified"])


if __name__ == "__main__":
    unittest.main()
