"""Synthetic, model-free quality/cost interpretation; no cherry-picked Qwen answers."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from locomo_reader_value_gate import (
    audit_pinned_report, classify, strict_json,
)


def fixture():
    arms = {}
    for name, bytes_, tokens in (
        ("lexical_k4", 1600, 3200),
        ("lexical_k8", 3200, 3520),
    ):
        arms[name] = dict(
            planned=16, succeeded=16, failed=0,
            diagnostic_scored=16, diagnostic_unscored=0,
            emitted_citation_markers=0, answers_with_undelivered_marker=0,
            actual_input_tokens=tokens, actual_generated_tokens=64,
            actual_source_bytes=bytes_, observed_inference_seconds=8.0,
            diagnostic_f1=(0.4 if name == "lexical_k4" else 0.5),
            all_planned_f1_bounds=(
                [0.4, 0.4] if name == "lexical_k4" else [0.5, 0.5]
            ),
            independent_citation_entailment_precision=None,
        )
    costs = [
        dict(
            question_id=f"q{i}", family_proxy_digest="f0" if i < 8 else "f1",
            both_real_model_calls_succeeded=True, extra_prompt_tokens=20,
            extra_source_utf8_bytes=100,
        )
        for i in range(16)
    ]
    cost = dict(
        schema="hepta.memorycell.locomo-reader-matched-cost.v1",
        original_planned_question_pairs=16,
        logical_reader_attempts=32,
        completed_paired_questions=16,
        k4_success_k8_failure=0, k8_success_k4_failure=0,
        both_reader_calls_failed=0,
        per_arm={name: dict(succeeded=16, failed=0) for name in arms},
        matched_only_cost=dict(
            complete_paired_question_count=16,
            mean_extra_prompt_tokens=20.0,
            mean_extra_source_utf8_bytes=100.0,
        ),
        per_family_proxy_matched_only={
            "f0": dict(complete_paired_question_count=8),
            "f1": dict(complete_paired_question_count=8),
        },
        paired_cost_rows=costs,
        independent_source_family_significance=False,
        reader_task_gain_measured_by_this_module=False,
        missing_pair_costs_not_treated_as_zero=True,
        production_accepted=False,
    )
    return dict(
        schema="hepta.memorycell.locomo-frozen-reader-pair.v1.diagnostic.v1",
        arms=arms,
        paired=dict(
            planned=16, complete_scored=16, wins=16, losses=0, ties=0,
            missing_or_unscored=0, observed_mean_f1_delta=0.1,
            all_planned_delta_bounds=[0.1, 0.1],
            family_proxies=2, independent_family_significance_established=False,
        ),
        actual_paired_prompt_and_generation_cost=cost,
        known_exposed_public_development_data=True,
        same_frozen_reader_no_parameter_training=True,
        independently_adjudicated_citation_precision=None,
        production_accepted=False,
    )


class QualityCostGateTests(unittest.TestCase):
    def test_gain_at_higher_cost_remains_exploratory(self):
        row = classify(fixture())
        self.assertEqual(row["development_interpretation"],
                         "exploratory_QA_gain_at_higher_reader_input_cost")
        self.assertEqual(row["extra_prompt_tokens_matched_only"], 320)
        self.assertEqual(row["extra_source_utf8_bytes_matched_only"], 1600)
        self.assertEqual(row["both_answer_scored"], 16)
        self.assertFalse(row["policy_winner_selected"])
        self.assertFalse(row["scale_out_permitted"])
        self.assertFalse(row["production_accepted"])

    def test_no_answer_gain_means_no_confirmed_reader_tradeoff(self):
        item = fixture()
        item["paired"].update(
            wins=0, losses=0, ties=16, observed_mean_f1_delta=0,
            all_planned_delta_bounds=[0, 0],
        )
        item["arms"]["lexical_k8"]["diagnostic_f1"] = 0.4
        item["arms"]["lexical_k8"]["all_planned_f1_bounds"] = [0.4, 0.4]
        row = classify(item)
        self.assertEqual(
            row["development_interpretation"],
            "no_positive_all_planned_QA_lower_bound",
        )

    def test_one_missing_or_unscored_gold_cannot_be_hidden(self):
        item = fixture()
        item["paired"].update(
            complete_scored=15, missing_or_unscored=1,
            wins=15, observed_mean_f1_delta=0.1,
            all_planned_delta_bounds=[(1.5 - 1) / 16, (1.5 + 1) / 16],
        )
        item["arms"]["lexical_k8"].update(
            diagnostic_scored=15, diagnostic_unscored=1,
            all_planned_f1_bounds=[7.5 / 16, 8.5 / 16],
        )
        row = classify(item)
        self.assertEqual(row["both_answer_scored"], 15)
        self.assertFalse(row["completed_original_control_comparison"])
        self.assertEqual(
            row["development_interpretation"],
            "incomplete_pairs_no_quality_cost_verdict",
        )

    def test_a_failed_reader_is_not_zero_token_cost(self):
        item = fixture()
        q = item["paired"]
        q.update(
            complete_scored=15, missing_or_unscored=1, wins=15,
            all_planned_delta_bounds=[(1.5 - 1) / 16, (1.5 + 1) / 16],
        )
        c = item["actual_paired_prompt_and_generation_cost"]
        c["completed_paired_questions"] = 15
        c["k4_success_k8_failure"] = 1
        c["paired_cost_rows"].pop()
        c["per_family_proxy_matched_only"]["f1"]["complete_paired_question_count"] = 7
        item["arms"]["lexical_k8"].update(
            succeeded=15, failed=1, diagnostic_scored=15,
            all_planned_f1_bounds=[7.5 / 16, 8.5 / 16],
            actual_input_tokens=3300, actual_source_bytes=3000,
        )
        c["per_arm"]["lexical_k8"] = dict(succeeded=15, failed=1)
        row = classify(item)
        self.assertEqual(row["live_reader_pairs"], 15)
        self.assertEqual(row["missing_or_unscored_questions"], 1)
        self.assertEqual(row["extra_prompt_tokens_matched_only"], 300)
        self.assertFalse(row["completed_original_control_comparison"])

    def test_optimistic_bound_must_match_original_planned_denominator(self):
        item = fixture()
        item["paired"]["all_planned_delta_bounds"] = [0.8, 0.8]
        with self.assertRaisesRegex(ValueError, "16 denominator"):
            classify(item)

    def test_impossible_paired_scored_intersection_is_rejected(self):
        item = fixture()
        item["paired"].update(
            complete_scored=15, missing_or_unscored=1,
            wins=15, observed_mean_f1_delta=0.1,
            all_planned_delta_bounds=[0.5 / 16, 2.5 / 16],
        )
        with self.assertRaisesRegex(ValueError, "scored intersection"):
            classify(item)

    def test_forged_positive_paired_mean_cannot_hide_false_arm_scores(self):
        item = fixture()
        item["paired"]["observed_mean_f1_delta"] = 0.0
        item["paired"]["all_planned_delta_bounds"] = [0.0, 0.0]
        with self.assertRaisesRegex(ValueError, "paired Reader F1"):
            classify(item)

    def test_forged_individual_arm_score_bound_rejected(self):
        item = fixture()
        item["arms"]["lexical_k4"]["all_planned_f1_bounds"] = [0.1, 0.9]
        with self.assertRaisesRegex(ValueError, "arm diagnostic score bounds"):
            classify(item)

    def test_different_prompt_or_source_token_totals_are_rejected(self):
        for field in ("actual_input_tokens", "actual_source_bytes"):
            item = fixture()
            item["arms"]["lexical_k8"][field] += 1
            with self.subTest(field=field), self.assertRaisesRegex(
                ValueError, "prompt/source token accounting"
            ):
                classify(item)

    def test_duplicate_cost_rows_and_false_family_denominators_rejected(self):
        for mode in ("duplicate", "family"):
            item = fixture()
            c = item["actual_paired_prompt_and_generation_cost"]
            if mode == "duplicate":
                c["paired_cost_rows"][15] = deepcopy(c["paired_cost_rows"][0])
            else:
                c["per_family_proxy_matched_only"]["f0"][
                    "complete_paired_question_count"
                ] = 9
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                classify(item)

    def test_altered_public_or_production_claim_never_accepted(self):
        for field, value in (
            ("production_accepted", True),
            ("same_frozen_reader_no_parameter_training", False),
            ("independently_adjudicated_citation_precision", 1.0),
        ):
            item = fixture()
            item[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                classify(item)

    def test_source_report_needs_independent_external_sha256(self):
        raw = json.dumps(fixture(), sort_keys=True).encode()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "original-completed.json"
            path.write_bytes(raw)
            pin = hashlib.sha256(raw).hexdigest()
            result = audit_pinned_report(path, expected_sha256=pin)
            self.assertEqual(result["actual_completed_report_sha256"], pin)
            with self.assertRaisesRegex(ValueError, "mismatch"):
                audit_pinned_report(path, expected_sha256="0"*64)

    def test_duplicate_json_key_is_not_silently_overwritten(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            strict_json(b'{"schema":1,"schema":2}')
        with self.assertRaises(ValueError):
            strict_json(b'{"gain":NaN}')


if __name__ == "__main__":
    unittest.main()
