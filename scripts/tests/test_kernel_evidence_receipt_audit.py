from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from scripts import kernel_evidence_receipt_audit as audit


IDENTITY = {
    "sourceHeadSha": "1" * 40,
    "sourceHeadTree": "2" * 40,
    "baseSha": "3" * 40,
    "deterministicMergeSha": "4" * 40,
    "githubSyntheticMergeSha": "5" * 40,
    "workflowSha": "6" * 40,
    "finalMergeSha": None,
    "workflowRunId": "123",
    "workflowRunAttempt": "1",
    "runnerImage": "ubuntu24-test",
    "targetTriple": "x86_64-unknown-linux-gnu",
}


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ReceiptAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self._create_valid_fixture()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _qualification_receipt(self, kind: str, log: Path) -> dict:
        merge = IDENTITY["deterministicMergeSha"] if kind == "deterministic_merge" else None
        tested = merge if kind == "deterministic_merge" else IDENTITY["sourceHeadSha"]
        return {
            "schemaVersion": 2,
            "module": "kernel.evidence",
            "receiptKind": "candidate_qualification",
            "kind": kind,
            "sourceHeadSha": IDENTITY["sourceHeadSha"],
            "sourceHeadTree": IDENTITY["sourceHeadTree"],
            "baseSha": IDENTITY["baseSha"],
            "deterministicMergeSha": merge,
            "testedObjectSha": tested,
            "workflowSha": IDENTITY["workflowSha"],
            "workflowRunId": IDENTITY["workflowRunId"],
            "workflowRunAttempt": IDENTITY["workflowRunAttempt"],
            "runnerImage": IDENTITY["runnerImage"],
            "targetTriple": IDENTITY["targetTriple"],
            "command": f"run {kind}",
            "startedAtUnixMs": 10,
            "finishedAtUnixMs": 20,
            "exitCode": 0,
            "status": "passed",
            "passed": True,
            "logPath": str(log),
            "logSha256": digest(log),
            "logBytes": log.stat().st_size,
            "qualificationGranted": False,
            "independentAcceptanceGranted": False,
            "productionActivationGranted": False,
            "releaseGranted": False,
        }

    def _create_valid_fixture(self) -> None:
        for kind, relative in audit.QUALIFICATION_LOGS.items():
            log = self.root / relative
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text(f"{kind} passed\n", encoding="utf-8")
            write_json(self.root / f"{kind}.json", self._qualification_receipt(kind, log))

        scenarios: dict[str, dict] = {}
        for scenario in audit.REQUIRED_CRASH_SCENARIOS:
            log = self.root / "crash" / scenario / "01-test.log"
            log.parent.mkdir(parents=True, exist_ok=True)
            marker = f"test {scenario} ... ok"
            log.write_text(marker + "\n", encoding="utf-8")
            command = {
                "package": "codex-hepta-evidence",
                "targetArgs": ["--lib"],
                "testName": scenario,
                "argv": ["cargo", "test", scenario],
                "command": f"cargo test {scenario}",
                "startedAtUnixMs": 30,
                "finishedAtUnixMs": 40,
                "exitCode": 0,
                "timedOut": False,
                "status": "passed",
                "logPath": str(log),
                "logSha256": digest(log),
                "logBytes": log.stat().st_size,
                "requiredMarkers": [marker],
                "missingMarkers": [],
                "skippedDetected": False,
            }
            receipt = {
                "schemaVersion": 2,
                "module": "kernel.evidence",
                "receiptKind": "crash_consistency_scenario",
                "scenario": scenario,
                "sourceHeadSha": IDENTITY["sourceHeadSha"],
                "sourceHeadTree": IDENTITY["sourceHeadTree"],
                "baseSha": IDENTITY["baseSha"],
                "workflowSha": IDENTITY["workflowSha"],
                "workflowRunId": IDENTITY["workflowRunId"],
                "workflowRunAttempt": IDENTITY["workflowRunAttempt"],
                "runnerImage": IDENTITY["runnerImage"],
                "targetTriple": IDENTITY["targetTriple"],
                "qualificationClass": "hosted_runner",
                "status": "passed",
                "startedAtUnixMs": 20,
                "finishedAtUnixMs": 50,
                "commands": [command],
                "qualificationGranted": False,
                "targetHostAcceptanceGranted": False,
                "productionActivationGranted": False,
                "releaseGranted": False,
            }
            receipt_path = self.root / "crash" / f"{scenario}.json"
            write_json(receipt_path, receipt)
            scenarios[scenario] = {
                "path": str(receipt_path),
                "sha256": digest(receipt_path),
                "passed": True,
            }
        summary = {
            "schemaVersion": 2,
            "module": "kernel.evidence",
            "receiptKind": "crash_consistency_matrix",
            "sourceHeadSha": IDENTITY["sourceHeadSha"],
            "sourceHeadTree": IDENTITY["sourceHeadTree"],
            "baseSha": IDENTITY["baseSha"],
            "workflowSha": IDENTITY["workflowSha"],
            "workflowRunId": IDENTITY["workflowRunId"],
            "workflowRunAttempt": IDENTITY["workflowRunAttempt"],
            "runnerImage": IDENTITY["runnerImage"],
            "targetTriple": IDENTITY["targetTriple"],
            "passed": True,
            "scenarioCount": len(audit.REQUIRED_CRASH_SCENARIOS),
            "requiredScenarioCount": len(audit.REQUIRED_CRASH_SCENARIOS),
            "scenarios": scenarios,
            "targetHostAcceptanceGranted": False,
            "productionActivationGranted": False,
            "releaseGranted": False,
        }
        write_json(self.root / "crash" / "SUMMARY.json", summary)

    def test_valid_fixture_passes(self) -> None:
        result = audit.build_audit(self.root, dict(IDENTITY))
        self.assertTrue(result["passed"], result["errors"])

    def test_boolean_exit_code_is_rejected(self) -> None:
        path = self.root / "exact_source.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        value["exitCode"] = False
        write_json(path, value)
        result = audit.build_audit(self.root, dict(IDENTITY))
        self.assertFalse(result["passed"])
        self.assertTrue(any("integer zero" in error for error in result["errors"]))

    def test_qualification_log_tamper_is_rejected(self) -> None:
        (self.root / "source" / "tests.log").write_text("tampered\n", encoding="utf-8")
        result = audit.build_audit(self.root, dict(IDENTITY))
        self.assertFalse(result["passed"])
        self.assertTrue(any("logSha256" in error for error in result["errors"]))

    def test_crash_log_tamper_is_rejected(self) -> None:
        scenario = audit.REQUIRED_CRASH_SCENARIOS[0]
        (self.root / "crash" / scenario / "01-test.log").write_text(
            "forged output\n", encoding="utf-8"
        )
        result = audit.build_audit(self.root, dict(IDENTITY))
        self.assertFalse(result["passed"])
        self.assertTrue(any("retained log" in error for error in result["errors"]))

    def test_mixed_identity_is_rejected(self) -> None:
        path = self.root / "metadata.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        value["workflowRunAttempt"] = "2"
        write_json(path, value)
        result = audit.build_audit(self.root, dict(IDENTITY))
        self.assertFalse(result["passed"])
        self.assertTrue(any("workflowRunAttempt" in error for error in result["errors"]))

    def test_summary_digest_substitution_is_rejected(self) -> None:
        path = self.root / "crash" / "SUMMARY.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        scenario = audit.REQUIRED_CRASH_SCENARIOS[0]
        value["scenarios"][scenario]["sha256"] = "0" * 64
        write_json(path, value)
        result = audit.build_audit(self.root, dict(IDENTITY))
        self.assertFalse(result["passed"])
        self.assertTrue(any("sha256" in error for error in result["errors"]))

    def test_symlink_scenario_directory_is_rejected(self) -> None:
        scenario = audit.REQUIRED_CRASH_SCENARIOS[0]
        original = self.root / "crash" / scenario
        with tempfile.TemporaryDirectory() as external_temp:
            external = Path(external_temp) / scenario
            original.rename(external)
            try:
                os.symlink(external, original, target_is_directory=True)
            except (OSError, NotImplementedError) as error:
                self.skipTest(f"directory symlink unavailable: {error}")
            result = audit.build_audit(self.root, dict(IDENTITY))
            self.assertFalse(result["passed"])
            self.assertTrue(
                any(
                    "boundary" in error and "symlink" in error
                    for error in result["errors"]
                )
            )

    def test_symlink_log_is_rejected(self) -> None:
        source = self.root / "source" / "tests.log"
        replacement = self.root / "source" / "actual.log"
        replacement.write_bytes(source.read_bytes())
        source.unlink()
        try:
            os.symlink(replacement, source)
        except (OSError, NotImplementedError) as error:
            self.skipTest(f"symlink unavailable: {error}")
        result = audit.build_audit(self.root, dict(IDENTITY))
        self.assertFalse(result["passed"])
        self.assertTrue(any("symlink" in error for error in result["errors"]))


if __name__ == "__main__":
    unittest.main()
