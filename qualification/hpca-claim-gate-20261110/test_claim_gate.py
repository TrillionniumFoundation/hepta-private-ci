"""Synthetic parser fixtures only: never replay HPCA model-training smoke."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from claim_gate import (CALIBRATION, SEEDS, SOURCE_MANIFEST,
                        EvidenceError, inspect_report)


def fixture():
    """A SCHEMA fixture transcribed from the existing *summary*, not raw evidence."""
    arms = ("exact_key", "recent", "uniform", "stratified", "error_priority")
    return {
        "schema": "HEPTA-HPCA-MICRO-V1",
        "authority": "QUALIFICATION_ONLY_NOT_REAL_MODEL_EVIDENCE",
        "decision": "HOLD_NO_GO",
        "source_manifest_sha256": SOURCE_MANIFEST,
        "calibration_seeds": list(CALIBRATION),
        "heldout_test_seeds": list(SEEDS),
        "open_gates": ["independent task outcome is missing"],
        "schedule": {
            "per_arm_update_budget": 256,
            "mean_mse": {
                "heterogeneous": 0.11269163,
                "uniform": 0.14798182,
            },
            "family_mean_mse": {
                "heterogeneous": {
                    "PERC": 0.04250566,
                    "PRED": 0.05712996,
                    "CTRL": 0.17859627,
                    "ACT": 0.17253461,
                },
                "uniform": {
                    "PERC": 0.01408723,
                    "PRED": 0.05712996,
                    "CTRL": 0.38376503,
                    "ACT": 0.13694506,
                },
            },
        },
        "credit": {
            "heldout_accuracy": {
                "routed": 0.86539908,
                "context_gradient": 0.86539908,
                "random": 0.5643818,
                "shuffled": 0.38314914,
                "broadcast": 0.62409847,
            },
            "mean_parameter_updates": {
                "routed": 137.438,
                "context_gradient": 137.438,
                "random": 137.438,
                "shuffled": 137.438,
                "broadcast": 412.312,
            },
        },
        "delay": {
            "d0_density1_event_id": {
                "mean_accuracy": 0.95692007,
                "mean_observed_feedback": 384,
            },
            "d0_density1_latest": {
                "mean_accuracy": 0.95692007,
                "mean_observed_feedback": 384,
            },
            "d8_density1_event_id": {
                "mean_accuracy": 0.95884947,
                "mean_observed_feedback": 384,
            },
            "d8_density1_latest": {
                "mean_accuracy": 0.48908216,
                "mean_observed_feedback": 384,
            },
            "d8_density0.15_event_id": {
                "mean_accuracy": 0.72137239,
                "mean_observed_feedback": 57,
            },
            "d8_density0.15_latest": {
                "mean_accuracy": 0.50408945,
                "mean_observed_feedback": 57,
            },
        },
        "replay": {
            "old_task_retention": dict(zip(arms,
                (1.0, 0.4, 0.52976190, 0.62202381, 0.62797619))),
            "new_task_accuracy": dict(zip(arms,
                (1.0, 0.8, 0.93055556, 0.82638889, 0.29861111))),
            "mean_parameter_updates": dict(zip(arms,
                (0, 560, 560, 560, 560))),
            "mean_selection_reads": dict(zip(arms,
                (32, 160, 160, 3520, 4800))),
        },
    }


def encoded(value):
    return json.dumps(value, sort_keys=True, allow_nan=False).encode("utf-8")


class DecisionTests(unittest.TestCase):
    def test_historical_summary_forces_all_open_gates_and_per_family_conclusions(self):
        report = inspect_report(encoded(fixture()))
        self.assertEqual(report["scientific_qualification"], "HOLD_NO_GO")
        self.assertEqual(report["production_qualification"], "HOLD_NO_GO")
        self.assertEqual(report["authority"], "DENY_ALL")
        self.assertEqual(set(report["heterogeneous_regressions"]), {"PERC", "ACT"})
        self.assertTrue(report["credit_equal_contextual_gradient"])
        self.assertTrue(report["broadcast_cost_not_matched"])
        self.assertEqual(report["retention_new_task_tradeoffs"],
                         ["stratified", "error_priority"])
        self.assertTrue(report["exact_key_accuracy_not_worse"])
        self.assertFalse(report["original_owner_attestation_verified"])

    def test_optimistic_metrics_cannot_override_missing_independent_evidence(self):
        value = fixture()
        value["schedule"]["family_mean_mse"]["heterogeneous"] = {
            k: 0 for k in ("PERC", "PRED", "CTRL", "ACT")}
        value["schedule"]["mean_mse"]["heterogeneous"] = 0
        value["credit"]["heldout_accuracy"]["routed"] = 1
        value["credit"]["heldout_accuracy"]["context_gradient"] = 0.5
        value["replay"]["old_task_retention"]["stratified"] = 1
        value["replay"]["new_task_accuracy"]["stratified"] = 1
        report = inspect_report(encoded(value))
        self.assertEqual(report["scientific_qualification"], "HOLD_NO_GO")
        self.assertEqual(report["independent_real_task_confirmations"], 0)

    def test_original_and_forged_promotion_flags_rejected(self):
        for field, value in [
            ("decision", "GO"), ("authority", "FULL_AUTHORITY"),
            ("source_manifest_sha256", "f"*64),
        ]:
            trial = fixture()
            trial[field] = value
            with self.subTest(field=field), self.assertRaises(EvidenceError):
                inspect_report(encoded(trial))

    def test_seed_collision_and_partial_repetitions_rejected(self):
        for field, value in [
            ("calibration_seeds", list(SEEDS[:6])),
            ("heldout_test_seeds", list(SEEDS[:-1])),
            ("heldout_test_seeds", list(SEEDS[:-1]) + [SEEDS[-2]]),
        ]:
            trial = fixture()
            trial[field] = value
            with self.subTest(field=field), self.assertRaises(EvidenceError):
                inspect_report(encoded(trial))

    def test_unbalanced_neural_replay_budget_rejected(self):
        trial = fixture()
        trial["replay"]["mean_parameter_updates"]["error_priority"] = 500
        with self.assertRaises(EvidenceError):
            inspect_report(encoded(trial))

    def test_contextual_gradient_cost_drift_rejected(self):
        trial = fixture()
        trial["credit"]["mean_parameter_updates"]["context_gradient"] += 1
        with self.assertRaises(EvidenceError):
            inspect_report(encoded(trial))

    def test_aggregate_mse_cannot_hide_family_mismatch(self):
        trial = fixture()
        trial["schedule"]["mean_mse"]["heterogeneous"] = 0.0001
        with self.assertRaises(EvidenceError):
            inspect_report(encoded(trial))

    def test_missing_schedule_family_structure_is_refused(self):
        trial = fixture()
        trial["schedule"]["family_mean_mse"] = []
        with self.assertRaises(EvidenceError):
            inspect_report(encoded(trial))

    def test_feedback_denominators_must_match_across_trace_controls(self):
        trial = fixture()
        trial["delay"]["d8_density0.15_latest"]["mean_observed_feedback"] -= 1
        with self.assertRaises(EvidenceError):
            inspect_report(encoded(trial))

    def test_zero_delay_trace_parity_violation_rejected(self):
        trial = fixture()
        trial["delay"]["d0_density1_latest"]["mean_accuracy"] = 0.6
        with self.assertRaises(EvidenceError):
            inspect_report(encoded(trial))

    def test_missing_family_and_arms_rejected(self):
        for field in ("credit", "replay"):
            trial = fixture()
            if field == "credit":
                del trial["credit"]["heldout_accuracy"]["context_gradient"]
            else:
                del trial["replay"]["old_task_retention"]["exact_key"]
            with self.subTest(field=field), self.assertRaises(EvidenceError):
                inspect_report(encoded(trial))

    def test_unusable_numbers_rejected(self):
        for invalid in (True, "0.8", -1, float("inf")):
            trial = fixture()
            trial["schedule"]["mean_mse"]["uniform"] = invalid
            payload = json.dumps(trial).encode("utf-8")
            with self.subTest(value=str(invalid)), self.assertRaises(EvidenceError):
                inspect_report(payload)

    def test_duplicate_json_keys_rejected(self):
        trial = encoded(fixture())
        duplicate = trial.replace(b'"schema":', b'"schema": "invented", "schema":', 1)
        with self.assertRaises(EvidenceError):
            inspect_report(duplicate)

    def test_rejects_truncated_and_oversized_input(self):
        with self.assertRaises(EvidenceError):
            inspect_report(b"")
        with self.assertRaises(EvidenceError):
            inspect_report(b" " * 300000)

    def test_report_is_read_only_and_digest_tracks_original_bytes(self):
        raw = encoded(fixture())
        report = inspect_report(raw)
        self.assertEqual(len(report["source_report_sha256"]), 64)
        self.assertEqual(raw, encoded(fixture()))
        self.assertNotEqual(report["source_report_sha256"],
                            inspect_report(raw + b"\n")["source_report_sha256"])

    def test_create_only_cli_and_wrong_source_preservation(self):
        src = encoded(fixture())
        with tempfile.TemporaryDirectory() as temp:
            inp = Path(temp) / "original.json"
            out = Path(temp) / "review.json"
            inp.write_bytes(src)
            cmd = [sys.executable, str(Path(__file__).with_name("claim_gate.py")),
                   "--input", str(inp), "--output", str(out)]
            first = subprocess.run(cmd, capture_output=True, text=True, check=False)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(inp.read_bytes(), src)
            published = out.read_bytes()
            second = subprocess.run(cmd, capture_output=True, text=True, check=False)
            self.assertNotEqual(second.returncode, 0)
            self.assertEqual(published, out.read_bytes())
            self.assertEqual(inp.read_bytes(), src)


if __name__ == "__main__":
    unittest.main()
