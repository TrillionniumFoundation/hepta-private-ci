import unittest
from stem_native_nonpromotion import audit_nonpromotion, ARMS, PHASES, STAGES


def record():
    metrics = {}
    for stage in STAGES:
        for phase in PHASES:
            for arm in ARMS:
                metrics[f"{stage}/{phase}/{arm}"] = dict(
                    attempted=8,
                    succeeded=8,
                    failed=0,
                    source_accuracy=0.25,
                    diagnostic_f1=0.125,
                    emitted_citation_markers=0,
                    delivered_citation_markers=0,
                )
    return dict(metrics=metrics, logical_policy_attempts=576, production_accepted=False)


class GateTests(unittest.TestCase):
    def test_complete_success_does_not_qualify(self):
        out = audit_nonpromotion(record())
        self.assertFalse(out["scale_out_permitted"])
        self.assertFalse(out["any_aggregate_source_or_answer_gain"])
        self.assertEqual(out["audited_policy_attempts"], 576)
        self.assertEqual(out["learning_arms"]["gated"]["identical_source_accuracy"], 12)

    def test_positive_aggregate_still_does_not_certify_production(self):
        data = record()
        data["metrics"]["48/test/gated"]["source_accuracy"] = 0.5
        out = audit_nonpromotion(data)
        self.assertTrue(out["any_aggregate_source_or_answer_gain"])
        self.assertFalse(out["scale_out_permitted"])

    def test_missing_row_and_faked_acceptance_rejected(self):
        for mutation in ("missing", "promoted", "mismatched_count"):
            data = record()
            if mutation == "missing":
                data["metrics"].pop("48/test/gated")
            elif mutation == "promoted":
                data["production_accepted"] = True
            else:
                data["metrics"]["48/test/gated"]["attempted"] = 7
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                audit_nonpromotion(data)

    def test_citation_fabrication_rejected(self):
        data = record()
        data["metrics"]["48/test/gated"]["delivered_citation_markers"] = 1
        with self.assertRaises(ValueError):
            audit_nonpromotion(data)


if __name__ == "__main__":
    unittest.main()


def full_fixture():
    from copy import deepcopy

    plan = dict(
        arms=list(ARMS),
        curriculum_attempted_examples=list(STAGES),
        questions=dict(train=[f"train-{i}" for i in range(48)]),
    )
    plan["questions"].update(
        {phase: [f"{phase}-{i}" for i in range(8)] for phase in PHASES}
    )
    plan["routes"] = {
        qid: "general" for qids in plan["questions"].values() for qid in qids
    }
    raw = []
    for stage in STAGES:
        for phase in PHASES:
            for qid in plan["questions"][phase]:
                for arm in ARMS:
                    raw.append(
                        dict(
                            stage=stage,
                            phase=phase,
                            question_id=qid,
                            arm=arm,
                            status="succeeded",
                            cell="general",
                            family="family-" + qid,
                            selected=0,
                            answer="fixture",
                            pool_digest="same-pool-" + qid,
                            feature_digest="feature",
                            head_sha256="h" * 64,
                            encoder_identity="frozen-encoder",
                            receipt=dict(
                                observable_query=dict(identity=qid),
                                generator_identity="pinned-reader",
                                generator_profile="pinned-prompt",
                                input_ids_digest="a" * 64,
                                generated_ids_digest="b" * 64,
                                delivered_evidence=[dict(label="E1")],
                            ),
                        )
                    )
    scored = deepcopy(raw)
    for row in scored:
        row.update(
            source_choice_correct=0,
            diagnostic_answer_f1=0.25,
            citation_structure=dict(
                markers=0,
                delivered_markers=0,
                precision=None,
                semantic_precision=None,
            ),
        )
    training = dict(
        checkpoints=[
            dict(
                checkpoint=stage,
                arm=arm,
                cell=cell,
                heldout_annotations_consulted=False,
                production_accepted=False,
                changed_train_top1_rows=0,
                mean_weak_loss_delta=-0.25,
                previous_head_sha256="a" * 64,
                updated_head_sha256="h" * 64,
            )
            for stage in STAGES
            for arm in ARMS[1:]
            for cell in ("general", "temporal")
        ]
    )
    ceiling = dict(
        phases={
            phase: dict(
                attempted=8,
                native_source_resolved=6,
                native_unanswerable=2,
                native_unresolved_support=0,
                support_available_within_pool=4,
                support_missing_from_pool=2,
                frozen_correct_source_choices=3,
                frozen_missed_available_support=1,
            )
            for phase in PHASES
        }
    )
    effective = dict(
        independent_question_ids_per_arm=16,
        repeated_question_evaluations_per_arm=48,
        source_family_sampling_independence_certified=False,
    )
    report = dict(
        production_accepted=False,
        semantic_citation_precision=None,
        learning=[
            dict(
                stage=stage,
                arm=arm,
                cell=cell,
                status="succeeded",
                before_sha256="a" * 64,
                after_sha256="h" * 64,
                other_head_states_unchanged=True,
            )
            for stage in STAGES
            for arm in ARMS
            for cell in ("general", "temporal")
        ],
    )
    return plan, raw, scored, report, training, ceiling, effective


class PairedNativeProofTests(unittest.TestCase):
    def check(self, args):
        from stem_native_nonpromotion import audit_exact_paired_choices

        return audit_exact_paired_choices(*args)

    def test_full_paired_success_does_not_promote(self):
        result = self.check(full_fixture())
        self.assertEqual(result["full_policy_attempts"], 576)
        self.assertEqual(result["exact_original_scored_receipt_matches"], 576)
        self.assertEqual(result["head_training_checkpoints"], 30)
        self.assertEqual(result["head_checkpoints_with_lower_weak_loss"], 30)
        self.assertFalse(result["scale_out_permitted"])
        self.assertFalse(result["production_accepted"])
        for arm in ARMS[1:]:
            self.assertEqual(result["learned_arms"][arm]["matched_policy_pairs"], 96)

    def test_one_changed_choice_without_answer_gain_remains_observable(self):
        args = full_fixture()
        raw, scored = args[1], args[2]
        for records in (raw, scored):
            row = next(
                x
                for x in records
                if x["stage"] == 48
                and x["phase"] == "retention"
                and x["question_id"] == "retention-0"
                and x["arm"] == "lineage_lora_gated"
            )
            row["selected"] = 1
        result = self.check(args)
        self.assertEqual(
            result["learned_arms"]["lineage_lora_gated"]["changed_source_top1"], 1
        )
        self.assertEqual(
            result["learned_arms"]["lineage_lora_gated"][
                "changed_original_answer_bytes"
            ],
            0,
        )
        self.assertFalse(result["scale_out_permitted"])

    def test_scoring_laundered_source_or_answer_is_rejected(self):
        for modified in ("selected", "answer", "receipt", "head_sha256"):
            args = full_fixture()
            row = args[2][0]
            if modified == "receipt":
                row[modified]["generator_identity"] = "fake"
            elif modified == "selected":
                row[modified] = 1
            else:
                row[modified] = "tampered"
            with (
                self.subTest(modified=modified),
                self.assertRaisesRegex(ValueError, "differs from exact"),
            ):
                self.check(args)

    def test_partial_duplicate_and_unregistered_census_is_rejected(self):
        for mode in ("missing", "duplicate", "extra"):
            args = full_fixture()
            rows = args[1]
            if mode == "missing":
                rows.pop()
            elif mode == "duplicate":
                rows[-1] = dict(rows[0])
            else:
                rows[-1]["question_id"] = "not-preregistered"
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                self.check(args)

    def test_cross_arm_reader_prompt_and_candidate_pool_cannot_drift(self):
        for field in ("pool_digest", "family", "cell", "generator_profile"):
            args = full_fixture()
            row = next(r for r in args[1] if r["arm"] == "gated")
            evaluated = next(
                r
                for r in args[2]
                if (r["stage"], r["phase"], r["question_id"], r["arm"])
                == (row["stage"], row["phase"], row["question_id"], row["arm"])
            )
            if field == "generator_profile":
                row["receipt"][field] = "different"
                evaluated["receipt"][field] = "different"
            else:
                row[field] = "different"
                evaluated[field] = "different"
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.check(args)

    def test_valid_but_wrong_cell_route_cannot_rebind_head(self):
        args = full_fixture()
        row = next(x for x in args[1] if x["arm"] == "gated")
        matched = next(
            x
            for x in args[2]
            if (x["stage"], x["phase"], x["question_id"], x["arm"])
            == (row["stage"], row["phase"], row["question_id"], row["arm"])
        )
        row["cell"] = "temporal"
        matched["cell"] = "temporal"
        with self.assertRaisesRegex(ValueError, "Cell route"):
            self.check(args)

    def test_invalid_or_unhashable_cell_fails_closed_as_value_error(self):
        for invalid in ("unknown", [], ["general"], 0, None):
            args = full_fixture()
            row = next(r for r in args[1] if r["arm"] == "gated")
            indexed = next(
                r
                for r in args[2]
                if (r["stage"], r["phase"], r["question_id"], r["arm"])
                == (row["stage"], row["phase"], row["question_id"], row["arm"])
            )
            row["cell"] = invalid
            indexed["cell"] = invalid
            with (
                self.subTest(cell=invalid),
                self.assertRaisesRegex(ValueError, "Cell route"),
            ):
                self.check(args)

    def test_false_citation_semantics_or_genuine_missing_evidence_rejected(self):
        for mode in ("self-certified-citation", "missing-phase", "fake-production"):
            args = full_fixture()
            if mode == "self-certified-citation":
                args[2][0]["citation_structure"]["semantic_precision"] = 1.0
            elif mode == "missing-phase":
                args[5]["phases"].pop("test")
            else:
                args[3]["production_accepted"] = True
            with self.subTest(mode=mode), self.assertRaises((ValueError, KeyError)):
                self.check(args)

    def test_repeated_48_question_measurements_not_independent(self):
        args = full_fixture()
        args[6]["repeated_question_evaluations_per_arm"] = 16
        with self.assertRaisesRegex(ValueError, "training/heldout"):
            self.check(args)

    def test_frozen_retrieval_and_forced_abstention_are_distinct_limits(self):
        result = self.check(full_fixture())
        self.assertEqual(
            result["heldout_potential_additional_weak_source_top1_choices_rerank_only"],
            2,
        )
        self.assertEqual(result["heldout_native_sources_absent_from_fixed_pool"], 4)
        self.assertEqual(result["heldout_native_unanswerable_forced_top1"], 4)
        self.assertTrue(result["these_are_upper_bounds_not_observed_task_gains"])
        self.assertFalse(result["scale_out_permitted"])

    def test_source_ceiling_cannot_fabricate_retrieval_or_head_opportunities(self):
        for mode in ("label-count", "double-count", "over-claimed-rerank"):
            args = full_fixture()
            phase = args[5]["phases"]["test"]
            if mode == "label-count":
                phase["native_unanswerable"] = 1
            elif mode == "double-count":
                phase["support_missing_from_pool"] = 3
            else:
                phase["frozen_correct_source_choices"] = 4
                phase["frozen_missed_available_support"] = 1
            with (
                self.subTest(mode=mode),
                self.assertRaisesRegex(ValueError, "opportunity ceiling"),
            ):
                self.check(args)

    def test_saved_head_hash_or_peer_mutation_is_not_laundered(self):
        for mutation in ("raw-head", "fit-head", "peer-mutation"):
            args = full_fixture()
            if mutation == "raw-head":
                args[1][0]["head_sha256"] = "other"
                args[2][0]["head_sha256"] = "other"
            elif mutation == "fit-head":
                args[4]["checkpoints"][0]["updated_head_sha256"] = "other"
            else:
                args[3]["learning"][0]["other_head_states_unchanged"] = False
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.check(args)

    def test_training_dropout_and_unsupported_optimizer_step_claim_rejected(self):
        for mode in ("missing", "invalid-heldout", "nan"):
            args = full_fixture()
            samples = args[4]["checkpoints"]
            if mode == "missing":
                samples.pop()
            elif mode == "invalid-heldout":
                samples[0]["heldout_annotations_consulted"] = True
            else:
                samples[0]["mean_weak_loss_delta"] = float("nan")
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                self.check(args)
