"""Fail-closed and nonparametric paired Reader-transport audit controls."""

import os
from pathlib import Path
import unittest
from unittest.mock import patch

from system2_reader_transport_audit import (
    AUDIT_SCHEMA,
    CASE_COUNT,
    NEW_CALLS,
    REUSED_CALLS,
    POSITIVES,
    ZIP_SHA,
    breakdown,
    authenticated_replay,
)
from system2_reader_transport_trial import COHORTS
from system2_reader_paired_capacity_audit import STRONG_ZIP_SHA


def rows():
    data = []
    for cohort in (*COHORTS, "fresh_fixed_20"):
        for arm in (
            "single_fact",
            "target_decoy_two_first",
            "decoy_one",
            "no_evidence",
        ):
            for i in range(CASE_COUNT):
                baseline = i < 3 if arm in POSITIVES else i < 18
                lines = i < 8 if arm in POSITIVES else i < 17
                data.append(
                    dict(
                        cohort=cohort,
                        arm=arm,
                        qid=f"{cohort}-{i}",
                        baseline_score=dict(
                            conditional_success=baseline,
                            exact_answer_only=i < 3 if arm in POSITIVES else False,
                            correct_refusal=not (arm in POSITIVES) and i < 18,
                        ),
                        new_score=dict(
                            conditional_success=lines,
                            exact_answer_only=i < 8 if arm in POSITIVES else False,
                            correct_refusal=not (arm in POSITIVES) and i < 17,
                        ),
                        baseline_input_tokens=120,
                        new_input_tokens=90,
                        baseline_output_tokens=8,
                        new_output_tokens=12,
                        baseline_cpu_ns=100,
                        new_cpu_ns=140,
                    )
                )
    return data


class TransportArchiveAuditTests(unittest.TestCase):
    def test_archive_sha_pin_and_trial_denominator(self):
        self.assertEqual(len(ZIP_SHA), 64)
        self.assertEqual(len(STRONG_ZIP_SHA), 64)
        self.assertEqual((NEW_CALLS, REUSED_CALLS), (320, 160))
        self.assertEqual(AUDIT_SCHEMA, "hepta.system2.sealed-transport-audit.v1")

    def test_paired_flags_do_not_hide_overrefusal(self):
        groups = breakdown(rows())
        self.assertEqual(len(groups), 12)
        positive = next(
            g
            for g in groups
            if g["cohort"] == "fresh_fixed_20" and g["arm"] == "single_fact"
        )
        self.assertEqual(
            (
                positive["both_success"],
                positive["json_only_success"],
                positive["lines_only_success"],
                positive["neither_success"],
            ),
            (3, 0, 5, 12),
        )
        self.assertEqual(
            (positive["json_exact_answers"], positive["lines_exact_answers"]), (3, 8)
        )
        self.assertEqual(
            (
                positive["json_appropriate_refusals"],
                positive["lines_appropriate_refusals"],
            ),
            (0, 0),
        )
        self.assertFalse(positive["compute_matched"])

    def test_refusal_success_is_not_answer_yield(self):
        control = next(
            g
            for g in breakdown(rows())
            if g["cohort"] == "fresh_fixed_20" and g["arm"] == "decoy_one"
        )
        self.assertEqual(control["json_exact_answers"], 0)
        self.assertEqual(control["lines_exact_answers"], 0)
        self.assertEqual(control["both_success"], 17)
        self.assertEqual(control["json_only_success"], 1)
        self.assertEqual(control["lines_only_success"], 0)
        self.assertIsNone(control["json_overrefusals"])

    def test_real_token_and_cpu_delta_is_not_free(self):
        control = next(
            g
            for g in breakdown(rows())
            if g["cohort"] == "exposed_20" and g["arm"] == "single_fact"
        )
        self.assertEqual(control["input_token_delta"], -600)
        self.assertEqual(control["generated_token_delta"], 80)
        self.assertEqual(control["decoder_cpu_delta_ns"], 800)

    def test_missing_and_duplicate_subjects_rejected(self):
        complete = rows()
        for broken in (complete[:-1], complete + [complete[0]]):
            with self.assertRaises(ValueError):
                breakdown(broken)

    def test_wrong_status_type_rejected(self):
        sample = rows()
        sample[0]["new_score"]["conditional_success"] = 1
        with self.assertRaises(ValueError):
            breakdown(sample)

    def test_archived_zip_digest_failure_is_not_repaired(self):
        with patch(
            "system2_reader_transport_audit.verified_archive",
            side_effect=ValueError("bad external SHA"),
        ):
            with self.assertRaisesRegex(ValueError, "external SHA"):
                authenticated_replay(Path("bad.zip"), Path("old.zip"))

    def test_pinned_real_model_archive_in_full_repo_ci(self):
        current = os.environ.get("HEPTA_TRANSPORT_ARCHIVE")
        original = os.environ.get("HEPTA_ORIGINAL_QWEN_ARCHIVE")
        if not current or not original:
            self.skipTest(
                "downloaded model archives not staged in this test environment"
            )
        receipt = authenticated_replay(Path(current), Path(original))
        self.assertEqual(receipt["new_model_calls"], NEW_CALLS)
        self.assertEqual(receipt["old_model_calls_reused"], REUSED_CALLS)
        self.assertEqual(receipt["complete_paired_conditions"], 240)
        self.assertEqual(len(receipt["breakdown"]), 12)
        self.assertFalse(receipt["production_accepted"])


if __name__ == "__main__":
    unittest.main()
