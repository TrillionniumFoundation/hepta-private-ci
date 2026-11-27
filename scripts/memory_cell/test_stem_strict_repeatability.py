"""Synthetic tamper checks; real success requires both byte-pinned ZIP archives."""

from copy import deepcopy
import os
import unittest

from stem_strict_repeatability import (
    ARMS,
    EARLIER,
    LATER,
    STAGES,
    PHASES,
    audit_pinned_paths,
    compare_adapters,
    compare_plan,
    compare_policy_pair,
)


def policies():
    before = dict(
        stage=16,
        phase="test",
        question_id="registered-q",
        arm="gated",
        status="succeeded",
        selected=0,
        answer="Original answer.",
        pool_digest="same-sealed-pool",
        feature_digest="same-features",
        head_sha256="saved-head",
        encoder_identity="same-encoder",
        family="same-original-family",
        cell="general",
        selection_geometry=dict(candidate_count=2, changed_selected_candidate=False),
        head_seconds=0.01,
        inclusive_attempt_seconds=0.02,
        receipt=dict(
            generator_identity="frozen-generator",
            generator_profile="same-prompt",
            generator_parameter_updates=0,
            semantic_citation_precision=None,
            production_accepted=False,
            delivered_evidence=[{"label": "E1"}],
            input_ids_digest="same-request-tokens",
            generated_ids_digest="same-output-tokens",
            reused_from=None,
            actual_reader_execution=True,
            generation_seconds=0.2,
            incremental_generation_seconds=0.2,
        ),
    )
    after = deepcopy(before)
    after.update(head_seconds=0.09, inclusive_attempt_seconds=0.14)
    after["receipt"].update(generation_seconds=0.4, incremental_generation_seconds=0.4)
    after["null_counterfactual"] = dict(
        schema="hepta.stem-label-free-null-counterfactual.v1",
        observed_forced_top1_index=0,
        original_forced_top1_unchanged=True,
        actual_reader_answer_not_recomputed=True,
        posthoc_labels_used_to_select_cutoff=False,
    )
    return before, after


def plans():
    old = dict(
        source_commit=EARLIER[0],
        arms=list(ARMS),
        curriculum_attempted_examples=list(STAGES),
        questions=dict(
            train=[f"train-{i}" for i in range(48)],
            **{p: [f"{p}-{i}" for i in range(8)] for p in PHASES},
        ),
        dataset_sha256="pinned-inputs",
        reader_inventory="frozen-model",
        generator_config={"do_sample": False},
        source_visibility_policy="strict-as-of-before-index-and-every-Encoder-v1",
    )
    new = deepcopy(old)
    new["source_commit"] = LATER[0]
    new["null_diagnostic"] = "zero-offset null observation only"
    return old, new


def adapters():
    old = dict(
        failures={},
        receipts={
            name: dict(
                prepared_questions=["q1", "q2"],
                adapter_delta_squared_norm=0.1,
                base_unchanged=True,
                status="succeeded",
                admission_digest="first-original-commit-bound-cut",
                seconds=1.0,
                reload_and_probe_seconds=0.2,
            )
            for name in ("lineage", "independent-general", "independent-temporal")
        },
    )
    new = deepcopy(old)
    for receipt in new["receipts"].values():
        receipt["admission_digest"] = "second-original-commit-bound-cut"
        receipt["seconds"] = 1.12
        receipt["reload_and_probe_seconds"] = 0.34
    return old, new


class StrictRepeatabilityTests(unittest.TestCase):
    def test_realistic_clock_differences_and_posthoc_null_do_not_change_answer(self):
        a, b = policies()
        compare_policy_pair(a, b)

    def test_forbid_any_original_answer_or_selected_window_mutation(self):
        for field, value in (
            ("answer", "different"),
            ("selected", 1),
            ("pool_digest", "changed"),
            ("head_sha256", "mismatched"),
            ("feature_digest", "changed"),
            ("encoder_identity", "new-adapter"),
        ):
            a, b = policies()
            b[field] = value
            with (
                self.subTest(field=field),
                self.assertRaisesRegex(ValueError, "changed"),
            ):
                compare_policy_pair(a, b)

    def test_canonical_reader_input_output_and_reuse_cannot_be_rewritten(self):
        for key, value in (
            ("input_ids_digest", "different"),
            ("generated_ids_digest", "different"),
            ("reused_from", "unaccounted"),
            ("generator_identity", "other-model"),
            ("generator_profile", "other-prompt"),
        ):
            a, b = policies()
            b["receipt"][key] = value
            with self.subTest(field=key), self.assertRaisesRegex(ValueError, "Reader"):
                compare_policy_pair(a, b)

    def test_unregistered_diagnostic_or_policy_field_is_rejected(self):
        a, b = policies()
        b["surreptitious_gold_answer"] = "leaked-after-generation"
        with self.assertRaisesRegex(ValueError, "unregistered"):
            compare_policy_pair(a, b)
        a, b = policies()
        b.pop("selection_geometry")
        with self.assertRaisesRegex(ValueError, "unregistered"):
            compare_policy_pair(a, b)

    def test_null_counterfactual_is_observation_not_new_reader_choice(self):
        for key, value in (
            ("observed_forced_top1_index", 1),
            ("original_forced_top1_unchanged", False),
            ("actual_reader_answer_not_recomputed", False),
            ("posthoc_labels_used_to_select_cutoff", True),
        ):
            a, b = policies()
            b["null_counterfactual"][key] = value
            with self.subTest(field=key), self.assertRaisesRegex(ValueError, "null"):
                compare_policy_pair(a, b)

    def test_frozen_provenance_or_training_cohort_drift_rejected(self):
        old, new = plans()
        compare_plan(old, new)
        for field, value in (
            ("reader_inventory", "changed-model"),
            ("dataset_sha256", "changed-source"),
            ("generator_config", {"do_sample": True}),
        ):
            a, b = plans()
            b[field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "drift"):
                compare_plan(a, b)
        a, b = plans()
        b["extra_calibrated_policy"] = "tuned-on-holdout"
        with self.assertRaisesRegex(ValueError, "unregistered"):
            compare_plan(a, b)

    def test_adapter_training_receipts_require_identical_real_fitted_examples(self):
        a, b = adapters()
        self.assertEqual(compare_adapters(a, b), dict.fromkeys(a["receipts"], 2))
        b["receipts"]["lineage"]["prepared_questions"].append("new-test-question")
        with self.assertRaisesRegex(ValueError, "LoRA"):
            compare_adapters(a, b)

    @unittest.skipUnless(
        os.environ.get("HEPTA_STEM_REPRO_EARLIER"),
        "real archived ZIP integration runs on pinned CI",
    )
    def test_exact_two_pinned_run_archives(self):
        result = audit_pinned_paths(
            os.environ["HEPTA_STEM_REPRO_EARLIER"],
            os.environ["HEPTA_STEM_REPRO_LATER"],
        )
        self.assertEqual(result["exact_matched_source_and_answer_rows"], 576)
        self.assertEqual(result["identical_head_checkpoints"], 36)
        self.assertEqual(result["identical_lora_adapter_tensors"], 3)
        self.assertFalse(result["production_accepted"])


if __name__ == "__main__":
    unittest.main()
