"""Synthetic parser regressions; these fixtures never establish native execution."""

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location("authority_port_acceptance", Path(__file__).with_name("port_acceptance.py"))
PORTS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PORTS)
RUNTIME = PORTS.RUNTIME
EXECUTION = PORTS.EXECUTION


class PortAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.identity = {
            "schema": "hepta.kernel-authority-candidate.v1", "mode": "exact-head",
            "sourceCommit": "1" * 40, "baseCommit": "2" * 40,
            "candidateCommit": "1" * 40, "candidateTree": "3" * 40,
            "activationGranted": False, "releaseGranted": False,
        }
        cases = []
        for case in RUNTIME.PILOT_CASES:
            expected = EXECUTION.EXPECTED_TESTS[case.name]
            text = "\n".join(f"test {name} ... ok" for name in expected)
            text += f"\ntest result: ok. {len(expected)} passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.01s\n"
            raw = text.encode()
            path = self.root / "logs" / f"{case.name}.log"
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(raw)
            cases.append({
                "name": case.name, "product": case.product,
                "command": list(EXECUTION.checked_command(case.command)),
                "workingDirectory": "codex-rs", "exitCode": 0, "durationMs": 1,
                "logPath": path.relative_to(self.root).as_posix(), "logBytes": len(raw),
                "logSha256": hashlib.sha256(raw).hexdigest(),
                "testExecution": EXECUTION.validate_output(text, expected),
                "validationError": None, "passed": True,
            })
        self.receipt = {
            "schema": "hepta.kernel-authority-product-pilot.v1", "schemaVersion": 1,
            "candidate": self.identity, "scope": "repository-process-pilot",
            "passed": True, "deploymentActivationProved": False, "productionTrustProved": False,
            "activationGranted": False, "releaseGranted": False, "cases": cases,
            **RUNTIME.pilot_claims(cases),
        }
        self.save()

        self.process_root = self.root / "product-process"
        process_text = (
            f"test {PORTS.PROCESS.TEST_NAME} ... ok\n"
            "test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; "
            "0 filtered out; finished in 0.01s\n"
        )
        process_raw = process_text.encode()
        process_log = self.process_root / "logs" / "authority-effect-process-restart.log"
        process_log.parent.mkdir(parents=True)
        process_log.write_bytes(process_raw)
        process_execution = PORTS.PROCESS.parse_execution(process_text)
        self.process_receipt = {
            "schema": "hepta.kernel-authority-product-process-recovery.v1",
            "schemaVersion": 1,
            "candidate": self.identity,
            "scope": "two-normal-agentd-product-processes",
            "command": list(PORTS.PROCESS.command()),
            "workingDirectory": "codex-rs",
            "exitCode": 0,
            "durationMs": 1,
            "logPath": "logs/authority-effect-process-restart.log",
            "logBytes": len(process_raw),
            "logSha256": hashlib.sha256(process_raw).hexdigest(),
            "testExecution": process_execution,
            "validationError": None,
            **{field: True for field in PORTS.PROCESS_PROOF_FIELDS},
            "passed": True,
            "productionTrustProved": False,
            "targetHostQualified": False,
            "independentAcceptance": False,
            "activationGranted": False,
            "releaseGranted": False,
        }
        self.save_process()

    def save(self):
        (self.root / "product-pilot-receipt.json").write_text(json.dumps(self.receipt))

    def save_process(self):
        (self.process_root / "product-process-recovery-receipt.json").write_text(
            json.dumps(self.process_receipt)
        )

    def verify(self):
        return PORTS.verified_pilot(self.identity, self.root)

    def verify_process(self):
        return PORTS.verified_product_process(self.identity, self.process_root)

    def test_matching_raw_fixture_is_reopened_without_granting_production(self):
        observed = self.verify()
        manifest = json.loads(Path(__file__).with_name("status_manifest.json").read_text())
        report = PORTS.project(manifest, self.identity, observed)
        self.assertEqual(report["schema"], "hepta.kernel-authority-port-acceptance.v2")
        self.assertEqual(len(report["ports"]), len(manifest["targetPorts"]))
        self.assertEqual(sum(row["nativePilotVerified"] for row in report["ports"]), 2)
        self.assertTrue(all(not row["nativeIntegrationVerified"] for row in report["ports"]))
        self.assertTrue(all(not row["productionAccepted"] for row in report["ports"]))
        self.assertFalse(report["activationGranted"])

    def test_combined_raw_evidence_reopens_product_process_without_granting_production(self):
        observed = self.verify()
        self.assertTrue(self.verify_process())
        manifest = json.loads(Path(__file__).with_name("status_manifest.json").read_text())
        report = PORTS.project(manifest, self.identity, observed, True)
        self.assertEqual(
            report["nativeEvidence"],
            "pilot-and-product-process-raw-logs-reopened",
        )
        self.assertTrue(report["productProcessVerified"])
        browser = next(
            row
            for row in report["ports"]
            if row["id"] == "ModulePort::kernel.authority::browser.servo"
        )
        self.assertTrue(browser["productProcessRecoveryVerified"])
        self.assertIn("two-product-process-recovery", browser["provenLifecycleObligations"])
        self.assertFalse(browser["nativeIntegrationVerified"])
        self.assertFalse(report["productionTrustProved"])

    def test_changed_product_process_log_and_overclaim_are_rejected(self):
        log = self.process_root / self.process_receipt["logPath"]
        original = log.read_bytes()
        log.write_text("running 0 tests\n")
        with self.assertRaises(PORTS.EvidenceError):
            self.verify_process()
        log.write_bytes(original)
        self.process_receipt["productionTrustProved"] = True
        self.save_process()
        with self.assertRaises(PORTS.EvidenceError):
            self.verify_process()

    def test_source_only_does_not_grant_native_execution(self):
        manifest = json.loads(Path(__file__).with_name("status_manifest.json").read_text())
        report = PORTS.project(manifest, self.identity, {})
        self.assertEqual(report["nativeEvidence"], "not-supplied")
        self.assertFalse(any(row["nativePilotVerified"] for row in report["ports"]))

    def test_changed_candidate_is_rejected(self):
        other = copy.deepcopy(self.identity)
        other["candidateCommit"] = "4" * 40
        with self.assertRaises(PORTS.EvidenceError):
            PORTS.verified_pilot(other, self.root)

    def test_altered_raw_log_is_rejected_even_when_receipt_claims_green(self):
        row = self.receipt["cases"][0]
        (self.root / row["logPath"]).write_text("running 0 tests\n")
        with self.assertRaises(PORTS.EvidenceError):
            self.verify()

    def test_zero_test_replacement_is_rejected_even_with_updated_hash(self):
        row = self.receipt["cases"][0]
        raw = b"test result: ok. 0 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.01s\n"
        (self.root / row["logPath"]).write_bytes(raw)
        row.update(logSha256=hashlib.sha256(raw).hexdigest(), logBytes=len(raw))
        self.save()
        with self.assertRaises(PORTS.EvidenceError):
            self.verify()

    def test_changed_command_owner_and_boolean_exit_code_are_rejected(self):
        original = copy.deepcopy(self.receipt)
        for field, replacement in (("command", ["cargo", "test"]), ("product", "other"), ("exitCode", False)):
            with self.subTest(field=field):
                self.receipt = copy.deepcopy(original)
                self.receipt["cases"][0][field] = replacement
                self.save()
                with self.assertRaises((PORTS.EvidenceError, RUNTIME.QualificationError)):
                    self.verify()

    def test_parent_traversal_and_symlink_logs_are_rejected(self):
        row = self.receipt["cases"][0]
        original = row["logPath"]
        row["logPath"] = "../outside.log"
        self.save()
        with self.assertRaises(PORTS.EvidenceError):
            self.verify()
        row["logPath"] = original
        self.save()
        path = self.root / original
        outside = self.root / "outside.log"
        path.rename(outside)
        path.symlink_to(outside)
        with self.assertRaises(PORTS.EvidenceError):
            self.verify()

    def test_missing_duplicate_cases_and_overclaimed_flags_are_rejected(self):
        original = copy.deepcopy(self.receipt)
        for change in ("missing", "duplicate", "authority", "aggregate"):
            self.receipt = copy.deepcopy(original)
            if change == "missing":
                self.receipt["cases"].pop()
            elif change == "duplicate":
                self.receipt["cases"].append(self.receipt["cases"][0])
            elif change == "authority":
                self.receipt["productionTrustProved"] = True
            else:
                self.receipt["passed"] = False
            self.save()
            with self.subTest(change=change), self.assertRaises((PORTS.EvidenceError, RUNTIME.QualificationError)):
                self.verify()


if __name__ == "__main__":
    unittest.main()
