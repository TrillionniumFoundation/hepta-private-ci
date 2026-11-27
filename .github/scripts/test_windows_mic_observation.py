#!/usr/bin/env python3
"""Adversarial checks for the native MIC observation collector, not Windows tests."""

import copy
import json
import unittest

from windows_mic_observation import validate_transcript


def observations():
    passed = {"success": True, "denied": False, "os": None}
    refused = {"success": False, "denied": True, "os": 5}
    rows = []
    # Independently enumerate the native 577c outcomes: baseline, low token,
    # prepared roots, low outside root, and explicit protected-object deny.
    for case, (outside_deletes, inside_writes, git_deleted) in enumerate(
        [
            (True, True, True),
            (False, False, False),
            (False, True, True),
            (True, True, True),
            (False, True, True),
        ]
    ):
        rows.append(
            {
                "schema": "hepta.windows-mic-counterexample.v1",
                "case": case,
                "observation": {
                    "outside_read": True,
                    "outside": [refused, refused]
                    + [passed if outside_deletes else refused] * 2,
                    "inside": [[passed if inside_writes else refused] * 3] * 2,
                    "protected_git": passed if git_deleted else refused,
                    "outside_postconditions": not outside_deletes,
                    "inside_postconditions": inside_writes,
                    "protected_git_retained": not git_deleted,
                },
                "original_oracle": False,
                "original_isolation_hypothesis": "FAIL",
                "production_admission": {
                    "legacy_error": "LegacyWindowsSandboxIsolationUnavailable",
                    "elevated_error": "ElevatedWindowsSandboxIsolationUnavailable",
                    "fixture_unchanged": True,
                    "child_marker_absent": True,
                    "provisioning_absent": True,
                },
                "permission_qualification": False,
            }
        )
    return copy.deepcopy(rows)


def transcript(rows):
    return "\n".join("MIC_CASE_JSON " + json.dumps(row) for row in rows)


class MicObservationTests(unittest.TestCase):
    def test_negative_hypothesis_and_refusal_regression_remain_distinct(self):
        report = validate_transcript(transcript(observations()))
        self.assertEqual(report["regression_status"], "PASS")
        self.assertEqual(report["original_isolation_hypothesis"], "FAIL")
        self.assertIs(report["permission_qualification"], False)
        self.assertEqual(report["original_oracle_failed_cases"], [0, 1, 2, 3, 4])
        self.assertEqual(report["public_capture_refusals"], 10)

    def test_missing_duplicate_and_extra_cases_are_rejected(self):
        rows = observations()
        for malformed in (rows[:-1], rows + [rows[0]], rows[:-1] + [rows[0]]):
            with self.subTest(rows=malformed), self.assertRaises(ValueError):
                validate_transcript(transcript(malformed))

    def test_isolation_success_or_qualification_cannot_replace_the_negative(self):
        for field, value in (
            ("original_oracle", True),
            ("original_isolation_hypothesis", "PASS"),
            ("permission_qualification", True),
        ):
            rows = observations()
            rows[2][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_transcript(transcript(rows))

    def test_broken_controls_and_wrong_errors_cannot_count_as_counterexamples(self):
        for field, value in (
            ("outside_read", False),
            ("inside_postconditions", False),
            ("protected_git_retained", True),
        ):
            rows = observations()
            rows[2]["observation"][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_transcript(transcript(rows))
        rows = observations()
        rows[2]["observation"]["outside"][0]["os"] = 32
        with self.assertRaises(ValueError):
            validate_transcript(transcript(rows))

    def test_missing_or_inexact_production_refusal_is_rejected(self):
        for field, value in (
            ("legacy_error", "OtherError"),
            ("elevated_error", "OtherError"),
            ("fixture_unchanged", False),
            ("child_marker_absent", False),
            ("provisioning_absent", False),
        ):
            rows = observations()
            rows[4]["production_admission"][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_transcript(transcript(rows))

    def test_truncated_ambiguous_or_mistyped_json_is_rejected(self):
        raw = transcript(observations())
        for malformed in (
            raw[:-1],
            raw.replace('"case": 0', '"case": 0, "case": 0', 1),
            raw.replace('"case": 0', '"case": false', 1),
            raw.replace('"outside_read": true', '"outside_read": 1', 1),
            raw.replace('"os": 5', '"os": NaN', 1),
        ):
            with self.subTest(raw=malformed), self.assertRaises(ValueError):
                validate_transcript(malformed)

    def test_historical_raw_negative_without_admission_proof_cannot_qualify(self):
        with self.assertRaises(ValueError):
            validate_transcript(
                "MIC_RESULT case=2 original_oracle=false\n"
                "Error: MIC_HYPOTHESIS original_oracle_failed case=2\n"
            )


if __name__ == "__main__":
    unittest.main()
