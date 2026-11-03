#!/usr/bin/env python3
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from candidate_promotion_gate import (
    AUTHORITY,
    MODE,
    Q32_TOLERANCE,
    evaluate,
    passing_evidence,
    run,
)


class CandidatePromotionGateTests(unittest.TestCase):
    def test_current_shadow_fixture_rejects_missing_qualification_evidence(self):
        result = run(17)
        decision = result["decision"]
        self.assertEqual(result["status"], "REJECTED_FAIL_CLOSED")
        self.assertFalse(decision["gates_passed"])
        self.assertFalse(decision["eligible_for_external_acceptance"])
        self.assertFalse(decision["promotion_allowed"])
        failed = {gate["name"] for gate in decision["gates"] if not gate["passed"]}
        self.assertIn("global_local_gap", failed)
        self.assertIn("future_windows", failed)
        self.assertIn("independent_snapshots", failed)
        self.assertIn("candidate_lcb_above_baseline_ucb", failed)
        self.assertIn("calibration_error", failed)
        self.assertIn("ood_false_acceptance", failed)
        self.assertEqual(decision["authority"], AUTHORITY)
        self.assertEqual(decision["mode"], MODE)

    def test_complete_evidence_is_eligible_but_never_activates(self):
        result = evaluate(passing_evidence())
        self.assertTrue(result.gates_passed)
        self.assertTrue(result.eligible_for_external_acceptance)
        self.assertFalse(result.promotion_allowed)
        self.assertEqual(result.status, "ELIGIBLE_FOR_EXTERNAL_ACCEPTANCE")
        self.assertEqual(result.mode, MODE)
        self.assertEqual(result.authority, AUTHORITY)
        self.assertEqual(len(result.gates), 27)

    def test_missing_and_malformed_evidence_fails_closed(self):
        evidence = passing_evidence()
        for key in ("candidate_lcb", "future_windows", "calibration_error", "safety_gate"):
            malformed = copy.deepcopy(evidence)
            malformed[key] = "not-a-number" if key != "safety_gate" else None
            decision = evaluate(malformed)
            self.assertFalse(decision.gates_passed, key)
            self.assertFalse(decision.promotion_allowed, key)
            self.assertIn(key if key in {"future_windows", "calibration_error", "safety_gate"} else "candidate_lcb_above_baseline_ucb", decision.reason)

    def test_q32_boundary_is_exact_and_strict_outside(self):
        evidence = passing_evidence()
        evidence["propensity_sum"] = 1.0 + Q32_TOLERANCE
        self.assertTrue(evaluate(evidence).gates_passed)
        evidence["propensity_sum"] = 1.0 + 2.0 * Q32_TOLERANCE
        result = evaluate(evidence)
        self.assertFalse(result.gates_passed)
        gate = next(item for item in result.gates if item.name == "propensity_sum_q32")
        self.assertFalse(gate.passed)

    def test_snapshot_digest_is_required_for_lineage_audit(self):
        evidence = passing_evidence()
        evidence["candidate_snapshot_digest"] = "bad"
        result = evaluate(evidence)
        self.assertFalse(result.gates_passed)
        gate = next(item for item in result.gates if item.name == "candidate_snapshot_digest")
        self.assertFalse(gate.passed)

    def test_safety_and_lineage_failures_cannot_be_overridden_by_scores(self):
        evidence = passing_evidence()
        evidence["candidate_lcb"] = 0.99
        evidence["baseline_ucb"] = 0.01
        evidence["safety_gate"] = False
        evidence["lineage_gate"] = False
        result = evaluate(evidence)
        self.assertFalse(result.gates_passed)
        failed = {gate.name for gate in result.gates if not gate.passed}
        self.assertIn("safety_gate", failed)
        self.assertIn("lineage_gate", failed)
        self.assertFalse(result.promotion_allowed)

    def test_external_evidence_cli_is_fail_closed_and_deterministic(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            evidence_path = Path(temp_dir) / "evidence.json"
            output_path = Path(temp_dir) / "report.json"
            evidence_path.write_text(json.dumps(passing_evidence()), encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, "candidate_promotion_gate.py", "--evidence", str(evidence_path), "--output", str(output_path)],
                check=True,
                capture_output=True,
                text=True,
            )
            report = json.loads(proc.stdout)
            self.assertEqual(report["status"], "ELIGIBLE_FOR_EXTERNAL_ACCEPTANCE")
            self.assertFalse(report["decision"]["promotion_allowed"])
            self.assertEqual(report, json.loads(output_path.read_text()))

            malformed = Path(temp_dir) / "malformed.json"
            malformed.write_text("[]", encoding="utf-8")
            rejected = subprocess.run(
                [sys.executable, "candidate_promotion_gate.py", "--evidence", str(malformed)],
                check=True,
                capture_output=True,
                text=True,
            )
            rejected_report = json.loads(rejected.stdout)
            self.assertEqual(rejected_report["status"], "REJECTED_FAIL_CLOSED")
            self.assertFalse(rejected_report["decision"]["promotion_allowed"])


if __name__ == "__main__":
    unittest.main()
