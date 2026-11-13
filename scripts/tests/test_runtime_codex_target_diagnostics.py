"""Pure synthetic input diagnostics; no provider, target host, or model execution."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HELPER = Path(__file__).resolve().parents[1] / "runtime-codex-target-qualification.py"
SPEC = importlib.util.spec_from_file_location("runtime_target_diagnostics", HELPER)
assert SPEC is not None and SPEC.loader is not None
TARGET = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TARGET)
SHA = "a" * 40
TREE = "b" * 40


class TargetDiagnosticsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="runtime-target-diagnostic-fixture-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.plan = {
            "schema": TARGET.PLAN_SCHEMA, "candidateSha": SHA, "candidateTree": TREE,
            "profileId": "synthetic-only", "iterations": 3,
            "cases": [{"case": case, "iteration": i} for case in TARGET.CASES for i in range(1, 4)],
            "requirements": {"realProvider": True, "independentIssuer": True,
                             "processInstanceIdentity": True, "trustedClock": True,
                             "antiRollbackRecovery": True, "blindReplayAttempts": 0},
        }
        self.thresholds = {"schema": "hepta.runtime-codex.target-thresholds.v1", "metrics": {
            name: ({"p95": 10, "p99": 10} if name in TARGET.TIMINGS else {"p99": 10})
            for name in (*TARGET.TIMINGS, "peakRssBytes", "cpuMillis")}}
        self.observations = []
        for item in self.plan["cases"]:
            case = item["case"]
            outcome = ("succeeded" if case == "success" else
                       "definitely_unsent" if case == "worker_kill_before_effect_entry" else
                       "revoked_before_effect" if case == "revocation_frontier_race" else "terminal")
            self.observations.append({
                "schema": TARGET.OBS_SCHEMA, "candidateSha": SHA, "candidateTree": TREE,
                "profileId": "synthetic-only", **item,
                "operationId": f"fixture-{case}-{item['iteration']}",
                "targetHostId": "fixture-host", "hostBootId": "fixture-boot",
                "appServerSessionId": "fixture-session", "issuerSignerId": "fixture-issuer",
                "providerEvidenceSha256": "c" * 64, "processEvidenceSha256": "d" * 64,
                "agentGeneration": 1, "issuerEpoch": 1, "revocationRevision": 1,
                "realProvider": True, "independentIssuer": True,
                "processInstanceIdentityVerified": True, "trustedClockAttested": True,
                "antiRollbackRecoveryAttested": True, "blindReplayAttempts": 0,
                "physicalProviderRequests": 0 if outcome in {"definitely_unsent", "revoked_before_effect"} else 1,
                "terminalObserved": outcome in {"succeeded", "terminal"}, "outcome": outcome,
                "timings": {key: 1 for key in TARGET.TIMINGS}, "peakRssBytes": 1, "cpuMillis": 1,
            })
        self.args = argparse.Namespace(plan=str(self.root/"plan.json"), evidence=str(self.root/"input.jsonl"),
                                       thresholds=str(self.root/"thresholds.json"), output=str(self.root/"diagnostic.json"))

    def files(self) -> None:
        Path(self.args.plan).write_bytes(TARGET.canonical(self.plan))
        Path(self.args.thresholds).write_bytes(TARGET.canonical(self.thresholds))
        Path(self.args.evidence).write_bytes(b"".join(TARGET.canonical(x) for x in self.observations))

    @staticmethod
    def git_identity(*args: str) -> str:
        return TREE if args[-1] == "HEAD^{tree}" else SHA

    def verify(self) -> dict:
        self.files()
        with mock.patch.object(TARGET, "git", side_effect=self.git_identity):
            TARGET.command_verify(self.args)
        return json.loads(Path(self.args.output).read_bytes())

    def rejected(self) -> None:
        with self.assertRaises(SystemExit):
            self.verify()
        self.assertFalse(Path(self.args.output).exists())

    def test_consistent_self_assertions_always_remain_unqualified(self) -> None:
        receipt = self.verify()
        self.assertEqual(receipt["schema"], "hepta.runtime-codex.target-diagnostic.v1")
        self.assertEqual(receipt["qualificationStatus"], "HOLD")
        self.assertEqual(receipt["diagnosticStatus"], "INPUT_CONSISTENT")
        self.assertEqual(receipt["observations"], 27)
        self.assertTrue(receipt["claims"]["suppliedInputConsistencyValidated"])
        for key in ("realProviderFaultMatrixValidated", "targetHostEvidenceValidated",
                    "independentAcceptance", "activation", "promotion", "release"):
            self.assertIs(receipt["claims"][key], False)
        self.assertIn("not authenticated", receipt["limitations"][1])

    def test_reduced_matrix_and_corresponding_evidence_rejected(self) -> None:
        self.plan["cases"] = self.plan["cases"][:3]
        self.observations = self.observations[:3]
        self.rejected()

    def test_duplicate_plan_case_rejected(self) -> None:
        self.plan["cases"][-1] = self.plan["cases"][0].copy()
        self.rejected()

    def test_less_than_three_iterations_rejected(self) -> None:
        self.plan["iterations"] = 2
        self.plan["cases"] = [x for x in self.plan["cases"] if x["iteration"] < 3]
        self.observations = [x for x in self.observations if x["iteration"] < 3]
        self.rejected()

    def test_boolean_iteration_is_not_integer(self) -> None:
        self.plan["cases"][0]["iteration"] = True
        self.rejected()

    def test_changed_plan_requirements_rejected(self) -> None:
        self.plan["requirements"]["realProvider"] = False
        self.rejected()

    def test_empty_thresholds_rejected(self) -> None:
        self.thresholds["metrics"] = {}
        self.rejected()

    def test_missing_threshold_percentile_rejected(self) -> None:
        self.thresholds["metrics"]["firstTokenMs"].pop("p99")
        self.rejected()

    def test_boolean_ceiling_rejected(self) -> None:
        self.thresholds["metrics"]["cpuMillis"]["p99"] = True
        self.rejected()

    def test_nan_and_infinite_numbers_rejected(self) -> None:
        for number in (float("nan"), float("inf"), float("-inf"), 10 ** 400):
            with self.subTest(number=str(number)[:20]):
                self.observations[0]["timings"]["terminalMs"] = number
                self.rejected()

    def test_boolean_numbers_rejected(self) -> None:
        for name in ("agentGeneration", "physicalProviderRequests", "iteration", "blindReplayAttempts"):
            with self.subTest(name=name):
                value = self.observations[0][name]
                self.observations[0][name] = bool(value)
                self.rejected()
                self.observations[0][name] = value

    def test_boolean_timing_rejected(self) -> None:
        self.observations[0]["timings"]["terminalMs"] = True
        self.rejected()

    def test_terminal_claim_requires_observed_terminal(self) -> None:
        self.observations[3]["terminalObserved"] = False
        self.rejected()

    def test_duplicate_operation_identity_rejected(self) -> None:
        self.observations[1]["operationId"] = self.observations[0]["operationId"]
        self.rejected()

    def test_missing_observation_rejected(self) -> None:
        self.observations.pop()
        self.rejected()

    def test_threshold_exceedance_rejected(self) -> None:
        for row in self.observations:
            row["timings"]["firstTokenMs"] = 11
        self.rejected()

    def test_checkout_identity_mismatch_rejected(self) -> None:
        self.files()
        with mock.patch.object(TARGET, "git", return_value="e"*40), self.assertRaises(SystemExit):
            TARGET.command_verify(self.args)

    def test_duplicate_json_keys_rejected(self) -> None:
        with self.assertRaises(SystemExit):
            TARGET.parse_json('{"schema":"one","schema":"two"}', "fixture")

    def test_input_hash_binds_consumed_snapshot(self) -> None:
        self.files()
        expected = Path(self.args.evidence).read_bytes()
        def change_after_read(*args: str) -> str:
            Path(self.args.evidence).write_text("changed after read\n")
            return self.git_identity(*args)
        with mock.patch.object(TARGET, "git", side_effect=change_after_read):
            TARGET.command_verify(self.args)
        receipt = json.loads(Path(self.args.output).read_bytes())
        self.assertEqual(receipt["evidenceSha256"], hashlib.sha256(expected).hexdigest())
        self.assertEqual(receipt["observations"], 27)

    def test_git_identity_disables_replace_objects(self) -> None:
        with mock.patch.object(TARGET.subprocess, "check_output", return_value=SHA+"\n") as run:
            self.assertEqual(TARGET.git("rev-parse", "HEAD"), SHA)
        self.assertEqual(run.call_args.args[0], ["git", "--no-replace-objects", "rev-parse", "HEAD"])


if __name__ == "__main__":
    unittest.main()
